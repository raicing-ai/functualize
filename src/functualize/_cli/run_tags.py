"""Validate and merge run tags supplied at the CLI process boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType

TAG_KEY_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
MAX_VALUE_LEN = 256
MAX_TAGS = 32


class RunTagError(ValueError):
    """A run tag cannot be accepted from its stated source."""


def parse_tag(text: str, *, where: str) -> tuple[str, str]:
    """Parse one ``key:value`` spelling, keeping colons inside the value."""
    if not isinstance(text, str):
        raise RunTagError(f"{where}: a run tag must be a string.")
    key, separator, value = text.partition(":")
    prefix = f"{where} '{text}':"
    if not separator:
        raise RunTagError(f"{prefix} a run tag is key:value (missing ':').")
    if not key:
        raise RunTagError(f"{prefix} a run tag needs a key before ':'.")
    if not value:
        raise RunTagError(f"{prefix} a run tag needs a value after ':'.")
    if any(char.isspace() for char in text):
        raise RunTagError(f"{prefix} a run tag cannot contain whitespace.")
    if TAG_KEY_RE.fullmatch(key) is None:
        raise RunTagError(f"{prefix} a run tag key uses a-z, 0-9, '.', '_' and '-'.")
    if len(value) > MAX_VALUE_LEN:
        raise RunTagError(
            f"{prefix} a run tag value cannot exceed {MAX_VALUE_LEN} characters."
        )
    return key, value


def _parse_items(items: Sequence[str], *, where: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    first_positions: dict[str, int] = {}
    first_items: dict[str, str] = {}
    for position, item in enumerate(items, 1):
        key, value = parse_tag(
            item, where=f"{where} item {position}" if where != "--run-tag" else where
        )
        if key in parsed:
            if where == "--run-tag":
                raise RunTagError(
                    f"run tag key '{key}' is given twice "
                    f"(--run-tag {first_items[key]}, --run-tag {item})."
                )
            raise RunTagError(
                f"{where} gives run tag key '{key}' twice "
                f"(items {first_positions[key]} and {position})."
            )
        parsed[key] = value
        first_positions[key] = position
        first_items[key] = item
    return parsed


def parse_env(raw: str) -> dict[str, str]:
    """Parse comma-separated environment items, ignoring blank entries."""
    if not isinstance(raw, str):
        raise RunTagError("FUNCTUALIZE_RUN_TAGS must be a string.")
    items = [item.strip() for item in raw.split(",")]
    return _parse_items([item for item in items if item], where="FUNCTUALIZE_RUN_TAGS")


def parse_config_list(items: object) -> dict[str, str]:
    """Validate ``[run] tags`` from the global user config file."""
    if not isinstance(items, list):
        raise RunTagError("[run] tags in the global config must be a list of strings.")
    return _parse_items(items, where="[run] tags")


def parse_flag_list(items: Sequence[str] | None) -> dict[str, str]:
    """Validate the collected ``--run-tag`` spellings."""
    if items is None:
        return {}
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
        raise RunTagError("--run-tag values must be a list of strings.")
    return _parse_items(items, where="--run-tag")


def merge_layers(*layers: Mapping[str, str]) -> Mapping[str, str]:
    """Overlay lowest-to-highest layers and freeze the effective map."""
    merged: dict[str, str] = {}
    for layer in layers:
        merged.update(layer)
    if len(merged) > MAX_TAGS:
        raise RunTagError(f"a run may have at most {MAX_TAGS} run tags.")
    return MappingProxyType(merged)
