"""Where a project's declared directories resolve to — the one answer.

This is "walk A" in `.spec/features/declared-plugin-directories/research.md` §5:
walk upward from the working directory collecting one config per level, merge
them nearest-first with ``root = true`` stop semantics, then resolve the
list-valued directory keys through the full precedence chain::

    CLI  +  ENV  +  File layers  +  Convention  +  Global  +  Defaults

It lived in ``functualize/app/utils.py`` until `declared-plugin-directories`/T2.
Nothing about the logic changed in the move; what changed is who can reach it.
``app/`` is a **public** package, and import-linter's *"Internal never imports
public"* contract means no internal layer may import from it — so ``_app/boot.py``
could not call this, and the plugin loader grew a second, divergent resolver of
its own that asked a source which does not exist yet at plugin-load time. That
is the bug the feature exists to fix, and a shared home is the fix.

Callers:

- ``functualize.app.utils`` re-exports ``resolve_project_config`` and
  ``resolve_effective_directories`` unchanged, so the public surface and its
  tests are untouched (public → internal is the legal direction);
- ``functualize._app.boot`` calls it directly at boot, before the resolution
  chain exists.

``_plugins/`` does **not** import this module and must not: peer layers are
independent. It receives the resolved ``list[str]`` from the composition root.

Only imports from ``_primitives/``, the sibling ``_config.merge``, and stdlib.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from functualize._config.merge import merge_config_layers
from functualize._primitives.locator import (
    ResourceLocator,
    find_functualize_dir,
    xdg_config_dir,
)

__all__ = [
    "PROJECT_CONFIG_CANDIDATES",
    "ProjectDirectories",
    "collect_convention_directories",
    "read_toml_file",
    "resolve_effective_directories",
    "resolve_plugin_directories",
    "resolve_project_config",
    "resolve_project_directories",
]


# The list-valued config keys this module resolves. Named once: the three
# functions below each used to carry an identical inline copy of this literal,
# and a key added to two of the three would have gone missing in the third.
LIST_KEYS = (
    "jobs_directories",
    "import_libs",
    "plugins_directories",
    "extra_directories",
    "exclude_patterns",
)

# Convention subdirectory under `.functualize/` for each directory key.
_KEY_TO_SUBDIR = {
    "jobs_directories": "jobs",
    "import_libs": "lib",
    "plugins_directories": "plugins",
}


def _warn(msg: str) -> None:
    """Emit a warning to stderr."""
    print(f"Warning: {msg}", file=sys.stderr)


def read_toml_file(path: Path) -> dict[str, Any] | None:
    """Read and parse a TOML file safely.

    Returns the parsed dict, or None if the file doesn't exist.
    Warns to stderr and returns empty dict on read/parse errors.
    """
    if not path.exists():
        return None

    try:
        content = path.read_bytes()
    except (PermissionError, OSError) as exc:
        _warn(f"{path}: {exc}")
        return {}

    try:
        return tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        _warn(f"{path}: {exc}")
        return {}


def _extract_functualize_section(path: Path) -> dict[str, Any] | None:
    """Extract [tool.functualize] section from a pyproject.toml file.

    Args:
        path: Path to the pyproject.toml file.

    Returns:
        The dict under [tool.functualize] if present, or None.
    """
    try:
        content = path.read_bytes()
        data = tomllib.loads(content.decode("utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return None

    tool = data.get("tool", {})
    if isinstance(tool, dict):
        section = tool.get("functualize")
        if isinstance(section, dict):
            return section
    return None


# Candidate list for project config resolution.
# Order within the list defines priority per directory (first match wins):
# 1. pyproject.toml [tool.functualize] section (highest priority — standard location)
# 2. Plain .functualize.toml at directory root
# 3. .functualize/.functualize.toml (convention directory)
PROJECT_CONFIG_CANDIDATES: list[str | tuple[str, Any]] = [
    ("pyproject.toml", _extract_functualize_section),
    ".functualize.toml",
    ".functualize/.functualize.toml",
]


def _flatten_dedup_resolve(
    layers: list[list[str]],
    anchor: Path,
    *,
    is_path: bool = True,
) -> list[str]:
    """Flatten layers, deduplicate by first occurrence, resolve relative paths.

    Args:
        layers: List of lists, in priority order (first = highest).
        anchor: Directory to resolve relative paths against.
        is_path: If True, resolve relative strings as filesystem paths.

    Returns:
        Deduplicated list of strings.
    """
    seen: set[str] = set()
    result: list[str] = []

    for layer in layers:
        for item in layer:
            if is_path:
                path = Path(os.path.expanduser(item))
                if not path.is_absolute():
                    path = anchor / path
                resolved = str(path.resolve())
            else:
                resolved = item

            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)

    return result


def resolve_project_config(cwd: Path) -> tuple[Path, dict[str, Any]]:
    """Walk upward from cwd, collect and merge project configs.

    Uses ResourceLocator with upward search + platform user config directory.
    Collects one config per directory using the candidate list, then merges
    them nearest-first with root-stop semantics.

    Args:
        cwd: The current working directory to start searching from.

    Returns:
        Tuple of (anchor, merged_config) where:
        - anchor: directory containing the nearest (highest-priority) config,
          or cwd if no config found.
        - merged_config: deep-merged config dict from all layers.
    """
    locator = (
        ResourceLocator().search_upward(start=cwd).search_platform_user("functualize")
    )

    results = locator.resolve_all_candidates(PROJECT_CONFIG_CANDIDATES)

    if not results:
        return (cwd, {})

    # Extract layers in priority order (nearest first)
    layers = [config for (_directory, config) in results]

    # The anchor is the nearest config's directory
    anchor = results[0][0]

    # Merge with root-stop semantics
    merged = merge_config_layers(layers)

    return (anchor, merged)


def collect_convention_directories(
    directories: list[Path],
) -> dict[str, list[str]]:
    """Detect convention directories at each level of the upward walk.

    For each directory in the walk, checks for:
    - .functualize/jobs/ → maps to "jobs_directories"
    - .functualize/lib/ → maps to "import_libs"
    - .functualize/plugins/ → maps to "plugins_directories"

    Args:
        directories: List of directories from the upward walk (nearest first).

    Returns:
        Dict mapping config keys to lists of resolved convention directory paths.
    """
    conv: dict[str, list[str]] = {key: [] for key in _KEY_TO_SUBDIR}

    seen: set[str] = set()

    for directory in directories:
        for key, subdir in _KEY_TO_SUBDIR.items():
            convention_path = directory / ".functualize" / subdir
            if convention_path.is_dir():
                resolved = str(convention_path.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    conv[key].append(resolved)

    return conv


def resolve_effective_directories(
    anchor: Path,
    merged_config: dict[str, Any],
    *,
    cli_overrides: dict[str, Any] | None = None,
    env_overrides: dict[str, Any] | None = None,
    global_config: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Resolve effective directory lists with full precedence chain.

    Public wrapper providing backward-compatible interface. Internally uses
    ResourceLocator-based resolution with convention directory detection.

    Implements the resolution order for list-type keys:
        CLI + ENV + File + Convention + Global + Defaults

    Each layer prepends (higher priority = earlier in the list).
    Deduplicated by first occurrence. All relative paths resolved against anchor.

    Args:
        anchor: The anchor directory for resolving relative paths.
        merged_config: The merged file-layer config dict.
        cli_overrides: CLI flag overrides (flat dict).
        env_overrides: Environment variable overrides.
        global_config: Global config dict (~/.config/functualize/config.toml).

    Returns:
        Dict with keys: "jobs_directories", "import_libs", "plugins_directories",
        "extra_directories", "exclude_patterns". Each value is a deduplicated
        list of absolute path strings (for directories) or patterns.
    """
    # Build a combined CLI overrides dict from cli + env (env prepends after cli)
    combined_cli: dict[str, Any] = {}

    env = env_overrides or {}
    cli = cli_overrides or {}

    # Merge env and cli into a single overrides dict (cli first, then env appended)
    for key in LIST_KEYS:
        combined: list[str] = []
        cli_val = cli.get(key)
        if cli_val and isinstance(cli_val, list):
            combined.extend([str(v) for v in cli_val])
        env_val = env.get(key)
        if env_val and isinstance(env_val, list):
            combined.extend([str(v) for v in env_val])
        if combined:
            combined_cli[key] = combined

    # Detect convention directories at the anchor
    convention_dirs = collect_convention_directories([anchor])

    return resolve_effective_directories_from_layers(
        anchor,
        merged_config,
        convention_dirs=convention_dirs,
        cli_overrides=combined_cli,
        global_config=global_config,
    )


