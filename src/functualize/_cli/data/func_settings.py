"""The catalog and resolution chain for `func`'s own settings.

One catalog covers **everything you can put in a functualize setting**: the
``[discovery]`` and ``[cli]`` sections, the top-level keys (``dotenv``,
``dotenv_path``, ``import_libs``), and the ``[tui]`` section. Every setting
resolves through the same chain the rest of `func` uses::

    default  <  global config.toml  <  project file(s)  <  FUNCTUALIZE_* env

- **default** — the catalog's built-in value; some settings have none.
- **global** — ``~/.config/functualize/config.toml`` (via
  ``resolve_user_config_dir``).
- **project** — the files ``resolve_cli_config`` already consults, found by
  the upward walk: ``pyproject.toml`` ``[tool.functualize]``,
  ``.functualize.toml``, ``.functualize/.functualize.toml``. Nearest wins.
- **env** — ``FUNCTUALIZE_<SECTION>_<KEY>`` (or ``FUNCTUALIZE_<KEY>`` for
  top-level settings). Highest: the most explicit, most transient layer.

Settings are addressed by **dotted name** (``tui.theme``, ``cli.output``,
``dotenv``) so the one namespace can span sections without collisions.

This replaces ``tui_settings.TuiSettingsStore``, which invented a parallel
``functualize.toml`` / ``settings.toml`` file pair that nothing else in
`func` read — a user could configure the TUI in a file the rest of the tool
silently ignored, or vice versa.

Every source is validated through the setting's schema; a value that fails
validation is dropped from the chain rather than allowed to break the TUI,
since these files are hand-editable.

This module is in the ``_cli/`` layer — stdlib + ``_cli`` siblings only.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._cli.data.settings_schema import (
    SETTING_SCHEMAS,
    SettingSchema,
    ValidationResult,
    validate_against,
)
from functualize._cli.data.toml_writer import SectionEdits, write_toml_sections
from functualize.plugin import (
    FUNCTUALIZE_SETTINGS,
    AppSettingsSchema,
    ResolvedSettings,
    Setting,
    SettingsLayer,
    resolve_settings,
)

if TYPE_CHECKING:
    from functualize._cli.tui.models.source_chain import ResolvedKey

# NOTE: functualize._cli.tui.models.source_chain is imported lazily inside
# resolve(). Importing it at module level triggers the tui package __init__,
# which imports settings_panel, which imports this module — a cycle that
# breaks whenever func_settings is imported before the tui package.

__all__ = [
    "DEFAULT_VALUES",
    "FUNC_SCHEMA",
    "FUNC_SETTINGS",
    "FuncSetting",
    "FuncSettingsStore",
    "SettingsStore",
    "PRECEDENCE_CLI",
    "PRECEDENCE_DEFAULT",
    "PRECEDENCE_ENV",
    "PRECEDENCE_GLOBAL",
    "PRECEDENCE_PROJECT_BASE",
    "SETTINGS_ORDER",
    "env_var_for",
    "func_setting",
    "setting_schema",
    "validate_func_setting",
]

PRECEDENCE_DEFAULT = 0
PRECEDENCE_GLOBAL = 10
PRECEDENCE_PROJECT_BASE = 20
PRECEDENCE_ENV = 90
#: A root CLI flag generated from `Setting.cli_flag` (convergence C3.1).
#: Above env because a flag typed on *this* invocation is the most explicit
#: statement of intent available — the same order `--log-level` already has
#: relative to everything else.
PRECEDENCE_CLI = 100


@dataclass(frozen=True)
class FuncSetting:
    """One entry in the settings catalog.

    Attributes:
        name: Dotted canonical name (``tui.theme``, ``dotenv``) — the row
            key everywhere in the TUI.
        section: TOML section the value lives in (``""`` for top-level keys).
        key: The bare key inside that section.
        schema: Validation schema; also supplies type and description.
        default: Built-in default as display text, or None when the setting
            simply has no default (most ``[discovery]`` filters).
        cli_flag: Root CLI flag generated for this setting (``"--foo"``), or
            None for settings that are file/env only. C3.1.
        phase: ``"early"`` marks a flag that must be honoured by the pre-boot
            argv scan, before the app is constructed. C3.2.
    """

    name: str
    section: str
    key: str
    schema: SettingSchema
    default: str | None = None
    cli_flag: str | None = None
    phase: str | None = None


def _spec(
    section: str,
    key: str,
    type_: str,
    description: str,
    *,
    default: str | None = None,
    choices: list[str] | None = None,
    min_value: int | None = None,
    max_value: int | None = None,
    cli_flag: str | None = None,
    phase: str | None = None,
) -> FuncSetting:
    name = f"{section}.{key}" if section else key
    return FuncSetting(
        name=name,
        section=section,
        key=key,
        schema=SettingSchema(
            name=name,
            type=type_,
            description=description,
            choices=choices,
            min_value=min_value,
            max_value=max_value,
        ),
        default=default,
        cli_flag=cli_flag,
        phase=phase,
    )


def _tui_spec(key: str, default: str) -> FuncSetting:
    """Lift one of the 9 TUI schemas into the catalog under ``tui.``."""
    schema = SETTING_SCHEMAS[key]
    return FuncSetting(
        name=f"tui.{key}",
        section="tui",
        key=key,
        schema=schema,
        default=default,
    )


# TRANSITIONAL(config-unknown-keys/6.3): this `FuncSetting` catalog is no longer
# what the store resolves or the TUI displays — the declared `Setting` schema is
# (see `FuncSettingsStore`). What still reads it: `register_settings` and
# `tui_settings` feed the transitional dispatch flag generation, and the
# deploy-tool example builds its declaration from `FUNC_SCHEMA`. Task 6.3
# removes the catalog; nothing new may depend on it, and the Settings panel and
# the store must not.
#: The shell's own knobs. **Not** in the base catalog — the shell registers
#: them (:func:`register_settings`), which is what makes `tui.*` absent from a
#: project app that never launches one. Kept here rather than in `_cli/tui/`
#: because they are catalog data, and the schemas they lift live next door.
def tui_settings() -> tuple[FuncSetting, ...]:
    """The shell's settings, for the shell to register."""
    return (
        _tui_spec("theme", "transparent"),
        _tui_spec("display_auto_switch", "indicator"),
        _tui_spec("default_surface", "panel"),
        _tui_spec("show_session_stamp", "true"),
        _tui_spec("history_retention", "100"),
        _tui_spec("signature_enabled", "true"),
        _tui_spec("default_override_target", "file"),
    )


