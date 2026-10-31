"""Resolve declared settings from flags, environment, files, and defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._config.settings_layers import SettingsLayer, settings_layers
from functualize._config.sources import EnvSource, LayerSource

if TYPE_CHECKING:
    from functualize._types.settings import AppSettingsSchema, Setting


@dataclass(frozen=True)
class ResolvedSettings:
    """Values with the source that supplied each declared setting."""

    values: Mapping[str, Any]
    provenance: Mapping[str, str]
    layers: tuple[SettingsLayer, ...]
    contributes: Mapping[Path, frozenset[str]]

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)


def _coerce(setting: Setting, value: Any) -> Any:
    if setting.type == "bool" and isinstance(value, str):
        lowered = value.lower()
        if lowered in {"true", "1"}:
            return True
        if lowered in {"false", "0"}:
            return False
    if setting.type == "int" and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    if setting.type == "list":
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        if isinstance(value, list | tuple):
            return tuple(value)
    return value


def _list_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list | tuple):
        return tuple(str(part) for part in value)
    return ()


# TRANSITIONAL(config-unknown-keys/2.1): the public seam consumes this snapshot.
def resolve_settings(
    schema: AppSettingsSchema,
    cwd: Path,
    *,
    flags: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    global_dir: Path | None = None,
) -> ResolvedSettings:
    """Apply the declared precedence ladder, retaining file provenance.

    Flags outrank environment; project files are nearest first; global is
    last. Scalar settings take the first value. Lists concatenate in that
    same order, with first-occurrence deduplication.
    """
    layers = settings_layers(schema, cwd, global_dir=global_dir)
    file_sources = tuple(LayerSource(layer, schema) for layer in layers)
    environ = dict(os.environ if env is None else env)
    env_source = EnvSource(environ, prefix=schema.env_prefix)
    supplied_flags = flags or {}
    values: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    contributors: dict[Path, set[str]] = {layer.path: set() for layer in layers}

    for setting in schema.settings:
        name = setting.name
        candidates: list[tuple[Any, str, Path | None]] = []
        flag_value = supplied_flags.get(name, supplied_flags.get(setting.key))
        if flag_value is not None:
            candidates.append((flag_value, "cli", None))
        if schema.sources.env:
            env_name = schema.env_var_for(setting)
            # Explicit names such as discovery.extra_directories are read
            # directly; the legacy unprefixed spelling is never consulted.
            env_value = (
                environ.get(env_name)
                if setting.env is not None
                else env_source.get(setting.key, setting.section or None)
            )
            if env_value:
                candidates.append((env_value, "env", None))
        for source in file_sources:
            file_value = source.get(setting.key, setting.section or None)
            if file_value is not None:
                candidates.append((file_value, source.source_id, source.layer.path))
        if setting.default is not None:
            candidates.append((setting.default, "default", None))

        if not candidates:
            continue
        if setting.type == "list":
            seen: set[str] = set()
            merged: list[str] = []
            for raw, _source, path in candidates:
                for item in _list_values(raw):
                    if item not in seen:
                        seen.add(item)
                        merged.append(item)
                        if path is not None:
                            contributors[path].add(name)
            values[name] = tuple(merged)
        else:
            raw, _source, path = candidates[0]
            values[name] = _coerce(setting, raw)
            if path is not None:
                contributors[path].add(name)
        provenance[name] = candidates[0][1]

    return ResolvedSettings(
        values=values,
        provenance=provenance,
        layers=layers,
        contributes={path: frozenset(names) for path, names in contributors.items()},
    )
