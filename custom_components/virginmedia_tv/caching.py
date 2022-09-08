"""Manage caching."""

# region #-- imports --#
import glob
import json
import logging
import os
from abc import ABC
from typing import Any, List, Optional

import homeassistant.util.dt as dt_util
from homeassistant.backports.enum import StrEnum
from homeassistant.core import HomeAssistant

from .const import DEF_AUTH_FILE, DEF_CHANNEL_FILE, DEF_CHANNEL_MAPPINGS_FILE, DOMAIN
from .flagging import VirginTvFlagFile
from .logger import Logger
from .pyvmtvguide.api import API, TVChannelLists
from .pyvmtvguide.exceptions import VirginMediaTVGuideError

# endregion

_LOGGER = logging.getLogger(__name__)


class VirginMediaCacheType(StrEnum):
    """Enumeration of the possible cache types."""

    AUTH = "auth"
    CHANNELS = "channels"
    CHANNEL_MAPPINGS = "channel_mappings"
    LISTINGS = "listings"


class VirginMediaCache:
    """Representation of a genric cache object."""

    _cache_type: VirginMediaCacheType
    _leaf_path: str

    async def async_fetch(self, *args, **kwargs) -> None:
        """Stub for fetching details to cache."""
        raise NotImplementedError

    def __init__(self, hass: HomeAssistant, unique_id: str, age: int = 0) -> None:
        """Initialise.

        :param age: how long the cache should be valid for (in hours)
        :param unique_id: unique_id of the entity using the cache
        :param hass: HomeAssistant object (used for path building)
        """
        self._age: int = age
        self._contents: Any = None
        self._hass: HomeAssistant = hass
        self._log_formatter = Logger(unique_id=unique_id)

        self.unique_id = unique_id

    def _is_loaded(self) -> bool:
        """Check if the cache has been loaded."""
        _LOGGER.debug(
            self._log_formatter.format("entered, cache_type: %s"),
            self._cache_type,
        )
        ret = self.contents is not None
        _LOGGER.debug(self._log_formatter.format("exited, %s"), ret)
        return ret

    def clear(self) -> None:
        """Clear the cache in memory and on disk."""
        _LOGGER.debug(self._log_formatter.format("entered"))

        self._contents = None

        files: List[str]
        if "*" not in self.path:
            files = [self.path]
        else:
            files = glob.glob(self.path)

        for cache_file in files:
            if os.path.exists(cache_file):
                _LOGGER.debug(self._log_formatter.format("removing: %s"), cache_file)
                os.remove(cache_file)
                # check if the directory needs removing
                # doing this each go round just in case the list has multiple different locations
                dir_path = os.path.dirname(cache_file)
                num_files_left = len([True for _ in list(os.scandir(dir_path))])
                if num_files_left == 0:
                    _LOGGER.debug(
                        self._log_formatter.format("%s is empty, removing it"),
                        dir_path,
                    )
                    os.rmdir(dir_path)

        _LOGGER.debug(self._log_formatter.format("exited"))

    def dump(self) -> None:
        """Dump the contents of the cache to a file."""
        _LOGGER.debug(
            self._log_formatter.format("entered, cache_type: %s"),
            self._cache_type,
        )

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf8") as cache_file:
            json.dump(self._contents, cache_file, indent=2)

        _LOGGER.debug(
            self._log_formatter.format("exited, cache_type: %s"),
            self._cache_type,
        )

    def fetch(self, *args, **kwargs) -> None:
        """Stub for fetching details to cache."""
        raise NotImplementedError

    def load(self) -> Any:
        """Load the contents of the cache into memory."""
        _LOGGER.debug(
            self._log_formatter.format("entered, cache_type: %s"),
            self._cache_type,
        )

        if self.path:
            if os.path.exists(self.path):
                _LOGGER.debug(
                    self._log_formatter.format("loading cache from %s"),
                    self.path,
                )
                with open(self.path, "r", encoding="utf8") as cache_file:
                    try:
                        self._contents = json.load(cache_file)
                        _LOGGER.debug(
                            self._log_formatter.format("cache loaded (%s)"),
                            self.path,
                        )
                    except json.JSONDecodeError:
                        _LOGGER.error(
                            self._log_formatter.format("invalid JSON (%s)"),
                            self.path,
                        )
            else:
                _LOGGER.debug(self._log_formatter.format("cache file does not exist"))
        else:
            _LOGGER.debug(self._log_formatter.format("unable to establish cache file"))

        _LOGGER.debug(
            self._log_formatter.format("exited, cache_type: %s"),
            self._cache_type,
        )

        return self.contents

    @property
    def contents(self) -> Any:
        """Return the contents of the cache."""
        return self._contents

    @property
    def expires_at(self) -> int:
        """Return the expiry epoch for the cache."""
        ret = int(self.contents.get("updated", 0) / 1000)
        ret += self._age * 60 * 60

        return ret

    @property
    def is_stale(self) -> bool:
        """Determine if an update of the given cache is required.

        :return: True if an update is required, False otherwise
        """
        _LOGGER.debug(
            self._log_formatter.format("entered, cache_type: %s"),
            self._cache_type,
        )

        if not self._is_loaded():
            self.load()

        if not self._is_loaded():
            _LOGGER.debug(
                self._log_formatter.format("exited, cache_type: %s"),
                self._cache_type,
            )
            return True

        _LOGGER.debug(
            self._log_formatter.format("last updated at: %d"), self.last_updated
        )

        current_epoch: int = int(dt_util.now().timestamp())
        _LOGGER.debug(self._log_formatter.format("current: %d"), current_epoch)
        _LOGGER.debug(
            self._log_formatter.format("needs updating at: %d"), self.expires_at
        )

        if self.expires_at < current_epoch:
            _LOGGER.debug(
                self._log_formatter.format("cache stale by %d seconds"),
                current_epoch - self.expires_at,
            )
            return True
        else:
            _LOGGER.debug(self._log_formatter.format("exited --> no update required"))
            return False

    @property
    def last_updated(self) -> int:
        """Return the last updated epoch for the cache."""
        ret = int(self._contents.get("updated", 0) / 1000)

        return ret

    @property
    def path(self) -> str:
        """Return the path for the specified cache.

        :return: the path to the cache file
        """
        return self._hass.config.path(DOMAIN, self._leaf_path)


