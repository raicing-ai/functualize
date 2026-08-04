"""Environment-slot parsing and role classification for config files.

Pure functions over filenames — no I/O, no ``os.environ``. The active
environment is always passed in; detecting it from the process environment
is ``_app/environment.py``'s job, because ``_config/`` may not read the
environment directly (see .spec/CONSTITUTION.md on layer boundaries).

Config files are named ``config.<slot>.<ext>``. Given an active
environment, each discovered file is one of:

- BASE — ``config.base.<ext>``, always merged.
- OVERLAY — ``<slot>`` matches the active environment, merged on top.
- INERT — ``<slot>`` names some other environment; never merged.
"""

from __future__ import annotations

import re
from pathlib import Path

from functualize._types.enums import ConfigFileRole

__all__ = ["BASE_SLOT", "classify", "parse_slot"]

#: The slot whose file is loaded regardless of the active environment.
BASE_SLOT = "base"

# ``config.<slot>.<ext>`` — mirrors the kernel's discovery regex in
# app/config.py, which likewise requires a slot segment.
_SLOTTED = re.compile(r"^config\.(?P<slot>[^.]+)\.[^.]+$")


def parse_slot(path: str) -> str | None:
    """Return the environment slot in ``config.<slot>.<ext>``, else None.

    None means the filename carries no slot (e.g. a plain ``config.toml``),
    not that it is invalid.
    """
    match = _SLOTTED.match(Path(path).name)
    if match is None:
        return None
    return match.group("slot")


def classify(path: str, environment: str | None) -> ConfigFileRole:
    """Classify a config file's role under ``environment``.

    Matching is case-insensitive: ``ENVIRONMENT=PROD`` selects
    ``config.prod.toml``. The filename is not lowercased — only compared
    case-insensitively — so ``config.Prod.toml`` is equally selectable.

    Args:
        path: Path to the config file (only the basename is inspected).
        environment: The active environment name, or None to disable
            banding entirely (every file is BASE, i.e. always merged).

    Returns:
        The file's :class:`ConfigFileRole`.
    """
    slot = parse_slot(path)

    # No slot: an unslotted config.<ext> can never be selected by an
    # environment, so treating it as BASE is the only reading where it does
    # anything at all.
    if slot is None:
        return ConfigFileRole.BASE

    # `base` is checked before the environment comparison so that
    # ENVIRONMENT=base degrades to "base is base" rather than promoting it
    # to an overlay of itself.
    if slot.casefold() == BASE_SLOT:
        return ConfigFileRole.BASE

    if environment is None:
        return ConfigFileRole.BASE

    if slot.casefold() == environment.casefold():
        return ConfigFileRole.OVERLAY

    return ConfigFileRole.INERT
