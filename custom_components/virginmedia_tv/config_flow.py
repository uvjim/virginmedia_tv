""""""

# region #-- imports --#
import logging
from typing import Union

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import callback, HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import DiscoveryInfoType

from .const import (
    CONF_CACHE_CLEAR,
    CONF_CACHE_CONFIRM,
    CONF_CHANNEL_FETCH_ENABLE,
    CONF_CHANNEL_INTERVAL,
    CONF_CHANNEL_PWD,
    CONF_CHANNEL_REGION,
    CONF_CHANNEL_USE_MEDIA_BROWSER,
    CONF_CHANNEL_USER,
    CONF_COMMAND_TIMEOUT,
    CONF_CONNECT_TIMEOUT,
    CONF_CREDS_CLEAR,
    CONF_DEVICE_PLATFORM,
    CONF_FLOW_NAME,
    CONF_HOST,
    CONF_IDLE_TIMEOUT,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SWVERSION,
    CONF_TITLE_PLACEHOLDERS,
    CONF_ZNAME,
    DEF_CACHE_CLEAR,
    DEF_CACHE_CONFIRM,
    DEF_CHANNEL_FETCH_ENABLE,
    DEF_CHANNEL_INTERVAL,
    DEF_CHANNEL_INTERVAL_MIN,
    DEF_CHANNEL_REGION,
    DEF_CHANNEL_USE_MEDIA_BROWSER,
    DEF_COMMAND_TIMEOUT,
    DEF_CONNECT_TIMEOUT,
    DEF_CREDS_CLEAR,
    DEF_DEVICE_PLATFORM,
    DEF_FLOW_NAME,
    DEF_IDLE_TIMEOUT,
    DEF_PORT,
    DEF_SCAN_INTERVAL,
    DOMAIN,
    KNOWN_PLATFORMS,
    KNOWN_V6_REGIONS,
    SIGNAL_CLEAR_CACHE,
    SIGNAL_SWVERSION,
    STEP_CACHE_CONFIRM,
    STEP_CACHE_MANAGE,
    STEP_DEVICE_PLATFORM,
    STEP_OPTIONS,
    STEP_TIMEOUTS,
    STEP_TIVO,
    STEP_V6_REGION,
    STEP_VIRGIN_CREDS,
)
from .logger import VirginTvLogger
from .pyvmtvguide.api import API as VirginMediaAPI
from .pyvmtvguide.exceptions import VirginMediaTVGuideError

# TODO: remove this try/except block when setting the minimum HASS version to 2021.12
# HASS 2021.12 uses dataclasses for discovery information
try:
    from homeassistant.components.zeroconf import ZeroconfServiceInfo
except ImportError:
    ZeroconfServiceInfo = None
# endregion

_LOGGER = logging.getLogger(__name__)


def _get_tivo_name(discovery_info: Union[DiscoveryInfoType, ZeroconfServiceInfo]) -> str:
    """Determine the friendliest device name to use

    :param discovery_info: details provided by the discovery service
    :return: string containing a friendly name
    """

    if not ZeroconfServiceInfo:
        ret: str = (
                discovery_info.get("name", "").split(".")[0] or
                discovery_info.get("hostname", "").split(".")[0] or
                discovery_info.get("host", "")
        )
    else:
        ret: str = (
                discovery_info.name.split(".")[0] or
                discovery_info.hostname.split(".")[0] or
                discovery_info.host
        )

    return ret


def _is_existing_configured_tivo(hass: HomeAssistant, address: str) -> Union[config_entries.ConfigEntry, None]:
    """Check if the specified device is already configured

    :param hass: the hass object
    :param address: IP address of device to look for
    :return: the configuration entry if the device is configured, None otherwise
    """

    configured_tivos = hass.config_entries.async_entries(domain=DOMAIN)
    for tivo in configured_tivos:
        if tivo.data.get(CONF_HOST).lower() == address.lower():
            return tivo