class VirginMediaCacheAuth(VirginMediaCache, ABC):
    """Representation of the Authentication cache."""

    _cache_type = VirginMediaCacheType.AUTH
    _leaf_path = DEF_AUTH_FILE

    @VirginMediaCache.contents.setter
    def contents(self, value):
        """Return the contents of the cache."""
        self._contents = value
        self.dump()


class VirginMediaCacheChannels(VirginMediaCache):
    """Representation of the channels."""

    _cache_type = VirginMediaCacheType.CHANNELS
    _leaf_path = DEF_CHANNEL_FILE

    async def async_fetch(self, username: str, password: str) -> None:
        """Fetch the channels from the online service and cache locally."""
        _LOGGER.debug(
            self._log_formatter.format("entered, cache_type: %s"),
            self._cache_type,
        )

        flag_cache = VirginTvFlagFile(
            path=self._hass.config.path(DOMAIN, ".channels_caching")
        )
        if flag_cache.is_flagged():
            _LOGGER.debug(self._log_formatter.format("exiting, already running"))
            return

        flag_cache.create()
        try:
            cached_session = VirginMediaCacheAuth(
                hass=self._hass, unique_id=self.unique_id
            )
            async with API(
                username=username,
                password=password,
                existing_session=cached_session.load(),
            ) as channel_api:
                channels = await channel_api.async_get_channels()
            if channel_api.session_details != cached_session.contents:
                _LOGGER.debug(self._log_formatter.format("API session details changed"))
                cached_session.contents = channel_api.session_details

        except VirginMediaTVGuideError as err:
            _LOGGER.error(
                "Invalid credentials used when attempting to cache the available channels"
            )
            _LOGGER.debug(
                self._log_formatter.format(
                    "type: %s, message: %s", include_lineno=True
                ),
                type(err),
                err,
            )
        except Exception as err:
            _LOGGER.error(
                self._log_formatter.format(
                    "type: %s, message: %s", include_lineno=True
                ),
                type(err),
                err,
            )
        else:
            self._contents = channels
            self.dump()
        finally:
            flag_cache.delete()
            _LOGGER.debug(
                self._log_formatter.format("exited, cache_type: %s"),
                self._cache_type,
            )