def resolve_effective_directories_from_layers(
    anchor: Path,
    merged_config: dict[str, Any],
    *,
    config_layers: list[tuple[Path, dict[str, Any]]] | None = None,
    convention_dirs: dict[str, list[str]] | None = None,
    cli_overrides: dict[str, Any] | None = None,
    global_config: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Resolve effective directory lists with full precedence chain.

    Implements the resolution order for list-type keys:
        CLI + File layers (all, nearest-first) + Convention + Global

    For list-type keys (jobs_directories, import_libs, etc.), values from
    ALL config layers are collected and concatenated (nearest-first) rather
    than being replaced wholesale by deep merge. This enables multi-level
    config scenarios where each ancestor contributes directories.

    For scalar keys, the merged_config (which uses nearest-wins) is used.

    Each layer prepends (higher priority = earlier in the list).
    Deduplicated by first occurrence. All relative paths resolved against anchor.

    Args:
        anchor: The anchor directory for resolving relative paths.
        merged_config: The merged file-layer config dict (for scalar keys).
        config_layers: Raw config layers with their directories, nearest-first.
            Used for list-type keys to collect from all layers.
        convention_dirs: Pre-collected convention directories per key.
        cli_overrides: CLI flag overrides (flat dict).
        global_config: Global config dict (~/.config/functualize/config.toml).

    Returns:
        Dict with keys: "jobs_directories", "import_libs", "plugins_directories",
        "extra_directories", "exclude_patterns". Each value is a deduplicated
        list of absolute path strings (for directories) or patterns.
    """
    cli = cli_overrides or {}
    global_ = global_config or {}
    conv = convention_dirs or {}
    raw_layers = config_layers or []

    result: dict[str, list[str]] = {}

    for key in LIST_KEYS:
        layers: list[list[str]] = []

        # 1. CLI overrides (highest priority)
        cli_val = cli.get(key)
        if cli_val and isinstance(cli_val, list):
            layers.append([str(v) for v in cli_val])

        # 2. File layers — collect from each raw layer individually
        #    (nearest-first, so all contribute their directories)
        if raw_layers:
            for layer_dir, layer_config in raw_layers:
                file_val = layer_config.get(key)
                if file_val and isinstance(file_val, list):
                    # Resolve relative paths against the layer's own directory
                    layer_items: list[str] = []
                    for v in file_val:
                        item = str(v)
                        p = Path(os.path.expanduser(item))
                        if not p.is_absolute():
                            p = layer_dir / p
                        layer_items.append(str(p.resolve()))
                    layers.append(layer_items)
                else:
                    # Check under [discovery] sub-section
                    discovery = layer_config.get("discovery", {})
                    if isinstance(discovery, dict):
                        disc_val = discovery.get(key)
                        if disc_val and isinstance(disc_val, list):
                            layer_items = []
                            for v in disc_val:
                                item = str(v)
                                p = Path(os.path.expanduser(item))
                                if not p.is_absolute():
                                    p = layer_dir / p
                                layer_items.append(str(p.resolve()))
                            layers.append(layer_items)
        else:
            # Fallback to merged_config if no raw layers provided
            file_val = merged_config.get(key)
            if file_val and isinstance(file_val, list):
                layers.append([str(v) for v in file_val])
            else:
                # Check under [discovery] sub-section for some keys
                discovery = merged_config.get("discovery", {})
                if isinstance(discovery, dict):
                    disc_val = discovery.get(key)
                    if disc_val and isinstance(disc_val, list):
                        layers.append([str(v) for v in disc_val])

        # 3. Convention directories (pre-collected from upward walk)
        if key in conv and conv[key]:
            layers.append(conv[key])

        # 4. Global config
        global_val = global_.get(key)
        if global_val and isinstance(global_val, list):
            layers.append([str(v) for v in global_val])
        else:
            # Check under [discovery] sub-section
            global_discovery = global_.get("discovery", {})
            if isinstance(global_discovery, dict):
                glob_disc_val = global_discovery.get(key)
                if glob_disc_val and isinstance(glob_disc_val, list):
                    layers.append([str(v) for v in glob_disc_val])

        # Flatten and deduplicate
        # When raw_layers are used, paths are already resolved against
        # their respective layer directories, so use is_path=False to avoid
        # double-resolution.
        if raw_layers:
            effective = _flatten_dedup_resolve(layers, anchor, is_path=False)
        else:
            effective = _flatten_dedup_resolve(
                layers, anchor, is_path=(key != "exclude_patterns")
            )
        result[key] = effective

    return result


# =============================================================================
# The one read, for the consumers that run before the resolution chain exists
# =============================================================================


@dataclass(frozen=True)
class ProjectDirectories:
    """What one walk-A read of the project yields, resolved once at boot.

    Produced by :func:`resolve_project_directories` at boot step 3.5 and handed
    to the two consumers that run *before* the resolution chain is built — the
    plugin loader (step 4) and the domain registry (step 4b). Frozen: the
    composition root reads it and passes parts of it on; nothing edits it.
    """

    anchor: Path
    """Nearest ancestor carrying a project config file, or ``cwd`` if none.

    Relative declared paths resolve against this.
    """

    project_root: Path | None
    """The ``.functualize/`` directory itself, or None in standalone mode.

    Walk C's answer (``find_functualize_dir``) — the *same* directory the app
    already reports as ``Mode: project`` and writes ``fresh.json`` into. The
    convention plugin directory hangs off this, which is what bounds the
    convention search at the project root rather than at the filesystem root.
    """

    merged: dict[str, Any]
    """Walk-A config layers deep-merged nearest-first.

    ``root = true`` has been applied and the key stripped. The domain registry
    reads ``[<section>].provider`` out of this.
    """

    declared_plugin_directories: tuple[str, ...]
    """Plugin directories the project *asked for*, in precedence order.

    Kept separate from the convention list rather than pre-concatenated, so the
    caller can warn about one and stay silent about the other: a declared
    directory that yields nothing is a user mistake worth reporting, an absent
    convention directory is the ordinary case for most projects.
    """

    convention_plugin_directories: tuple[str, ...]
    """``<project_root>/plugins``, if it exists and is wanted.

    Empty when ``ambient_directory`` is False, when there is no project root,
    or when the directory was already declared.
    """

    @property
    def plugin_directories(self) -> tuple[str, ...]:
        """Every directory to scan, declared first — the loader's input.

        Order is contractual (`spec.md` §C.2): the loader's existing first-wins
        duplicate-name rule resolves collisions across both in this order.
        """
        return self.declared_plugin_directories + self.convention_plugin_directories


def resolve_plugin_directories(
    *,
    anchor: Path,
    merged: dict[str, Any],
    project_root: Path | None,
    ambient_directory: bool = True,
    global_config: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(declared, convention)`` plugin directories, in scan order.

    **Two lists, not one concatenated list**, because the caller must treat them
    differently: a *declared* directory that yields nothing deserves a warning —
    the user named it — while an absent *convention* directory is the ordinary
    case and must stay silent. A merged list cannot tell them apart.

    Order is contractual: declared first, convention second.

    The convention directory is ``<project_root>/plugins``, where
    ``project_root`` comes from walk C — **not** from walk A's convention
    collection. Walk A only collects convention directories at levels that
    produced a *config hit*, so a directory holding ``.functualize/plugins/``
    but no config file is invisible to it. That is precisely the reported
    layout, and the two walks disagreeing about which level is "the project" is
    why fixing either one alone would not have closed the bug.

    Args:
        anchor: Walk A's anchor; relative declared paths resolve against it.
        merged: Walk A's merged config layers.
        project_root: Walk C's ``.functualize/`` directory, or None.
        ambient_directory: When False, the convention list is empty. A
            *declared* directory is unaffected — ``func <file>.py <job>`` sets
            this so a neighbour's plugin directory cannot hijack the named
            file, and that rule has nothing to say about a directory the
            project declared on purpose.
        global_config: The XDG global layer.

    Returns:
        ``(declared, convention)``. Either may be empty.
    """
    # `resolve_effective_directories` folds convention directories into its
    # result. That is right for `jobs_directories`, and wrong here: this
    # function's whole job is to keep *declared* and *convention* separable, so
    # the caller can refuse one (`ambient_directory=False`) and warn about the
    # other. Going through the from-layers form with no convention input keeps
    # the CLI/File/Global rungs and leaves the convention half to us.
    #
    # Caught by `test_a_cwd_plugin_directory_is_not_executed`: with the folding
    # in place, `ambient_directory=False` did not suppress the cwd plugin
    # directory, and `func <file>.py <job>` was hijackable again — the exact
    # defect `single-file-cwd-isolation` exists to prevent.
    effective = resolve_effective_directories_from_layers(
        anchor,
        merged,
        convention_dirs={},
        global_config=global_config,
    )
    declared = list(effective.get("plugins_directories", ()))

    convention: list[str] = []
    if ambient_directory and project_root is not None:
        candidate = project_root / "plugins"
        if candidate.is_dir():
            convention.append(str(candidate.resolve()))

    # A directory reachable both ways counts as declared: that is the stronger
    # statement, and it is what the caller warns about when nothing loads.
    declared_set = set(declared)
    convention = [d for d in convention if d not in declared_set]

    return declared, convention


def resolve_project_directories(
    cwd: Path,
    *,
    ambient_directory: bool = True,
) -> ProjectDirectories:
    """Read the project once, for the consumers that precede the chain.

    Boot step 3.5. This exists because boot loads plugins at step 4 so they can
    register config *format providers*, and builds the resolution chain at step
    6 (ADR-007) — so anything the plugin loader or the domain registry needs
    from configuration must be read here, by a path that does not go through
    the chain.

    Args:
        cwd: Where both walks start.
        ambient_directory: Forwarded to :func:`resolve_plugin_directories`.

    Returns:
        A frozen :class:`ProjectDirectories`.
    """
    anchor, merged = resolve_project_config(cwd)
    project_root = find_functualize_dir(cwd)
    global_config = read_toml_file(xdg_config_dir() / "config.toml") or {}

    declared, convention = resolve_plugin_directories(
        anchor=anchor,
        merged=merged,
        project_root=project_root,
        ambient_directory=ambient_directory,
        global_config=global_config,
    )

    return ProjectDirectories(
        anchor=anchor,
        project_root=project_root,
        merged=merged,
        declared_plugin_directories=tuple(declared),
        convention_plugin_directories=tuple(convention),
    )
