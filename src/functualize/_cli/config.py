"""CLI tool configuration reader and environment variable resolver.

Reads global config (~/.config/functualize/config.toml), project-level config
(pyproject.toml [tool.functualize] or .functualize.toml), and FUNCTUALIZE_*
environment variables.

This module is in the ``_cli/`` layer — it imports ONLY from public API
(``functualize.app``). It does NOT import from ``_primitives/``, ``_discovery/``,
or other internal modules.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from functualize.app.config import DiscoveryConfig
from functualize.app.utils import resolve_user_config_dir

# Recognized top-level sections in the global config
_RECOGNIZED_SECTIONS = frozenset({"discovery", "cli", "aliases", "tui"})

# Recognized top-level keys (non-section values) in the global config
_RECOGNIZED_TOP_LEVEL_KEYS = frozenset(
    {"import_libs", "jobs_directories", "extra_directories", "dotenv", "dotenv_path"}
)

# Recognized keys per section in the global config
_RECOGNIZED_KEYS: dict[str, frozenset[str]] = {
    "discovery": frozenset(
        {
            "require_file_prefix",
            "require_file_postfix",
            "require_file_import",
            "require_file_marker",
            "require_job_decorators",
            "require_job_prefix",
            "require_job_postfix",
            "extra_directories",
            "exclude_patterns",
            "scan_depth",
        }
    ),
    "cli": frozenset({"output", "show_timing", "inline_tui"}),
    # The inline TUI's settings live in the same config files as everything
    # else. (They previously read a parallel `functualize.toml` /
    # `settings.toml` pair that no other part of `func` consulted — a user
    # could set them and have all real func config silently ignored.)
    "tui": frozenset(
        {
            "default_surface",
            "show_session_stamp",
            "history_retention",
            "signature_enabled",
            "sensitive_keywords",
            "display_auto_switch",
            "default_override_target",
            "theme",
        }
    ),
    # [aliases] section has free-form string keys — no validation
}

# Env var prefix
_ENV_PREFIX = "FUNCTUALIZE_"


def _warn(msg: str) -> None:
    """Emit a warning to stderr."""
    print(f"Warning: {msg}", file=sys.stderr)


def read_global_config(config_dir: Path) -> dict[str, Any]:
    """Read and parse the global config file.

    Handles:
    - Missing file → empty dict (no error)
    - Unreadable file (permissions, I/O) → warn to stderr, return empty dict
    - TOML syntax errors → warn to stderr with file path + line number, return empty dict
    - Unrecognized top-level sections → silently ignored
    - Unrecognized keys in recognized sections → warn to stderr, ignore key

    Parameters
    ----------
    config_dir:
        Path to the config directory (e.g. ``~/.config/functualize/``).

    Returns
    -------
    dict[str, Any]
        Raw parsed TOML as nested dict, with unrecognized keys filtered out.
    """
    config_path = config_dir / "config.toml"

    if not config_path.exists():
        return {}

    try:
        content = config_path.read_bytes()
    except PermissionError:
        _warn(f"{config_path}: permission denied")
        return {}
    except OSError as exc:
        _warn(f"{config_path}: {exc}")
        return {}

    try:
        data = tomllib.loads(content.decode("utf-8"))
    except UnicodeDecodeError as exc:
        _warn(f"{config_path}: invalid UTF-8 encoding: {exc}")
        return {}
    except tomllib.TOMLDecodeError as exc:
        _warn(f"{config_path}: {exc}")
        return {}

    # Filter out unrecognized keys in recognized sections
    result: dict[str, Any] = {}
    for section, value in data.items():
        # Check if it's a recognized top-level key (non-section)
        if section in _RECOGNIZED_TOP_LEVEL_KEYS:
            result[section] = value
            continue

        if section not in _RECOGNIZED_SECTIONS:
            # Silently ignore unrecognized top-level sections
            continue

        if section == "aliases":
            # [aliases] section has free-form keys — pass through as-is
            result[section] = value
            continue

        if not isinstance(value, dict):
            # Section should be a table; skip if not
            _warn(f"{config_path}: section [{section}] is not a table, ignoring")
            continue

        recognized_keys = _RECOGNIZED_KEYS.get(section, frozenset())
        filtered_section: dict[str, Any] = {}
        for key, val in value.items():
            if key not in recognized_keys:
                _warn(
                    f"{config_path}: unrecognized key '{key}' in [{section}], ignoring"
                )
                continue
            filtered_section[key] = val

        if filtered_section:
            result[section] = filtered_section

    return result


def resolve_env_overrides() -> dict[str, Any]:
    """Collect FUNCTUALIZE_* environment variables and map to config keys.

    Mapping convention:
        ``FUNCTUALIZE_<SECTION>_<KEY>`` → ``{section: {key: value}}``

    For example:
        ``FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT=functualize``
        → ``{"discovery": {"require_file_import": "functualize"}}``

    Recognized top-level keys take precedence over section splitting:
        ``FUNCTUALIZE_DOTENV=true`` → ``{"dotenv": "true"}``
        ``FUNCTUALIZE_DOTENV_PATH=.env.local`` → ``{"dotenv_path": ".env.local"}``

    Empty string values are treated as unset (skipped).

    Returns
    -------
    dict[str, Any]
        Nested dict matching config structure.
    """
    result: dict[str, Any] = {}

    for env_key, env_value in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue

        # Skip empty string values
        if not env_value:
            continue

        # Strip the prefix and split into section + key parts
        remainder = env_key[len(_ENV_PREFIX) :]

        # Recognized top-level keys win over section splitting — otherwise
        # FUNCTUALIZE_DOTENV_PATH would parse as {"dotenv": {"path": ...}}
        # and shadow the real top-level "dotenv" value in the chain.
        top_level_key = remainder.lower()
        if top_level_key in _RECOGNIZED_TOP_LEVEL_KEYS:
            result[top_level_key] = env_value
            continue

        # Find the section boundary: first underscore after the prefix
        # FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_IMPORT
        #            ^^^^^^^^^^ section
        #                       ^^^^^^^^^^^^^^^^^^ key (underscores preserved)
        parts = remainder.split("_", 1)
        if len(parts) < 2:
            # Single word after prefix that isn't a recognized top-level key
            # — not a section.key structure, skip
            continue

        section = parts[0].lower()
        key = parts[1].lower()

        if section not in result:
            result[section] = {}

        result[section][key] = env_value

    return result


# =============================================================================
# CliConfig dataclass and resolve_cli_config()
# =============================================================================

# Valid output format values
_VALID_OUTPUT_FORMATS = frozenset({"rich", "plain", "json"})

# Alias name validation pattern: starts with letter, then alphanumeric/underscore/dash
_ALIAS_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
_ALIAS_MAX_LENGTH = 32

# Boolean env var mapping (case-insensitive)
_BOOL_TRUE_VALUES = frozenset({"true", "1"})
_BOOL_FALSE_VALUES = frozenset({"false", "0"})


@dataclass(frozen=True)
class CliConfig:
    """Fully resolved CLI tool configuration (merged from all sources)."""

    discovery: DiscoveryConfig
    output: str  # "rich" | "plain" | "json"
    show_timing: bool
    aliases: dict[str, str]
    dotenv: bool
    dotenv_path: str | None
    scan_depth: int = (
        0  # Resolved from config escalation (CLI flag takes precedence externally)
    )
    import_libs: tuple[str, ...] = ()
    anchor: Path | None = None  # Directory containing the nearest config file


def _parse_bool_env(value: str) -> bool | None:
    """Parse a boolean environment variable value.

    Accepts case-insensitive: "true"/"1" → True, "false"/"0" → False.
    Returns None if the value is not a recognized boolean string.
    """
    lower = value.lower()
    if lower in _BOOL_TRUE_VALUES:
        return True
    if lower in _BOOL_FALSE_VALUES:
        return False
    return None


def _merge_lists_dedup(
    project_list: list[str] | None, global_list: list[str] | None
) -> tuple[str, ...]:
    """Concatenate project + global lists, deduplicating (project wins on conflict).

    Project-level entries are retained when a string appears in both lists.
    """
    project = project_list or []
    global_ = global_list or []

    seen: set[str] = set()
    result: list[str] = []

    # Project entries first (they take priority)
    for item in project:
        if item not in seen:
            seen.add(item)
            result.append(item)

    # Then global entries (skipped if already seen from project)
    for item in global_:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return tuple(result)


def _get_value(
    key: str,
    cli_flags: dict[str, Any],
    env: dict[str, Any],
    project: dict[str, Any],
    global_: dict[str, Any],
    *,
    section: str | None = None,
) -> Any:
    """Get a value from the precedence chain (highest non-None wins).

    Resolution: cli_flags → env → project → global → None
    """
    # CLI flags (flat keys)
    val = cli_flags.get(key)
    if val is not None:
        return val

    # Env overrides (nested under section)
    if section:
        env_section = env.get(section, {})
        val = env_section.get(key)
        if val is not None:
            return val
    else:
        val = env.get(key)
        if val is not None:
            return val

    # Project config (nested under section)
    if section:
        proj_section = project.get(section, {})
        val = proj_section.get(key)
        if val is not None:
            return val
    else:
        val = project.get(key)
        if val is not None:
            return val

    # Global config (nested under section)
    if section:
        glob_section = global_.get(section, {})
        val = glob_section.get(key)
        if val is not None:
            return val
    else:
        val = global_.get(key)
        if val is not None:
            return val

    return None


def _validate_aliases(aliases_raw: dict[str, Any]) -> dict[str, str]:
    """Validate alias names against pattern and max length, warn on invalid."""
    validated: dict[str, str] = {}
    for name, target in aliases_raw.items():
        if not isinstance(target, str):
            _warn(f"alias '{name}': value must be a string, skipping")
            continue
        if len(name) > _ALIAS_MAX_LENGTH:
            _warn(
                f"alias '{name}': name exceeds {_ALIAS_MAX_LENGTH} characters, skipping"
            )
            continue
        if not _ALIAS_PATTERN.match(name):
            _warn(
                f"alias '{name}': name does not match pattern "
                f"[a-zA-Z][a-zA-Z0-9_-]*, skipping"
            )
            continue
        validated[name] = target
    return validated


def _resolve_import_libs(
    flags: dict[str, Any],
    env_overrides: dict[str, Any],
    project_config: dict[str, Any],
    global_config: dict[str, Any],
    anchor: Path,
) -> tuple[str, ...]:
    """Resolve import_libs from the full precedence chain.

    Resolution: CLI flags → ENV → project config → global config.
    All relative paths resolved against anchor. Deduplicated by first occurrence.

    Returns:
        Tuple of absolute path strings.
    """
    layers: list[list[str]] = []

    # 1. CLI flags (highest priority)
    cli_val = flags.get("import_libs")
    if cli_val:
        if isinstance(cli_val, list | tuple):
            layers.append([str(v) for v in cli_val])
        elif isinstance(cli_val, str):
            layers.append([cli_val])

    # 2. ENV: FUNCTUALIZE_IMPORT_LIBS (comma-separated)
    env_val = os.environ.get("FUNCTUALIZE_IMPORT_LIBS", "")
    if env_val:
        layers.append([p.strip() for p in env_val.split(",") if p.strip()])

    # 3. Project config (top-level import_libs key)
    project_val = project_config.get("import_libs")
    if project_val and isinstance(project_val, list):
        layers.append([str(v) for v in project_val])

    # 4. Global config
    global_val = global_config.get("import_libs")
    if global_val and isinstance(global_val, list):
        layers.append([str(v) for v in global_val])

    # Flatten, resolve relative paths against anchor, deduplicate
    seen: set[str] = set()
    result: list[str] = []
    for layer in layers:
        for item in layer:
            path = Path(item)
            if not path.is_absolute():
                path = anchor / path
            resolved = str(path.resolve())
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)

    return tuple(result)


def resolve_cli_config(
    *,
    cli_flags: dict[str, Any] | None = None,
    cwd: Path | None = None,
) -> CliConfig:
    """Resolve CLI tool configuration from the full precedence chain.

    Resolution order (highest to lowest priority):
    1. cli_flags (--require-file-import, --exclude, etc.)
    2. FUNCTUALIZE_* environment variables
    3. Project config (upward-walk: .functualize.toml, pyproject.toml, etc.)
    4. ~/.config/functualize/config.toml
    5. Built-in defaults

    For each setting, highest non-None wins.
    For list settings (exclude_patterns, extra_directories): concatenate project + global,
    then deduplicate (project-level retained on conflict).

    Parameters
    ----------
    cli_flags:
        Dict of CLI flag overrides (flat keys, e.g. "require_file_import").
    cwd:
        Working directory for config resolution. Defaults to Path.cwd().

    Returns
    -------
    CliConfig
        Fully resolved, frozen configuration.
    """
    from functualize.app.utils import resolve_project_config

    flags = cli_flags or {}
    effective_cwd = cwd or Path.cwd()

    # Read all sources
    config_dir = resolve_user_config_dir()
    global_config = read_global_config(config_dir)
    anchor, project_config = resolve_project_config(effective_cwd)
    env_overrides = resolve_env_overrides()

    # --- Resolve discovery settings ---
    discovery_section_project = project_config.get("discovery", {})
    discovery_section_global = global_config.get("discovery", {})

    # Scalar discovery fields
    require_file_prefix = _get_value(
        "require_file_prefix",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="discovery",
    )
    require_file_postfix = _get_value(
        "require_file_postfix",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="discovery",
    )
    require_file_import = _get_value(
        "require_file_import",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="discovery",
    )
    require_file_marker = _get_value(
        "require_file_marker",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="discovery",
    )
    require_job_prefix = _get_value(
        "require_job_prefix",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="discovery",
    )
    require_job_postfix = _get_value(
        "require_job_postfix",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="discovery",
    )

    # require_job_decorators — may come as list or tuple
    require_job_decorators_raw = _get_value(
        "require_job_decorators",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="discovery",
    )
    require_job_decorators: tuple[str, ...] | None = None
    if require_job_decorators_raw is not None:
        if isinstance(require_job_decorators_raw, list | tuple):
            require_job_decorators = tuple(require_job_decorators_raw)
        else:
            # Single string value (e.g., from env var)
            require_job_decorators = (str(require_job_decorators_raw),)

    # List fields: concatenate project + global, then deduplicate
    # CLI flag exclude_patterns are appended on top
    project_exclude = discovery_section_project.get("exclude_patterns")
    global_exclude = discovery_section_global.get("exclude_patterns")
    exclude_patterns = _merge_lists_dedup(
        project_exclude if isinstance(project_exclude, list) else None,
        global_exclude if isinstance(global_exclude, list) else None,
    )
    # CLI flags append additional patterns
    cli_exclude = flags.get("exclude_patterns")
    if cli_exclude:
        if isinstance(cli_exclude, list | tuple):
            all_exclude = list(exclude_patterns) + list(cli_exclude)
        else:
            all_exclude = list(exclude_patterns) + [str(cli_exclude)]
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for item in all_exclude:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        exclude_patterns = tuple(deduped)

    # Env override for exclude_patterns (comma-separated string)
    env_exclude = env_overrides.get("discovery", {}).get("exclude_patterns")
    if (
        env_exclude
        and isinstance(env_exclude, str)
        and not project_exclude
        and not global_exclude
    ):
        # Only use env if no file-based config provides it
        exclude_patterns = tuple(p.strip() for p in env_exclude.split(",") if p.strip())

    project_extra_dirs = discovery_section_project.get("extra_directories")
    global_extra_dirs = discovery_section_global.get("extra_directories")
    extra_directories = _merge_lists_dedup(
        project_extra_dirs if isinstance(project_extra_dirs, list) else None,
        global_extra_dirs if isinstance(global_extra_dirs, list) else None,
    )

    discovery = DiscoveryConfig(
        exclude_patterns=exclude_patterns,
        extra_directories=extra_directories,
        require_file_prefix=require_file_prefix,
        require_file_postfix=require_file_postfix,
        require_file_import=require_file_import,
        require_file_marker=require_file_marker,
        require_job_decorators=require_job_decorators,
        require_job_prefix=require_job_prefix,
        require_job_postfix=require_job_postfix,
    )

    # --- Resolve CLI settings ---
    output_raw = _get_value(
        "output", flags, env_overrides, project_config, global_config, section="cli"
    )
    output: str = "rich"  # default
    if output_raw is not None:
        output_str = str(output_raw)
        if output_str in _VALID_OUTPUT_FORMATS:
            output = output_str
        else:
            _warn(
                f"[cli].output: invalid value '{output_str}', "
                f"must be one of {sorted(_VALID_OUTPUT_FORMATS)}, falling back to 'rich'"
            )

    show_timing_raw = _get_value(
        "show_timing",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="cli",
    )
    show_timing: bool = False  # default
    if show_timing_raw is not None:
        if isinstance(show_timing_raw, bool):
            show_timing = show_timing_raw
        elif isinstance(show_timing_raw, str):
            parsed = _parse_bool_env(show_timing_raw)
            if parsed is not None:
                show_timing = parsed
            else:
                _warn(
                    f"[cli].show_timing: invalid boolean value '{show_timing_raw}', "
                    f"expected true/1/false/0, falling back to false"
                )

    # --- Resolve aliases ---
    # Merge project + global aliases (project wins on conflict)
    project_aliases = project_config.get("aliases", {})
    global_aliases = global_config.get("aliases", {})
    merged_aliases: dict[str, Any] = {}
    if isinstance(global_aliases, dict):
        merged_aliases.update(global_aliases)
    if isinstance(project_aliases, dict):
        merged_aliases.update(project_aliases)  # project wins

    # CLI flag aliases override
    cli_aliases = flags.get("aliases")
    if isinstance(cli_aliases, dict):
        merged_aliases.update(cli_aliases)

    aliases = _validate_aliases(merged_aliases)

    # --- Resolve dotenv settings ---
    dotenv_raw = _get_value(
        "dotenv", flags, env_overrides, project_config, global_config
    )
    dotenv: bool = False  # default
    if dotenv_raw is not None:
        if isinstance(dotenv_raw, bool):
            dotenv = dotenv_raw
        elif isinstance(dotenv_raw, str):
            parsed = _parse_bool_env(dotenv_raw)
            if parsed is not None:
                dotenv = parsed
        else:
            _warn(
                f"dotenv: expected a boolean, got {type(dotenv_raw).__name__}; ignoring"
            )
            dotenv_fallback = _get_value(
                "dotenv", {}, {}, project_config, global_config
            )
            if isinstance(dotenv_fallback, bool):
                dotenv = dotenv_fallback

    dotenv_path = _get_value(
        "dotenv_path", flags, env_overrides, project_config, global_config
    )
    if dotenv_path is not None and not isinstance(dotenv_path, str | Path):
        _warn(
            f"dotenv_path: expected a string, got {type(dotenv_path).__name__}; "
            f"ignoring"
        )
        dotenv_path = None
    if dotenv_path is not None:
        dotenv_path = str(dotenv_path)

    # --- Resolve scan_depth ---
    scan_depth_raw = _get_value(
        "scan_depth",
        flags,
        env_overrides,
        project_config,
        global_config,
        section="discovery",
    )
    scan_depth: int = 0  # default
    if scan_depth_raw is not None:
        try:
            scan_depth = int(scan_depth_raw)
        except (ValueError, TypeError):
            _warn(
                f"[discovery].scan_depth: invalid integer value '{scan_depth_raw}', "
                f"falling back to 0"
            )

    # --- Resolve import_libs ---
    import_libs = _resolve_import_libs(
        flags, env_overrides, project_config, global_config, anchor
    )

    return CliConfig(
        discovery=discovery,
        output=output,
        show_timing=show_timing,
        aliases=aliases,
        dotenv=dotenv,
        dotenv_path=dotenv_path,
        scan_depth=scan_depth,
        import_libs=import_libs,
        anchor=anchor,
    )


# =============================================================================
# Per-file provenance
# =============================================================================


@dataclass(frozen=True)
class SettingsFileInfo:
    """One config file participating in `func`'s own settings resolution.

    ``resolve_cli_config`` merges every layer into a flat ``CliConfig`` and
    discards which file said what. This keeps the layers apart, so a settings
    UI can attribute each value to the file that contributed it — and offer
    the right file to write an edit back to.

    Attributes:
        path: Absolute path to the file.
        kind: ``"project"`` (found by the upward walk) or ``"global"``
            (the user config directory). Project layers outrank global.
        section_prefix: TOML path under which functualize settings live in
            this file — ``"tool.functualize"`` for ``pyproject.toml``, empty
            for dedicated files whose whole document is functualize's.
        values: The functualize-scoped table (already stripped of the
            prefix), parsed fresh. Empty when the file is missing or broken.
    """

    path: Path
    kind: str
    section_prefix: str
    values: dict[str, Any]

    @property
    def exists(self) -> bool:
        """Whether the file is present on disk."""
        return self.path.is_file()


def _parse_toml_or_empty(path: Path) -> dict[str, Any]:
    """Parse a TOML file, treating any failure as "contributes nothing"."""
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def _functualize_table(path: Path) -> tuple[dict[str, Any], str]:
    """Return (functualize-scoped values, section prefix) for a config file."""
    data = _parse_toml_or_empty(path)
    if path.name == "pyproject.toml":
        tool = data.get("tool")
        section = tool.get("functualize") if isinstance(tool, dict) else None
        return (section if isinstance(section, dict) else {}, "tool.functualize")
    return (data, "")


def resolve_cli_config_layers(cwd: Path | None = None) -> list[SettingsFileInfo]:
    """Return every settings file layer, in precedence order (winner first).

    The same files ``resolve_cli_config`` consults, kept apart instead of
    merged: project files nearest-first (each one the file that would win in
    its directory), then the global ``config.toml`` last.

    The global file is included even when it does not exist yet — its path is
    where a "save globally" edit goes, so callers need it either way; check
    :attr:`SettingsFileInfo.exists`.
    """
    from functualize.app.utils import list_project_config_files

    effective_cwd = cwd or Path.cwd()

    layers: list[SettingsFileInfo] = []
    for _directory, file_path in list_project_config_files(effective_cwd):
        values, prefix = _functualize_table(file_path)
        layers.append(
            SettingsFileInfo(
                path=file_path, kind="project", section_prefix=prefix, values=values
            )
        )

    global_path = resolve_user_config_dir() / "config.toml"
    layers.append(
        SettingsFileInfo(
            path=global_path,
            kind="global",
            section_prefix="",
            values=_parse_toml_or_empty(global_path) if global_path.is_file() else {},
        )
    )
    return layers
