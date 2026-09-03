"""Public utility functions for the app package.

These utilities support the ``_cli/`` layer and external tools by providing
everything needed to build CLI commands, import jobs, and auto-discover
job directories without reaching into internal packages.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import sys
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from functualize._config.merge import merge_config_layers
from functualize._primitives.agent_epilog import (
    agent_epilog,
    write_agent_epilog,
)
from functualize._primitives.cache_format import resolve_cache_path
from functualize._primitives.capability_names import INJECTED_PARAM_TYPE_NAMES
from functualize._primitives.config_class_detection import detect_config_class
from functualize._primitives.di import DIValidationError
from functualize._primitives.display_detection import (
    find_display_providers,
    is_display_provider,
)
from functualize._primitives.job_schema import (
    field_property,
    input_schema,
    job_input_schema,
)
from functualize._primitives.locator import ResourceLocator
from functualize._primitives.state_format import (
    resolve_state_location,
    resolve_state_path,
)
from functualize._primitives.state_store import StateStore
from functualize._types.annotations import resolved_hints
from functualize._types.descriptors import FieldDescriptor, GroupOptionsSpec
from functualize._types.enums import RunStatus
from functualize._types.errors import JobMaterializationError
from functualize._types.exit_codes import ExitCode, exit_code_for_status
from functualize._types.naming import (
    BUILTIN_SEGMENT,
    GroupTrie,
    NodeKind,
    TrieNode,
    TrieResolution,
    group_ancestors,
    negative_flag_for,
    normalize_segment,
    resolve_name,
)
from functualize._types.redaction import (
    MASK,
    display_value,
    is_secret_field,
    reveal,
)
from functualize.app._workflow_resume import deposit_gate_input, pending_gates
from functualize.app.config import JobSources


def job_config_fields(app: Any, job_name: str) -> list[Any]:
    """A job's config as ``ResolvedField`` rows — the one resolution seam.

    Re-exported here because ``_cli/`` may import only public API, and the
    surfaces that report configuration (``builtin env``, the TUI panels) all
    live there. They previously each re-derived values, knew different subsets
    of the environment conventions, and disagreed with the executor.

    Returns ``[]`` when the job declares no config model. Never raises for an
    unresolved field: a caller asking "what is missing?" is answered, not
    handed a ``ValidationError``.
    """
    from functualize._config.job_config import JobConfigView
    from functualize._config.resolved_field import resolve_job_fields

    try:
        entry = app.execution_engine.materialize_job(job_name)
    except Exception:
        return []
    config_class = getattr(entry, "config_class", None)
    if config_class is None:
        return []

    return resolve_job_fields(
        config_class,
        job_name,
        JobConfigView(
            resolution_chain=app._resolution_chain,
            default_section_prefix=job_name,
        ),
    )


__all__ = [
    "auto_discover",
    "job_config_fields",
    "is_secret_field",
    "MASK",
    "reveal",
    "exit_code_for_status",
    "ExitCode",
    "RunStatus",
    "build_discovery_cache_provider",
    "build_group_trie",
    "build_job_filter",
    "BUILTIN_SEGMENT",
    "coerce_kwargs",
    "deposit_gate_input",
    "DiscoveryOverrides",
    "display_value",
    "DiscoveryResult",
    "DIValidationError",
    "enumerate_group_names",
    "enumerate_job_names",
    "FieldDescriptor",
    "find_display_providers",
    "GroupOptionsSpec",
    "GroupTrie",
    "import_job",
    "is_display_provider",
    "JobMaterializationError",
    "list_project_config_files",
    "NodeKind",
    "pending_gates",
    "read_display_modules_from_cache",
    "read_group_options_from_cache",
    "read_routing_names_from_cache",
    "read_routing_rows_from_cache",
    "resolve_cache_path",
    "TrieNode",
    "TrieResolution",
    "resolve_state_location",
    "resolve_state_path",
    "StateStore",
    "resolved_hints",
    "detect_config_class",
    "INJECTED_PARAM_TYPE_NAMES",
    "agent_epilog",
    "resolve_effective_directories",
    "resolve_project_config",
    "resolve_user_config_dir",
    "field_property",
    "input_schema",
    "job_input_schema",
    "write_agent_epilog",
    "resolve_user_data_dir",
    "ResourceLocator",
    "merge_config_layers",
    "group_ancestors",
    "negative_flag_for",
    "normalize_segment",
    "resolve_name",
]

_SKIP_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".venv",
        "__pycache__",
        ".git",
        "node_modules",
        "dist",
        "build",
    }
)
"""Directory names to unconditionally skip during CWD pre-filter scanning."""


@dataclass(frozen=True)
class DiscoveryOverrides:
    """Typed overrides for auto_discover parameters.

    Replaces untyped ``dict[str, Any]`` with validated fields.
    All fields default to ``None``, meaning "use file-based config value".
    """

    scan_depth: int | None = None
    import_libs: list[str] | None = None
    jobs_directories: list[str] | None = None
    extra_directories: list[str] | None = None
    exclude_patterns: list[str] | None = None


@dataclass
class DiscoveryResult:
    """Result of auto_discover: unified discovery output.

    Contains everything callers need: the resolved anchor directory,
    job sources for the engine, import_libs for sys.path manipulation,
    the merged config dict, and the effective jobs_directories list.
    """

    anchor: Path
    job_sources: JobSources
    import_libs: list[str]
    merged_config: dict[str, Any]
    jobs_directories: list[str]

    @property
    def directories(self) -> list[str] | None:
        """Convenience property delegating to job_sources.directories."""
        return self.job_sources.directories


# =============================================================================
# Resolution helpers (absorbed from _cli/resolution.py)
# =============================================================================


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
_CANDIDATES: list[str | tuple[str, Any]] = [
    ("pyproject.toml", _extract_functualize_section),
    ".functualize.toml",
    ".functualize/.functualize.toml",
]


def _convention_subdir_name(key: str) -> str:
    """Map a config key to its convention subdirectory name."""
    mapping = {
        "jobs_directories": "jobs",
        "import_libs": "lib",
        "plugins_directories": "plugins",
    }
    return mapping.get(key, key)


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


def enumerate_job_names(jobs_directories: list[str]) -> set[str]:
    """Enumerate likely job names from jobs_directories WITHOUT importing.

    Uses filename-based heuristics:
    - Each .py file that doesn't start with _ yields its stem as job name
    - Intentionally imprecise (may include non-job files) but NEVER
      misses a valid job. False positives resolved at execution time.

    Args:
        jobs_directories: List of absolute directory path strings.

    Returns:
        Set of candidate job names (stems of .py files).
    """
    names: set[str] = set()
    for dir_str in jobs_directories:
        dir_path = Path(dir_str)
        if not dir_path.is_dir():
            continue
        for entry in dir_path.iterdir():
            if (
                entry.is_file()
                and entry.suffix == ".py"
                and not entry.name.startswith("_")
            ):
                names.add(entry.stem)
    return names


def enumerate_group_names(jobs_directories: list[str]) -> set[str]:
    """Cold-boot fallback: AST-scan for JOB_GROUP assignments.

    Uses lightweight AST inspection (no full import) to find
    ``JOB_GROUP = "..."`` assignments in module files.

    For nested groups like ``"infra.aws"``, also emits all ancestor prefixes
    (``"infra"``) so that ``func infra`` can list nested sub-groups.

    Args:
        jobs_directories: List of absolute directory path strings.

    Returns:
        Set of group name strings found across all directories,
        including ancestor prefixes for nested groups.
    """
    import ast

    group_names: set[str] = set()

    for dir_str in jobs_directories:
        dir_path = Path(dir_str)
        if not dir_path.is_dir():
            continue
        for entry in dir_path.iterdir():
            if not (
                entry.is_file()
                and entry.suffix == ".py"
                and not entry.name.startswith("_")
            ):
                continue
            try:
                tree = ast.parse(entry.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.iter_child_nodes(tree):
                if (
                    isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "JOB_GROUP"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    full_group = node.value.value
                    group_names.add(full_group)
                    # Emit ancestor prefixes for nested groups
                    group_names.update(group_ancestors(full_group))

    return group_names


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

    results = locator.resolve_all_candidates(_CANDIDATES)

    if not results:
        return (cwd, {})

    # Extract layers in priority order (nearest first)
    layers = [config for (_directory, config) in results]

    # The anchor is the nearest config's directory
    anchor = results[0][0]

    # Merge with root-stop semantics
    merged = merge_config_layers(layers)

    return (anchor, merged)


def _first_existing_candidate_file(
    directory: Path, candidates: list[str | tuple[str, Any]]
) -> Path | None:
    """Return the path of the first candidate filename that exists in directory."""
    for candidate in candidates:
        filename = candidate if isinstance(candidate, str) else candidate[0]
        file_path = directory / filename
        if file_path.is_file():
            return file_path
    return None


def list_project_config_files(cwd: Path) -> list[tuple[Path, Path]]:
    """List individual project config file candidates, without merging.

    Performs the same upward walk + platform-user search as
    ``resolve_project_config``, but returns the resolved file path found in
    each directory instead of a merged config dict. This is the single
    source of truth for "which files could a project-level config write go
    to" — callers building a file picker/target selector should use this
    instead of re-implementing the directory walk.

    Args:
        cwd: The current working directory to start searching from.

    Returns:
        List of (directory, file_path) tuples in priority order (nearest
        first), one per directory that has a matching candidate file.
    """
    locator = (
        ResourceLocator().search_upward(start=cwd).search_platform_user("functualize")
    )

    results = locator.resolve_all_candidates(_CANDIDATES)

    files: list[tuple[Path, Path]] = []
    for directory, _config in results:
        file_path = _first_existing_candidate_file(directory, _CANDIDATES)
        if file_path is not None:
            files.append((directory, file_path))

    return files


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
    list_keys = [
        "jobs_directories",
        "import_libs",
        "plugins_directories",
        "extra_directories",
        "exclude_patterns",
    ]
    for key in list_keys:
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
    convention_dirs = _collect_convention_directories([anchor])

    return _resolve_effective_directories(
        anchor,
        merged_config,
        convention_dirs=convention_dirs,
        cli_overrides=combined_cli,
        global_config=global_config,
    )


def _resolve_effective_directories(
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

    # List-type keys to resolve
    list_keys = [
        "jobs_directories",
        "import_libs",
        "plugins_directories",
        "extra_directories",
        "exclude_patterns",
    ]

    for key in list_keys:
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


def _collect_convention_directories(
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
    conv: dict[str, list[str]] = {
        "jobs_directories": [],
        "import_libs": [],
        "plugins_directories": [],
    }

    seen: set[str] = set()
    key_to_subdir = {
        "jobs_directories": "jobs",
        "import_libs": "lib",
        "plugins_directories": "plugins",
    }

    for directory in directories:
        for key, subdir in key_to_subdir.items():
            convention_path = directory / ".functualize" / subdir
            if convention_path.is_dir():
                resolved = str(convention_path.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    conv[key].append(resolved)

    return conv


# =============================================================================
# Type coercion and import utilities
# =============================================================================


def _resolve_type(type_annotation: str) -> type:
    """Resolve a type annotation string to a Python type object.

    Supports built-in types (str, int, float, bool), pathlib.Path,
    and generic forms like list[str], list[int], etc.

    Args:
        type_annotation: The type annotation string (e.g., "int", "list[str]", "Path").

    Returns:
        The resolved Python type.
    """
    # Mapping of simple type names to their Python type objects
    simple_types: dict[str, type] = {
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "Path": Path,
    }

    # Handle simple types
    if type_annotation in simple_types:
        return simple_types[type_annotation]

    # Handle generic types like list[str], list[int], etc.
    if type_annotation.startswith("list[") and type_annotation.endswith("]"):
        inner = type_annotation[5:-1]
        if inner in simple_types:
            return list[simple_types[inner]]  # type: ignore[valid-type]
        # Fallback to list[str] for unknown inner types
        return list[str]

    # Fallback: treat as str
    return str


def coerce_kwargs(
    raw: dict[str, str],
    parameters: list[FieldDescriptor],
) -> dict[str, Any]:
    """Convert CLI string values to Python types using Pydantic TypeAdapter.

    Uses Pydantic TypeAdapter internally to convert each string value to the
    Python type indicated by the corresponding FieldDescriptor.type_annotation.

    Args:
        raw: Dictionary of raw string key-value pairs from CLI input.
        parameters: List of FieldDescriptor instances describing expected types.

    Returns:
        Dictionary with values coerced to their target Python types.

    Raises:
        ValueError: If a value cannot be coerced to the target type.
            The message includes the parameter name and expected type.
    """
    param_map = {p.name: p for p in parameters}
    result: dict[str, Any] = {}

    for key, value in raw.items():
        if key not in param_map:
            result[key] = value
            continue

        descriptor = param_map[key]
        type_ann = descriptor.type_annotation
        target_type = _resolve_type(type_ann)
        adapter: TypeAdapter[Any] = TypeAdapter(target_type)

        try:
            # For list types, the raw value is a JSON string — use validate_json
            if type_ann.startswith("list["):
                result[key] = adapter.validate_json(value)
            else:
                result[key] = adapter.validate_python(value)
        except (ValidationError, ValueError) as exc:
            raise ValueError(
                f"Parameter '{key}': cannot convert '{value}' to {type_ann}"
            ) from exc

    return result


def import_job(
    path: str | Path,
    function_name: str | None = None,
) -> Callable[..., Any] | list[Callable[..., Any]]:
    """Import job function(s) from a file path.

    When ``function_name`` is provided, returns the single callable matching
    that name. When None, returns a list of all public (non-underscore-prefixed)
    functions defined in the module.

    Args:
        path: Path to the Python file containing job function(s).
        function_name: Specific function to import (None = all public functions).

    Returns:
        Single callable if function_name is provided, otherwise list of callables.

    Raises:
        ImportError: If the path does not exist or cannot be imported.
        LookupError: If function_name does not exist in the module.
    """
    file_path = Path(path).resolve()

    if not file_path.exists():
        raise ImportError(f"Cannot import job from '{path}': file not found")

    if not file_path.is_file():
        raise ImportError(f"Cannot import job from '{path}': not a file")

    # Load the module from file path
    module_name = file_path.stem
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import job from '{path}': invalid module spec")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        del sys.modules[module_name]
        raise ImportError(f"Cannot import job from '{path}': {exc}") from exc

    if function_name is not None:
        func: Callable[..., Any] | None = getattr(module, function_name, None)
        if func is None or not callable(func):
            raise LookupError(
                f"Function '{function_name}' not found in module '{path}'"
            )
        return func

    # Return all public functions defined in the module
    functions: list[Callable[..., Any]] = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if not name.startswith("_") and obj.__module__ == module_name:
            functions.append(obj)

    return functions


def _warn(msg: str) -> None:
    """Emit a warning to stderr."""
    print(f"Warning: {msg}", file=sys.stderr)


def resolve_user_config_dir() -> Path:
    """Resolve the XDG config directory for functualize.

    Uses $XDG_CONFIG_HOME/functualize if set to a non-empty string,
    otherwise falls back to ~/.config/functualize.

    This is the single source of truth for the user-level config
    directory; callers should not re-derive this path independently.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        return Path(xdg) / "functualize"
    return Path.home() / ".config" / "functualize"


