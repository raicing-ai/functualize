"""Validate and merge run tags from selected settings layers and run inputs."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._config.settings_layers import SettingsLayer

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
    if "," in value:
        raise RunTagError(f"{prefix} a run tag value cannot contain ','.")
    if TAG_KEY_RE.fullmatch(key) is None:
        raise RunTagError(f"{prefix} a run tag key uses a-z, 0-9, '.', '_' and '-'.")
    if len(value) > MAX_VALUE_LEN:
        raise RunTagError(
            f"{prefix} a run tag value cannot exceed {MAX_VALUE_LEN} characters."
        )
    return key, value


def _parse_items(
    items: Sequence[str], *, where: str, comma_split: bool = False
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    first_positions: dict[str, int] = {}
    first_items: dict[str, str] = {}
    previous_item: str | None = None
    for position, item in enumerate(items, 1):
        if comma_split and previous_item is not None and ":" not in item:
            combined = f"{previous_item},{item}"
            raise RunTagError(
                f"{where} item {position - 1} '{combined}': "
                "a run tag value cannot contain ','."
            )
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
        previous_item = item
    return parsed


def parse_env(raw: str) -> dict[str, str]:
    """Parse comma-separated environment items, ignoring blank entries."""
    if not isinstance(raw, str):
        raise RunTagError("FUNCTUALIZE_RUN_TAGS must be a string.")
    items = [item.strip() for item in raw.split(",")]
    return _parse_items(
        [item for item in items if item],
        where="FUNCTUALIZE_RUN_TAGS",
        comma_split=True,
    )


def parse_config_list(items: object, *, where: str = "[run] tags") -> dict[str, str]:
    """Validate one file's ``[run] tags`` list with its source label."""
    if not isinstance(items, list):
        location = "[run] tags in the global config" if where == "[run] tags" else where
        raise RunTagError(f"{location} must be a list of strings.")
    return _parse_items(items, where=where)


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


def _file_label(layer: SettingsLayer) -> str:
    section = f"{layer.section_prefix}.run" if layer.section_prefix else "run"
    return f"[{section}] tags in {layer.path}"


# TRANSITIONAL(run-tags-from-settings-files/5.1): CLI merge will call this resolver.
def resolve_run_tags(
    layers: Sequence[SettingsLayer],
    *,
    flag_items: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Mapping[str, str]:
    """Overlay selected files, environment, and CLI flags per key.

    ``settings_layers`` supplies nearest-first projects and the global file
    last. Reverse that sequence to apply the ordinary precedence ladder.
    Files are never reopened here. Every source is validated before merging.
    """
    parsed: list[Mapping[str, str]] = []
    for layer in reversed(layers):
        run_section = layer.values.get("run")
        if not isinstance(run_section, dict) or "tags" not in run_section:
            continue
        parsed.append(parse_config_list(run_section["tags"], where=_file_label(layer)))

    source = os.environ if environ is None else environ
    parsed.append(parse_env(source.get("FUNCTUALIZE_RUN_TAGS", "")))
    parsed.append(parse_flag_list(flag_items))
    return merge_layers(*parsed)
