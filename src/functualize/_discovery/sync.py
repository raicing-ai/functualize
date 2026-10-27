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

import functools
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
from functualize._types.class_job import ClassJobMethod
from functualize._types.descriptors import GroupOptionsSpec, JobDescriptor
from functualize._types.discovery_report import (
    DiscoveryFailure,
    record_discovery_finding,
)
from functualize._types.from_job import from_job_names
from functualize._types.job_declaration import JobDeclaration
from functualize._types.naming import is_valid_job_group
from functualize._types.workflow import workflow_shape_of

if TYPE_CHECKING:
    from pydantic import BaseModel


#: ``DiscoveryFailure.error_type`` for a job class that still has unimplemented
#: abstract methods (rule F1-a). Not an exception class name, like
#: ``JOB_NAME_COLLISION``: nothing is raised, the class simply registers nothing.
ABSTRACT_JOB_CLASS = "AbstractJobClass"

#: ``DiscoveryFailure.error_type`` for a method whose own ``@job(group=...)``
#: disagrees with its class's group (contract C4).
METHOD_GROUP_CONFLICT = "MethodGroupConflict"

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

    job_functions, job_classes = _find_all_jobs(module)

    if not job_functions and not job_classes:
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

    # A job class contributes one descriptor per public method, built by the
    # same function the static provider uses (3.4) so a class job discovered
    # from a directory and one named by a plugin are the same job.
    for job_class in job_classes:
        descriptors.extend(
            class_job_descriptors(
                job_class,
                module_name=dotted_module_path,
                job_group=job_group,
                source_file=source_file,
                source_mtime=source_mtime,
                content_hash=content_hash,
                decorators_by_func=decorators_by_func,
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


def _find_all_jobs(
    module: Any,
) -> tuple[list[tuple[Any, type[BaseModel] | None]], list[type[BaseModel]]]:
    """Find ALL registerable job functions and job classes in a module.

    A registerable function is:
    - Callable and passes inspect.isfunction()
    - Public (no underscore prefix on name)
    - Defined in the module (inspect.getmodule() matches, or file comparison fallback)

    Also detects the JobConfig parameter (Pydantic BaseModel subclass) for each function.

    A registerable job class carries ``__functualize_job__`` in its **own**
    namespace — never through a base, because the opt-in is not inherited
    (rule F1-b) — is defined in this module, and subclasses ``BaseModel``.

    This aligns with scan_and_register() behavior which discovers all public
    functions, not just the first.

    Args:
        module: The imported module to inspect.

    Returns:
        A ``(functions, classes)`` pair. ``functions`` holds
        (job_function, job_config_class) tuples; ``classes`` holds the job
        classes, whose methods are turned into descriptors by
        :func:`class_job_descriptors`.
    """
    from pydantic import BaseModel

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

    job_classes: list[type[BaseModel]] = []
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue

        attr = getattr(module, attr_name, None)
        if not isinstance(attr, type):
            continue
        # Own namespace, not ``getattr``: a base class's opt-in would otherwise
        # enlist every subclass, including the plain config models that only
        # inherit from another job class.
        if "__functualize_job__" not in attr.__dict__:
            continue
        if attr.__module__ != module.__name__:
            continue
        if not issubclass(attr, BaseModel):
            continue

        job_classes.append(attr)

    return results, job_classes


def _job_class_methods(job_class: type[BaseModel]) -> dict[str, Any]:
    """The public instance methods a job class contributes, nearest definition first.

    ``inspect.getmembers(cls, isfunction)`` cannot serve here: it answers with a
    plain function for a ``staticmethod``, so an attribute that is deliberately
    not a job method would register as one. Reading each base's ``__dict__``
    keeps the descriptor/function distinction intact and yields the raw
    function, whose own ``__dict__`` still carries the ``@job``/``@cache``
    dunders that ``getattr`` on the bound attribute would lose.
    """
    methods: dict[str, Any] = {}
    from pydantic import BaseModel

    for base in job_class.__mro__:
        if base is BaseModel or base is object:
            continue
        # pydantic's own bases are excluded by ``__mro__`` order, but a mixin a
        # user subclasses from pydantic's namespace would still walk methods
        # like ``model_dump`` — none of which are job methods.
        if base.__module__.split(".")[0] == "pydantic":
            continue
        for name, value in base.__dict__.items():
            if name.startswith("_") or name in methods:
                continue
            if isinstance(value, staticmethod | classmethod | property):
                continue
            if isinstance(value, functools.cached_property):
                continue
            if not inspect.isfunction(value):
                continue
            methods[name] = value
    return methods


def _job_class_group(
    job_class: type[BaseModel],
    class_declaration: JobDeclaration,
    job_group: str | None,
) -> str:
    """The class's group, in its author-facing spelling.

    ``@job(group=...)`` on the class wins outright, exactly as it does on a
    function. Otherwise the class name *is* the group segment, and the module's
    ``JOB_GROUP`` stays the namespace above it — a class file still groups as a
    unit, and two classes in one file stay distinct.

    The class name is returned unnormalized on purpose: ``qualified_name``
    validates every segment as an identifier before it normalizes, and
    ``normalize_segment("LocalPostgres")`` is ``"local-postgres"``, which it
    would reject.
    """
    if class_declaration.group is not None:
        return class_declaration.group
    if job_group:
        return f"{job_group}.{job_class.__name__}"
    return job_class.__name__


def _job_class_tags(
    job_class: type[BaseModel],
    class_declaration: JobDeclaration,
    method_declaration: JobDeclaration | None,
) -> tuple[str, ...]:
    """The merged tag tuple: author, then class, then ``JOB_TAGS`` outward.

    Nearest declaration first, so a method's own tags lead; duplicates keep
    their first position rather than reordering the tuple. ``JOB_TAGS`` is read
    from each class's ``__dict__`` — a ``ClassVar`` is not a model field, and
    ``getattr`` would read a base's list into every subclass below it twice.
    """
    merged: list[str] = []
    if method_declaration is not None:
        merged.extend(method_declaration.tags)
    merged.extend(class_declaration.tags)
    for base in job_class.__mro__:
        declared = base.__dict__.get("JOB_TAGS")
        if isinstance(declared, tuple | list):
            merged.extend(tag for tag in declared if isinstance(tag, str))

    seen: set[str] = set()
    ordered = []
    for tag in merged:
        if tag not in seen:
            seen.add(tag)
            ordered.append(tag)
    return tuple(ordered)


def class_job_descriptors(
    job_class: type[BaseModel],
    *,
    module_name: str,
    job_group: str | None,
    source_file: str = "",
    source_mtime: float = 0.0,
    content_hash: str = "",
    decorators_by_func: dict[str, tuple[str, ...]] | None = None,
) -> list[JobDescriptor]:
    """Turn one job class into one :class:`JobDescriptor` per public method.

    Shared by the directory scan (this module) and the static provider (3.4):
    a class job is a class job however it was found, and two implementations
    would eventually disagree about its name, group or merged declaration.

    Args:
        job_class: The class carrying ``__functualize_job__`` in its own
            namespace.
        module_name: The defining module — the failure record's ``module`` and
            the descriptor's ``module_path``.
        job_group: The module's ``JOB_GROUP``, or None.
        source_file: Absolute path to the defining source file.
        source_mtime: Source file mtime, for cache invalidation.
        content_hash: Source content hash, for cache invalidation.
        decorators_by_func: Decorator roots keyed by ``"<Class>.<method>"``
            (with a bare-method-name fallback), from the source AST.

    Returns:
        The descriptors, one per job method. Empty for an abstract class and
        for a class whose methods are all group-conflicting — in both cases a
        discovery finding is recorded instead of a job.
    """
    # Deferred: ``providers`` imports this module inside a function to break the
    # cycle, so the reverse import has to be just as late.
    from functualize._discovery.providers import (
        extract_capability_markers,
        extract_ext_metadata,
        extract_parameters_from_signature,
    )

    abstract_methods: frozenset[str] = getattr(
        job_class, "__abstractmethods__", frozenset()
    )
    if abstract_methods:
        unimplemented = ", ".join(sorted(abstract_methods))
        record_discovery_finding(
            DiscoveryFailure(
                module=module_name,
                path=source_file,
                error_type=ABSTRACT_JOB_CLASS,
                message=(
                    f"Job class '{job_class.__name__}' in module '{module_name}' "
                    f"is abstract (unimplemented: {unimplemented}); "
                    "no job is registered."
                ),
            )
        )
        return []

    class_declaration: JobDeclaration = job_class.__dict__["__functualize_job__"]
    raw_group = _job_class_group(job_class, class_declaration, job_group)
    effective_group = normalize_name(raw_group)
    decorators = decorators_by_func or {}

    descriptors: list[JobDescriptor] = []
    for method_name, method in _job_class_methods(job_class).items():
        method_declaration = method.__dict__.get("__functualize_job__")
        if (
            method_declaration is not None
            and method_declaration.group is not None
            and normalize_name(method_declaration.group) != effective_group
        ):
            record_discovery_finding(
                DiscoveryFailure(
                    module=module_name,
                    path=source_file,
                    error_type=METHOD_GROUP_CONFLICT,
                    message=(
                        f"Job method '{job_class.__name__}.{method_name}' declares "
                        f"group '{method_declaration.group}' but its class "
                        f"'{job_class.__name__}' declares '{raw_group}'; the two "
                        "must agree, so no job is registered."
                    ),
                )
            )
            continue

        # The effective declaration: identity and tags are the class's to merge,
        # the method's own declaration supplies everything that acts (guards,
        # exec, cache, deps). ``declaration.group`` is normalized so
        # ``descriptor.group == normalize_name(declaration.group)`` holds for a
        # class job exactly as it does for a function.
        effective = JobDeclaration(
            group=effective_group,
            extra_description=(
                method_declaration.extra_description
                if method_declaration is not None
                else class_declaration.extra_description
            ),
            category=(
                method_declaration.category
                if method_declaration is not None
                else class_declaration.category
            ),
            examples=(
                method_declaration.examples
                if method_declaration is not None
                else class_declaration.examples
            ),
            tags=_job_class_tags(job_class, class_declaration, method_declaration),
            visibility=(
                method_declaration.visibility
                if method_declaration is not None
                else class_declaration.visibility
            ),
            config_section=(
                method_declaration.config_section
                if method_declaration is not None
                else class_declaration.config_section
            ),
            deps=method_declaration.deps if method_declaration is not None else None,
            cache=method_declaration.cache if method_declaration is not None else None,
            guards=(
                method_declaration.guards if method_declaration is not None else None
            ),
            exec=method_declaration.exec if method_declaration is not None else None,
        )
        # ``<Class>.<method>`` first: a method's own decorators are recorded
        # there together with its class's, because the class's ``@job`` is what
        # brings the method into existence (D8). The bare name is the fallback
        # for a source file that yields only top-level keys.
        method_key = f"{job_class.__name__}.{method_name}"
        method_decorators = (
            decorators[method_key]
            if method_key in decorators
            else decorators.get(method_name, ())
        )

        proxy = ClassJobMethod(job_class, method_name, declaration=effective)
        parameters = extract_parameters_from_signature(proxy)
        try:
            config_fields = extract_field_descriptors(job_class) or parameters
        except Exception as exc:
            logger.warning(
                "Failed to extract config fields for job class '%s' in '%s': %s",
                job_class.__name__,
                source_file,
                exc,
            )
            config_fields = parameters

        descriptors.append(
            JobDescriptor(
                name=qualified_name(raw_group, method_name),
                python_name=method_name,
                group=effective_group,
                owner_class=job_class.__name__,
                function=proxy,
                docstring=method.__doc__,
                parameters=parameters,
                source=source_file,
                module_path=module_name,
                source_file=source_file,
                source_mtime=source_mtime,
                content_hash=content_hash,
                config_fields=config_fields,
                decorators=method_decorators,
                # Metadata and capabilities are read off the raw method: the
                # proxy has no ``__dict__`` of the author's, and plugin dunders
                # (``__functualize_surface_hint__`` and friends) live there.
                metadata=extract_ext_metadata(method),
                workflow=workflow_shape_of(method),
                from_job_deps=from_job_names(method),
                declaration=effective,
                **extract_capability_markers(method),
            )
        )

    return descriptors