def resolve_user_data_dir() -> Path:
    """Resolve the XDG *data* directory for functualize.

    Uses $XDG_DATA_HOME/functualize if set to a non-empty string, otherwise
    falls back to ~/.local/share/functualize.

    Distinct from :func:`resolve_user_config_dir` on purpose: config is what
    the user writes and expects to survive, data is what functualize writes
    and may regenerate. Materialized agent skills are the latter — a copy of
    what the installed wheel already carries, safe to delete.
    """
    xdg = os.environ.get("XDG_DATA_HOME", "")
    if xdg:
        return Path(xdg) / "functualize"
    return Path.home() / ".local" / "share" / "functualize"


def _read_toml_file(path: Path) -> dict[str, Any] | None:
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


def _should_skip_directory(name: str) -> bool:
    """Return True if a directory name should be skipped during CWD scan.

    Skips directories in the ``_SKIP_DIRECTORIES`` frozenset as well as
    any directory whose name starts with a dot (dot-prefixed).

    Args:
        name: The basename of the directory to check.

    Returns:
        True if the directory should be skipped, False otherwise.
    """
    if name.startswith("."):
        return True
    return name in _SKIP_DIRECTORIES


def _read_config_scan_depth(*configs: dict[str, Any]) -> int | None:
    """Read ``[discovery].scan_depth`` from the first config layer that sets it.

    Args:
        configs: Config dicts in priority order (e.g. merged project config,
            then global config).

    Returns:
        The configured scan depth, or None if no layer sets a usable value.
    """
    for config in configs:
        section = config.get("discovery")
        if isinstance(section, dict) and "scan_depth" in section:
            try:
                return int(section["scan_depth"])
            except (ValueError, TypeError):
                return None
    return None


