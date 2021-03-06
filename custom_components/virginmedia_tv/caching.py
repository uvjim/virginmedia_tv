"""Manage caching"""

# region #-- imports --#
import glob
import json
import logging
import os
from abc import ABC
from typing import (
    Any,
    List,
    Optional,
)

import homeassistant.util.dt as dt_util
from homeassistant.backports.enum import StrEnum
from homeassistant.core import HomeAssistant

from .const import (
    DEF_AUTH_FILE,
    DEF_CHANNEL_FILE,
    DEF_CHANNEL_MAPPINGS_FILE,
    DOMAIN,
)
from .flagging import VirginTvFlagFile
from .logger import VirginTvLogger
from .pyvmtvguide.api import (
    API,
    TVChannelLists,
)
from .pyvmtvguide.exceptions import VirginMediaTVGuideError

# endregion

_LOGGER = logging.getLogger(__name__)


class VirginMediaCacheType(StrEnum):
    """"""

    AUTH = "auth"
    CHANNELS = "channels"
    CHANNEL_MAPPINGS = "channel_mappings"
    LISTINGS = "listings"


class VirginMediaCache:
    """"""

    _cache_type: VirginMediaCacheType
    _leaf_path: str

    def __init__(self, hass: HomeAssistant, unique_id: str, age: int = 0) -> None:
        """Constructor

        :param age: how long the cache should be valid for (in hours)
        :param unique_id: unique_id of the entity using the cache
        :param hass: HomeAssistant object (used for path building)
        """

        self._age: int = age
        self._contents: Any = None
        self._hass: HomeAssistant = hass
        self._log_formatter = VirginTvLogger(unique_id=unique_id)
        
        self.unique_id = unique_id

    def _is_loaded(self) -> bool:
        """"""

        _LOGGER.debug(self._log_formatter.message_format("entered, cache_type: %s"), self._cache_type)
        ret = self.contents is not None
        _LOGGER.debug(self._log_formatter.message_format("exited, %s"), ret)
        return ret

    def clear(self) -> None:
        """Clear the cache in memory and on disk"""

        _LOGGER.debug(self._log_formatter.message_format("entered"))

        self._contents = None

        files: List[str]
        if "*" not in self.path:
            files = [self.path]
        else:
            files = glob.glob(self.path)

        for f in files:
            if os.path.exists(f):
                _LOGGER.debug(self._log_formatter.message_format("removing: %s"), f)
                os.remove(f)
                # check if the directory needs removing
                # doing this each go round just in case the list has multiple different locations
                dir_path = os.path.dirname(f)
                num_files_left = len([True for _ in list(os.scandir(dir_path))])
                if num_files_left == 0:
                    _LOGGER.debug(self._log_formatter.message_format("%s is empty, removing it"), dir_path)
                    os.rmdir(dir_path)

        _LOGGER.debug(self._log_formatter.message_format("exited"))

    def dump(self) -> None:
        """"""

        _LOGGER.debug(self._log_formatter.message_format("entered, cache_type: %s"), self._cache_type)

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as cache_file:
            json.dump(self._contents, cache_file, indent=2)

        _LOGGER.debug(self._log_formatter.message_format("exited, cache_type: %s"), self._cache_type)

    def fetch(self, *args, **kwargs) -> None:
        """"""

        raise NotImplementedError

    def load(self) -> Any:
        """"""

        _LOGGER.debug(self._log_formatter.message_format("entered, cache_type: %s"), self._cache_type)

        if self.path:
            if os.path.exists(self.path):
                _LOGGER.debug(self._log_formatter.message_format("loading cache from %s"), self.path)
                with open(self.path, "r") as cache_file:
                    try:
                        self._contents = json.load(cache_file)
                        _LOGGER.debug(self._log_formatter.message_format("cache loaded (%s)"), self.path)
                    except json.JSONDecodeError:
                        _LOGGER.error(self._log_formatter.message_format("invalid JSON (%s)"), self.path)
            else:
                _LOGGER.debug(self._log_formatter.message_format("cache file does not exist"))
        else:
            _LOGGER.debug(self._log_formatter.message_format("unable to establish cache file"))

        _LOGGER.debug(self._log_formatter.message_format("exited, cache_type: %s"), self._cache_type)

        return self.contents

    @property
    def contents(self) -> Any:
        """"""

        return self._contents

    @property
    def expires_at(self) -> int:
        """Return the expiry epoch for the cache"""

        ret = int(self.contents.get("updated", 0) / 1000)
        ret += (self._age * 60 * 60)

        return ret

    @property
    def is_stale(self) -> bool:
        """Determine if an update of the given cache is required

        :return: True if an update is required, False otherwise
        """

        _LOGGER.debug(self._log_formatter.message_format("entered, cache_type: %s"), self._cache_type)

        if not self._is_loaded():
            self.load()

        if not self._is_loaded():
            _LOGGER.debug(self._log_formatter.message_format("exited, cache_type: %s"), self._cache_type)
            return True

        _LOGGER.debug(self._log_formatter.message_format("last updated at: %d"), self.last_updated)

        current_epoch: int = int(dt_util.now().timestamp())
        _LOGGER.debug(self._log_formatter.message_format("current: %d"), current_epoch)
        _LOGGER.debug(self._log_formatter.message_format("needs updating at: %d"), self.expires_at)

        if self.expires_at < current_epoch:
            _LOGGER.debug(
                self._log_formatter.message_format("cache stale by %d seconds"),
                current_epoch - self.expires_at
            )
            return True
        else:
            _LOGGER.debug(self._log_formatter.message_format("exited --> no update required"))
            return False

    @property
    def last_updated(self) -> int:
        """Return the last updated epoch for the cache"""

        ret = int(self._contents.get("updated", 0) / 1000)

        return ret

    @property
    def path(self) -> str:
        """Returns the path for the specified cache

        :return: the path to the cache file
        """

        return self._hass.config.path(DOMAIN, self._leaf_path)


