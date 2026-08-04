"""Active-environment detection from the process environment.

Lives in ``_app/`` rather than ``_config/`` because reading ``os.environ``
is a boot-time concern: ``_config/`` is handed the environment name and
stays a pure function of its inputs (see .spec/CONSTITUTION.md).
"""

from __future__ import annotations

import os
import re

from functualize._types.enums import EnvironmentSource

__all__ = ["DEFAULT_ENVIRONMENT", "detect_environment"]

#: Used when no environment variable selects one.
DEFAULT_ENVIRONMENT = "DEV"

#: Variables consulted, in precedence order.
_PRECEDENCE: tuple[tuple[str, EnvironmentSource], ...] = (
    ("FUNCTUALIZE_ENV", EnvironmentSource.FUNCTUALIZE_ENV),
    ("ENVIRONMENT", EnvironmentSource.ENVIRONMENT),
    ("ENV", EnvironmentSource.ENV),
)

# An environment name becomes part of a filename (config.<name>.toml), so
# it must look like one. This guard matters most for $ENV: POSIX sh/ksh use
# it as the path to a startup file, so an unguarded read would take
# something like "/home/u/.kshrc" as the environment name and silently make
# every overlay inert.
_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def detect_environment(
    environ: dict[str, str] | None = None,
) -> tuple[str, EnvironmentSource]:
    """Resolve the active environment name and where it came from.

    Precedence is ``FUNCTUALIZE_ENV`` > ``ENVIRONMENT`` > ``ENV``, falling
    back to :data:`DEFAULT_ENVIRONMENT`. A variable that is unset, blank, or
    not a valid filename segment is skipped, not fatal — the next candidate
    is tried.

    Args:
        environ: Environment mapping to read; defaults to ``os.environ``.
            Injectable so callers can test precedence without mutating the
            real process environment.

    Returns:
        ``(name, source)`` — the source is what lets a caller tell
        "explicitly selected" from "defaulted".
    """
    env = os.environ if environ is None else environ

    for variable, source in _PRECEDENCE:
        raw = env.get(variable)
        if raw is None:
            continue
        value = raw.strip()
        if not value or not _VALID_NAME.match(value):
            continue
        return value, source

    return DEFAULT_ENVIRONMENT, EnvironmentSource.DEFAULT
