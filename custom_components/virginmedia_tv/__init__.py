"""Initialise based on the configuration entries."""

# region #-- imports --#
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SERVICES_HANDLER, DOMAIN
from .logger import Logger
from .service_handler import VirginMediaServiceHandler

# endregion

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player", "sensor"]


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up a device from a config entry."""
    log_formatter = Logger(unique_id=config_entry.unique_id)
    _LOGGER.debug(
        log_formatter.format("Setting up config entry: %s"),
        config_entry.unique_id,
    )

    # region #-- prepare the memory storage --#
    _LOGGER.debug(log_formatter.format("preparing memory storage"))
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault(config_entry.entry_id, {})
    # endregion

    # region #-- listen for config changes --#
    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_update_listener)
    )
    # endregion

    _LOGGER.debug(
        log_formatter.format("Setting up entities for: %s"),
        config_entry.unique_id,
    )
    hass.config_entries.async_setup_platforms(config_entry, PLATFORMS)

    # region #-- Service Definition --#
    _LOGGER.debug(log_formatter.format("registering services"))
    services = VirginMediaServiceHandler(hass=hass)
    services.register_services()
    hass.data[DOMAIN][config_entry.entry_id][CONF_SERVICES_HANDLER] = services
    # endregion

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Cleanup when unloading a config entry."""
    log_formatter = Logger(unique_id=config_entry.unique_id)
    _LOGGER.debug(log_formatter.format("entered"))

    # region #-- remove services but only if there are no other instances --#
    all_config_entries = hass.config_entries.async_entries(domain=DOMAIN)
    _LOGGER.debug(log_formatter.format("%i instances"), len(all_config_entries))
    if len(all_config_entries) == 1:
        _LOGGER.debug(log_formatter.format("unregistering services"))
        services: VirginMediaServiceHandler = hass.data[DOMAIN][config_entry.entry_id][
            CONF_SERVICES_HANDLER
        ]
        services.unregister_services()
    # endregion

    # region #-- clean up the platforms --#
    _LOGGER.debug(log_formatter.format("cleaning up platforms"))
    ret = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    if ret:
        _LOGGER.debug(log_formatter.format("removing data from memory"))
        hass.data[DOMAIN].pop(config_entry.entry_id)
        ret = True
    else:
        ret = False
    # endregion

    _LOGGER.debug(log_formatter.format("exited"))
    return ret


async def _async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Reload the config entry."""
    return await hass.config_entries.async_reload(config_entry.entry_id)
