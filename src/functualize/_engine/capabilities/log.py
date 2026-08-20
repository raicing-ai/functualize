"""Log capability — structured logging for job functions.

Provides a simple logging interface that delegates to the standard library
logger. Each job invocation receives its own Log instance scoped to the
job's logger name (``functualize.job.<job_name>``).
"""

from __future__ import annotations

import logging
from typing import ClassVar

_DEFAULT_LOGGER = logging.getLogger("functualize.job")

#: The level names accepted by every logging entry point in the framework.
#: ``RunContext.log()`` and the ``CapturingLog`` double validate against this
#: same set, so an invalid level fails identically whichever one a job calls.
VALID_LOG_LEVELS: frozenset[str] = frozenset(
    {"debug", "info", "warning", "error", "critical"}
)


def validate_log_level(level: str) -> None:
    """Raise ValueError unless ``level`` is one of :data:`VALID_LOG_LEVELS`.

    Args:
        level: The level name to check.

    Raises:
        ValueError: If level is not a valid log level.
    """
    if level not in VALID_LOG_LEVELS:
        raise ValueError(
            f"Invalid log level '{level}'. Must be one of: {sorted(VALID_LOG_LEVELS)}"
        )


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

    #: Alias of the module-level set, kept for anything that reached for it.
    _VALID_LEVELS: ClassVar[frozenset[str]] = VALID_LOG_LEVELS

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
        validate_log_level(level)
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