def _is_valid_tivo(discovery_info: Union[DiscoveryInfoType, ZeroconfServiceInfo]) -> bool:
    """Check if there's enough info to be a valid TiVo device

    :param discovery_info: info provided by the discovery service
    :return: True if valid, False otherwise
    """

    if not ZeroconfServiceInfo:
        return (
                discovery_info.get("host") and
                discovery_info.get("port") and
                discovery_info.get("properties", {}).get("TSN")
        )
    else:
        return (
                discovery_info.host and
                discovery_info.port and
                discovery_info.properties.get("TSN")
        )


# noinspection PyUnusedLocal
async def _async_build_schema_with_user_input(step: str, user_input: dict, **kwargs) -> vol.Schema:
    """Build the input and validation schema for the config UI

    :param step: the step we're in for a configuration or installation of the integration
    :param user_input: the data that should be used as defaults
    :param kwargs: additional information that might be required
    :return: the schema including necessary restrictions, defaults, pre-selections etc.
    """

    schema = {}

    if step == STEP_CACHE_CONFIRM:
        schema = {
            vol.Required(
                CONF_CACHE_CONFIRM,
                default=user_input.get(CONF_CACHE_CONFIRM, DEF_CACHE_CONFIRM)
            ): vol.In({True: "Yes", False: "No"})
        }

    if step == STEP_CACHE_MANAGE:
        schema = {
            vol.Required(
                CONF_CREDS_CLEAR,
                default=user_input.get(CONF_CREDS_CLEAR, DEF_CREDS_CLEAR)
            ): cv.boolean,
            vol.Required(
                CONF_CACHE_CLEAR,
                default=user_input.get(CONF_CACHE_CLEAR, DEF_CACHE_CLEAR)
            ): cv.boolean,
        }

    if step == STEP_DEVICE_PLATFORM:
        schema = {
             vol.Required(
                 CONF_DEVICE_PLATFORM,
                 default=user_input.get(CONF_DEVICE_PLATFORM, DEF_DEVICE_PLATFORM)
             ): vol.In(KNOWN_PLATFORMS),
        }

    if step == STEP_OPTIONS:
        schema = {
            vol.Required(
                CONF_CHANNEL_FETCH_ENABLE,
                default=user_input.get(CONF_CHANNEL_FETCH_ENABLE, DEF_CHANNEL_FETCH_ENABLE)
            ): cv.boolean,
            vol.Required(
                CONF_CHANNEL_USE_MEDIA_BROWSER,
                default=user_input.get(CONF_CHANNEL_USE_MEDIA_BROWSER, DEF_CHANNEL_USE_MEDIA_BROWSER)
            ): cv.boolean,
        }

    if step == STEP_TIMEOUTS:
        schema = {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=user_input.get(CONF_SCAN_INTERVAL, DEF_SCAN_INTERVAL)
            ): cv.positive_int,
            vol.Required(
                CONF_IDLE_TIMEOUT,
                default=user_input.get(CONF_IDLE_TIMEOUT, DEF_IDLE_TIMEOUT)
            ): cv.positive_float,
        }
        if kwargs.get("show_channel_timeouts", False):
            schema.update({
                vol.Required(
                    CONF_CHANNEL_INTERVAL,
                    default=user_input.get(CONF_CHANNEL_INTERVAL, DEF_CHANNEL_INTERVAL)
                ): vol.All(cv.positive_int, vol.Range(min=DEF_CHANNEL_INTERVAL_MIN)),
            })

    if step == STEP_TIVO:
        schema = {
            vol.Required(
                CONF_HOST,
            ): cv.string,
            vol.Required(
                CONF_PORT,
                default=user_input.get(CONF_PORT, DEF_PORT)
            ): cv.port,
        }

    if step == STEP_V6_REGION:
        schema = {
            vol.Required(
                CONF_CHANNEL_REGION,
                default=user_input.get(CONF_CHANNEL_REGION, DEF_CHANNEL_REGION)
            ): vol.In(KNOWN_V6_REGIONS),
        }

    if step == STEP_VIRGIN_CREDS:
        schema = {
            vol.Required(
                CONF_CHANNEL_USER,
                default=user_input.get(CONF_CHANNEL_USER)
            ): cv.string,
            vol.Required(
                CONF_CHANNEL_PWD,
                default=user_input.get(CONF_CHANNEL_PWD)
            ): cv.string,
        }

    return vol.Schema(schema)


