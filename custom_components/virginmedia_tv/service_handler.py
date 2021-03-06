"""Manage the services for the pyvelop integration"""

# region #-- imports --#
import logging

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
)

from .caching import (
    VirginMediaCacheAuth,
    VirginMediaCacheChannels,
    VirginMediaCacheChannelMappings,
    VirginMediaCacheListings,
)
from .const import DOMAIN
from .logger import VirginTvLogger

# endregion


_LOGGER = logging.getLogger(__name__)


class VirginMediaServiceHandler:
    """"""

    SERVICES = {
        "clear_cache": {
            "schema":
                vol.Schema(
                    {
                        vol.Required("cache_type"): vol.In(["auth", "channels", "listings"]),
                    }
                )
        },
    }

    def __init__(self, hass: HomeAssistant) -> None:
        """Constructor"""

        self._hass: HomeAssistant = hass
        self._log_formatter: VirginTvLogger = VirginTvLogger()

    async def _async_service_call(self, call: ServiceCall) -> None:
        """Call the required method based on the given argument

        :param call: the service call that should be made
        :return: None
        """

        _LOGGER.debug(self._log_formatter.message_format("entered, call: %s"), call)

        args = call.data.copy()
        method = getattr(self, call.service, None)
        if method:
            try:
                await method(**args)
            except Exception as err:
                _LOGGER.warning(self._log_formatter.message_format("%s"), err)

        _LOGGER.debug(self._log_formatter.message_format("exited"))

    def register_services(self) -> None:
        """Register the services"""

        for service_name, service_details in self.SERVICES.items():
            self._hass.services.async_register(
                domain=DOMAIN,
                service=service_name,
                service_func=self._async_service_call,
                schema=service_details.get("schema", None),
            )

    def unregister_services(self) -> None:
        """Unregister the services"""

        for service_name, service_details in self.SERVICES.items():
            self._hass.services.async_remove(domain=DOMAIN, service=service_name)

    async def clear_cache(self, **kwargs) -> None:
        """Clear the given cache"""

        _LOGGER.debug(self._log_formatter.message_format("entered, kwargs: %s"), kwargs)

        if kwargs.get("cache_type") == "auth":
            VirginMediaCacheAuth(hass=self._hass, unique_id="").clear()
        elif kwargs.get("cache_type") == "channels":
            VirginMediaCacheChannels(hass=self._hass, unique_id="").clear()
            VirginMediaCacheChannelMappings(hass=self._hass, unique_id="").clear()
        elif kwargs.get("cache_type") == "listings":
            VirginMediaCacheListings(hass=self._hass, station_id="lgi-*", unique_id="").clear()

        _LOGGER.debug(self._log_formatter.message_format("exited"))
