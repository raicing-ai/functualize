"""Discover ordered settings files for an application declaration."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._primitives.locator import xdg_config_dir

if TYPE_CHECKING:
    from functualize._types.settings import AppSettingsSchema


@dataclass(frozen=True)
class SettingsLayer:
    """One file and its application-scoped values, before precedence is applied."""

    path: Path
    kind: str
    section_prefix: str
    values: dict[str, Any]

    @property
    def exists(self) -> bool:
        return self.path.is_file()


def _read(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None


def _app_values(data: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    value: Any = data
    for part in prefix.split(".") if prefix else ():
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value if isinstance(value, dict) else None


# TRANSITIONAL(config-unknown-keys/1.2): the resolver consumes these layers next.
def settings_layers(
    schema: AppSettingsSchema,
    cwd: Path,
    *,
    global_dir: Path | None = None,
) -> tuple[SettingsLayer, ...]:
    """Return one winning file per directory, stopping at ``root = true``.

    The global file is always last, including when it has not been created.
    """
    layers: list[SettingsLayer] = []
    for directory in (cwd.resolve(), *cwd.resolve().parents):
        for candidate in schema.sources.project_file_names:
            path = directory / candidate
            data = _read(path)
            if data is None:
                continue
            prefix = schema.section_prefix_for(path.name)
            values = _app_values(data, prefix)
            if values is None:
                continue
            layers.append(SettingsLayer(path, "project", prefix, values))
            break
        if (
            layers
            and layers[-1].path.parent == directory
            and layers[-1].values.get("root") is True
        ):
            break

    config_dir = global_dir if global_dir is not None else xdg_config_dir()
    global_path = config_dir / schema.sources.global_file_name
    global_prefix = schema.section_prefix_for(global_path.name)
    global_data = _read(global_path)
    global_values = _app_values(global_data, global_prefix) if global_data else None
    layers.append(
        SettingsLayer(global_path, "global", global_prefix, global_values or {})
    )
    return tuple(layers)