def _scan_cwd_directories(cwd: Path, scan_depth: int) -> list[str]:
    """Scan CWD for directories containing qualifying Python files.

    Traverses directories from ``cwd`` up to ``scan_depth`` levels deep,
    applying the default pre-filter stack (``DefaultModulePreFilter`` +
    ``ASTModulePreFilter`` via ``AllOf``) to each ``.py`` file found.

    A directory "qualifies" if it contains at least one ``.py`` file that
    passes both pre-filters.

    Args:
        cwd: The root directory to scan from.
        scan_depth: Max levels below cwd to traverse. Already clamped by caller.

    Returns:
        List of resolved directory path strings that qualify.
    """
    from functualize._primitives import (
        AllOf,
        ASTModulePreFilter,
        DefaultModulePreFilter,
    )

    pre_filter = AllOf(DefaultModulePreFilter(), ASTModulePreFilter())
    qualifying: list[str] = []

    def _check_directory(directory: Path) -> bool:
        """Return True if directory contains at least one qualifying .py file."""
        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError):
            return False

        for entry in entries:
            if (
                entry.is_file()
                and entry.suffix == ".py"
                and pre_filter.should_import(entry)
            ):
                return True
        return False

    # BFS traversal: visit directories level by level up to scan_depth
    # Level 0 = cwd itself, level 1 = direct children, etc.
    current_level: list[Path] = [cwd]

    for depth in range(scan_depth + 1):
        next_level: list[Path] = []

        for directory in current_level:
            # Check if this directory qualifies
            if _check_directory(directory):
                qualifying.append(str(directory.resolve()))

            # Gather subdirectories for next level (if not at max depth)
            if depth < scan_depth:
                try:
                    entries = list(directory.iterdir())
                except (PermissionError, OSError):
                    continue

                for entry in entries:
                    if entry.is_dir() and not _should_skip_directory(entry.name):
                        next_level.append(entry)

        current_level = next_level

    return qualifying


