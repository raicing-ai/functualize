"""CLI tool configuration reader and environment variable resolver.

Reads global config (~/.config/functualize/config.toml), project-level config
(pyproject.toml [tool.functualize] or .functualize.toml), and FUNCTUALIZE_*
environment variables.

This module is in the ``_cli/`` layer — it imports ONLY from public API
(``functualize.app``). It does NOT import from ``_primitives/``, ``_discovery/``,
or other internal modules.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from functualize.app.config import CliConfig, resolve_app_settings
from functualize.app.utils import resolve_user_config_dir

# TRANSITIONAL(config-unknown-keys/8.1): row 8.1 deletes this after config show and the settings store have moved.
# Recognized top-level sections in the global config
_RECOGNIZED_SECTIONS = frozenset({"discovery", "cli", "aliases", "tui", "vault"})

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
            "display_auto_switch",
            "default_override_target",
            "theme",
        }
    ),
    # The OS keyring wait for the vault key. Read here, carried to the app as
    # data in `ConfigSources`, so `_config`/`_app` never import this layer.
    "vault": frozenset({"keyring_timeout"}),
    # [aliases] section has free-form string keys — no validation
}


def _warn(msg: str) -> None:
    """Emit a warning to stderr."""
    print(f"Warning: {msg}", file=sys.stderr)


# TRANSITIONAL(config-unknown-keys/8.1): row 8.1 deletes this after config show and the settings store have moved.
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


# =============================================================================
# resolve_cli_config — projection of the shared settings resolution
# =============================================================================


def resolve_cli_config(
    *,
    cli_flags: dict[str, Any] | None = None,
    cwd: Path | None = None,
) -> CliConfig:
    """Project the shared settings resolution onto ``CliConfig``.

    Resolution order (highest to lowest priority) is the declared ladder:
    CLI flags, ``FUNCTUALIZE_*`` environment variables, project files
    nearest-first, the global config, then built-in defaults.

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
    return CliConfig.from_settings(
        resolve_app_settings(
            cwd or Path.cwd(),
            flags=cli_flags,
            global_dir=resolve_user_config_dir(),
        )
    )


# =============================================================================
# Per-file provenance
# =============================================================================


# TRANSITIONAL(config-unknown-keys/8.1): row 8.1 deletes this after config show and the settings store have moved.
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


# TRANSITIONAL(config-unknown-keys/8.1): row 8.1 deletes this after config show and the settings store have moved.
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
