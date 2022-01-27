"""Communication with the TiVo device"""

import asyncio
import logging
import re
from typing import (
    Callable,
    List,
    Optional,
)

from .const import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_CONNECT_PORT,
    DEFAULT_CONNECT_TIMEOUT,
)
from .exceptions import (
    format_error_message,
    VirginMediaError,
    VirginMediaCommandTimeout,
    VirginMediaConnectionReset,
    VirginMediaInvalidChannel,
    VirginMediaInvalidCommand,
    VirginMediaInvalidKey,
    VirginMediaNotLive,
)

_LOGGER = logging.getLogger(__name__)


class Device:
    """Represents the attributes of the device"""

    def __init__(self, host: str, port: int):
        """Constructor"""

        self._host: str = host
        self._port: int = port

        self._channel_number: Optional[int] = None
        self._prev_channel_number: Optional[int] = None

    def _set_channel_number(self, value: Optional[int] = None) -> None:
        """Set the channel number

        :param value: the current channel number
        :return: None
        """

        if value != self._channel_number:
            self._prev_channel_number = self._channel_number
            self._channel_number = value

    @property
    def host(self) -> str:
        """Device hostname"""

        return self._host

    @property
    def port(self) -> int:
        """Port number used for connecting to the device"""

        return self._port

    @property
    def channel_number(self) -> Optional[int]:
        """Current channel number"""

        return self._channel_number

    @property
    def previous_channel_number(self) -> Optional[int]:
        """Previous channel number"""

        return self._prev_channel_number