# Display order: registered settings first (the shell's, when it has
# registered — this catalog is what its Settings panel shows), then [cli],
# [discovery], and the top-level keys.
_BASE_SETTINGS: tuple[FuncSetting, ...] = (
    _spec(
        "cli",
        "output",
        "enum",
        "CLI output format",
        default="rich",
        choices=["rich", "plain", "json"],
    ),
    _spec("cli", "show_timing", "bool", "Show timing after runs", default="false"),
    _spec("discovery", "require_file_prefix", "str", "Only scan files named <prefix>*"),
    _spec(
        "discovery", "require_file_postfix", "str", "Only scan files named *<postfix>"
    ),
    _spec(
        "discovery",
        "require_file_import",
        "str",
        "Only scan files importing this module",
    ),
    _spec(
        "discovery",
        "require_file_marker",
        "str",
        "Only scan files defining this marker",
    ),
    _spec(
        "discovery",
        "require_job_decorators",
        "list",
        "Only register decorated functions",
    ),
    _spec(
        "discovery", "require_job_prefix", "str", "Only register jobs named <prefix>*"
    ),
    _spec(
        "discovery", "require_job_postfix", "str", "Only register jobs named *<postfix>"
    ),
    _spec("discovery", "extra_directories", "list", "Additional job directories"),
    _spec("discovery", "exclude_patterns", "list", "Glob patterns to skip"),
    _spec(
        "discovery",
        "scan_depth",
        "int",
        "Directory scan depth (0 = unlimited)",
        default="0",
        min_value=0,
        max_value=32,
    ),
    _spec(
        "plugins",
        "strict",
        "bool",
        "Error (not warn) on job metadata whose plugin is not loaded",
        default="false",
    ),
    _spec(
        "shell",
        "program",
        "str",
        "Shell binary for raw shell=True commands (default: platform shell)",
    ),
    _spec(
        "shell",
        "sudo_password",
        "str",
        "Password for sh.sudo() (secret — masked in all output)",
    ),
    _spec(
        "cli",
        "inline_tui",
        "bool",
        "Launch the interactive shell on a bare invocation at a TTY",
        default="true",
    ),
    _spec(
        "vault",
        "keyring_timeout",
        "str",
        "How long a run waits on the OS keyring for the vault key (e.g. 30s, 2m)",
        default="30s",
    ),
    _spec("", "dotenv", "bool", "Load .env at startup", default="false"),
    _spec("", "dotenv_path", "str", "Explicit .env file path"),
    _spec("", "import_libs", "list", "Paths importable by job modules"),
)


