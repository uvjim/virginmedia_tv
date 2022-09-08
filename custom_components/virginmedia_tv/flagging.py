"""Manage flag files."""

# region #-- imports --#
import logging
import os
from typing import Optional

from .logger import Logger

# endregion

_LOGGER = logging.getLogger(__name__)


class VirginTvFlagFile:
    """Representation of a flag file."""

    def __init__(self, path: str):
        """Initialise."""
        self._flag_path = path
        self._log_formatter = Logger()

    def create(self, contents: Optional[str] = None) -> None:
        """Create the flag file using the path denoted by _flag_path.

        :param contents: the optional contents to store in the flag file
        :return: None
        """
        _LOGGER.debug(
            self._log_formatter.format("entered, include contents: %s"),
            contents is not None,
        )

        if self.is_flagged():
            _LOGGER.debug(
                self._log_formatter.format("flag file already exists (%s)"),
                self._flag_path,
            )
            return

        _LOGGER.debug(
            self._log_formatter.format("creating flag file: %s"),
            self._flag_path,
        )
        os.makedirs(name=os.path.dirname(self._flag_path), exist_ok=True)
        with open(self._flag_path, "x", encoding="utf8") as flag_file:
            if contents is not None:
                _LOGGER.debug(
                    self._log_formatter.format("writing contents to flag file")
                )
                flag_file.write(contents)

        _LOGGER.debug(self._log_formatter.format("exited"))

    def delete(self) -> None:
        """Remove the flag file using the path denoted by _flag_path."""
        _LOGGER.debug(self._log_formatter.format("entered"))

        if not self._flag_path:
            _LOGGER.debug(self._log_formatter.format("_flag_path not defined"))
            return

        _LOGGER.debug(
            self._log_formatter.format("deleting flag file: %s"),
            self._flag_path,
        )
        try:
            os.remove(self._flag_path)
        except FileNotFoundError:
            _LOGGER.debug(
                self._log_formatter.format("flag file does not exist (%s)"),
                self._flag_path,
            )
        else:
            _LOGGER.debug(
                self._log_formatter.format("flag file successfully removed (%s)"),
                self._flag_path,
            )

        _LOGGER.debug(self._log_formatter.format("exited"))

    def is_flagged(self) -> bool:
        """Check if the flag file denoted by _flag_path exists.

        :return: True if the flag exists, False otherwise
        """
        return os.path.exists(self._flag_path)