class VirginMediaCacheAuth(VirginMediaCache, ABC):
    """"""

    _cache_type = VirginMediaCacheType.AUTH
    _leaf_path = DEF_AUTH_FILE

    @VirginMediaCache.contents.setter
    def contents(self, value):
        """"""

        self._contents = value
        self.dump()


class VirginMediaCacheChannels(VirginMediaCache):
    """"""

    _cache_type = VirginMediaCacheType.CHANNELS
    _leaf_path = DEF_CHANNEL_FILE

    async def fetch(self, username: str, password: str) -> None:
        """Fetch the channels from the online service and cache locally"""

        _LOGGER.debug(self._log_formatter.message_format("entered, cache_type: %s"), self._cache_type)

        flag_cache = VirginTvFlagFile(path=self._hass.config.path(DOMAIN, ".channels_caching"))
        if flag_cache.is_flagged():
            _LOGGER.debug(self._log_formatter.message_format("exiting, already running"))
            return

        flag_cache.create()
        try:
            cached_session = VirginMediaCacheAuth(hass=self._hass, unique_id=self.unique_id)
            async with API(username=username, password=password, existing_session=cached_session.load()) as channel_api:
                channels = await channel_api.async_get_channels()
            if channel_api.session_details != cached_session.contents:
                _LOGGER.debug(self._log_formatter.message_format("API session details changed"))
                cached_session.contents = channel_api.session_details

        except VirginMediaTVGuideError as err:
            _LOGGER.error("Invalid credentials used when attempting to cache the available channels")
            _LOGGER.debug(
                self._log_formatter.message_format("type: %s, message: %s", include_lineno=True),
                type(err),
                err
            )
        except Exception as err:
            _LOGGER.error(
                self._log_formatter.message_format("type: %s, message: %s", include_lineno=True),
                type(err),
                err
            )
        else:
            self._contents = channels
            self.dump()
        finally:
            flag_cache.delete()
            _LOGGER.debug(self._log_formatter.message_format("exited, cache_type: %s"), self._cache_type)


class VirginMediaCacheChannelMappings(VirginMediaCache, ABC):
    """"""

    _cache_type = VirginMediaCacheType.CHANNEL_MAPPINGS
    _leaf_path = DEF_CHANNEL_MAPPINGS_FILE

    async def fetch(self) -> None:
        """"""

        _LOGGER.debug(self._log_formatter.message_format("entered, cache_type: %s"), self._cache_type)

        flag_cache = VirginTvFlagFile(path=self._hass.config.path(DOMAIN, ".channel_mappings_caching"))
        if flag_cache.is_flagged():
            _LOGGER.debug(self._log_formatter.message_format("exiting, already running"))
            return

        flag_cache.create()

        try:
            async with TVChannelLists() as tvc:
                await tvc.async_fetch()
        except Exception as err:
            _LOGGER.error(self._log_formatter.message_format(
                "type: %s, message: %s", include_lineno=True),
                type(err),
                err
            )
        else:
            self._contents = tvc.channels
            self.dump()
        finally:
            flag_cache.delete()

        _LOGGER.debug(self._log_formatter.message_format("exited, cache_type: %s"), self._cache_type)

    @VirginMediaCache.contents.setter
    def contents(self, value):
        """"""

        self._contents = value
        self.dump()


class VirginMediaCacheListings(VirginMediaCache, ABC):
    """"""

    _cache_type = VirginMediaCacheType.LISTINGS

    def __init__(self, hass: HomeAssistant, station_id: str, unique_id: str, age: Optional[int] = None) -> None:
        """Constructor

        :param age: how long the cache should be valid for (in hours)
        :param hass: HomeAssistant object (used for path building)
        :param station_id: the string representing the station ID
        :param unique_id: unique_id of the entity using the cache
        """

        super().__init__(age=age, hass=hass, unique_id=unique_id)
        self._station_id = station_id
        self._leaf_path = f"{self._station_id}.json"

    async def fetch(self, username: str, password: str) -> None:
        """"""

        _LOGGER.debug(self._log_formatter.message_format("entered, cache_type: %s"), self._cache_type)
        _LOGGER.debug(self._log_formatter.message_format("station id: %s"), self._station_id)

        flag_cache = VirginTvFlagFile(path=self._hass.config.path(DOMAIN, f".{self._station_id}_caching"))
        if flag_cache.is_flagged():
            _LOGGER.debug(self._log_formatter.message_format("exiting, already running"))
            return

        flag_cache.create()
        try:
            cached_session = VirginMediaCacheAuth(hass=self._hass, unique_id=self.unique_id)
            async with API(username=username, password=password, existing_session=cached_session.load()) as listing_api:
                listings = await listing_api.async_get_listing(
                    channel_id=self._station_id,
                    start_time=int(dt_util.now().timestamp()),
                    duration_hours=self._age,
                )
            if listing_api.session_details != cached_session.contents:
                _LOGGER.debug(self._log_formatter.message_format("API session details changed"))
                cached_session.contents = listing_api.session_details

        except Exception as err:
            _LOGGER.error(
                self._log_formatter.message_format("type: %s, message: %s", include_lineno=True),
                type(err),
                err
            )
        else:
            self._contents = listings
            self.dump()
        finally:
            flag_cache.delete()
            _LOGGER.debug(self._log_formatter.message_format("exited, cache_type: %s"), self._cache_type)

    @property
    def expires_at(self) -> int:

        prog_last = self.contents["listings"][-1]
        prog_last = prog_last.get("endTime", (int(dt_util.now().timestamp()) * 1000))

        return (prog_last / 1000) - 60
