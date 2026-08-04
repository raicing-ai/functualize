"""Config file discovery for the target selector.

Builds the ordered list of ConfigTarget entries for inline edit flows,
sourced from the same project-config discovery used everywhere else in
the framework (``functualize.app.utils.list_project_config_files`` /
``resolve_user_config_dir``) rather than re-walking the filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path

from functualize._cli.data.config_target import ConfigTarget
from functualize.app.utils import list_project_config_files, resolve_user_config_dir


def discover_config_targets(
    job_name: str,
    field_name: str,
    cwd: Path,
) -> list[ConfigTarget]:
    """Discover all writable config persistence targets.

    Order: project files (nearest to farthest) → user config → env var.
    Deduplicates by resolved absolute path.

    Under the SmartBar-as-CLI model there is no
    "This session only" target — a value has no life apart from the SmartBar.

    Args:
        job_name: Qualified job name (e.g., "infra.deploy").
        field_name: Config field name being edited.
        cwd: Current working directory to start walking from.

    Returns:
        Ordered list of ConfigTarget entries for the target selector.
    """
    targets: list[ConfigTarget] = []
    seen_paths: set[Path] = set()

    # 1. Walk from CWD to filesystem root looking for project config files
    project_targets = _discover_project_files(cwd, seen_paths)
    targets.extend(project_targets)

    # 2. Add user-level config (always shown, even if not exists)
    user_config = _get_user_config_target(seen_paths)
    if user_config is not None:
        targets.append(user_config)

    # 3. Add environment variable target
    env_target = _build_env_var_target(job_name, field_name)
    targets.append(env_target)

    return targets


def _discover_project_files(
    cwd: Path,
    seen_paths: set[Path],
) -> list[ConfigTarget]:
    """Collect writable project config files, nearest to farthest.

    Delegates discovery to ``list_project_config_files`` — the same
    upward-walking candidate resolution used by ``resolve_project_config``
    (one file per directory, ``pyproject.toml [tool.functualize]``
    preferred over ``.functualize.toml`` when both exist).
    """
    targets: list[ConfigTarget] = []
    for _directory, file_path in list_project_config_files(cwd):
        _try_add_file_target(file_path, seen_paths, targets)
    return targets


def _try_add_file_target(
    file_path: Path,
    seen_paths: set[Path],
    targets: list[ConfigTarget],
) -> None:
    """Add a file target if it exists, is writable, and not a duplicate."""
    if not file_path.is_file():
        return

    try:
        resolved = file_path.resolve()
    except OSError:
        # Broken symlink or resolution failure
        return

    if resolved in seen_paths:
        return

    if not os.access(resolved, os.W_OK):
        return

    seen_paths.add(resolved)
    targets.append(
        ConfigTarget(
            type="file",
            label=file_path.name,
            detail=str(resolved),
            path=resolved,
        ),
    )


def _get_user_config_target(seen_paths: set[Path]) -> ConfigTarget | None:
    """Build the user-level config target.

    Always shown even if the file doesn't exist (created on write).
    Still deduplicated by resolved path if a symlink elsewhere points here.
    """
    user_config_path = resolve_user_config_dir() / "config.toml"

    # Resolve the path for deduplication. If the file doesn't exist,
    # use the unresolved path (it will be created on write).
    if user_config_path.exists():
        try:
            resolved = user_config_path.resolve()
        except OSError:
            resolved = user_config_path
    else:
        resolved = user_config_path

    if resolved in seen_paths:
        return None

    seen_paths.add(resolved)
    return ConfigTarget(
        type="file",
        label=user_config_path.name,
        detail=str(resolved),
        path=resolved,
    )


def _build_env_var_target(job_name: str, field_name: str) -> ConfigTarget:
    """Build the environment variable target.

    Pattern: {JOB_NAME}_{FIELD} in uppercase, with dots and hyphens
    replaced by underscores.
    """
    env_name = f"{job_name}_{field_name}".upper().replace(".", "_").replace("-", "_")
    return ConfigTarget(
        type="env",
        label=env_name,
        detail="environment variable",
    )