def _normalize_overrides(
    overrides: dict[str, Any] | DiscoveryOverrides | None,
) -> DiscoveryOverrides | None:
    """Normalize overrides to DiscoveryOverrides or None.

    If a plain dict is passed, construct a DiscoveryOverrides from its fields.
    If already a DiscoveryOverrides instance, return as-is. If None, return None.
    """
    if overrides is None:
        return None
    if isinstance(overrides, DiscoveryOverrides):
        return overrides
    # Plain dict: extract known fields and construct DiscoveryOverrides
    return DiscoveryOverrides(
        scan_depth=overrides.get("scan_depth"),
        import_libs=overrides.get("import_libs"),
        jobs_directories=overrides.get("jobs_directories"),
        extra_directories=overrides.get("extra_directories"),
        exclude_patterns=overrides.get("exclude_patterns"),
    )


def _overrides_to_cli_dict(
    typed: DiscoveryOverrides | None,
) -> dict[str, Any]:
    """Convert DiscoveryOverrides to the flat dict expected by _resolve_effective_directories."""
    if typed is None:
        return {}
    result: dict[str, Any] = {}
    if typed.scan_depth is not None:
        result["scan_depth"] = typed.scan_depth
    if typed.import_libs is not None:
        result["import_libs"] = typed.import_libs
    if typed.jobs_directories is not None:
        result["jobs_directories"] = typed.jobs_directories
    if typed.extra_directories is not None:
        result["extra_directories"] = typed.extra_directories
    if typed.exclude_patterns is not None:
        result["exclude_patterns"] = typed.exclude_patterns
    return result


