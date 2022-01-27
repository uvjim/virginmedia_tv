"""Custom Exceptions"""

import asyncio

DEFAULT_ERROR_MESSAGES = {
    ConnectionError: "Connection error",
    BrokenPipeError: "Broken pipe",
    ConnectionAbortedError: "Connection aborted",
    ConnectionRefusedError: "Connection refused",
    ConnectionResetError: "Connection reset",
    OSError: "OS I/O error",
}


def format_error_message(error: Exception) -> str:
    """"""

    error_message = str(error)
    if not error_message:
        # noinspection PyTypeChecker
        error_message = DEFAULT_ERROR_MESSAGES.get(type(error))
    return error_message


class VirginMediaError(Exception):
    """"""

    pass


class VirginMediaCommandTimeout(VirginMediaError):
    """"""

    def __init__(self):
        """"""

        super().__init__(f"Command timeout")


class VirginMediaConnectionReset(VirginMediaError):
    """"""

    def __init__(self):
        """"""

        super().__init__(f"Connection reset")


class VirginMediaInvalidChannel(VirginMediaError):
    """"""

    def __init__(self, channel_number):
        """"""

        self._channel_number = channel_number
        super().__init__(f"Invalid channel ({self.channel_number})")

    @property
    def channel_number(self) -> int:
        """"""

        return self._channel_number


class VirginMediaInvalidCommand(VirginMediaError):
    """"""

    def __init__(self, command: str) -> None:
        """"""

        self._command = command
        super().__init__(f"Invalid command ({self.command})")

    @property
    def command(self) -> str:
        """"""

        return self._command


class VirginMediaInvalidKey(VirginMediaError):
    """"""

    def __init__(self, key_code: str):
        """"""

        self._keycode = key_code
        super().__init__(f"Invalid key ({self._keycode})")

    @property
    def key_code(self) -> str:
        """"""

        return self._keycode


class VirginMediaNotLive(VirginMediaError):
    """"""

    def __init__(self):
        super().__init__("Not in LiveTV mode")
