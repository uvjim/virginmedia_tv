"""Sensor entities."""

# region #-- imports --#
import logging

from homeassistant.components.sensor import DOMAIN as ENTITY_DOMAIN
from homeassistant.components.sensor import SensorEntity, StateType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SWVERSION, DOMAIN, SIGNAL_SWVERSION
from .logger import Logger

# endregion

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entities."""
    async_add_entities([TiVoSoftwareSensor(hass=hass, config_entry=config_entry)])


class TiVoSoftwareSensor(SensorEntity):
    """Representation of software sensor."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialise."""
        super().__init__()

        self._hass: HomeAssistant = hass
        self._config: ConfigEntry = config_entry

        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = False
        self._attr_name = f"{self._config.title} Software Version"
        self._attr_unique_id = (
            f"{self._config.unique_id}::" f"{ENTITY_DOMAIN.lower()}::" f"{self.name}"
        )
        self._attr_should_poll = False

        self._log_formatter: Logger = Logger(unique_id=self._config.unique_id)
        self._state: str = self._config.data.get(CONF_SWVERSION, "")

    # region #-- private methods --#
    def _update_callback(self, swversion: str) -> None:
        """Update method for the sensor."""
        _LOGGER.debug(self._log_formatter.format("entered, swversion: %s"), swversion)
        _LOGGER.debug(
            self._log_formatter.format("sensor is: %s"),
            "enabled" if self.enabled else "disabled",
        )
        if self.enabled:
            self._state = swversion
            self.async_schedule_update_ha_state()
        _LOGGER.debug(self._log_formatter.format("exited"))

    # endregion

    # region #-- initialise/cleanup methods --#
    async def async_added_to_hass(self) -> None:
        """Initialise the entity from a config entry.

        :return: None
        """
        _LOGGER.debug(self._log_formatter.format("entered"))
        self.async_on_remove(
            async_dispatcher_connect(
                hass=self.hass,
                signal=SIGNAL_SWVERSION,
                target=self._update_callback,
            )
        )
        _LOGGER.debug(self._log_formatter.format("exited"))

    # endregion

    # region #-- standard properties --#
    @property
    def device_info(self) -> DeviceInfo:
        """Set the device information."""
        ret = DeviceInfo(
            **{
                "identifiers": {(DOMAIN, self._config.unique_id)},
                "manufacturer": "Virgin Media",
                "model": "TiVo",
                "name": self._config.title,
                "sw_version": self._config.data.get(CONF_SWVERSION, ""),
            }
        )
        return ret

    @property
    def native_value(self) -> StateType:
        """Sensor value."""
        return self._state

    # endregion
