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
    """One file and its application-scoped values, before precedence is applied.

    ``text`` is the file exactly as it was read, kept beside the parsed values
    because a writer that appends an edit has to preserve everything it is not
    editing — comments, order, unrelated tables. Reading happens here, once;
    consumers never open a settings file themselves.
    """

    path: Path
    kind: str
    section_prefix: str
    values: dict[str, Any]
    text: str = ""

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @classmethod
    def read(cls, path: Path, kind: str, section_prefix: str) -> SettingsLayer:
        """Load one file as a layer.

        The single-file entry point for a caller that has a path but no walk —
        a file a picker is about to create, or one the walk did not pick. A
        missing or unparsable file yields a layer with no values and no text;
        a file without the application table keeps its text and contributes no
        values, so a later save appends to the real file instead of replacing
        it.
        """
        parsed = _read(path)
        if parsed is None:
            return cls(path, kind, section_prefix, {}, "")
        text, data = parsed
        values = _app_values(data, section_prefix)
        return cls(path, kind, section_prefix, values or {}, text)


def _read(path: Path) -> tuple[str, dict[str, Any]] | None:
    """Read a file as text plus its parsed TOML, or None if unusable."""
    try:
        text = path.read_text(encoding="utf-8")
        return text, tomllib.loads(text)
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
            parsed = _read(path)
            if parsed is None:
                continue
            text, data = parsed
            prefix = schema.section_prefix_for(path.name)
            values = _app_values(data, prefix)
            if values is None:
                continue
            layers.append(SettingsLayer(path, "project", prefix, values, text))
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
    global_parsed = _read(global_path)
    global_text = global_parsed[0] if global_parsed is not None else ""
    global_values = (
        _app_values(global_parsed[1], global_prefix)
        if global_parsed is not None
        else None
    )
    layers.append(
        SettingsLayer(
            global_path, "global", global_prefix, global_values or {}, global_text
        )
    )
    return tuple(layers)