# ----------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------

#: Settings contributed at runtime, in registration order. The shell puts its
#: `tui.*` here; a project app's own components can do the same.
_REGISTERED: list[FuncSetting] = []


#: Values captured by the pre-boot early-flag scan (C3.2), dotted name -> value.
#:
#: Process-global rather than threaded through, because the scan happens in
#: ``main()`` *before* the app — and therefore before any store — exists. Every
#: store built afterwards seeds from this, which is precisely what "takes
#: effect before app construction" means for a setting.
_PREBOOT_OVERRIDES: dict[str, tuple[str, str]] = {}


def set_preboot_override(name: str, value: str, *, flag: str = "") -> None:
    """Record an early flag's value for stores built later in this process."""
    _PREBOOT_OVERRIDES[name] = (value, flag)


def preboot_overrides() -> dict[str, tuple[str, str]]:
    """The early-flag values captured so far, as ``name -> (value, flag)``."""
    return dict(_PREBOOT_OVERRIDES)


def clear_preboot_overrides() -> None:
    """Drop captured early-flag values. For tests — the map is process-global."""
    _PREBOOT_OVERRIDES.clear()


def early_flag_specs() -> list[tuple[str, str]]:
    """``(flag, dotted name)`` for settings whose flag must be read pre-boot.

    Empty for `func` itself today — nothing ships ``phase="early"`` — so the
    pre-boot scan short-circuits without touching argv.
    """
    return [
        (s.cli_flag, s.name)
        for s in _current_settings()
        if s.cli_flag and s.phase == "early"
    ]


def register_settings(*settings: FuncSetting) -> None:
    """Contribute settings to the catalog.

    Idempotent per name: registering the same setting twice (a relaunched
    shell, a module imported through two paths) replaces rather than
    duplicates, because a duplicate would render twice in the settings panel
    and make `SETTINGS_ORDER` lie about its own length.

    Raises:
        ValueError: a registered name collides with a **base** setting. That
            is a genuine conflict — the base catalog is not something a
            component may quietly redefine.
    """
    base_names = {s.name for s in _BASE_SETTINGS}
    for setting in settings:
        if setting.name in base_names:
            raise ValueError(
                f"setting {setting.name!r} is already defined in the base "
                f"catalog and cannot be re-registered"
            )
        for i, existing in enumerate(_REGISTERED):
            if existing.name == setting.name:
                _REGISTERED[i] = setting
                break
        else:
            _REGISTERED.append(setting)


def registered_settings() -> tuple[FuncSetting, ...]:
    """Everything registered so far, in registration order."""
    return tuple(_REGISTERED)


def clear_registered_settings() -> None:
    """Drop all registrations. For tests — the catalog is process-global."""
    _REGISTERED.clear()


def _current_settings() -> tuple[FuncSetting, ...]:
    """The live catalog: registered settings first, then the base ones."""
    return (*_REGISTERED, *_BASE_SETTINGS)