def auto_discover(
    cwd: Path | None = None,
    *,
    overrides: dict[str, Any] | DiscoveryOverrides | None = None,
    scan_depth: int = 0,
    search_ancestors: bool = True,
) -> DiscoveryResult:
    """Discover all job directories: config-based + CWD pre-filter scan.

    Single source of truth. All callers (CLI main, cache rebuild,
    cache check, MCP server) get identical results for the same
    CWD and config state.

    Args:
        cwd: Directory to scan from. Defaults to Path.cwd().
        overrides: Optional overrides that take precedence over file config.
                   Accepts either a ``DiscoveryOverrides`` instance or a plain dict
                   with supported keys: ``"scan_depth"`` (int),
                   ``"jobs_directories"`` (list[str]), ``"import_libs"`` (list[str]),
                   ``"extra_directories"`` (list[str]), ``"exclude_patterns"`` (list[str]).
                   If a plain dict is passed, a ``DiscoveryOverrides`` is constructed
                   from it.
        scan_depth: Max directory levels below CWD to traverse.
                    Clamped to [0, 5]. Negative values → 0.
                    Deprecated in favor of ``overrides.scan_depth``;
                    kept for backward compatibility.
        search_ancestors: When True (default), use ResourceLocator.search_upward()
                    for full upward-walk config resolution. When False, only check
                    the given CWD directory for config (local-only mode).

    Returns:
        DiscoveryResult with anchor, job_sources, import_libs, merged_config,
        and jobs_directories.
    """
    if cwd is None:
        cwd = Path.cwd()

    cwd = cwd.resolve()

    # Normalize overrides to typed form
    typed_overrides = _normalize_overrides(overrides)

    # Resolve scan_depth: overrides > explicit param > config > default (0).
    # Config layers aren't loaded yet, so a None here means "fall back to
    # [discovery].scan_depth from merged/global config" once they are.
    resolved_scan_depth: int | None = scan_depth if scan_depth else None
    if typed_overrides and typed_overrides.scan_depth is not None:
        try:
            resolved_scan_depth = int(typed_overrides.scan_depth)
        except (ValueError, TypeError):
            resolved_scan_depth = scan_depth if scan_depth else None

    # --- Config resolution ---
    if search_ancestors:
        # Full upward-walk using ResourceLocator + candidate-based matching
        locator = (
            ResourceLocator()
            .search_upward(start=cwd)
            .search_platform_user("functualize")
        )

        results = locator.resolve_all_candidates(_CANDIDATES)

        if results:
            # Extract layers in priority order (nearest first)
            layers = [config for (_directory, config) in results]
            # The anchor is the nearest config's directory
            anchor = results[0][0]
            # Merge with root-stop semantics
            merged_config = merge_config_layers(layers)
        else:
            anchor = cwd
            merged_config = {}

        # Collect convention directories at each level of the walk
        walk_directories = [directory for (directory, _config) in results]
        # Also check cwd itself if it's not already in the results
        if cwd not in [d.resolve() for d in walk_directories]:
            walk_directories.insert(0, cwd)

        convention_dirs = _collect_convention_directories(walk_directories)

        # Read XDG global config as lowest-priority layer
        xdg_config_path = resolve_user_config_dir() / "config.toml"
        global_config = _read_toml_file(xdg_config_path) or {}

        # Resolve effective directories using full precedence chain
        cli_overrides = _overrides_to_cli_dict(typed_overrides)
        effective = _resolve_effective_directories(
            anchor,
            merged_config,
            config_layers=results,
            convention_dirs=convention_dirs,
            cli_overrides=cli_overrides,
            global_config=global_config,
        )

        # Collect config directories: jobs + extra, filtering to existing
        config_directories: list[str] = []
        seen_config: set[str] = set()

        for dir_str in effective.get("jobs_directories", []):
            if dir_str not in seen_config and Path(dir_str).is_dir():
                seen_config.add(dir_str)
                config_directories.append(dir_str)

        for dir_str in effective.get("extra_directories", []):
            if dir_str not in seen_config and Path(dir_str).is_dir():
                seen_config.add(dir_str)
                config_directories.append(dir_str)

    else:
        # Local-only mode: ResourceLocator-based but CWD-only (no upward walk)
        locator = (
            ResourceLocator().search_explicit(cwd).search_platform_user("functualize")
        )

        results = locator.resolve_all_candidates(_CANDIDATES)

        if results:
            layers = [config for (_directory, config) in results]
            anchor = results[0][0]
            merged_config = merge_config_layers(layers)
        else:
            anchor = cwd
            merged_config = {}

        # Convention directories: only check CWD itself
        convention_dirs = _collect_convention_directories([cwd])

        # XDG global config as lowest-priority layer
        xdg_config_path = resolve_user_config_dir() / "config.toml"
        global_config = _read_toml_file(xdg_config_path) or {}

        # Resolve effective directories
        cli_overrides = _overrides_to_cli_dict(typed_overrides)
        effective = _resolve_effective_directories(
            anchor,
            merged_config,
            config_layers=results,
            convention_dirs=convention_dirs,
            cli_overrides=cli_overrides,
            global_config=global_config,
        )

        # Collect config directories: jobs + extra, filtering to existing
        config_directories = []
        seen_config = set()

        for dir_str in effective.get("jobs_directories", []):
            if dir_str not in seen_config and Path(dir_str).is_dir():
                seen_config.add(dir_str)
                config_directories.append(dir_str)

        for dir_str in effective.get("extra_directories", []):
            if dir_str not in seen_config and Path(dir_str).is_dir():
                seen_config.add(dir_str)
                config_directories.append(dir_str)

    # Effective import_libs and jobs_directories lists
    effective_import_libs = effective.get("import_libs", [])
    effective_jobs_directories = effective.get("jobs_directories", [])

    # Config fallback for scan_depth ([discovery].scan_depth), then clamp to [0, 5]
    if resolved_scan_depth is None:
        resolved_scan_depth = _read_config_scan_depth(merged_config, global_config)
    effective_depth = max(0, min(resolved_scan_depth or 0, 5))

    # CWD pre-filter scan: find directories with qualifying .py files
    scan_directories = _scan_cwd_directories(cwd, effective_depth)

    # Merge: combine config-based directories with CWD scan results
    all_directories = config_directories + scan_directories

    # Deduplicate by resolved path (not raw strings)
    seen: set[str] = set()
    deduplicated: list[str] = []
    for d in all_directories:
        resolved = str(Path(d).resolve())
        if resolved not in seen:
            seen.add(resolved)
            deduplicated.append(resolved)

    job_sources = JobSources(directories=deduplicated if deduplicated else None)

    return DiscoveryResult(
        anchor=anchor,
        job_sources=job_sources,
        import_libs=effective_import_libs,
        merged_config=merged_config,
        jobs_directories=effective_jobs_directories,
    )


