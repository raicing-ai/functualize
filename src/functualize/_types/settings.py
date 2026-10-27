"""App-parameterized settings declaration — ``Setting`` / ``AppSettingsSchema``.

`func`'s settings store is currently func-shaped: the catalog is a module-level
tuple, the environment prefix ``FUNCTUALIZE_`` is written into a formatting
call, and "which TOML section does this file use" is a filename comparison
against ``pyproject.toml``. These types are the declaration a *second* app
supplies to get the same machinery under its own name.

This module declares shape only — resolution, file discovery, and persistence
stay in the store. It lives in ``_types`` and imports nothing internal
(import-linter contract "Types import nothing internal"); the public re-export
is ``functualize.plugin``, beside ``Surface``/``PromptCollector``.

**Reconciled with the shipped ``FuncSetting``, not a clean-sheet redesign.**
The Phase-C contract sketched ``Setting(name, type, default, help, cli_flag,
phase)``. Adopting that verbatim would have dropped ``section`` and ``key`` —
which are not decoration: ``section``/``key`` are what place a value inside a
TOML file (``section_in_file``) and what build its environment variable
(``FUNCTUALIZE_<SECTION>_<KEY>``). They are preserved here as **derived**
properties of the dotted name, which is exactly the relationship the existing
catalog already maintains (``_spec`` builds ``name = f"{section}.{key}"``), so
nothing is lost and there is still a single spelling of a setting's identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

__all__ = ["AppSettingsSchema", "Setting", "SettingsSources"]


@dataclass(frozen=True)
class Setting:
    """One declared setting.

    Attributes:
        name: Dotted canonical identity — ``"tui.theme"``, or a bare
            ``"dotenv"`` for a top-level key. This is the row key everywhere.
        type: ``"enum" | "int" | "bool" | "list" | "str"``.
        description: Human-readable help.
        default: Built-in default **as display text**, or None when the setting
            genuinely has no default (most ``[discovery]`` filters).
        choices / min_value / max_value / max_items: Validation bounds, carried
            over from the shipped ``SettingSchema`` unchanged.
        cli_flag: Generated root CLI flag (``"--log-level"``), or None for a
            settings-only knob. Consumed by C3.1; nothing reads it yet.
        phase: ``"early"`` marks a setting whose flag must be honoured by the
            pre-boot argv scan, before app construction. Consumed by C3.2.
        places: File sections that may contain this key. The dotted name's
            section is canonical, even when an accepted legacy place comes
            first in this tuple.
        listed: Whether to show the setting in an interactive settings list.
        surface: The delivery surface that owns this setting, if any.
        env: Explicit environment-variable name; otherwise the schema derives
            one from its prefix and the canonical dotted name.
    """

    name: str
    type: str
    description: str
    default: str | None = None
    choices: tuple[str, ...] | None = None
    min_value: int | None = None
    max_value: int | None = None
    max_items: int | None = None
    cli_flag: str | None = None
    phase: str | None = None
    places: tuple[str, ...] = ()
    listed: bool = True
    surface: str | None = None
    env: str | None = None

    @property
    def section(self) -> str:
        """TOML section this setting lives in; ``""`` for a top-level key.

        Derived from the dotted name rather than stored, so a setting cannot
        have a name and a section that disagree.
        """
        section, _, _ = self.name.rpartition(".")
        return section

    @property
    def key(self) -> str:
        """The bare key inside :attr:`section`."""
        _, _, key = self.name.rpartition(".")
        return key

    @property
    def accepted_places(self) -> tuple[str, ...]:
        """Canonical section first, followed by accepted legacy sections."""
        return (
            self.section,
            *(place for place in self.places if place != self.section),
        )


@dataclass(frozen=True)
class SettingsSources:
    """Where an app's settings are read from, in precedence order.

    Precedence is fixed (default < global < project < env); what varies per app
    is the *file names*. Declaring them makes the store app-agnostic.

    Attributes:
        global_file_name: File inside the user config dir (XDG-resolved).
        project_file_names: Candidates for the upward project walk, nearest
            wins, in the order they are probed at each level.
        env: Whether environment variables participate at all.
    """

    global_file_name: str = "config.toml"
    project_file_names: tuple[str, ...] = (
        "pyproject.toml",
        ".functualize.toml",
        ".functualize/.functualize.toml",
    )
    env: bool = True


def _default_file_section_prefixes() -> Mapping[str, str]:
    return MappingProxyType({"pyproject.toml": "tool.functualize"})


@dataclass(frozen=True)
class AppSettingsSchema:
    """The full settings declaration one app hands to the store.

    Attributes:
        settings: The catalog, in display order.
        env_prefix: Environment-variable prefix without the trailing underscore
            (``"FUNCTUALIZE"`` → ``FUNCTUALIZE_TUI_THEME``). Replaces the
            hardcoded literal in ``env_var_for``.
        sources: File discovery declaration.
        file_section_prefixes: ``{filename: section prefix}``. A shared file
            such as ``pyproject.toml`` nests an app's settings under its own
            table (``tool.functualize``); a dedicated file uses the bare
            section. **Declared as data** — this replaces the
            ``"tool.functualize" if path.name == "pyproject.toml" else ""``
            branch, which hardcodes both the filename and func's own table name
            and so cannot answer the question for a second app.
    """

    settings: tuple[Setting, ...]
    env_prefix: str = "FUNCTUALIZE"
    sources: SettingsSources = field(default_factory=SettingsSources)
    file_section_prefixes: Mapping[str, str] = field(
        default_factory=_default_file_section_prefixes
    )
    freeform_sections: frozenset[str] = frozenset()

    def extend(self, *settings: Setting) -> AppSettingsSchema:
        """Return a new schema with additional settings, rejecting name clashes."""
        existing = {setting.name for setting in self.settings}
        added: set[str] = set()
        for setting in settings:
            if setting.name in existing or setting.name in added:
                raise ValueError(f"setting {setting.name!r} is already declared")
            added.add(setting.name)
        return replace(self, settings=(*self.settings, *settings))

    def setting(self, name: str) -> Setting | None:
        """Find a setting by its canonical dotted name."""
        return next(
            (setting for setting in self.settings if setting.name == name), None
        )

    def sections(self) -> frozenset[str]:
        """File sections that the declaration recognizes."""
        return frozenset(
            (
                *self.freeform_sections,
                *(place for s in self.settings for place in s.accepted_places if place),
            )
        )

    # TRANSITIONAL(config-unknown-keys/6.1): vocabulary check consumes this.
    def keys_in(self, section: str) -> frozenset[str]:
        """Declared keys accepted in one file section."""
        return frozenset(
            setting.key
            for setting in self.settings
            if section in setting.accepted_places
        )

    def flag(self, spelling: str) -> Setting | None:
        """Find the setting controlled by a root CLI option."""
        return next(
            (setting for setting in self.settings if setting.cli_flag == spelling),
            None,
        )

    # TRANSITIONAL(config-unknown-keys/1.2): the resolver consumes this in wave 1.
    def value_in(self, values: Mapping[str, Any], name: str) -> Any | None:
        """Read a declared key from a file table, preferring its canonical place."""
        setting = self.setting(name)
        if setting is None:
            return None
        for place in setting.accepted_places:
            table = values if not place else values.get(place)
            if isinstance(table, Mapping) and setting.key in table:
                return table[setting.key]
        return None

    def env_var_for(self, setting: Setting) -> str:
        """The environment variable that overrides ``setting``.

        Byte-identical to the shipped ``env_var_for`` when
        ``env_prefix == "FUNCTUALIZE"``.
        """
        if setting.env is not None:
            return setting.env
        if setting.section:
            return f"{self.env_prefix}_{setting.section.upper()}_{setting.key.upper()}"
        return f"{self.env_prefix}_{setting.key.upper()}"

    def section_prefix_for(self, file_name: str) -> str:
        """The TOML table an app's settings nest under inside ``file_name``."""
        return self.file_section_prefixes.get(file_name, "")

    def section_in_file(self, setting: Setting, file_name: str) -> str:
        """Full dotted TOML section for ``setting`` inside ``file_name``.

        What the shipped store used to derive per call: prefix and section
        joined, empty parts dropped.
        """
        parts = [p for p in (self.section_prefix_for(file_name), setting.section) if p]
        return ".".join(parts)