# ----------------------------------------------------------------------
# Catalog-derived views
# ----------------------------------------------------------------------
#
# `FUNC_SETTINGS`, `SETTINGS_ORDER` and `DEFAULT_VALUES` used to be constants
# derived from a module-level tuple **at import time**, which a registration
# API silently invalidates: anything registered afterwards would be missing
# from them forever, and the failure presents as a setting that renders in the
# panel but resolves to nothing.
#
# They are **live views**, not module attributes recomputed via PEP 562
# `__getattr__`. The difference is load-bearing: the dominant idiom here is
# `from func_settings import FUNC_SETTINGS`, which binds the object once — and
# `settings_panel.py` imports all three exactly that way. Under `__getattr__`
# that hands out a stale snapshot; a view object stays correct however it was
# imported, so "was the shell registered before this module was imported?"
# stops being a question anyone has to get right.


class _SettingsView(Sequence["FuncSetting"]):
    """The live catalog, readable as a sequence."""

    __slots__ = ()

    def __getitem__(self, index: Any) -> Any:
        return _current_settings()[index]

    def __len__(self) -> int:
        return len(_current_settings())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (tuple, list, _SettingsView)):
            return list(self) == list(other)
        return NotImplemented

    def __repr__(self) -> str:
        return f"<live settings catalog: {len(self)} entries>"


class _NamesView(Sequence[str]):
    """Catalog names, in display order."""

    __slots__ = ()

    def _names(self) -> list[str]:
        return [s.name for s in _current_settings()]

    def __getitem__(self, index: Any) -> Any:
        return self._names()[index]

    def __len__(self) -> int:
        return len(_current_settings())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (tuple, list, _NamesView)):
            return self._names() == list(other)
        return NotImplemented

    def __repr__(self) -> str:
        return repr(self._names())


class _DefaultsView(Mapping[str, str]):
    """Catalog defaults, for the settings that declare one."""

    __slots__ = ()

    def _map(self) -> dict[str, str]:
        return {s.name: s.default for s in _current_settings() if s.default is not None}

    def __getitem__(self, key: str) -> str:
        return self._map()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._map())

    def __len__(self) -> int:
        return len(self._map())

    def __repr__(self) -> str:
        return repr(self._map())


#: The live settings catalog — registered settings first, then the base ones.
FUNC_SETTINGS: Sequence[FuncSetting] = _SettingsView()

#: Catalog names in display order.
SETTINGS_ORDER: Sequence[str] = _NamesView()

#: Catalog defaults by name.
DEFAULT_VALUES: Mapping[str, str] = _DefaultsView()


class _ProjectedView(Sequence["Setting"]):
    """The live catalog projected onto the public, app-agnostic ``Setting``."""

    __slots__ = ()

    def _projected(self) -> list[Setting]:
        return [_as_setting(s) for s in _current_settings()]

    def __getitem__(self, index: Any) -> Any:
        return self._projected()[index]

    def __len__(self) -> int:
        return len(_current_settings())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (tuple, list, _ProjectedView)):
            return self._projected() == list(other)
        return NotImplemented

    def __repr__(self) -> str:
        return f"<live setting projection: {len(self)} entries>"


def _func_schema() -> AppSettingsSchema:
    """`func`'s settings declaration, over the live catalog.

    Passing a different one to :class:`SettingsStore` is what makes the store
    app-agnostic — the env-var prefix and the per-file TOML section prefix come
    from here rather than from literals buried in the store's methods.

    The schema object is stable while its ``settings`` track registration:
    ``_ProjectedView`` is a live sequence, so `from … import FUNC_SCHEMA` is
    not a snapshot the way a materialized tuple would be.
    """
    return AppSettingsSchema(
        settings=_ProjectedView(),  # type: ignore[arg-type]
        env_prefix="FUNCTUALIZE",
    )


def _as_setting(func_setting: FuncSetting) -> Setting:
    """Project a catalog entry onto the public, app-agnostic ``Setting``."""
    schema = func_setting.schema
    return Setting(
        name=func_setting.name,
        type=schema.type,
        description=schema.description,
        default=func_setting.default,
        choices=tuple(schema.choices) if schema.choices else None,
        min_value=schema.min_value,
        max_value=schema.max_value,
        max_items=schema.max_items,
        cli_flag=func_setting.cli_flag,
        phase=func_setting.phase,
    )