# =============================================================================
# Pre-boot name resolution (cache-first)
# =============================================================================


def build_job_filter(discovery_config: Any) -> Any:
    """Build the job-level (``require_job_*``) filter for a DiscoveryConfig.

    Public re-export of the ``_discovery`` factory so ``_cli`` can apply the
    same job-level filter to its pre-boot routing read that the booted app
    applies to discovery, without importing an internal package.

    Returns:
        A JobFilter, or None when no job-level setting is configured.
    """
    from functualize._discovery.filter_factory import build_job_filter_from_config

    return build_job_filter_from_config(discovery_config)


def build_discovery_cache_provider(
    cwd: Path | None = None,
    discovery_config: Any = None,
) -> Any:
    """Build the discovery cache provider over auto-discovered job directories.

    Public entry point for CLI tooling (`func cache` commands) that needs
    direct access to the persisted discovery cache without booting an app.

    Args:
        cwd: Directory to discover from. Defaults to the current directory.
        discovery_config: Resolved discovery configuration. When given, the
            provider is built with the same pre-filter, job filter and
            ``discovery_hash`` a booting app would build from it, so a command
            that *writes* the cache writes it under the caller's filters and
            under the fingerprint the next boot expects.

            When ``None`` the provider is bare and skips the fingerprint check.
            That is right for a pure reader; it is wrong for a writer, because a
            bare provider persists ``discovery_hash: null`` and the next boot
            reads that as a mismatch and rescans. See ADR-011.

    Returns:
        A CachedDirectoryScanProvider bound to the resolved cache location.
    """
    from functualize._app.impl import build_cached_provider
    from functualize._discovery.filter_factory import (
        build_job_filter_from_config,
        build_pre_filter_from_config,
        discovery_hash_from_config,
    )

    if cwd is None:
        cwd = Path.cwd()

    discovery_result = auto_discover(cwd)
    directories = list(
        (
            discovery_result.job_sources.directories
            if discovery_result.job_sources
            else []
        )
        or []
    )

    pre_filter = None
    job_filter = None
    discovery_hash = None
    if discovery_config is not None:
        discovery_hash = discovery_hash_from_config(discovery_config)
        job_filter = build_job_filter_from_config(discovery_config)
        if directories:
            scan_roots = [Path(d) for d in directories]
            pre_filter = build_pre_filter_from_config(
                discovery_config, scan_roots[0], scan_roots
            )

    return build_cached_provider(
        directories,
        project_root=cwd,
        pre_filter=pre_filter,
        job_filter=job_filter,
        discovery_hash=discovery_hash,
    )


