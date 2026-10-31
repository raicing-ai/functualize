"""CLI projection of the shared application settings resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from functualize.app.config import CliConfig, resolve_app_settings
from functualize.app.utils import resolve_user_config_dir


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