#: `func`'s own settings declaration.
#:
#: A plain constant, not a lazy attribute: the schema *object* never needs
#: rebuilding because its ``settings`` is a live view, so binding it with
#: `from … import FUNC_SCHEMA` is not a snapshot.
FUNC_SCHEMA: AppSettingsSchema = _func_schema()


def func_setting(name: str) -> FuncSetting | None:
    """Look up a catalog entry by dotted name.

    Scans the live catalog rather than a dict built at import time, for the
    same reason `SETTINGS_ORDER` is dynamic: a registered setting must be
    findable, and this is not a hot path.
    """
    for setting in _current_settings():
        if setting.name == name:
            return setting
    return None


def validate_func_setting(name: str, value: str) -> ValidationResult:
    """Validate a value against the catalog schema for ``name``."""
    setting = func_setting(name)
    if setting is None:
        return ValidationResult(valid=False, error=f"Unknown setting: {name}")
    return validate_against(setting.schema, value)


def env_var_for(setting: FuncSetting) -> str:
    """The FUNCTUALIZE_* environment variable that overrides ``setting``."""
    if setting.section:
        return f"FUNCTUALIZE_{setting.section.upper()}_{setting.key.upper()}"
    return f"FUNCTUALIZE_{setting.key.upper()}"


def _scalar_to_str(value: Any) -> str:
    """Render a parsed TOML scalar the way the panel displays it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(v) for v in value)
    return str(value)


def _short_display(path: Path) -> str:
    """A compact label for a settings file: cwd-relative, else ~-relative."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        try:
            return "~/" + str(path.relative_to(Path.home()))
        except ValueError:
            return str(path)


