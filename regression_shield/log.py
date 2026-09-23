"""Logging for RegShield.

The SDK logs through the standard ``logging`` module under the
``regression_shield`` logger and prints nothing by default. Turn logs on with
``--verbose`` on the CLI, ``evaluate_trace(..., verbose=True)``,
``enable_logging()``, or the ``REGSHIELD_LOG`` environment variable
(``debug``, ``info`` or ``warning``).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import IO

LOGGER_NAME = "regression_shield"

_logger = logging.getLogger(LOGGER_NAME)
_logger.addHandler(logging.NullHandler())


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.short_name = record.name.rsplit(".", 1)[-1]  # "regression_shield.core.evaluator" -> "evaluator"
        return super().format(record)


class _Handler(logging.StreamHandler):
    """The handler ``enable_logging`` adds, so calling it again reuses it."""

    _regshield = True


class _StderrHandler(_Handler):
    """Writes to whatever ``sys.stderr`` is when a record is logged, so redirecting
    or capturing stderr later (pytest, host applications) keeps working."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self) -> IO[str]:
        return sys.stderr

    @stream.setter
    def stream(self, value: IO[str]) -> None:
        pass


def enable_logging(level: str | int = "DEBUG", stream: IO[str] | None = None) -> None:
    """Print RegShield logs (to stderr by default). Safe to call more than once."""
    if not any(isinstance(h, _Handler) for h in _logger.handlers):
        handler = _Handler(stream) if stream else _StderrHandler()
        handler.setFormatter(_Formatter("[regshield] %(levelname)-7s %(short_name)s: %(message)s"))
        _logger.addHandler(handler)
    _logger.setLevel(level.upper() if isinstance(level, str) else level)


_env_level = os.environ.get("REGSHIELD_LOG", "").strip().upper()
if _env_level:
    # Any value that isn't a level name (e.g. "1", "true") means debug
    enable_logging(_env_level if isinstance(logging.getLevelName(_env_level), int) else "DEBUG")