def read_routing_names_from_cache(
    cache_path: Path,
    job_filter: Any = None,
) -> tuple[set[str], set[str]] | None:
    """Read job names and group names from an existing cache file.

    Fast path (~3ms): parses the cache JSON and extracts name/group fields
    from all cached descriptors without importing any modules.

    Args:
        cache_path: Path to the discovery cache file.
        job_filter: Optional JobFilter (the ``require_job_*`` settings). The
            cache is written as a superset — job-level filters are applied on
            read — so routing must apply the same filter, or ``func <name>``
            would route to a job the booted app then refuses to resolve.

    Returns:
        Tuple of (job_names, group_names) if cache exists and is valid.
        group_names includes ancestor prefixes for nested groups.
        Returns None if cache is missing, unreadable, or malformed.
    """
    from functualize._primitives.cache_format import CACHE_VERSION

    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    # Validate structure
    if not isinstance(data, dict):
        return None

    # Validate cache format version
    if data.get("version") != CACHE_VERSION:
        return None

    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None

    job_names: set[str] = set()
    group_names: set[str] = set()

    for entry in entries.values():
        if not isinstance(entry, dict):
            continue

        name = entry.get("name")
        group = entry.get("group")

        if job_filter is not None and isinstance(name, str):
            from functualize._primitives.job_filter import RawJobCandidate

            raw_decorators = entry.get("decorators") or ()
            candidate = RawJobCandidate(
                name=name,
                decorators=tuple(str(d) for d in raw_decorators),
                python_name=str(entry.get("python_name") or ""),
            )
            if not job_filter.should_register(candidate):
                continue

        if isinstance(name, str) and name:
            job_names.add(name)

        if isinstance(group, str) and group:
            group_names.add(group)
            # Emit ancestor prefixes for nested groups
            group_names.update(group_ancestors(group))

    return (job_names, group_names)


def read_routing_rows_from_cache(
    cache_path: Path,
    job_filter: Any = None,
) -> list[tuple[str | None, str, str]] | None:
    """Read ``(group, name, kind)`` rows from an existing cache file.

    The row form of :func:`read_routing_names_from_cache`. That function returns
    two flattened *sets*, which is all today's prefix-matching dispatch needs
    but loses the group↔name pairing the group trie is built from — a trie
    cannot place ``provision-it`` under ``infra/aws`` from two unrelated sets.

    Same fast path and the same ``job_filter`` semantics: the cache is written
    as a superset and job-level filters apply on read, so routing must apply
    the same filter or ``func <name>`` would route to a job the booted app then
    refuses to resolve.

    Args:
        cache_path: Path to the discovery cache file.
        job_filter: Optional JobFilter (the ``require_job_*`` settings).

    Returns:
        One row per cached job — ``(dotted_group_or_None, canonical_name,
        kind)``, where ``canonical_name`` is the descriptor's full dotted name.
        ``None`` if the cache is missing, unreadable, malformed, or a different
        format version — callers fall back to a scan.

    Note:
        Plugin commands are **not** here and cannot be: they are registered at
        APP_READY, in memory, and never reach the cache. A trie built from
        these rows describes job space only; plugin namespaces are added
        post-boot from ``app.get_plugin_commands()``.
    """
    from functualize._primitives.cache_format import CACHE_VERSION

    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None

    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None

    rows: list[tuple[str | None, str, str]] = []
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue

        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue

        if job_filter is not None:
            from functualize._primitives.job_filter import RawJobCandidate

            raw_decorators = entry.get("decorators") or ()
            candidate = RawJobCandidate(
                name=name,
                decorators=tuple(str(d) for d in raw_decorators),
                python_name=str(entry.get("python_name") or ""),
            )
            if not job_filter.should_register(candidate):
                continue

        group = entry.get("group")
        rows.append(
            (
                group if isinstance(group, str) and group else None,
                name,
                NodeKind.JOB.value,
            )
        )

    return rows


