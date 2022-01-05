"""Media Player entities"""

# region #-- imports --#
import asyncio
import glob
import json
import logging
import os
from abc import ABC
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Union,
)

import voluptuous as vol
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect

# TODO: Fix up the try/except block if setting the minimum HASS version to 2021.12
# MediaPlayerDeviceClass enum is introduced with HASS 2021.12
try:
    from homeassistant.components.media_player import MediaPlayerDeviceClass
    DEVICE_CLASS_TV = None
except ImportError:
    MediaPlayerDeviceClass = None
    from homeassistant.components.media_player import DEVICE_CLASS_TV

from homeassistant.components.media_player.const import (
    MEDIA_CLASS_DIRECTORY,
    MEDIA_CLASS_URL,
    MEDIA_TYPE_CHANNEL,
    MEDIA_TYPE_CHANNELS,
    MEDIA_TYPE_TVSHOW,
    SUPPORT_BROWSE_MEDIA,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_STOP,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_IDLE,
    STATE_OFF,
    STATE_PAUSED,
    STATE_PLAYING,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
    EntityPlatform,
)
from homeassistant.helpers.event import async_track_time_interval, async_track_point_in_time
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CHANNEL_FETCH_ENABLE,
    CONF_CHANNEL_INTERVAL,
    CONF_CHANNEL_LISTINGS_CACHE,
    CONF_CHANNEL_PWD,
    CONF_CHANNEL_REGION,
    CONF_CHANNEL_USE_MEDIA_BROWSER,
    CONF_CHANNEL_USER,
    CONF_CONNECT_TIMEOUT,
    CONF_COMMAND_TIMEOUT,
    CONF_DEVICE_PLATFORM,
    CONF_HOST,
    CONF_IDLE_TIMEOUT,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SWVERSION,
    DEF_AUTH_FILE,
    DEF_CHANNEL_FETCH_ENABLE,
    DEF_CHANNEL_FILE,
    DEF_CHANNEL_INTERVAL,
    DEF_CHANNEL_LISTINGS_CACHE,
    DEF_CHANNEL_MAPPINGS_FILE,
    DEF_CHANNEL_REGION,
    DEF_CHANNEL_USE_MEDIA_BROWSER,
    DEF_DEVICE_PLATFORM,
    DEF_IDLE_TIMEOUT,
    DEF_SCAN_INTERVAL,
    DOMAIN,
    SIGNAL_CLEAR_CACHE,
)

from .flagging import VirginTvFlagFile

from .logger import VirginTvLogger

from .pyvmtvguide.api import (
    API,
    TVChannelLists,
)

from .pyvmtivo.client import Client

from .pyvmtivo.exceptions import (
    VirginMediaCommandTimeout,
    VirginMediaError,
    VirginMediaInvalidChannel,
)
# endregion

_CHANNEL_REGION_MAPPING: dict = {
    "Eng-Lon": ["eng", "excl. london"],
    "Eng+Lon": ["eng", "london"],
    "NI": ["ni"],
    "Scot": ["scot"],
    "Wales": ["wales"],
}
_CHANNEL_SEPARATOR: str = ":"
_FLAG_TURNING_ON: str = "turning_on"
_FLAG_TURNING_OFF: str = "turning_off"
_LOGGER = logging.getLogger(__name__)
_MEDIA_POSITION_UPDATE_INTERVAL: float = 60


