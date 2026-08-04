"""Log capability — structured logging for job functions.

Provides a simple logging interface that delegates to the standard library
logger. Each job invocation receives its own Log instance scoped to the
job's logger name (``functualize.job.<job_name>``).
"""

from __future__ import annotations

import logging
from typing import ClassVar

_DEFAULT_LOGGER = logging.getLogger("functualize.job")


class Log:
    """Structured logging capability for job functions.

    Supports both direct call syntax and named level methods:
        log("message")            # defaults to info
        log("message", level="warning")
        log.error("something broke")

    When constructed with a ``job_name``, log records are emitted to the
    per-job logger ``functualize.job.<job_name>``, which allows the TUI and
    other handlers to capture output for the specific job. Without a job name
    the fallback ``functualize.job`` logger is used (backward-compatible).
    """

    _VALID_LEVELS: ClassVar[frozenset[str]] = frozenset(
        {"debug", "info", "warning", "error", "critical"}
    )

    def __init__(self, job_name: str | None = None) -> None:
        if job_name:
            self._logger = logging.getLogger(f"functualize.job.{job_name}")
        else:
            self._logger = _DEFAULT_LOGGER

    def __call__(self, message: object, level: str = "info") -> None:
        """Log a message at the specified level.

        Args:
            message: The message to log (will be converted to str).
            level: One of "debug", "info", "warning", "error", "critical".

        Raises:
            ValueError: If level is not a valid log level.
        """
        if level not in self._VALID_LEVELS:
            raise ValueError(
                f"Invalid log level '{level}'. "
                f"Must be one of: {sorted(self._VALID_LEVELS)}"
            )
        numeric_level = getattr(logging, level.upper())
        self._logger.log(numeric_level, str(message))

    def info(self, msg: object) -> None:
        """Log at INFO level."""
        self(msg, level="info")

    def warning(self, msg: object) -> None:
        """Log at WARNING level."""
        self(msg, level="warning")

    def error(self, msg: object) -> None:
        """Log at ERROR level."""
        self(msg, level="error")

    def debug(self, msg: object) -> None:
        """Log at DEBUG level."""
        self(msg, level="debug")