# noinspection DuplicatedCode
class VirginTvHandler(config_entries.ConfigFlow, VirginTvLogger, domain=DOMAIN):
    """
    Paths:
        user --> tivo details --> options (none selected) --> timeouts --> finish
        user --> tivio details --> options (something selected) --> virgin_creds --> timeouts --> finish
        zeroconf --> options (none selected) --> timeouts --> finish
        zeroconf --> options (something selected) --> virgin_creds --> timeouts --> finish
    """

    task_login = None

    def __init__(self) -> None:
        """Constructor"""

        self._data: dict = {}
        self._errors: dict = {}
        self._options: dict = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Get the options flow for this handler"""

        return VirginTvOptionsFlowHandler(config_entry=config_entry)

    async def _async_task_login(self, user_input) -> None:
        """Login to the Virgin Media online service

        :param user_input: credentials for login
        :return: None
        """

        _LOGGER.debug(self._logger_message_format("entered, user_input: %s"), user_input)
        async with VirginMediaAPI(**user_input) as vm_api:
            try:
                await vm_api.async_login()
            except VirginMediaTVGuideError as err:
                _LOGGER.debug(self._logger_message_format("type: %s, message: %s", include_lineno=True), type(err), err)
                self._errors["base"] = "login_error"

        self.hass.async_create_task(self.hass.config_entries.flow.async_configure(flow_id=self.flow_id))
        _LOGGER.debug(self._logger_message_format("exited"))

    async def async_step_finish(self) -> data_entry_flow.FlowResult:
        """Create the configuration entry

        Should always be the last step in the flow
        """

        _LOGGER.debug(self._logger_message_format("entered"))
        title = self.context.get(CONF_TITLE_PLACEHOLDERS, {}).get(CONF_FLOW_NAME) or DEF_FLOW_NAME
        _LOGGER.debug(
            self._logger_message_format("creating entry --> title: %s; data: %s; options: %s"),
            title,
            self._data,
            self._options
        )
        return self.async_create_entry(title=title, data=self._data, options=self._options)

    async def async_step_login(self, user_input=None) -> data_entry_flow.FlowResult:
        """Initiate the login task

        :param user_input: details entered by the user
        :return: the necessary FlowResult
        """

        _LOGGER.debug(self._logger_message_format("entered, user_input: %s"), user_input)
        if not self.task_login:
            _LOGGER.debug(self._logger_message_format("creating login task"))
            details: dict = {
                "username": self._options.get(CONF_CHANNEL_USER),
                "password": self._options.get(CONF_CHANNEL_PWD),
            }
            self.task_login = self.hass.async_create_task(
                self._async_task_login(user_input=details)
            )
            return self.async_show_progress(step_id="login", progress_action="task_login")

        try:
            _LOGGER.debug(self._logger_message_format("running login task"))
            await self.task_login
            _LOGGER.debug(self._logger_message_format("returned from login task"))
        except Exception as err:
            _LOGGER.debug(self._logger_message_format("exception: %s"), err)
            return self.async_abort(reason="abort_login")

        _LOGGER.debug(self._logger_message_format("_errors: %s"), self._errors)
        if self._errors:
            return self.async_show_progress_done(next_step_id=STEP_VIRGIN_CREDS)

        return self.async_show_progress_done(next_step_id=STEP_TIMEOUTS)

    async def async_step_options(self, user_input=None) -> data_entry_flow.FlowResult:
        """Generic options for the integration"""

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            self._options.update(user_input)
            # region #-- where to next? --#
            get_creds = any([v for k, v in user_input.items()])
            if get_creds:
                return await self.async_step_virgin_creds()
            else:
                return await self.async_step_timeouts()
            # endregion

        return self.async_show_form(
            step_id=STEP_OPTIONS,
            data_schema=await _async_build_schema_with_user_input(STEP_OPTIONS, self._options),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_timeouts(self, user_input=None) -> data_entry_flow.FlowResult:
        """Prompt for configurable timeouts"""

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            self._options[CONF_CONNECT_TIMEOUT] = DEF_CONNECT_TIMEOUT
            self._options[CONF_COMMAND_TIMEOUT] = DEF_COMMAND_TIMEOUT
            self._options.update(user_input)
            return await self.async_step_finish()

        return self.async_show_form(
            step_id=STEP_TIMEOUTS,
            data_schema=await _async_build_schema_with_user_input(
                STEP_TIMEOUTS,
                self._options,
                show_channel_timeouts=self._options.get(CONF_CHANNEL_FETCH_ENABLE, DEF_CHANNEL_FETCH_ENABLE),
            ),
            errors=self._errors,
        )

    async def async_step_tivo(self, user_input=None) -> data_entry_flow.FlowResult:
        """Prompt for TiVo details

        Should only end up here if not configuring from a discovered device
        """

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            # region #-- check if the tivo already exists --#
            _LOGGER.debug(self._logger_message_format("Checking if TiVo exists by address"))
            tivo = _is_existing_configured_tivo(hass=self.hass, address=user_input.get(CONF_HOST))
            if tivo:
                _LOGGER.debug(
                    self._logger_message_format("found existing TiVo with address %s"),
                    user_input.get(CONF_HOST)
                )
                return self.async_abort(reason="already_configured")
            # end region

            # region #-- set the data and move on --#
            self._data.update(user_input)
            return await self.async_step_options()
            # endregion

        return self.async_show_form(
            step_id=STEP_TIVO,
            data_schema=await _async_build_schema_with_user_input(STEP_TIVO, self._options),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_user(self, user_input=None) -> data_entry_flow.FlowResult:
        """Entry point for the flow"""

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)

        return await self.async_step_tivo()

    async def async_step_virgin_creds(self, user_input=None) -> data_entry_flow.FlowResult:
        """Get the Virgin Media credentials"""

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            self.task_login = None
            self._errors = {}
            self._options.update(user_input)
            return await self.async_step_login()

        return self.async_show_form(
            step_id=STEP_VIRGIN_CREDS,
            data_schema=await _async_build_schema_with_user_input(STEP_VIRGIN_CREDS, self._options),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_zeroconf(
        self,
        discovery_info: Union[DiscoveryInfoType, ZeroconfServiceInfo]
    ) -> data_entry_flow.FlowResult:
        """Entry point for an automatically discovered device"""

        _LOGGER.debug(self._logger_message_format("discovery_info: %s"), discovery_info)

        if not _is_valid_tivo(discovery_info):
            self.async_abort(reason="incomplete_tivo")

        if not ZeroconfServiceInfo:
            host = discovery_info.get("host")
            port = discovery_info.get("port")
            serial = discovery_info.get("properties", {}).get("TSN")
            swversion = discovery_info.get("properties", {}).get("swversion", "")
            zname = discovery_info.get("name")
        else:
            host = discovery_info.host
            port = discovery_info.port
            serial = discovery_info.properties.get("TSN")
            swversion = discovery_info.properties.get("swversion", "")
            zname = discovery_info.name

        # region #-- set the unique_id --#
        if serial:
            _LOGGER.debug(self._logger_message_format("unique_id: %s"), serial)
            await self.async_set_unique_id(serial)
            _LOGGER.debug(self._logger_message_format("dispatching swversion message"))
            async_dispatcher_send(self.hass, SIGNAL_SWVERSION, swversion)
            _LOGGER.debug(self._logger_message_format("aborting if already configured"))
            self._abort_if_unique_id_configured()
        # endregion

        # region #-- check if the TiVo has already been manually configured --#
        _LOGGER.debug(self._logger_message_format("checking if TiVo exists by address"))
        tivo = _is_existing_configured_tivo(hass=self.hass, address=host)
        if tivo:
            _LOGGER.debug(self._logger_message_format("found existing TiVo with address %s"), host)
            _LOGGER.debug(self._logger_message_format("updating"))
            self.hass.config_entries.async_update_entry(entry=tivo, unique_id=serial)
            _LOGGER.debug(self._logger_message_format("dispatching swversion message"))
            async_dispatcher_send(self.hass, SIGNAL_SWVERSION, swversion)
            return self.async_abort(reason="already_configured")
        else:
            _LOGGER.debug(self._logger_message_format("no existing TiVo found"))
        # endregion

        # region #-- set flow title --#
        self.context[CONF_TITLE_PLACEHOLDERS] = {CONF_FLOW_NAME: _get_tivo_name(discovery_info)}
        # endregion

        # region #-- set the data --#
        self._data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_SWVERSION: swversion,
            CONF_ZNAME: zname,
        }
        # endregion

        return await self.async_step_options()


# noinspection DuplicatedCode
class VirginTvOptionsFlowHandler(config_entries.OptionsFlow, VirginTvLogger):
    """Handle options from the configuration of the integration

    Paths:
        init --> device_platform (v6 not selected) --> options (unselected) --> cache_manage
            --> instances still configured --> cache_confirm --> timeouts --> finish
        init --> device_platform (v6 not selected) --> options (selected) --> virgin_creds --> timeouts
            --> finish
        init --> device_platform (v6 selected) --> options (unselected) --> cache_manage
            --> instances still configured --> cache_confirm --> timeouts --> finish
        init --> device_platform (v6 selected) --> options (selected) --> virgin_creds --> channel_region
            --> timeouts --> finish
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Constructor"""

        super().__init__()
        self._cache_to_clean: dict = {}
        self._config_entry: config_entries.ConfigEntry = config_entry
        self._data: dict = dict(config_entry.data)
        self._errors: dict = {}
        self._options: dict = dict(config_entry.options)
        self._logger_prefix: str = "options "

        self.unique_id: str = self._config_entry.unique_id

    def _cache_do_cleanup(self) -> None:
        """Trigger the cache cleanup"""

        # region #-- check for channel cache cleanup --#
        if self._cache_to_clean.get(CONF_CACHE_CLEAR, DEF_CACHE_CLEAR):
            _LOGGER.debug(self._logger_message_format("dispatching clear channel cache signal"))
            async_dispatcher_send(self.hass, SIGNAL_CLEAR_CACHE, "channel")
        # endregion

        # region #-- check for credential cache cleanup --#
        if self._cache_to_clean.get(CONF_CREDS_CLEAR, DEF_CREDS_CLEAR):
            _LOGGER.debug(self._logger_message_format("clearing credentials"))
            to_clear = (CONF_CHANNEL_PWD, CONF_CHANNEL_USER, CONF_CREDS_CLEAR)
            for prop in to_clear:
                self._options.pop(prop, None)
            _LOGGER.debug(self._logger_message_format("dispatching clear session cache signal"))
            async_dispatcher_send(self.hass, SIGNAL_CLEAR_CACHE, "auth")
            _LOGGER.debug(self._logger_message_format("cleared credentials"))
        # endregion

        # reset the instance variable
        self._cache_to_clean = {}

    async def async_step_cache_confirm(self, user_input=None) -> data_entry_flow.FlowResult:
        """Prompt for confirmation if other instances are configured"""

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            if user_input.get(CONF_CACHE_CONFIRM, DEF_CACHE_CONFIRM):
                self._cache_do_cleanup()
            return await self.async_step_timeouts()

        # region #-- get the names of the currently configured instances --#
        configured_instances = self.hass.config_entries.async_entries(domain=DOMAIN)
        configured_instances_text = [
            f"{idx}. {instance.title} <i>({'disabled' if instance.disabled_by else 'enabled'})</i>"
            for idx, instance in enumerate(configured_instances)
            if instance.unique_id != self._config_entry.unique_id
        ]
        # endregion

        return self.async_show_form(
            step_id=STEP_CACHE_CONFIRM,
            data_schema=await _async_build_schema_with_user_input(STEP_CACHE_CONFIRM, self._options),
            description_placeholders={"configured_instances": "\n".join(configured_instances_text)},
            errors=self._errors,
            last_step=False,
        )

    async def async_step_cache_manage(self, user_input=None) -> data_entry_flow.FlowResult:
        """Determine what to do with the cache

        These options aren't stored in the entry but should kick off actions to clean up
        """

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            configured_instances = self.hass.config_entries.async_entries(domain=DOMAIN)
            self._cache_to_clean.update(user_input)
            any_cache_selected = any(dict(user_input).values())
            if any_cache_selected and len(configured_instances) > 1:  # need to clean and other configured items
                return await self.async_step_cache_confirm()
            else:
                self._cache_do_cleanup()
                return await self.async_step_timeouts()

        return self.async_show_form(
            step_id=STEP_CACHE_MANAGE,
            data_schema=await _async_build_schema_with_user_input(STEP_CACHE_MANAGE, self._options),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_device_platform(self, user_input=None) -> data_entry_flow.FlowResult:
        """Prompt for the device platform

        Should be able to determine this automatically really but don't have any other platforms
        to test with. This step is only available after initial configuration.
        """

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_options()

        return self.async_show_form(
            step_id=STEP_DEVICE_PLATFORM,
            data_schema=await _async_build_schema_with_user_input(STEP_DEVICE_PLATFORM, self._options),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_init(self, _=None) -> data_entry_flow.FlowResult:
        """Entry point for the flow"""

        _LOGGER.debug(self._logger_message_format("entered"))

        return await self.async_step_device_platform()

    async def async_step_options(self, user_input=None) -> data_entry_flow.FlowResult:
        """Generic options for the integration"""

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            self._options.update(user_input)
            # region #-- where to next? --#
            get_creds = user_input.get(CONF_CHANNEL_FETCH_ENABLE, DEF_CHANNEL_FETCH_ENABLE)
            if get_creds:
                return await self.async_step_virgin_creds()
            else:
                # region #-- do we need to cleanup --#
                if not self._options.get(CONF_CHANNEL_FETCH_ENABLE, DEF_CHANNEL_FETCH_ENABLE):
                    return await self.async_step_cache_manage()
                else:
                    return await self.async_step_timeouts()
            # endregion

        return self.async_show_form(
            step_id=STEP_OPTIONS,
            data_schema=await _async_build_schema_with_user_input(STEP_OPTIONS, self._options),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_timeouts(self, user_input=None) -> data_entry_flow.FlowResult:
        """Prompy for configurable timeouts"""

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            self._options[CONF_CONNECT_TIMEOUT] = DEF_CONNECT_TIMEOUT
            self._options[CONF_COMMAND_TIMEOUT] = DEF_COMMAND_TIMEOUT
            self._options.update(user_input)
            return await self.async_step_finish()

        return self.async_show_form(
            step_id=STEP_TIMEOUTS,
            data_schema=await _async_build_schema_with_user_input(
                STEP_TIMEOUTS,
                self._options,
                show_channel_timeouts=self._options.get(CONF_CHANNEL_FETCH_ENABLE, DEF_CHANNEL_FETCH_ENABLE),
            ),
            errors=self._errors,
            last_step=True,
        )

    async def async_step_finish(self) -> data_entry_flow.FlowResult:
        """Update the configuration entry

        This should alwats be the last step in the flow.
        """

        _LOGGER.debug(self._logger_message_format("entered"))
        title = self.context.get(CONF_TITLE_PLACEHOLDERS, {}).get(CONF_FLOW_NAME) or DEF_FLOW_NAME
        _LOGGER.debug(
            self._logger_message_format("title: %s; options: %s"),
            self._config_entry.unique_id,
            title,
            self._options
        )

        return self.async_create_entry(title=title, data=self._options)

    async def async_step_v6_region(self, user_input=None) -> data_entry_flow.FlowResult:
        """Prompt for the channel region

        Should only reach here if the device platform selected is V6
        """

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_timeouts()

        return self.async_show_form(
            step_id=STEP_V6_REGION,
            data_schema=await _async_build_schema_with_user_input(STEP_V6_REGION, self._options),
            errors=self._errors,
            last_step=False,
        )

    async def async_step_virgin_creds(self, user_input=None) -> data_entry_flow.FlowResult:
        """Prompt for the Virgin Media credentials"""

        _LOGGER.debug(self._logger_message_format("user_input: %s"), user_input)
        if user_input is not None:
            self._options.update(user_input)
            if self._options.get(CONF_DEVICE_PLATFORM) == "v6":
                return await self.async_step_v6_region()
            else:
                return await self.async_step_timeouts()

        return self.async_show_form(
            step_id=STEP_VIRGIN_CREDS,
            data_schema=await _async_build_schema_with_user_input(STEP_VIRGIN_CREDS, self._options),
            errors=self._errors,
            last_step=False,
        )