class VirginMediaCacheChannelMappings(VirginMediaCache, ABC):
    """Representation of the channel mappings."""

    _cache_type = VirginMediaCacheType.CHANNEL_MAPPINGS
    _leaf_path = DEF_CHANNEL_MAPPINGS_FILE

    async def async_fetch(self) -> None:
        """Retrieve the channel mappings from the online service."""
        _LOGGER.debug(
            self._log_formatter.format("entered, cache_type: %s"),
            self._cache_type,
        )

        flag_cache = VirginTvFlagFile(
            path=self._hass.config.path(DOMAIN, ".channel_mappings_caching")
        )
        if flag_cache.is_flagged():
            _LOGGER.debug(self._log_formatter.format("exiting, already running"))
            return

        flag_cache.create()

        try:
            async with TVChannelLists() as tvc:
                await tvc.async_fetch()
        except Exception as err:
            _LOGGER.error(
                self._log_formatter.format(
                    "type: %s, message: %s", include_lineno=True
                ),
                type(err),
                err,
            )
        else:
            self._contents = tvc.channels
            self.dump()
        finally:
            flag_cache.delete()

        _LOGGER.debug(
            self._log_formatter.format("exited, cache_type: %s"),
            self._cache_type,
        )

    @VirginMediaCache.contents.setter
    def contents(self, value):
        """Return the contents of the cache."""
        self._contents = value
        self.dump()


class VirginMediaCacheListings(VirginMediaCache, ABC):
    """Representation of the Listings cache."""

    _cache_type = VirginMediaCacheType.LISTINGS

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str,
        unique_id: str,
        age: Optional[int] = None,
    ) -> None:
        """Initialise.

        :param age: how long the cache should be valid for (in hours)
        :param hass: HomeAssistant object (used for path building)
        :param station_id: the string representing the station ID
        :param unique_id: unique_id of the entity using the cache
        """
        super().__init__(age=age, hass=hass, unique_id=unique_id)
        self._station_id = station_id
        self._leaf_path = f"{self._station_id}.json"

    async def async_fetch(self, username: str, password: str) -> None:
        """Retrieve the listings from the API."""
        _LOGGER.debug(
            self._log_formatter.format("entered, cache_type: %s"),
            self._cache_type,
        )
        _LOGGER.debug(self._log_formatter.format("station id: %s"), self._station_id)

        flag_cache = VirginTvFlagFile(
            path=self._hass.config.path(DOMAIN, f".{self._station_id}_caching")
        )
        if flag_cache.is_flagged():
            _LOGGER.debug(self._log_formatter.format("exiting, already running"))
            return

        flag_cache.create()
        try:
            cached_session = VirginMediaCacheAuth(
                hass=self._hass, unique_id=self.unique_id
            )
            async with API(
                username=username,
                password=password,
                existing_session=cached_session.load(),
            ) as listing_api:
                listings = await listing_api.async_get_listing(
                    channel_id=self._station_id,
                    start_time=int(dt_util.now().timestamp()),
                    duration_hours=self._age,
                )
            if listing_api.session_details != cached_session.contents:
                _LOGGER.debug(self._log_formatter.format("API session details changed"))
                cached_session.contents = listing_api.session_details

        except Exception as err:
            _LOGGER.error(
                self._log_formatter.format(
                    "type: %s, message: %s", include_lineno=True
                ),
                type(err),
                err,
            )
        else:
            self._contents = listings
            self.dump()
        finally:
            flag_cache.delete()
            _LOGGER.debug(
                self._log_formatter.format("exited, cache_type: %s"),
                self._cache_type,
            )

    @property
    def expires_at(self) -> int:
        """Return when the listings expire."""
        prog_last = self.contents["listings"][-1]
        prog_last = prog_last.get("endTime", (int(dt_util.now().timestamp()) * 1000))

        return (prog_last / 1000) - 60
