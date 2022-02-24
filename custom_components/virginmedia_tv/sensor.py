"""Sensor entities"""

import asyncio
import logging
from typing import Optional

from homeassistant.components.sensor import (
    SensorEntity,
    StateType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ENTITY_CATEGORY_DIAGNOSTIC,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_SWVERSION,
    DOMAIN,
    SIGNAL_SWVERSION,
)
from .logger import VirginTvLogger

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entities"""

    async_add_entities(
        [
            TiVoSoftwareSensor(hass=hass, config_entry=config_entry)
        ]
    )


# noinspection PyAbstractClass
class TiVoSoftwareSensor(SensorEntity, VirginTvLogger):
    """Representation of software sensor"""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Constructor"""

        super().__init__()
        self._hass: HomeAssistant = hass
        self._config: ConfigEntry = config_entry
        self._state: str = self._config.data.get(CONF_SWVERSION, "")

    # region #-- private methods --#
    def _update_callback(self, swversion: str) -> None:
        """Update method for the sensor"""

        _LOGGER.debug(self._logger_message_format("entered, swversion: %s"), swversion)
        _LOGGER.debug(self._logger_message_format("sensor is: %s"), "enabled" if self.enabled else "disabled")
        if self.enabled:
            self._state = swversion
            asyncio.run_coroutine_threadsafe(coro=self.async_update_ha_state(), loop=self._hass.loop)
        _LOGGER.debug(self._logger_message_format("exited"))
    # endregion

    # region #-- initialise/cleanup methods --#
    async def async_added_to_hass(self) -> None:
        """Initialise the entity from a config entry

        :return: None
        """

        _LOGGER.debug(self._logger_message_format("entered"))
        self.async_on_remove(
            async_dispatcher_connect(
                hass=self.hass,
                signal=SIGNAL_SWVERSION,
                target=self._update_callback,
            )
        )
        _LOGGER.debug(self._logger_message_format("exited"))
    # endregion

    # region #-- standard properties --#
    @property
    def device_info(self) -> DeviceInfo:
        """Set the device information"""

        ret = DeviceInfo(**{
            "identifiers": {(DOMAIN, self._config.unique_id)},
            "manufacturer": "Virgin Media",
            "model": "TiVo",
            "name": self._config.title,
            "sw_version": self._config.data.get(CONF_SWVERSION, ""),
        })
        return ret

    @property
    def entity_category(self) -> Optional[str]:
        """Entity category"""

        return ENTITY_CATEGORY_DIAGNOSTIC

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Disable the entity by default"""

        return False

    @property
    def name(self) -> Optional[str]:
        """Friendly name"""

        return f"{self._config.title} Software Version"

    @property
    def native_value(self) -> StateType:
        """Sensor value"""

        return self._state

    @property
    def unique_id(self) -> str:
        """Unique ID"""

        return f"{self._config.unique_id}:sensor:{self.name}"
    # endregion
