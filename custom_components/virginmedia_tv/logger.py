"""Logging"""

# region #-- imports --#
import inspect
# endregion


class VirginTvLogger:
    """Provide functions for managing log messages"""

    unique_id: str = ""
    _logger_prefix: str = ""

    def _logger_message_format(self, msg: str, include_lineno: bool = False) -> str:
        """Format a log message in the correct format"""

        caller: inspect.FrameInfo = inspect.stack()[1]
        line_no = f" --> line: {caller.lineno}" if include_lineno else ""
        return f"{self._logger_prefix}{caller.function} ({self.unique_id}){line_no} --> {msg}"