def _get_current_epoch() -> int:
    """Get the current epoch time"""

    return int(dt_util.now().timestamp())


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up services and entities"""

    # region #-- create the entities --#
    async_add_entities(
        [
            VirginMediaPlayer(hass=hass, config_entry=config_entry)
        ]
    )
    # endregion

    # region #-- create the entity services --#
    service_definitions = [
        {
            "func": "_async_send_ircode",
            "name": "send_ircode",
            "schema": {
                vol.Required("code"): cv.string
            }
        },
        {
            "func": "_async_send_keycode",
            "name": "send_keycode",
            "schema": {
                vol.Required("code"): cv.string
            }
        },
    ]

    platform: EntityPlatform = async_get_current_platform()
    for service_details in service_definitions:
        platform.async_register_entity_service(
            name=service_details.get("name", ""),
            schema=service_details.get("schema", None),
            func=service_details.get("func", "")
        )
    # endregion


class VirginMediaPlayer(MediaPlayerEntity, VirginTvLogger, ABC):
    """Representation of a Virgin Media device"""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Constructor"""

        self._channel_current: Dict[str, Any] = {
            "number": None,
        }
        self._channel_mappings: Dict[str, Any] = {}
        self._channels_available: List[Dict[str, Any]] = []
        self._client: Client
        self._config: ConfigEntry = config_entry
        self._extra_state_attributes: Dict[str, Any] = {}
        self._flags: Dict[str, bool] = {}
        self._global_flag_channel_cache = VirginTvFlagFile(path=hass.config.path(DOMAIN, ".channels_caching"))
        self._hass: HomeAssistant = hass
        self._intervals: Dict[str, Callable] = {}
        self._listeners: Dict[str, Callable] = {}
        self._lock_client: asyncio.Lock = asyncio.Lock()
        self._lock_removing: asyncio.Lock = asyncio.Lock()
        self._media_position: Optional[int] = None
        self._media_position_updated_at: Optional[dt_util.dt.datetime] = None
        self._signals: Dict[str, Callable] = {}
        self._state: Optional[str] = None

        self._client = Client(
            host=self._config.data.get(CONF_HOST),
            port=self._config.data.get(CONF_PORT),
            timeout=self._config.options.get(CONF_CONNECT_TIMEOUT),
            command_timeout=self._config.options.get(CONF_COMMAND_TIMEOUT),
        )
        self._current_channel_reset()

    # region #-- private methods --#
    def _cache_cleanup(self, cleanup_type: str) -> None:
        """Cleanup the given cache type

        This will remove all files and folders for the given cache type
        """

        _LOGGER.debug(self._logger_message_format("entered, cleanup_type: %s"), cleanup_type)

        paths: list = []
        if cleanup_type == "auth":
            paths.append(self._cache_get_path(cache_type="auth"))
        elif cleanup_type == "channel":
            paths.append(self._cache_get_path(cache_type="channels"))
            paths.append(self._cache_get_path(cache_type="channel_mappings"))
            listings_path = self._cache_get_path("listings", station_id="dummy")
            listings_files = glob.glob(f"{os.path.join(os.path.dirname(listings_path), '*.json')}")
            paths.extend(listings_files)
            paths = list(set(paths))
            try:
                paths.remove(self._cache_get_path(cache_type="auth"))
            except ValueError:
                pass

        if paths:
            _LOGGER.debug(self._logger_message_format("cleaning up %d files"), len(paths))

        for path in paths:
            if os.path.exists(path):
                os.remove(path)
                # check if the directory needs removing
                # doing this each go round just in case the list has multiple different locations
                dir_path = os.path.dirname(path)
                num_files_left = len([True for _ in list(os.scandir(dir_path))])
                if num_files_left == 0:
                    _LOGGER.debug(self._logger_message_format("%s is empty, removing it"), dir_path)
                    os.rmdir(dir_path)

        _LOGGER.debug(self._logger_message_format("exited"))

    def _cache_get_path(self, cache_type: str, **kwargs) -> str:
        """Returns the path for the specified cache

        Valid cahce types are: "auth", "channels", "listings"

        :param cache_type: the cache type to return the path for
        :return: the path to the cache file
        """

        if not cache_type.lower() in ("auth", "channels", "listings", "channel_mappings"):
            raise ValueError("Invalid cache type")

        path: str = ""
        if cache_type.lower() == "auth":
            path = self.hass.config.path(DOMAIN, DEF_AUTH_FILE)
        elif cache_type.lower() == "channels":
            path = self.hass.config.path(DOMAIN, DEF_CHANNEL_FILE)
        elif cache_type.lower() == "channel_mappings":
            path = self.hass.config.path(DOMAIN, DEF_CHANNEL_MAPPINGS_FILE)
        elif cache_type.lower() == "listings":
            if kwargs.get("station_id"):
                path = self.hass.config.path(DOMAIN, f"{kwargs.get('station_id')}.json")

        return path

    def _cache_load(self, cache_type: str, **kwargs) -> Dict[str, Any]:
        """Load the specified cache type and return the contents

        :param cache_type: the type of cache to load
        :param kwargs: additional info to pass into the method
        :return: a mapping containing the cached details
        """

        _LOGGER.debug(self._logger_message_format("entered, cache_type: %s"), cache_type)

        ret = {}
        path = self._cache_get_path(cache_type=cache_type, **kwargs)
        if path:
            if os.path.exists(path):
                _LOGGER.debug(self._logger_message_format("loading cache from %s"), path)
                with open(path, "r") as cache_file:
                    try:
                        ret = json.load(cache_file)
                        _LOGGER.debug(self._logger_message_format("cache loaded (%s)"), path)
                    except json.JSONDecodeError:
                        _LOGGER.error(self._logger_message_format("invalid JSON (%s)"), path)
            else:
                _LOGGER.debug(self._logger_message_format("cache file does not exist"))
        else:
            _LOGGER.debug(self._logger_message_format("unable to establish cache file"))

        _LOGGER.debug(self._logger_message_format("exited"))

        return ret

    def _cache_process_available_channels(self, channel_cache: dict) -> None:
        """Ensure the available channels matches the device type and region for the device"""

        if self._config.options.get(CONF_DEVICE_PLATFORM, DEF_DEVICE_PLATFORM).lower() == "v6":
            _LOGGER.debug(self._logger_message_format("processing V6 channel mappings"))
            # v6 devices don't merge resolutions onto the same channel number so use the mappings to build
            # the available channels
            self._channels_available = []

            # region #-- bring the sub channels to the root --#
            for p360_channel in channel_cache.get("channels", []):
                if p360_channel.get("subChannels", []):
                    self._channels_available.append(p360_channel)
                    for sub_channel in p360_channel.get("subChannels", []):
                        self._channels_available.append(sub_channel)
                else:
                    self._channels_available.append(p360_channel)
            # endregion

            # region #-- process only the V6 channels in the specified region --#
            region = self._config.options.get(CONF_CHANNEL_REGION, DEF_CHANNEL_REGION)
            for cmap in self._channel_mappings.get("channels", []):
                regions = cmap.get("region", "").lower().split(",")
                if len(set(regions).intersection(_CHANNEL_REGION_MAPPING.get(region, []))) > 0 or not regions[0]:
                    platform_v6_channel: list = []
                    platform_360_channel: list = []
                    if "tv v6" in cmap and cmap["tv v6"]:
                        platform_v6_channel = list(cmap.get("tv v6", {}).items())[0]
                    if "tv 360" in cmap and cmap["tv 360"]:
                        platform_360_channel = list(cmap.get("tv 360", {}).items())[0]
                    if platform_360_channel and platform_v6_channel:
                        # region #-- lookup in the channels provided by the online service --#
                        for oc_idx, online_channel in enumerate(self._channels_available):
                            # interested in the channels with same channel number
                            if online_channel.get("channelNumber") == platform_360_channel[1]:
                                # check for the resolution and update accordingly
                                station_schedule: Union[list, dict] = online_channel.get("stationSchedules", [])
                                if station_schedule:
                                    station: dict = station_schedule[0].get("station", {})
                                    online_resolution = "hd" if station.get("isHd") else "sd"
                                    if online_resolution == platform_v6_channel[0]:
                                        self._channels_available[oc_idx]["channelNumber"] = platform_v6_channel[1]
                        # endregion
            # endregion

            self._channels_available = sorted(self._channels_available, key=lambda itm: itm["channelNumber"])
            _LOGGER.debug(self._logger_message_format("finished processing V6 channel mappings"))
        else:
            # assume all other devices can use the list as is from the online service
            _LOGGER.debug(self._logger_message_format("loading tv 360 channnels"))
            self._channels_available = channel_cache.get("channels", [])

    def _channel_details(self, channel_number: int) -> dict:
        """Retrieve the details for the given channel

        :param channel_number: the channel number to lookup details for
        :return: object containing the details
        """

        ret = {}
        channel_details = [
            channel
            for channel in self._channels_available
            if channel.get("channelNumber") == channel_number
        ]
        if channel_details:
            ret = channel_details[0]

        return ret

    def _channel_logo(self, channel_number: int) -> str:
        """Retrieve the logo for the given channel number

        :param channel_number: the channel number to get the logo for
        :return: path to the channel logo
        """

        ret = ""
        if self._channels_available:
            channel_details = self._channel_details(channel_number=channel_number)
            if channel_details:
                station_schedules: list = channel_details.get("stationSchedules", [])
                if station_schedules:
                    station: dict = station_schedules[0].get("station", {})
                    station_images: list = station.get("images", [])
                    image_details: dict
                    image: list = [
                        image_details.get("url", "")
                        for image_details in station_images
                        if image_details.get("assetType", "").lower() == "station-logo-large"
                    ]
                    if image:
                        ret = image[0]

        return ret

    def _channel_title(self, channel_number: int) -> str:
        """Build the channel title for the given channel

        :param channel_number: channel number to get the title for
        :return: the channel title
        """

        ret = channel_number
        if self._channels_available:
            channel_name = self._channel_details(channel_number=channel_number).get('title')
            if channel_name:
                ret = f"{ret}{_CHANNEL_SEPARATOR} {channel_name}"

        return str(ret)

    def _current_channel_reset(self) -> None:
        """Reset all the instance channel details

        This ignores the channel number because that should be (re)set by the update method
        """

        self._channel_current["details"] = {}
        self._channel_current["listings"] = {}
        self._channel_current["program"] = {}
        self._channel_current["station_id"] = None

    def _current_program_get_position(self, _: Optional[dt_util.dt.datetime] = None) -> None:
        """Get the current position in the playing media"""

        current_program = self._channel_current.get("program")
        if current_program:
            self._media_position = _get_current_epoch() - (current_program.get("startTime") / 1000)
            self._media_position_updated_at = dt_util.utcnow()
            if "media_position" not in self._intervals:
                self._ils_create(
                    create_type="interval",
                    name="media_position",
                    func=self._current_program_get_position,
                    when=dt_util.dt.timedelta(seconds=_MEDIA_POSITION_UPDATE_INTERVAL)
                )
        else:
            self._media_position = None
            self._media_position_updated_at = None
            if "media_position" in self._intervals:
                self._ils_cancel(name="media_position", cancel_type="interval")

        asyncio.run_coroutine_threadsafe(coro=self.async_update_ha_state(), loop=self._hass.loop)

    def _current_program_set(self, _: Optional[dt_util.dt.datetime] = None) -> None:
        """Set the current program from the cached listings"""

        _LOGGER.debug(self._logger_message_format("entered"))
        current_epoch = _get_current_epoch()
        current_program = [
            program
            for program in self._channel_current["listings"]
            if (program.get("endTime") / 1000) >= current_epoch >= (program.get("startTime") / 1000)
        ]
        if current_program:
            self._channel_current["program"] = current_program[0]
            # region #-- set the program to update after this one finishes --#
            program_change_at = dt_util.dt.datetime.fromtimestamp(
                (self._channel_current["program"].get("endTime") / 1000) + 1
            )
            _LOGGER.debug(self._logger_message_format("setting to change program at: %s"), program_change_at)
            self._ils_create(
                create_type="listener",
                name="current_program",
                func=self._current_program_set,
                when=program_change_at
            )
            # endregion
        else:
            self._channel_current["program"] = None

        _LOGGER.debug(
            self._logger_message_format("current program is set: %s"),
            self._channel_current["program"] is not None
        )

        self._current_program_get_position()
        asyncio.run_coroutine_threadsafe(coro=self.async_update_ha_state(), loop=self.hass.loop)
        _LOGGER.debug(self._logger_message_format("exited"))

    def _ils_cancel(self, name: str, cancel_type: str) -> None:
        """Cancel the given interval/listener/signal"""

        _LOGGER.debug(self._logger_message_format("entered, %s: %s"), cancel_type, name)

        if cancel_type not in ("interval", "listener", "signal"):
            raise TypeError("Invalid type (%s)", cancel_type)

        unsubs = {}
        if cancel_type.lower() == "interval":
            unsubs = self._intervals
        elif cancel_type.lower() == "listener":
            unsubs = self._listeners
        elif cancel_type.lower() == "signal":
            unsubs = self._signals

        if name in unsubs:
            _LOGGER.debug(self._logger_message_format("cancelling %s: %s"), cancel_type, name)
            unsubs[name]()
            unsubs.pop(name, None)

        _LOGGER.debug(self._logger_message_format("exited"))

    def _ils_create(
        self,
        create_type: str,
        name: str,
        func: Callable,
        when: Optional[Union[dt_util.dt.timedelta, dt_util.dt.datetime]] = None
    ):
        """Create an interval, listener or signal using the given details

        `when` is required if creating an interval or listener
        `name` should be the signal to listen for if listening for a signal
        """

        _LOGGER.debug(
            self._logger_message_format("entered, type: %s, name: %s, when: %s"),
            create_type,
            name,
            when
        )

        if create_type not in ("interval", "listener", "signal"):
            raise TypeError("Invalid type (%s)", create_type)

        if not self._lock_removing.locked():
            if create_type == "interval":
                self._intervals[name] = async_track_time_interval(
                    hass=self._hass,
                    action=func,
                    interval=when
                )
            elif create_type == "listener":
                self._listeners[name] = async_track_point_in_time(
                    hass=self._hass,
                    action=func,
                    point_in_time=when
                )
            elif create_type == "signal":
                self._signals[name] = async_dispatcher_connect(
                    hass=self._hass,
                    signal=name,
                    target=func,
                )
        else:
            _LOGGER.debug(self._logger_message_format("locked not creating the %s"), create_type)

        _LOGGER.debug(self._logger_message_format("exited"))

    def _is_cache_update_required(self, cache_type: str, duration_hours: int, **kwargs) -> bool:
        """Determine if an update of the given cache is required

        :param cache_type: the type of cache to check
        :param duration_hours: how long the cache should be valid for (in hours)
        :param kwargs: additional arguments
        :return: True if an update is required, False otherwise
        """

        _LOGGER.debug(self._logger_message_format("entered, cache_type: %s"), cache_type)

        cache = self._cache_load(cache_type=cache_type, **kwargs)
        if not cache:
            return True

        cache_date = int(cache.get("updated", 0) / 1000)
        _LOGGER.debug(self._logger_message_format("last update: %d"), cache_date)
        current_epoch: int = _get_current_epoch()
        _LOGGER.debug(self._logger_message_format("current: %d"), current_epoch)
        update_at = cache_date + (duration_hours * 60 * 60)
        _LOGGER.debug(self._logger_message_format("needs updating at: %d"), update_at)

        if update_at < current_epoch:
            _LOGGER.debug(self._logger_message_format("cache is stale by %d seconds"), current_epoch - update_at)
            return True
        else:
            _LOGGER.debug(self._logger_message_format("exited --> no update required"))
            return False

    async def _async_cache_channel_mappings(self) -> None:
        """Fetch the channel mappings from the online service and cache locally

        :return: None
        """

        _LOGGER.debug(self._logger_message_format("entered"))
        async with TVChannelLists() as tvc:
            await tvc.async_fetch()
        channel_mappings: dict = tvc.channels

        # region #-- cache the channel details --#
        cache_path_channel_mappings = self._cache_get_path(cache_type="channel_mappings")
        os.makedirs(os.path.dirname(cache_path_channel_mappings), exist_ok=True)
        with open(cache_path_channel_mappings, "w") as cache_file:
            json.dump(channel_mappings, cache_file, indent=2)
        self._channel_mappings = channel_mappings  # load the mappings into the instance
        _LOGGER.debug(self._logger_message_format("channel mappings cached"))
        # endregion

        _LOGGER.debug(self._logger_message_format("exited"))

    async def _async_cache_channels(self, _: Optional[dt_util.dt.datetime] = None) -> None:
        """Fetch the channels from the online service and cache locally

        :return: None
        """

        _LOGGER.debug(self._logger_message_format("entered"))

        if self._global_flag_channel_cache.is_flagged():
            _LOGGER.debug(self._logger_message_format("exiting, already running"))
            return

        self._global_flag_channel_cache.create()
        cached_session = self._cache_load(cache_type="auth")
        try:
            async with API(
                    username=self._config.options.get(CONF_CHANNEL_USER, ""),
                    password=self._config.options.get(CONF_CHANNEL_PWD, ""),
                    existing_session=cached_session,
            ) as channels_api:
                channels = await channels_api.async_get_channels()
        except Exception as err:
            _LOGGER.error(self._logger_message_format("type: %s, message: %s", include_lineno=True), type(err), err)
            return

        # region #-- cache the channel details --#
        cache_path_channels = self._cache_get_path(cache_type="channels")
        os.makedirs(os.path.dirname(cache_path_channels), exist_ok=True)
        with open(cache_path_channels, "w") as cache_file:
            json.dump(channels, cache_file, indent=2)
        await self.async_update_ha_state()
        _LOGGER.debug(self._logger_message_format("channels cached"), len(channels))
        # endregion

        # region #-- cache the session auth details --#
        cache_path_auth = self._cache_get_path(cache_type="auth")
        os.makedirs(os.path.dirname(cache_path_auth), exist_ok=True)
        with open(cache_path_auth, "w") as auth_file:
            json.dump(channels_api.session_details, auth_file, indent=2)
        _LOGGER.debug(self._logger_message_format("auth details cached"), len(channels))
        # endregion

        # region #-- get the channel mappings cached as well if we need to --#
        if self._config.options.get(CONF_DEVICE_PLATFORM, DEF_DEVICE_PLATFORM).lower() == "v6":
            await self._async_cache_channel_mappings()
        # endregion

        self._cache_process_available_channels(channel_cache=channels)

        self._global_flag_channel_cache.delete()
        _LOGGER.debug(self._logger_message_format("exited"))

    async def _async_cache_listings(
        self,
        station_id: Optional[Union[str, dt_util.dt.datetime]] = None
    ) -> None:
        """Fetch the channel listings from the online service and cache locally

        N.B. if this function is called on an interval the station_id will be
        of type datetime. In this case we'll need to use the current station_id
        from the listings.

        :param station_id: the station ID to fetch the listings for
        :return: None
        """

        _LOGGER.debug(self._logger_message_format("entered, station_id: %s"), station_id)

        cached_session = self._cache_load(cache_type="auth")
        async with API(
            username=self._config.options.get(CONF_CHANNEL_USER, ""),
            password=self._config.options.get(CONF_CHANNEL_PWD, ""),
            existing_session=cached_session,
        ) as listings_api:
            if isinstance(station_id, dt_util.dt.datetime) or station_id is None:
                _LOGGER.debug(
                    self._logger_message_format("using stored station id: %s"),
                    self._channel_current["station_id"]
                )
                station_id = self._channel_current["station_id"]

            if station_id:
                listings = await listings_api.async_get_listing(
                    channel_id=station_id,
                    start_time=_get_current_epoch(),
                    duration_hours=self._config.options.get(CONF_CHANNEL_LISTINGS_CACHE, DEF_CHANNEL_LISTINGS_CACHE)
                )

        # region #-- cache the details --#
        if station_id:
            listings_path = self._cache_get_path(cache_type="listings", station_id=station_id)
            os.makedirs(os.path.dirname(listings_path), exist_ok=True)
            with open(listings_path, "w") as cache_file:
                json.dump(listings, cache_file, indent=2)
            self._channel_current["listings"] = listings.get("listings", [])  # load the cache into the instance
        # endregion

        _LOGGER.debug(self._logger_message_format("exited"))

    async def _async_fetch_player_state(self, _: Optional[dt_util.dt.datetime] = None) -> None:
        """Fetch the information from the player and store accordingly

        :param _: Unused parameter denoting time the method was called
        :return: None
        """

        skip_update_flags = [_FLAG_TURNING_OFF]
        if any([flag_value for flag_name, flag_value in self._flags.items() if flag_name in skip_update_flags]):
            _LOGGER.debug(self._logger_message_format("skipping due to current processing"))
            return

        async with self._lock_client:
            try:
                async with self._client:
                    try:
                        await self._client.wait_for_data()
                    except VirginMediaError as err:
                        if not isinstance(err, VirginMediaCommandTimeout):
                            _LOGGER.warning(
                                self._logger_message_format("type: %s, message: %s", include_lineno=True),
                                type(err),
                                err
                            )
                            _LOGGER.debug(
                                self._logger_message_format("device.channel_number: %s"),
                                self._client.device.channel_number
                            )
            except VirginMediaCommandTimeout:
                _LOGGER.debug(self._logger_message_format("unable to connect"))
                return
            except VirginMediaError as err:
                _LOGGER.warning(
                    self._logger_message_format("type: %s, message: %s", include_lineno=True),
                    type(err),
                    err
                )
                return

        if not self._client.device.channel_number:
            if self._channel_current["number"]:
                self._extra_state_attributes["channel_at_idle_off"] = self._channel_current["number"]
            self._channel_current["number"] = None
            self._current_channel_reset()
            self._current_program_get_position()
            if "current_program" in self._listeners:
                self._ils_cancel(name="current_program", cancel_type="listener")
            if not self._config.options.get(CONF_IDLE_TIMEOUT):
                self._state = STATE_OFF
            else:
                if self._state != STATE_OFF:
                    self._state = STATE_IDLE
                    # region #-- set up a listener to fire if we need to turn off after a period of time --#
                    if self._config.options.get(CONF_IDLE_TIMEOUT, DEF_IDLE_TIMEOUT):
                        def _idle_to_off(_: Optional[dt_util.dt.datetime] = None):
                            """Switch the player to off if idle after a period of time"""

                            _LOGGER.debug(self._logger_message_format("entered"))
                            _LOGGER.debug(self._logger_message_format("current state: %s"), self._state)
                            if self._state == STATE_IDLE:
                                _LOGGER.debug(self._logger_message_format("setting state to off"))
                                self._state = STATE_OFF
                                asyncio.run_coroutine_threadsafe(coro=self.async_update_ha_state(), loop=self.hass.loop)
                            if "idle_to_off" in self._listeners:
                                self._ils_cancel(name="idle_to_off", cancel_type="listener")
                            _LOGGER.debug(self._logger_message_format("exited"))

                        if "idle_to_off" not in self._listeners:
                            num_hours = self._config.options.get(CONF_IDLE_TIMEOUT, DEF_IDLE_TIMEOUT)
                            fire_at = dt_util.now() + dt_util.dt.timedelta(hours=num_hours)
                            _LOGGER.debug(self._logger_message_format("switching from idle to off at: %s"), fire_at)
                            self._ils_create(
                                create_type="listener",
                                name="idle_to_off",
                                func=_idle_to_off,
                                when=fire_at
                            )
                    # endregion
        else:
            if self._state != STATE_PAUSED:
                self._state = STATE_PLAYING
            if "idle_to_off" in self._listeners:
                self._ils_cancel(name="idle_to_off", cancel_type="listener")
            if self._channel_current["number"] != self._client.device.channel_number:
                _LOGGER.debug(
                    self._logger_message_format("channel changed from %s to %s"),
                    self._channel_current["number"],
                    self._client.device.channel_number
                )
                self._current_channel_reset()
                self._channel_current["number"] = self._client.device.channel_number
                if self._config.options.get(CONF_CHANNEL_FETCH_ENABLE, DEF_CHANNEL_FETCH_ENABLE):
                    if "current_program" in self._listeners:
                        self._ils_cancel(name="current_program", cancel_type="listener")
                    # region #-- get the channel details --#
                    channel_details = self._channel_details(channel_number=self._client.device.channel_number)
                    if channel_details:
                        self._channel_current["details"] = channel_details
                    # endregion

                    # region #-- get the listings for the channel --#
                    station_id: str = ""
                    if self._channel_current["details"]:
                        # region #-- get the station_id --#
                        station_schedules = self._channel_current["details"].get("stationSchedules")
                        if station_schedules:
                            station_details = station_schedules[0]
                            station_details = station_details.get("station", {})
                            station_id = station_details.get("id")
                        # endregion
                    if not station_id:
                        _LOGGER.warning(
                            self._logger_message_format("unable to retrieve station id for %d"),
                            self._channel_current["number"]
                        )
                    else:
                        self._channel_current["station_id"] = station_id
                        # region #-- load the listings cache --#
                        if self._is_cache_update_required(
                            cache_type="listings",
                            duration_hours=self._config.options.get(
                                CONF_CHANNEL_LISTINGS_CACHE,
                                DEF_CHANNEL_LISTINGS_CACHE
                            ),
                            station_id=station_id
                        ):
                            await self._async_cache_listings()
                        else:
                            cache_listings = self._cache_load(cache_type="listings", station_id=station_id)
                            self._channel_current["listings"] = cache_listings.get("listings", [])

                        # set the listings to update
                        if "listings_update" in self._listeners:
                            self._ils_cancel(cancel_type="listener", name="listings_update")
                        if self._channel_current.get("listings"):
                            prog_last = self._channel_current["listings"][-1]
                            prog_last = prog_last.get("endTime", (_get_current_epoch() * 1000))
                            cache_again_at = dt_util.dt.datetime.fromtimestamp((prog_last / 1000) - 60)
                            self._ils_create(
                                create_type="listener",
                                name="listings_update",
                                func=self._async_cache_listings,
                                when=cache_again_at,
                            )
                        # endregion

                        # region #-- set the current program --#
                        self._current_program_set()
                        # endregion
                    # endregion

        await self.async_update_ha_state()

    async def _async_send_ircode(self, code: str) -> None:
        """Sends an ircode to the device"""

        _LOGGER.debug(self._logger_message_format("entered, code: %s"), code)
        async with self._lock_client:
            async with self._client:
                try:
                    await self._client.send_ircode(code=code)
                except Exception as err:
                    _LOGGER.debug(
                        self._logger_message_format("type: %s, message: %s", include_lineno=True),
                        type(err),
                        err
                    )
                    if not isinstance(err, VirginMediaCommandTimeout) and not self._flags.get(_FLAG_TURNING_ON):
                        raise err from None
        _LOGGER.debug(self._logger_message_format("exited"))

    async def _async_send_keycode(self, code: str) -> None:
        """Sends a keycode to the device"""

        _LOGGER.debug(self._logger_message_format("entered, code: %s"), code)
        async with self._lock_client:
            async with self._client:
                try:
                    await self._client.send_keyboard(code=code)
                except Exception as err:
                    _LOGGER.warning(
                        self._logger_message_format("type: %s, message: %s", include_lineno=True),
                        type(err),
                        err
                    )
                    raise err from None
        _LOGGER.debug(self._logger_message_format("exited"))
    # endregion

    # region #-- initialise/cleanup methods --#
    async def async_added_to_hass(self) -> None:
        """Initialise the entity from a config entry

        :return: None
        """

        _LOGGER.debug(self._logger_message_format("entered"))

        # region #-- setup the channel numbers and listings if needed --#
        if self._config.options.get(CONF_CHANNEL_FETCH_ENABLE, DEF_CHANNEL_FETCH_ENABLE):
            cache_channel_duration = self._config.options.get(CONF_CHANNEL_INTERVAL, DEF_CHANNEL_INTERVAL)

            async def _async_cache_channels_start(_: Optional[dt_util.dt.datetime] = None) -> None:
                """Cache the channels and set a timer up

                :return: None
                """

                _LOGGER.debug(self._logger_message_format("entered"))
                await self._async_cache_channels()
                self._ils_create(
                    create_type="interval",
                    name="channel_cache",
                    func=self._async_cache_channels,
                    when=dt_util.dt.timedelta(
                        hours=self._config.options.get(CONF_CHANNEL_INTERVAL, DEF_CHANNEL_INTERVAL)
                    )
                )
                self._ils_cancel(name="channels_init_cache", cancel_type="listener")
                _LOGGER.debug(self._logger_message_format("exited"))

            if not self._is_cache_update_required(cache_type="channels", duration_hours=cache_channel_duration):
                # load the channels
                cache_channels = self._cache_load(cache_type="channels")
                self._channel_mappings = self._cache_load(cache_type="channel_mappings")
                self._cache_process_available_channels(channel_cache=cache_channels)
                _LOGGER.debug(self._logger_message_format("channels loaded"))
                # region #-- set up time to reload the channels 24 hours after cached time --#
                cache_started = cache_channels.get("updated", 0)
                cache_again_at = dt_util.dt.datetime.fromtimestamp(
                    (cache_started / 1000) + (cache_channel_duration * 60 * 60)
                )
                self._ils_create(
                    create_type="listener",
                    name="channels_init_cache",
                    func=_async_cache_channels_start,
                    when=cache_again_at
                )
                _LOGGER.debug(self._logger_message_format("channels will re-cache at: %s"), cache_again_at)
                # endregion
            else:
                await _async_cache_channels_start()
        # endregion

        # region #-- update now --#
        await self._async_fetch_player_state()
        self._current_program_get_position()
        # endregion

        # region #-- setup the scan interval --#
        self._ils_create(
            create_type="interval",
            name="scan_interval",
            func=self._async_fetch_player_state,
            when=dt_util.dt.timedelta(seconds=self._config.options.get(CONF_SCAN_INTERVAL, DEF_SCAN_INTERVAL))
        )
        # endregion

        # region #-- listen for signals --#
        self._ils_create(
            create_type="signal",
            name=SIGNAL_CLEAR_CACHE,
            func=self._cache_cleanup
        )
        # endregion

        _LOGGER.debug(self._logger_message_format("exited"))

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup when removing from HASS

        :return: None
        """

        _LOGGER.debug(self._logger_message_format("entered"))

        async with self._lock_removing:
            # region #-- stop the timers --#
            _LOGGER.debug(self._logger_message_format("%d intervals to stop"), len(self._intervals))
            interval_names = list(self._intervals.keys())
            for interval_name in interval_names:
                self._ils_cancel(name=interval_name, cancel_type="interval")
            # endregion

            # region #-- cancel the listeners --#
            _LOGGER.debug(self._logger_message_format("%d listeners to cancel"), len(self._listeners))
            listener_names = list(self._listeners.keys())
            for listener_name in listener_names:
                self._ils_cancel(name=listener_name, cancel_type="interval")
            # endregion

            # region #-- stop the listening for the signals --#
            _LOGGER.debug(self._logger_message_format("%d signals to stop listening for"), len(self._signals))
            signal_names = list(self._signals.keys())
            for signal_name in signal_names:
                self._ils_cancel(name=signal_name, cancel_type="signal")
            # endregion

            _LOGGER.debug(self._logger_message_format("exited"))
    # endregion

    # region #-- standard control methods --#
    async def async_browse_media(
        self,
        media_content_type: Optional[str] = None,
        media_content_id: Optional[str] = None,
    ) -> BrowseMedia:
        """Build the browse capability for the channels"""

        all_channels = [
            BrowseMedia(
                can_expand=False,
                can_play=True,
                media_class=MEDIA_CLASS_URL,  # fake the media class so the layout is a list
                media_content_type=MEDIA_TYPE_CHANNEL,
                media_content_id=channel.get("channelNumber"),
                thumbnail=self._channel_logo(channel_number=channel.get("channelNumber")),
                title=self._channel_title(channel_number=channel.get('channelNumber')),
            )
            for channel in self._channels_available
        ]

        return BrowseMedia(
            can_expand=True,
            can_play=False,
            children=all_channels,
            media_class=MEDIA_CLASS_DIRECTORY,
            media_content_id="channels",
            media_content_type=MEDIA_TYPE_CHANNELS,
            title="Channels",
        )

    async def async_media_pause(self) -> None:
        """Pause the currently playing media"""

        _LOGGER.debug(self._logger_message_format("entered"))
        try:
            await self._async_send_keycode(code="pause")
        except Exception:
            raise
        else:
            self._state = STATE_PAUSED
            await self.async_update_ha_state()
        _LOGGER.debug(self._logger_message_format("exited"))

    async def async_media_play(self) -> None:
        """Play the media"""

        _LOGGER.debug(self._logger_message_format("entered"))

        try:
            await self._async_send_keycode(code="play")
        except Exception:
            raise
        else:
            self._state = STATE_PLAYING
            await self.async_update_ha_state()
        _LOGGER.debug(self._logger_message_format("exited"))

    async def async_media_stop(self) -> None:
        """Stop the media"""

        _LOGGER.debug(self._logger_message_format("entered"))
        try:
            await self._async_send_keycode(code="stop")
        except Exception:
            raise
        else:
            await self.async_update_ha_state()
        _LOGGER.debug(self._logger_message_format("exited"))

    async def async_play_media(self, media_type, media_id, **kwargs) -> None:
        """"""

        _LOGGER.debug(
            self._logger_message_format("entered, media_type: %s, media_id: %s, kwargs: %s"),
            media_type,
            media_id,
            kwargs
        )
        if media_type == "channel":
            await self.async_select_source(source=media_id)
        else:
            _LOGGER.debug(self._logger_message_format("invalid media type (%s)"), media_type)
        _LOGGER.debug(self._logger_message_format("exited"))

    async def async_select_source(self, source) -> None:
        """Change the source of the media player"""

        _LOGGER.debug(self._logger_message_format("entered, source: %s"), source)

        if self._state == STATE_OFF:
            await self.async_turn_on()

        channel_number = int(source.split(_CHANNEL_SEPARATOR)[0])
        _LOGGER.debug(self._logger_message_format("changing source to: %s"), channel_number)
        async with self._lock_client:
            async with self._client:
                _LOGGER.debug(self._logger_message_format("issuing channel change"))
                try:
                    await self._client.set_channel(channel_number=channel_number)
                except VirginMediaInvalidChannel as err:
                    _LOGGER.warning(self._logger_message_format("%s"), err)
                except Exception:
                    raise
        await self._async_fetch_player_state()

        _LOGGER.debug(self._logger_message_format("exited"))

    async def async_turn_off(self) -> None:
        """Turn the media player off"""

        _LOGGER.debug(self._logger_message_format("entered"))
        self._flags[_FLAG_TURNING_OFF] = True
        if self._state not in (STATE_OFF, STATE_IDLE):
            _LOGGER.debug(self._logger_message_format("issuing turn off request"))
            try:
                await self._async_send_ircode(code="standby")
                await self._async_send_ircode(code="standby")
            except Exception:
                raise
            else:
                self._state = STATE_OFF
                await self.async_update_ha_state()
        else:
            _LOGGER.warning(self._logger_message_format("invalid state for turning off: %s"), self._state)
        self._flags[_FLAG_TURNING_OFF] = False
        _LOGGER.debug(self._logger_message_format("exited"))

    async def async_turn_on(self) -> None:
        """Turn the media player on"""

        _LOGGER.debug(self._logger_message_format("entered"))
        self._flags[_FLAG_TURNING_ON] = True
        if self._state in (STATE_IDLE, STATE_OFF):
            try:
                await self._async_send_ircode(code="standby")
            except Exception:
                raise
            else:
                if not self._client.device.channel_number:
                    _LOGGER.debug(self._logger_message_format("waiting for device to be ready for commands"))
                while not self._client.device.channel_number:
                    await self._async_fetch_player_state()
                    await asyncio.sleep(0.2)
                self._state = STATE_PLAYING
                await self.async_update_ha_state()
        else:
            _LOGGER.warning(self._logger_message_format("invalid state for turning on: %s"), self._state)
        self._flags[_FLAG_TURNING_ON] = False
        _LOGGER.debug(self._logger_message_format("exited"))
    # endregion

    # region #-- standard properties --#
    @property
    def device_class(self) -> Optional[str]:
        """Device class of the entity"""

        # TODO: Remove DEVICE_CLASS_TV if setting the minimum HASS version to 2021.12
        # noinspection PyUnresolvedReferences
        return DEVICE_CLASS_TV or MediaPlayerDeviceClass.TV

    @property
    def device_info(self) -> DeviceInfo:
        """Set the device information"""

        ret = DeviceInfo(**{
            "identifiers": {(DOMAIN, self._config.unique_id)},
            "manufacturer": "Virgin Media",
            "model": "TiVo",
            "name": self.name,
            "sw_version": self._config.data.get(CONF_SWVERSION, ""),
        })
        return ret

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """"""

        if self._state in (STATE_OFF, STATE_IDLE):
            ret = self._extra_state_attributes
        else:
            ret = None

        return ret

    @property
    def media_channel(self) -> Optional[str]:
        """"""

        return self._channel_current["number"]

    @property
    def media_content_type(self) -> Optional[str]:
        """Content type of the current program"""

        if self._channel_current.get("program"):
            return MEDIA_TYPE_TVSHOW
        else:
            return MEDIA_TYPE_CHANNEL

    @property
    def media_duration(self) -> Optional[int]:
        """Duration of the media currently playing"""

        current_program = self._channel_current.get("program")
        if current_program:
            start_time = current_program.get("startTime", 0)
            end_time = current_program.get("endTime", 0)
            return (end_time - start_time) / 1000

    @property
    def media_episode(self) -> Optional[str]:
        """Episode number of the currently playing media

        The guide sends back some weird numbers sometimes, so if the episode
        number is not less than `upper_episode_number` then None will be used.

        Note: Using the standard media control card, if the season is blank the
        episode is not shown. It'll still be set in the attributes though.

        :return: the episode number
        """

        episode = None
        upper_episode_number = 300
        if self._channel_current:
            current_program = self._channel_current.get("program")
            if current_program:
                program_details = current_program.get("program", {})
                if int(program_details.get("seriesEpisodeNumber", upper_episode_number)) < upper_episode_number:
                    episode = program_details.get("seriesEpisodeNumber")
        return episode

    @property
    def media_image_remotely_accessible(self) -> bool:
        """Is the image accessible remotely"""

        if self._channel_logo(channel_number=self._channel_current["number"]):
            return True
        else:
            return False

    @property
    def media_image_url(self) -> Optional[str]:
        """Set the URL for the media image"""

        return self._channel_logo(channel_number=self._channel_current["number"])

    @property
    def media_position(self) -> Optional[int]:
        """Current position for the player in seconds"""

        return self._media_position

    @property
    def media_position_updated_at(self) -> Optional[dt_util.dt.datetime]:
        """When was the media position updated?"""

        return self._media_position_updated_at

    @property
    def media_season(self) -> Optional[str]:
        """Season of the currently playing media

        The guide sends back some weird numbers sometimes, so if the season
        number is not less than `upper_season_number` it will be set None.

        Note: Using the standard media control card, if the season is empty the
        episode is not shown. It'll still be set in the attributes though.

        :return: the season number or None.
        """

        season = None
        upper_season_number = 100
        if self._channel_current:
            current_program = self._channel_current.get("program")
            if current_program:
                program_details = current_program.get("program", {})
                if int(program_details.get("seriesNumber", upper_season_number)) < upper_season_number:
                    season = program_details.get("seriesNumber")
        return season

    @property
    def media_series_title(self) -> Optional[str]:
        """The title of the current program"""

        ret = None
        if self._channel_current:
            current_program = self._channel_current.get("program")
            if current_program:
                start_time = dt_util.utc_from_timestamp(current_program.get("startTime", 0) / 1000).strftime("%H:%M")
                end_time = dt_util.utc_from_timestamp(current_program.get("endTime", 0) / 1000).strftime("%H:%M")
                title = current_program.get("program", {}).get("title", "")
                ret = f"({start_time}-{end_time}) {title}"
                secondary_title = current_program.get("program", {}).get("secondaryTitle", "")
                if secondary_title:
                    secondary_title = f" - {secondary_title}"
                categories = [
                    category.get("title", "").lower()
                    for category in current_program.get("program", {}).get("categories", [])
                ]
                if (
                    "film" in categories or
                    current_program.get("program", {}).get("mediaType", "").lower() == "featurefilm"
                ):
                    year = current_program.get("program", {}).get("year", "")
                    if year:
                        secondary_title = f" ({year})"

                if secondary_title:
                    ret = f"{ret}{secondary_title}"
        return ret

    @property
    def media_title(self) -> Optional[str]:
        """Main title of the player"""

        ret = None
        if self.state not in (STATE_IDLE, STATE_OFF):
            ret = self._channel_title(channel_number=self._channel_current.get("number"))

        return ret

    @property
    def name(self) -> str:
        """Return the name of the entity"""

        return f"{self._config.title} TiVo"

    @property
    def should_poll(self) -> bool:
        """Should we poll?"""

        return False

    @property
    def source(self) -> Optional[str]:
        """Return the current source"""

        return self.media_title

    @property
    def source_list(self) -> Optional[list[str]]:
        """"""

        if self._channels_available:
            return [
                f"{channel.get('channelNumber')}{_CHANNEL_SEPARATOR} {channel.get('title')}"
                for channel in self._channels_available
            ]

    @property
    def state(self) -> Optional[str]:
        """State of the player"""

        return self._state

    @property
    def supported_features(self) -> int:
        """Return the supported features"""

        ret = (
            SUPPORT_PAUSE |
            SUPPORT_PLAY |
            SUPPORT_STOP |
            SUPPORT_TURN_OFF |
            SUPPORT_TURN_ON
        )

        if self._config.options.get(CONF_CHANNEL_FETCH_ENABLE, DEF_CHANNEL_FETCH_ENABLE):
            if self._config.options.get(CONF_CHANNEL_USE_MEDIA_BROWSER, DEF_CHANNEL_USE_MEDIA_BROWSER):
                ret = (
                    ret |
                    SUPPORT_BROWSE_MEDIA |
                    SUPPORT_PLAY_MEDIA
                )
            else:
                ret = (
                    ret |
                    SUPPORT_SELECT_SOURCE
                )

        return ret

    @property
    def unique_id(self) -> str:
        """Unique ID for player"""

        return f"{self._config.unique_id}:media_player:{self.name}"
    # endregion
