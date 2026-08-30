"""Module import and descriptor extraction for job discovery.

Provides the shared import/extract machinery used by
CachedDirectoryScanProvider and directory scanning:
- discover_module_files: enumerate module files on disk without importing.
- extract_module: import a module and extract all public JobDescriptors plus
  the DisplayProvider classes it defines (with content hash and mtime for
  cache validation), in one exec_module pass.
- full_import_and_extract: jobs-only wrapper around extract_module.
- scan_directory_for_descriptors: eager per-directory extraction.

Import failures are logged and skipped gracefully by callers.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import inspect
import logging
import os
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from functualize._discovery.ast_extractor import extract_first_level_dependencies
from functualize._discovery.group_options_extractor import extract_group_options_spec
from functualize._discovery.naming import normalize_name, qualified_name
from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize._primitives.config_class_detection import detect_config_class
from functualize._primitives.display_detection import find_display_providers
from functualize._primitives.group_options_detection import find_group_options
from functualize._primitives.pre_filter import extract_function_decorators
from functualize._types.descriptors import GroupOptionsSpec, JobDescriptor
from functualize._types.from_job import from_job_names
from functualize._types.naming import is_valid_job_group
from functualize._types.workflow import workflow_shape_of

if TYPE_CHECKING:
    from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleExtraction:
    """Everything one exec_module pass extracts from a module.

    Attributes:
        jobs: JobDescriptors for the module's public job functions.
        display_classes: Names of DisplayProvider classes the module defines.
        group_options: Specs for the GroupOptions subclasses the module binds
            to a group path.
        source_mtime: os.path.getmtime() of the source at extraction time.
        content_hash: sha256 hex digest of the source at extraction time.
    """

    jobs: list[JobDescriptor] = field(default_factory=list)
    display_classes: list[str] = field(default_factory=list)
    group_options: list[GroupOptionsSpec] = field(default_factory=list)
    source_mtime: float = 0.0
    content_hash: str = ""


def discover_module_files(jobs_dirs: list[str]) -> set[str]:
    """Scan directories for Python module files using pkgutil (no imports).

    Uses pkgutil.iter_modules to enumerate module files on disk without
    importing them. Returns absolute file paths for all discovered modules.

    Args:
        jobs_dirs: List of directory paths to scan.

    Returns:
        A set of absolute source file paths for discovered modules.
    """
    on_disk: set[str] = set()

    for jobs_dir in jobs_dirs:
        dir_path = Path(jobs_dir)
        if not dir_path.is_dir():
            continue

        try:
            for _importer, module_name, is_pkg in pkgutil.iter_modules([jobs_dir]):
                if is_pkg:
                    continue
                # Resolve the source file path
                source_file = _resolve_module_source(jobs_dir, module_name)
                if source_file is not None:
                    on_disk.add(source_file)
        except Exception as e:
            logger.warning("Failed to enumerate modules in '%s': %s", jobs_dir, e)

    return on_disk


def _resolve_module_source(jobs_dir: str, module_name: str) -> str | None:
    """Resolve a module name within a directory to its source file path.

    Args:
        jobs_dir: The directory containing the module.
        module_name: The module name (without .py extension).

    Returns:
        The absolute path to the source file, or None if not found.
    """
    candidate = Path(jobs_dir) / f"{module_name}.py"
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def extract_module(source_file: str, project_root: Path) -> ModuleExtraction:
    """Import a module and extract jobs + display classes in one pass.

    Uses importlib.util.spec_from_file_location to import the module, then
    inspects it to find ALL public job functions (and their config classes)
    and any DisplayProvider classes it defines.

    Public function criteria:
    - callable and passes inspect.isfunction()
    - no underscore prefix on name
    - inspect.getmodule() matches the imported module (locally defined)

    Display detection runs before the no-jobs early return so a module
    containing only displays still yields a cacheable record.

    Args:
        source_file: Absolute path to the Python source file.
        project_root: The project root directory (for dependency extraction).

    Returns:
        A ModuleExtraction with the discovered jobs and display class names.

    Raises:
        ImportError: If the module cannot be imported.
        SyntaxError: If the source file has syntax errors.
    """
    source_path = Path(source_file)
    module_name = source_path.stem

    # Create a unique module name to avoid conflicts with already-loaded modules
    unique_module_name = f"_functualize_sync_.{module_name}_{id(source_file)}"

    spec = importlib.util.spec_from_file_location(unique_module_name, source_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for '{source_file}'")

    module = importlib.util.module_from_spec(spec)

    # Temporarily add the module's directory to sys.path for relative imports
    module_dir = str(source_path.parent)
    path_added = False
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
        path_added = True

    # Register BEFORE exec_module — the documented importlib recipe, and here
    # it is load-bearing rather than ceremonial. A pydantic model resolves its
    # forward references by looking its own `__module__` up in `sys.modules`,
    # and under `from __future__ import annotations` *every* annotation is a
    # forward reference. So a jobs module holding
    #
    #     class Finding(BaseModel): ...
    #     class Findings(BaseModel):
    #         payload: list[Finding]
    #
    # exec'd without this line produces a `Findings` that cannot be
    # instantiated: "`Findings` is not fully defined". The class builds, the
    # scan succeeds, the job registers — and the failure surfaces only when the
    # body finally constructs one, as a pydantic error naming a class the
    # author defined right there.
    #
    # The name is uniquified per source file above, so nothing real can be
    # shadowed. On failure the entry is removed rather than left half-executed.
    sys.modules[unique_module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(unique_module_name, None)
        raise
    finally:
        if path_added and module_dir in sys.path:
            sys.path.remove(module_dir)

    # Shared metadata for jobs and display entries alike
    content = source_path.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()
    source_mtime = os.path.getmtime(source_file)

    # Displays are detected on the same executed module, before any
    # job-related early return — a display-only module must still cache.
    display_classes = [cls.__name__ for cls in find_display_providers(module)]

    # Group options likewise: the conventional home for a declaration is a
    # job-free module (``jobs/deploy/_group.py``), so it must be cached
    # before any no-jobs early return or it would never persist.
    group_options = [
        extract_group_options_spec(
            options_class,
            source_file=source_file,
            source_mtime=source_mtime,
            content_hash=content_hash,
            module_path=module_name,
        )
        for options_class in find_group_options(module)
    ]

    # Find ALL public job functions
    raw_job_group = getattr(module, "JOB_GROUP", None)
    # Treat non-string JOB_GROUP as None (ungrouped)
    job_group: str | None = raw_job_group if isinstance(raw_job_group, str) else None

    # Validate JOB_GROUP segments at discovery time
    if job_group is not None and not is_valid_job_group(job_group):
        logger.warning(
            "Module '%s' has invalid JOB_GROUP %r: each segment must be a "
            "valid Python identifier with no empty segments. Skipping module.",
            source_file,
            job_group,
        )
        return ModuleExtraction(
            display_classes=display_classes,
            group_options=group_options,
            source_mtime=source_mtime,
            content_hash=content_hash,
        )

    job_functions = _find_all_job_functions(module)

    if not job_functions:
        return ModuleExtraction(
            display_classes=display_classes,
            group_options=group_options,
            source_mtime=source_mtime,
            content_hash=content_hash,
        )

    dotted_module_path = module_name
    extract_first_level_dependencies(source_path, project_root)

    # Decorators must come from the source AST: a transparent decorator leaves
    # nothing on the imported function to introspect. Cached so job-level
    # filtering on require_job_decorators works off the cache too.
    decorators_by_func = extract_function_decorators(source_path)

    descriptors: list[JobDescriptor] = []
    for job_func, job_config_class in job_functions:
        # Extract parameters from function signature
        from functualize._discovery.providers import (
            extract_capability_markers,
            extract_ext_metadata,
            extract_parameters_from_signature,
        )

        parameters = extract_parameters_from_signature(job_func)

        # Extract config_fields from Pydantic BaseModel if present
        config_fields: list[Any] = []
        if job_config_class is not None:
            try:
                config_fields = extract_field_descriptors(job_config_class)
            except Exception as e:
                logger.warning(
                    "Failed to extract config fields from %s: %s",
                    job_config_class.__name__,
                    e,
                )

        # @job(...) declaration: identity overrides (name/group) plus the
        # cached operational contract (deps/cache/guards/exec).
        declaration = getattr(job_func, "__functualize_job__", None)
        workflow_shape = workflow_shape_of(job_func)
        raw_group = (
            declaration.group
            if declaration is not None and declaration.group is not None
            else job_group
        )
        effective_group = normalize_name(raw_group)
        descriptors.append(
            JobDescriptor(
                # `qualified_name` normalizes internally and validates what it
                # is handed as a Python identifier, so it takes the raw group —
                # passing `effective_group` made it reject its own canonical
                # form and broke every multi-word JOB_GROUP.
                name=qualified_name(raw_group, job_func.__name__),
                python_name=job_func.__name__,
                group=effective_group,
                function=job_func,
                docstring=job_func.__doc__,
                parameters=parameters,
                source=source_file,
                metadata=extract_ext_metadata(job_func),
                module_path=dotted_module_path,
                source_file=source_file,
                source_mtime=source_mtime,
                content_hash=content_hash,
                config_fields=config_fields if config_fields else parameters,
                decorators=decorators_by_func.get(job_func.__name__, ()),
                declaration=declaration,
                from_job_deps=from_job_names(job_func),
                workflow=workflow_shape,
                **extract_capability_markers(job_func),
            )
        )

    return ModuleExtraction(
        jobs=descriptors,
        display_classes=display_classes,
        group_options=group_options,
        source_mtime=source_mtime,
        content_hash=content_hash,
    )


def full_import_and_extract(
    source_file: str, project_root: Path
) -> list[JobDescriptor]:
    """Import a module and extract all public JobDescriptors.

    Jobs-only wrapper around :func:`extract_module`, kept for callers that
    don't care about display detection.

    Raises:
        ImportError: If the module cannot be imported.
        SyntaxError: If the source file has syntax errors.
    """
    return extract_module(source_file, project_root).jobs


def scan_directory_for_descriptors(
    directory: Path, *, lazy: bool = False
) -> list[JobDescriptor]:
    """Scan a single directory for job modules and return their descriptors.

    Enumerates top-level Python modules (non-recursive, skipping sub-packages)
    in the given directory and extracts a JobDescriptor for each module
    containing a registerable job function.

    Import failures are logged as warnings and skipped.

    Args:
        directory: Path to the directory to scan.
        lazy: If True, descriptors are still extracted (metadata only) but
              the caller may choose to defer actual function loading.

    Returns:
        A list of JobDescriptor instances for successfully extracted modules.
    """
    results: list[JobDescriptor] = []
    dir_str = str(directory)

    try:
        for _importer, module_name, is_pkg in pkgutil.iter_modules([dir_str]):
            if is_pkg:
                continue
            source_file = _resolve_module_source(dir_str, module_name)
            if source_file is None:
                continue
            try:
                descriptors = full_import_and_extract(source_file, directory)
                results.extend(descriptors)
            except Exception as e:
                logger.warning(
                    "Failed to extract descriptor from '%s': %s", source_file, e
                )
    except Exception as e:
        logger.warning("Failed to enumerate modules in '%s': %s", dir_str, e)

    return results


def _find_all_job_functions(
    module: Any,
) -> list[tuple[Any, type[BaseModel] | None]]:
    """Find ALL registerable job functions in a module.

    A registerable function is:
    - Callable and passes inspect.isfunction()
    - Public (no underscore prefix on name)
    - Defined in the module (inspect.getmodule() matches, or file comparison fallback)

    Also detects the JobConfig parameter (Pydantic BaseModel subclass) for each function.

    This aligns with scan_and_register() behavior which discovers all public
    functions, not just the first.

    Args:
        module: The imported module to inspect.

    Returns:
        A list of (job_function, job_config_class) tuples. Empty if no qualifying
        functions are found.
    """
    results: list[tuple[Any, type[BaseModel] | None]] = []
    module_file = getattr(module, "__file__", None)

    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue

        attr = getattr(module, attr_name, None)
        if attr is None:
            continue

        if not callable(attr) or not inspect.isfunction(attr):
            continue

        # Check that the function is defined in this module.
        # For dynamically loaded modules (via spec_from_file_location),
        # inspect.getmodule() may return None. In that case, compare the
        # function's source file against the module's __file__.
        attr_module = inspect.getmodule(attr)
        if attr_module is not None and attr_module is not module:
            continue
        if attr_module is None and module_file is not None:
            # Fall back to comparing source files
            try:
                func_file = inspect.getfile(attr)
                if os.path.abspath(func_file) != os.path.abspath(module_file):
                    continue
            except (TypeError, OSError):
                continue

        # The job's config class, through the one shared rule
        # (_primitives/config_class_detection) rather than a local copy.
        results.append((attr, detect_config_class(attr)))

    return results
