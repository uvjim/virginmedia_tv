"""Logging"""

# region #-- imports --#
import inspect
# endregion


class VirginTvLogger:
    """Provide functions for managing log messages"""

    unique_id: str = ""
    _logger_prefix: str = ""

    def __init__(self, unique_id: str = "", prefix: str = ""):
        """Constructor"""

        self._unique_id: str = unique_id
        self._prefix: str = prefix

    def message_format(self, msg: str, include_lineno: bool = False) -> str:
        """Format a log message in the correct format"""

        caller: inspect.FrameInfo = inspect.stack()[1]
        line_no = f" --> line: {caller.lineno}" if include_lineno else ""
        unique_id = f" ({self._unique_id})" if self._unique_id else ""
        return f"{self._prefix}{caller.function}{unique_id}{line_no} --> {msg}"