class FuncSettingsStore:
    """Resolves, and persists, an app's declared settings with provenance.

    The store **owns no precedence of its own**. Values and provenance come
    from ``resolve_settings``, layers come from the same call, and each layer
    carries the file text a save needs — so the TUI, the CLI and the panel
    cannot disagree about which file won. What the store adds is what a
    settings UI asks for and a resolver does not answer: a chain per key to
    display, a prospective layer for a file that is about to be created, and a
    save that re-resolves afterwards.

    Construct with :meth:`discover` for normal use, or with an app's schema and
    frozen snapshot when a host already resolved them.
    """

    def __init__(
        self,
        schema: AppSettingsSchema | None = None,
        *,
        snapshot: ResolvedSettings | None = None,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        app_name: str = "functualize",
        global_dir: Path | None = None,
    ) -> None:
        """
        Args:
            schema: The app's settings declaration — the env-var prefix, the
                per-file TOML prefixes, and the settings themselves. ``None``
                uses func's own, so `func`'s behavior is unchanged and a second
                app passes its own.
            snapshot: An already-resolved snapshot to start from (the running
                app's boot resolution). ``None`` resolves on first use, so a
                store that is never read never touches a settings file.
            cwd: Where the upward file walk starts. Defaults to the current
                directory, read once here rather than on every refresh.
            env: Environment mapping; defaults to ``os.environ``.
            app_name: Namespaces the global config file. Defaults to func's.
            global_dir: The user config directory holding the global file.
                ``None`` derives it from ``app_name``.
        """
        self._schema = FUNCTUALIZE_SETTINGS if schema is None else schema
        self._snapshot = snapshot
        self._stale = False
        self._cwd = Path(cwd) if cwd is not None else Path.cwd()
        self._env = dict(os.environ) if env is None else dict(env)
        self._app_name = app_name
        self._global_dir = global_dir
        # Layers for files the picker is about to write. Never resolved from:
        # the snapshot decides every value.
        self._prospective: list[SettingsLayer] = []
        # Seeded from the pre-boot scan so an `phase="early"` flag is already
        # in effect for the first store anyone builds (C3.2). A late `--flag`
        # recorded via `set_cli_override` simply overwrites the same slot.
        self._cli_overrides: dict[str, str] = {}
        self._cli_labels: dict[str, str] = {}
        for _name, (_value, _flag) in _PREBOOT_OVERRIDES.items():
            self._cli_overrides[_name] = _value
            if _flag:
                self._cli_labels[_name] = _flag

    def set_cli_override(self, name: str, value: str, *, flag: str = "") -> None:
        """Record a root CLI flag's value as the top precedence rung (C3.1).

        TRANSITIONAL(config-unknown-keys/5.1): the adapter that parses the flags
        is its own row; the override rides into the resolver as ``flags``.

        Args:
            name: Dotted setting name.
            value: The value as typed, validated by the caller against the
                setting's schema.
            flag: The spelling to show as the source label (``--foo``), so the
                TUI's source chain names the flag rather than a generic label.
        """
        self._cli_overrides[name] = value
        if flag:
            self._cli_labels[name] = flag
        # The override changes the answer, so the snapshot is stale. Resolved
        # on next read rather than here: a store nobody reads stays free of
        # file reads, exactly like one built with no overrides.
        self._stale = True

    @classmethod
    def discover(
        cls,
        cwd: Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
        schema: AppSettingsSchema | None = None,
        app_name: str = "functualize",
    ) -> FuncSettingsStore:
        """Build a store over the files this app actually consults."""
        return cls(schema, cwd=cwd, env=env, app_name=app_name)

    # ------------------------------------------------------------------
    # Declaration and layers
    # ------------------------------------------------------------------

    @property
    def schema(self) -> AppSettingsSchema:
        """The declaration this store resolves."""
        return self._schema

    def declared_settings(self, *, surface: str | None = None) -> tuple[Setting, ...]:
        """The declared settings, in declaration order, optionally one surface."""
        settings = tuple(self._schema.settings)
        if surface is None:
            return settings
        return tuple(setting for setting in settings if setting.surface == surface)

    def _resolved(self) -> ResolvedSettings:
        """The current resolution, computing it once on first use."""
        if self._snapshot is None or self._stale:
            self._snapshot = self._resolve_now()
            self._stale = False
        return self._snapshot

    def _resolve_now(self) -> ResolvedSettings:
        return resolve_settings(
            self._schema,
            self._cwd,
            flags=self._cli_overrides,
            env=self._env,
            global_dir=self._global_dir or self._default_global_dir(),
        )

    def _default_global_dir(self) -> Path:
        """``~/.config/<app_name>`` — the directory the global file lives in."""
        from functualize.app.utils import resolve_user_config_dir

        return resolve_user_config_dir().parent / self._app_name

    def _all_layers(self) -> tuple[SettingsLayer, ...]:
        discovered = self._resolved().layers
        known = {layer.path for layer in discovered}
        front = [layer for layer in self._prospective if layer.path not in known]
        return (*front, *discovered)

    @property
    def layers(self) -> list[SettingsLayer]:
        """The file layers, in precedence order (winner first, global last)."""
        return list(self._all_layers())

    @property
    def global_path(self) -> Path:
        """The global config file (may not exist yet)."""
        for layer in self._resolved().layers:
            if layer.kind == "global":
                return layer.path
        # A snapshot always carries a global layer; this fallback only exists
        # so a host-supplied snapshot cannot crash the TUI.
        return self._default_global_dir() / self._schema.sources.global_file_name

    def ensure_layer(self, path: Path) -> None:
        """Register a file a picker may create, without touching the disk.

        The new-file picker lets a user drill into a file that does not exist
        yet; without a layer for it the Detail view would have no chain entry
        to scope to and a save would have nowhere to go. The prospective layer
        goes in front — a file created at the cwd is the nearest project file —
        and contributes **no values**: the snapshot decides those, and a file
        the walk did not pick must not become a second resolution path.
        """
        if any(layer.path == path for layer in self._all_layers()):
            return
        self._prospective.insert(
            0,
            SettingsLayer(
                path, "project", self._schema.section_prefix_for(path.name), {}
            ),
        )

    def refresh(self) -> None:
        """Re-resolve from disk.

        The snapshot is the one place a value comes from, so a save, a flag
        parsed after boot, and a re-opened Detail view all become visible by
        throwing it away.
        """
        self._snapshot = self._resolve_now()
        self._stale = False

    def defined_settings(self, layer: SettingsLayer) -> list[str]:
        """Which declared settings ``layer``'s file defines."""
        return [
            setting.name
            for setting in self._schema.settings
            if self._schema.value_in(layer.values, setting.name) is not None
        ]

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def _layer_value(self, setting: Setting, layer: SettingsLayer) -> str | None:
        """``setting``'s value in one file as display text, or None."""
        raw = self._schema.value_in(layer.values, setting.name)
        return None if raw is None else _scalar_to_str(raw)

    def _env_value(self, setting: Setting) -> str | None:
        """``setting``'s environment value, if the schema reads the environment."""
        if not self._schema.sources.env:
            return None
        raw = self._env.get(self._schema.env_var_for(setting))
        return raw or None

    def resolve(self) -> list[ResolvedKey]:
        """Return each setting's full source chain."""
        # Lazy import — see the module-level note about the tui package cycle.
        from functualize._cli.tui.models.source_chain import (
            NOT_SET,
            ResolvedKey,
            SourceEntry,
        )

        layers = self._all_layers()
        project_layers = [layer for layer in layers if layer.kind == "project"]
        global_layer = next((layer for layer in layers if layer.kind == "global"), None)

        keys: list[ResolvedKey] = []
        for setting in self._schema.settings:
            choices: list[str] | None = None
            if setting.type == "enum" and setting.choices:
                choices = list(setting.choices)
            elif setting.type == "bool":
                choices = ["true", "false"]

            chain: list[SourceEntry] = [
                SourceEntry(
                    source_id="default",
                    label="default",
                    value=setting.default if setting.default is not None else NOT_SET,
                    writable=False,
                    precedence=PRECEDENCE_DEFAULT,
                )
            ]

            if global_layer is not None:
                chain.append(
                    SourceEntry(
                        source_id=f"file:{global_layer.path}",
                        label="global config",
                        value=self._layer_value(setting, global_layer) or NOT_SET,
                        writable=_is_writable(global_layer.path),
                        precedence=PRECEDENCE_GLOBAL,
                    )
                )

            # Nearest project file wins, so it gets the highest rank in the
            # project band. The project band is empty in practice: the global
            # layer is the only one every store has.
            count = len(project_layers)
            for index, layer in enumerate(project_layers):
                chain.append(
                    SourceEntry(
                        source_id=f"file:{layer.path}",
                        label=_short_display(layer.path),
                        value=self._layer_value(setting, layer) or NOT_SET,
                        writable=_is_writable(layer.path),
                        precedence=PRECEDENCE_PROJECT_BASE + (count - 1 - index),
                    )
                )

            env_name = self._schema.env_var_for(setting)
            chain.append(
                SourceEntry(
                    source_id=f"env:{env_name}",
                    label=env_name,
                    value=self._env_value(setting) or NOT_SET,
                    writable=False,
                    precedence=PRECEDENCE_ENV,
                )
            )

            # A root CLI flag, when one was generated for this setting and
            # actually passed (C3.1). Only appended when present so that an
            # un-passed flag does not show up as an empty rung in the TUI's
            # source chain — "not given" and "given as empty" are different.
            cli_value = self._cli_overrides.get(setting.name)
            if cli_value is not None:
                chain.append(
                    SourceEntry(
                        source_id=f"cli:{setting.name}",
                        label=self._cli_labels.get(setting.name, "command line"),
                        value=cli_value,
                        writable=False,
                        precedence=PRECEDENCE_CLI,
                    )
                )

            keys.append(
                ResolvedKey(
                    name=setting.name,
                    chain=chain,
                    description=setting.description,
                    type_hint=setting.type,
                    choices=choices,
                )
            )
        return keys

    def effective_values(self) -> dict[str, str]:
        """The winning value for each setting, keyed by dotted name.

        Read from the snapshot, not from the chain: the chain is a display of
        each source's contribution, the snapshot is the answer.
        """
        snapshot = self._resolved()
        return {
            setting.name: _scalar_to_str(snapshot.values[setting.name])
            for setting in self._schema.settings
            if setting.name in snapshot.values
        }

    def source_labels(self) -> dict[str, str]:
        """The label of the winning source for each setting, from provenance."""
        snapshot = self._resolved()
        global_path = self.global_path
        labels: dict[str, str] = {}
        for setting in self._schema.settings:
            provenance = snapshot.provenance.get(setting.name, "default")
            if provenance == "default":
                labels[setting.name] = "default"
            elif provenance == "cli":
                labels[setting.name] = self._cli_labels.get(
                    setting.name, "command line"
                )
            elif provenance == "env":
                labels[setting.name] = self._schema.env_var_for(setting)
            else:
                path = Path(provenance)
                labels[setting.name] = (
                    "global config" if path == global_path else _short_display(path)
                )
        return labels

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _layer_for(self, path: Path) -> SettingsLayer:
        for layer in self._all_layers():
            if layer.path == path:
                return layer
        # A file outside the discovered layers: derive its shape from the
        # filename. Its text is loaded by :meth:`write` before the save.
        return SettingsLayer(
            path, "project", self._schema.section_prefix_for(path.name), {}
        )

    def _text_for(self, layer: SettingsLayer) -> str:
        """The file's current text, read through the one settings reader."""
        if layer.text:
            return layer.text
        if not layer.path.is_file():
            return ""
        return SettingsLayer.read(layer.path, layer.kind, layer.section_prefix).text

    def write(
        self,
        path: Path,
        edits: dict[str, str],
        removals: set[str] | None = None,
    ) -> None:
        """Persist settings (keyed by dotted name) to one file, atomically.

        Edits may span sections (``tui.theme`` and ``cli.output`` in one
        save); they are grouped by section and written by one call, so a save
        is a single atomic replacement of the file. Values land with their
        declared type, so ``tui.history_retention`` is written as ``100``
        rather than ``"100"``.

        Nothing here opens the file for reading: the text comes from the layer,
        which read it once, and goes to the writer as data.

        Raises:
            ValueError: If a name is not declared or a value fails its schema —
                callers should validate before staging, so reaching here is a
                bug.
        """
        self.refresh()
        layer = self._layer_for(path)
        text = self._text_for(layer)

        sections: dict[str, SectionEdits] = {}

        def _bucket(name: str) -> tuple[Setting, SectionEdits]:
            setting = next((s for s in self._schema.settings if s.name == name), None)
            if setting is None:
                raise ValueError(f"Unknown setting: {name}")
            section = self._schema.section_in_file(setting, path.name)
            return setting, sections.setdefault(section, SectionEdits())

        for name, value in edits.items():
            setting, bucket = _bucket(name)
            result = validate_against(setting_schema(setting), value)
            if not result.valid:
                raise ValueError(f"Invalid value for {name!r}: {result.error}")
            bucket.edits[setting.key] = value
            bucket.type_hints[setting.key] = setting.type

        for name in removals or set():
            setting, bucket = _bucket(name)
            bucket.removals.add(setting.key)

        write_toml_sections(path, text, sections)
        self.refresh()


def setting_schema(setting: Setting) -> SettingSchema:
    """A `SettingSchema` for validating one edited value.

    The panel validates an edit the same way with the same adapter; the store
    has to keep doing it because a save is reachable without the panel.
    """
    return SettingSchema(
        name=setting.name,
        type=setting.type,
        description=setting.description,
        choices=list(setting.choices) if setting.choices else None,
        min_value=setting.min_value,
        max_value=setting.max_value,
        max_items=setting.max_items,
    )


def _is_writable(path: Path) -> bool:
    """Whether we could write ``path`` — creating it if it doesn't exist yet."""
    if path.exists():
        return os.access(path, os.W_OK)
    parent = path.parent
    while not parent.exists() and parent.parent != parent:
        parent = parent.parent
    return os.access(parent, os.W_OK)


#: The app-agnostic spelling. ``FuncSettingsStore`` is the same class under its
#: historical name — every default on the constructor is func's, so the two are
#: interchangeable for func and only a second app ever passes the parameters.
SettingsStore = FuncSettingsStore