def build_group_trie(
    job_groups: Iterable[tuple[str | None, str, str]],
    plugin_namespaces: Iterable[tuple[str | None, str]] = (),
    *,
    groups: Iterable[str] = (),
    builtin: bool = True,
    group_options: Mapping[str, GroupOptionsSpec] | None = None,
) -> GroupTrie:
    """Build the namespace trie — the public, pre-boot access path.

    Wraps the single implementation in ``_types/naming.py``. ``_cli`` dogfoods
    the public API only, so this (and ``FunctualizeApp.group_trie`` for the
    post-boot path) are the sole ways to reach it.

    Import-free and boot-free: feed it
    :func:`read_routing_rows_from_cache` output and it answers dispatch and
    completion questions without constructing an app or importing a job module.

    Args:
        job_groups: ``(dotted_group_or_None, canonical_name, kind)`` rows.
        plugin_namespaces: ``(namespace_or_None, command_name)`` rows. Empty
            pre-boot — plugin commands are not cached.
        groups: Dotted group names to materialize as payload-less nodes, for
            callers that know the group shape without knowing what is under it
            (the cold-boot AST sweep).
        builtin: Seed the reserved ``builtin`` subtree.
        group_options: ``{dotted_group: GroupOptionsSpec}`` from
            :func:`read_group_options_from_cache`, carried as the trie's side
            map so a walk can tell which mid-path flags a group owns.

    Raises:
        ValueError: reserved-name or path collisions (see
            :meth:`GroupTrie.from_cache`).
    """
    return GroupTrie.from_cache(
        job_groups,
        plugin_namespaces,
        groups=groups,
        builtin=builtin,
        group_options=group_options,
    )


def read_group_options_from_cache(
    cache_path: Path,
) -> dict[str, GroupOptionsSpec] | None:
    """Read the declared per-group flags from an existing cache file.

    Fast path for the surfaces that never boot — completion, the shell, and
    the mid-path flag parse — so "does ``deploy`` accept ``--env``?" is
    answered without importing the declaring module. The declaring class is
    imported only when a value must be validated.

    Returns:
        A ``{group_path: GroupOptionsSpec}`` mapping if the cache exists and
        is valid (possibly empty when no group declares options). Returns
        None if the cache is missing, unreadable, malformed, or a different
        format version — callers should fall back to scanning.
    """
    from functualize._primitives.cache_format import CACHE_VERSION

    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None

    section = data.get("group_options")
    if section is None:
        # A valid cache written before any group declared options.
        return {}
    if not isinstance(section, dict):
        return None

    specs: dict[str, GroupOptionsSpec] = {}
    for group, spec_data in section.items():
        if not isinstance(group, str) or not group:
            continue
        try:
            specs[group] = GroupOptionsSpec.from_dict(spec_data)
        except (ValueError, TypeError, KeyError):
            # One malformed record must not blind the caller to the rest.
            continue

    return specs


def read_display_modules_from_cache(
    cache_path: Path,
) -> list[tuple[str, list[str]]] | None:
    """Read the display-flagged modules from an existing cache file.

    Fast path for TUI startup: parses the cache JSON's ``displays`` section
    without importing any modules, so the TUI knows exactly which files to
    import for their DisplayProvider classes.

    Returns:
        A list of ``(source_file, class_names)`` pairs if the cache exists
        and is valid (possibly empty when no module defines displays).
        Returns None if the cache is missing, unreadable, malformed, or a
        different format version — callers should fall back to scanning.
    """
    from functualize._primitives.cache_format import CACHE_VERSION

    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None

    displays = data.get("displays")
    if not isinstance(displays, dict):
        return None

    results: list[tuple[str, list[str]]] = []
    for entry in displays.values():
        if not isinstance(entry, dict):
            continue
        source_file = entry.get("source_file")
        class_names = entry.get("class_names")
        if not isinstance(source_file, str) or not source_file:
            continue
        if not isinstance(class_names, list):
            continue
        names = [name for name in class_names if isinstance(name, str) and name]
        if names:
            results.append((source_file, names))

    return results
