"""Initialise based on the configuration entries"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player", "sensor"]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up a device from a config entry"""

    _LOGGER.debug("Setting up config entry: %s", config_entry.unique_id)

    # region #-- listen for config changes --#
    config_entry.async_on_unload(
        config_entry.add_update_listener(
            _async_update_listener
        )
    )
    # endregion

    _LOGGER.debug("Setting up entities for: %s", config_entry.unique_id)
    hass.config_entries.async_setup_platforms(config_entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Cleanup when unloading a config entry"""

    return await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Reload the config entry"""

    return await hass.config_entries.async_reload(config_entry.entry_id)


def get_current_epoch() -> int:
    """Get the current epoch time"""

    return int(dt_util.now().timestamp())