class Client:
    """Represent a connection to the TiVo device"""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_CONNECT_PORT,
        timeout: float = DEFAULT_CONNECT_TIMEOUT,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        """Constructor"""

        self._command_timeout: Optional[float] = command_timeout or DEFAULT_COMMAND_TIMEOUT
        self._data_callback: List = []
        self._host: str = host
        self._lock_read: asyncio.Lock = asyncio.Lock()
        self._port: int = port
        self._timeout: float = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._tivo: Device = Device(host=self._host, port=self._port)
        self._writer: Optional[asyncio.StreamWriter] = None

    async def __aenter__(self) -> "Client":
        """Entry point for the Context Manager"""

        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit point for the Context Manager"""

        await self.disconnect()

    # region #-- private methods --#
    async def _send(self, data: str, wait_for_reply: bool = True) -> None:
        """Send request to the device

        :param data: data to send
        :param wait_for_reply: True to wait for the reply
        :return: None
        """

        data = f"{data}\r".upper()
        try:
            if self._writer:
                self._writer.write(data.encode())
                await self._writer.drain()
                if wait_for_reply:
                    await self.wait_for_data()
        except Exception as err:
            _LOGGER.debug("_send --> type: %s, message: %s", type(err), err)
            if type(err) == asyncio.TimeoutError:
                raise VirginMediaCommandTimeout from err
            elif isinstance(err, VirginMediaError):
                raise
            else:
                raise VirginMediaError(format_error_message(err)) from err
    # endregion

    # region #-- public methods --#
    async def connect(self) -> None:
        """Create a connection to the device"""

        _LOGGER.debug("connect --> entered")
        try:
            _LOGGER.debug(
                "connect --> connecting to %s on port %d with timeout %0.1fs",
                self._host,
                self._port,
                self._timeout
            )
            open_future = asyncio.open_connection(self._host, self._port)
            self._reader, self._writer = await asyncio.wait_for(open_future, self._timeout)
            _LOGGER.debug("connect --> connected to %s on port %d", self._host, self._port)
        except (OSError, ConnectionError, ConnectionResetError, asyncio.TimeoutError) as err:
            _LOGGER.debug("connect --> error --> type: %s, message: %s", type(err), err)
            if type(err) == asyncio.TimeoutError:
                raise VirginMediaCommandTimeout from err
            else:
                raise VirginMediaError(format_error_message(err)) from err
        _LOGGER.debug("connect --> exited")

    async def disconnect(self) -> None:
        """Disconnect from the device"""

        _LOGGER.debug("disconnect --> entered")
        if self._writer:
            _LOGGER.debug("disconnect --> disconnecting from %s on port %d", self._host, self._port)
            self._writer.close()
            await self._writer.wait_closed()
            _LOGGER.debug("disconnect -> disconnected from %s on port %d", self._host, self._port)
            self._writer = None
            self._reader = None
        else:
            _LOGGER.debug("disconnect --> not currently connected to %s on port %d", self._host, self._port)

        _LOGGER.debug("disconnect --> exited")

    async def send_ircode(self, code: str, wait_for_reply: bool = True) -> None:
        """Send an infrared code to the device

        :param code: the IR code to send
        :param wait_for_reply: True if intending to wait for a response
        :return: None
        """

        _LOGGER.debug("send_ircode --> entered")
        try:
            _LOGGER.debug("send_ircode --> sending ircode: %s", code)
            await self._send(f"ircode {code}", wait_for_reply=wait_for_reply)
        except VirginMediaError as err:
            if str(err).lower() == "invalid_key":
                raise VirginMediaInvalidKey(key_code=code)
            else:
                raise
        except Exception as err:
            _LOGGER.error(err)
        else:
            _LOGGER.debug("send_ircode --> ircode sent: %s", code)

        _LOGGER.debug("send_ircode --> exited")

    async def send_keyboard(self, code: str, wait_for_reply: bool = True) -> None:
        """Send a keyboard code to the device

        :param code: the keyboard code to send
        :param wait_for_reply: True to wait for a response after sending
        :return: None
        """

        _LOGGER.debug("send_keyboard --> entered")
        try:
            _LOGGER.debug("send_keyboard --> sending keyboard: %s", code)
            await self._send(f"keyboard {code}", wait_for_reply=wait_for_reply)
        except VirginMediaError as err:
            _LOGGER.warning("send_keyboard --> type: %s, message: %s", type(err), err)
            if str(err).lower() == "invalid_key":
                raise VirginMediaInvalidKey(key_code=code)
        else:
            _LOGGER.debug("send_keyboard --> keyboard sent: %s", code)

        _LOGGER.debug("send_keyboard --> exited")

    async def send_teleport(self, code: str) -> None:
        """Send a teleport code to the device

        :param code: the teleport code to send
        :return: None
        """

        _LOGGER.debug("send_teleport --> entered")
        try:
            _LOGGER.debug("send_teleport --> sending teleport: %s", code)
            await self._send(f"teleport {code}")
        except VirginMediaError as err:
            if str(err).lower() == "invalid_command":
                raise VirginMediaInvalidCommand(command=code)
        else:
            _LOGGER.debug("send_teleport --> teleport sent: %s", code)

        _LOGGER.debug("send_teleport --> exited")

    async def set_channel(self, channel_number: int) -> None:
        """Change the channel on the device

        :param channel_number: the channel number to change to
        :return: None
        """

        _LOGGER.debug("set_channel --> entered")
        try:
            _LOGGER.debug("set_channel --> setting channel number to: %d", channel_number)
            await self._send(f"setch {channel_number}")
        except VirginMediaError as err:
            if str(err).lower() == "no_live":
                raise VirginMediaNotLive()
            elif str(err).lower() == 'invalid_channel':
                raise VirginMediaInvalidChannel(channel_number=channel_number)
            else:
                raise
        else:
            _LOGGER.debug("set_channel --> channel number set to: %d", channel_number)

        _LOGGER.debug("set_channel --> exited")

    async def wait_for_data(self) -> None:
        """Process the data from the device

        The device only returns an error or the current channel number
        """

        _LOGGER.debug("wait_for_data --> entered")
        async with self._lock_read:
            buffer_size = 1024
            try:
                data_future = self._reader.read(buffer_size)
                data = await asyncio.wait_for(data_future, timeout=self._command_timeout)
            except Exception as err:
                if type(err) == asyncio.TimeoutError:
                    # noinspection PyProtectedMember
                    self._tivo._set_channel_number(None)
                    raise VirginMediaCommandTimeout from err
                else:
                    _LOGGER.warning("wait_for_data --> line 276 --> type: %s, message: %s", type(err), err)
                    raise VirginMediaError(format_error_message(err)) from None
            else:
                _LOGGER.debug("wait_for_data --> raw data: %s", data)

                if not data:
                    # noinspection PyProtectedMember
                    self._tivo._set_channel_number()
                    raise VirginMediaConnectionReset from None

                data = data.decode().strip()
                if data.startswith("CH_STATUS"):
                    regex = r"\d{4}"
                    m: re.Match = re.search(regex, data)
                    if m:
                        # noinspection PyProtectedMember
                        self._tivo._set_channel_number(int(m.group(0)))
                elif data.startswith("CH_FAILED"):
                    raise VirginMediaError(data.split(" ")[-1])
                elif data == "INVALID_KEY":
                    raise VirginMediaError(data)
                elif data == "INVALID_COMMAND":
                    raise VirginMediaError(data)

                if self._data_callback:
                    _LOGGER.debug("wait_for_data --> executing callbacks")
                    for fn in self._data_callback:
                        if isinstance(fn, Callable):
                            fn(self._tivo)

        _LOGGER.debug("wait_for_data --> exited")

    def add_data_callback(self, callback: Callable) -> None:
        """Add a callback for execution after data has been retrieved"""

        _LOGGER.debug("add_data_callback --> entered")
        self._data_callback.append(callback)
        _LOGGER.debug("add_data_callback --> exited")

    def remove_data_callback(self, callback: Callable) -> None:
        """Remove the given callback from being processed"""

        _LOGGER.debug("remove_data_callback --> entered")
        try:
            self._data_callback.remove(callback)
        except ValueError:
            pass
        _LOGGER.debug("remove_data_callback --> exited")
    # endregion

    # region #-- properties --#
    @property
    def device(self) -> Device:
        """The device class"""

        return self._tivo

    @property
    def is_connected(self) -> bool:
        """Connected to the device?

        :return: True if connected, False otherwise
        """

        ret: bool = False
        if self._writer:
            ret = not self._writer.is_closing()

        return ret
    # endregion
