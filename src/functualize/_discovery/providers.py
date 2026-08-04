"""Job provider implementations for the discovery pipeline.

Concrete providers that satisfy the JobProvider protocol from _types/:
- DirectoryScanProvider: Scans filesystem directories for job modules.
- StaticProvider: Wraps pre-imported callables as JobDescriptors with zero I/O.
- EntryPointProvider: Discovers jobs from installed packages via entry points.

The cache-first provider (CachedDirectoryScanProvider) lives in
`cached_provider.py`.

Only imports from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

import contextlib
import enum
import importlib.metadata
import importlib.util
import inspect
import logging
import os
import sys
import types as builtin_types
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin

from functualize._primitives import JobFilter, ModulePreFilter, iter_module_files
from functualize._primitives.group_options_detection import (
    is_group_options_subclass,
)
from functualize._types import FieldDescriptor, JobDescriptor
from functualize._types.annotations import resolved_hints
from functualize._types.from_job import from_job_names
from functualize._types.naming import normalize_name, normalize_segment
from functualize._types.workflow import workflow_shape_of

logger = logging.getLogger(__name__)


# Names of types that should be excluded from parameter extraction
# (framework-injected parameters, not user-facing CLI parameters)
_EXCLUDED_PARAM_TYPE_NAMES = frozenset(
    {
        "RunContext",
        "Log",
        "Invoke",
        "Prompt",
        "Perf",
        "State",
        "JobContext",
        "JobConfigView",
        "TTY",
        "Live",
    }
)

# Capability marker type names harvested into job-level JobDescriptor flags
# (routing hints), distinct from user-facing CLI parameters.
_TTY_TYPE_NAME = "TTY"
_LIVE_TYPE_NAME = "Live"


def extract_parameters_from_signature(
    func: Callable[..., Any],
) -> list[FieldDescriptor]:
    """Extract FieldDescriptors from a function's signature via introspection.

    For each parameter in the function signature:
    - Skips 'self' and 'cls' parameters.
    - Skips parameters annotated with RunContext or JobConfigView types.
    - Defaults to type_annotation="str" when no annotation is present.
    - Populates `choices` with enum member names for Enum-typed parameters.
    - Detects Arg() marker for positional arguments.
    - Detects Option() marker for short flag aliases.

    Args:
        func: The callable to inspect.

    Returns:
        A list of FieldDescriptor instances, one per user-facing parameter.
    """
    from typing import Annotated

    parameters: list[FieldDescriptor] = []
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return parameters

    # Resolve string annotations (from `from __future__ import annotations`)
    # to actual type objects for proper Annotated introspection
    hints = resolved_hints(func)

    for param_name, param in sig.parameters.items():
        # Skip 'self', 'cls'
        if param_name in ("self", "cls"):
            continue

        # Use resolved hint if available, fall back to raw annotation
        annotation = hints.get(param_name, param.annotation)

        # Skip `FromJob` parameters: the engine fills them from the upstream's
        # recorded result, so exposing one as a CLI option would hand the
        # executor the option's *default* and look like a caller-supplied
        # value — silently suppressing the injection it exists for.
        if _has_from_job(annotation):
            continue

        # Skip framework-injected types (RunContext, JobConfigView)
        if _is_excluded_type(annotation):
            continue

        # Skip a `GroupOptions` parameter — the injection point that *receives*
        # a group's resolved flags (`opts: DeployOptions`). It is settable on no
        # surface, so it must not enter `parameters`: for a convention job with
        # no dedicated config class, `config_fields` falls back to `parameters`,
        # and an injection point left here leaks into every surface that reads
        # config_fields (completion did — the parity harness caught it). Each
        # surface filtered it downstream; removing it at the source means one
        # exclusion instead of one-per-surface, which is one fewer place to miss.
        if isinstance(annotation, type) and is_group_options_subclass(annotation):
            continue

        # Unwrap Annotated to extract markers and base type
        is_positional = False
        short_flag: str | None = None
        is_stdin = False
        stdin_flag: str | None = None
        description = ""

        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            base_annotation = args[0]
            metadata = args[1:]

            # Check for Arg/Option/Stdin markers (matched by class name to keep
            # this internal module free of CLI-marker imports).
            for meta in metadata:
                cls_name = type(meta).__name__
                if cls_name == "Arg":
                    is_positional = True
                    if hasattr(meta, "help") and meta.help:
                        description = meta.help
                elif cls_name == "Option":
                    if hasattr(meta, "short") and meta.short:
                        short_flag = meta.short
                    if hasattr(meta, "help") and meta.help:
                        description = meta.help
                elif cls_name == "Stdin":
                    is_stdin = True
                    if getattr(meta, "flag", None):
                        stdin_flag = meta.flag
                    if getattr(meta, "help", None) and not description:
                        description = meta.help

            # Check for Pydantic Field metadata
            for meta in metadata:
                if (
                    hasattr(meta, "description")
                    and meta.description
                    and not description
                ):
                    description = meta.description
        else:
            base_annotation = annotation

        # Determine type_annotation string (use unwrapped base type, not Annotated wrapper)
        type_str = _annotation_to_type_str(base_annotation)

        # Determine default and required
        has_default = param.default is not inspect.Parameter.empty
        default_value = param.default if has_default else None

        # Determine choices for Enum types
        choices = _extract_enum_choices(base_annotation)

        parameters.append(
            FieldDescriptor(
                name=param_name,
                type_annotation=type_str,
                default=default_value,
                description=description,
                required=not has_default,
                choices=choices,
                positional=is_positional,
                short_flag=short_flag,
                is_stdin=is_stdin,
                stdin_flag=stdin_flag,
            )
        )

    return parameters


def _has_from_job(annotation: Any) -> bool:
    """True when the annotation carries a ``FromJob`` marker."""
    from functualize._types.from_job import FromJob

    if get_origin(annotation) is not Annotated:
        return False
    return any(isinstance(meta, FromJob) for meta in get_args(annotation)[1:])


def _is_excluded_type(annotation: Any) -> bool:
    """Check if an annotation represents a framework-injected type to skip.

    Optional-aware: ``tty: TTY | None`` (a preference-level capability) is
    excluded from CLI parameters just like a bare ``tty: TTY``.
    """
    name, _optional = _base_type_name(annotation)
    return bool(name and name in _EXCLUDED_PARAM_TYPE_NAMES)


def _base_type_name(annotation: Any) -> tuple[str | None, bool]:
    """Return ``(bare type name, is_optional)`` for a parameter annotation.

    Unwraps ``Annotated[...]`` and ``Optional[T]`` / ``T | None`` so the name
    is the underlying type. Handles both resolved types and string
    (forward-ref) annotations such as ``"TTY | None"`` / ``"Optional[TTY]"``.
    Returns ``(None, False)`` for un-annotated parameters.
    """
    from typing import Annotated

    if annotation is inspect.Parameter.empty:
        return (None, False)

    # Unwrap Annotated[...] to its base type.
    if get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]

    # String (forward-ref) annotation — parse textually.
    if isinstance(annotation, str):
        s = annotation.strip()
        optional = "None" in s and ("|" in s or s.startswith("Optional["))
        s = s.replace("| None", "").replace("|None", "").strip()
        if s.startswith("Optional[") and s.endswith("]"):
            s = s[len("Optional[") : -1].strip()
        return (s or None, optional)

    # Resolved type, possibly Optional[...].
    unwrapped = _unwrap_optional(annotation)
    optional = unwrapped is not annotation
    name = getattr(unwrapped, "__name__", None)
    return (name, optional)


def extract_capability_markers(func: Callable[..., Any]) -> dict[str, Any]:
    """Harvest TTY/Live capability declarations from a function signature.

    Returns a dict suitable for ``JobDescriptor(**markers)``:

    - ``requires_tty`` — a bare ``tty: TTY`` (HARD requirement; forces
      EXCLUSIVE surface resolution, refused off-terminal).
    - ``optional_tty`` — ``tty: TTY | None`` (preference; injected when
      EXCLUSIVE is grantable, else None — the job degrades).
    - ``uses_live`` — ``live: Live`` (per-surface live-display channel).

    Matched by type *name* (like the ``Stdin`` marker) so this internal module
    imports no capability types, and works whether the annotation resolved to
    a real class or stayed a PEP 563 string.
    """
    markers = {"requires_tty": False, "optional_tty": False, "uses_live": False}
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return markers

    hints = resolved_hints(func)

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        annotation = hints.get(param_name, param.annotation)
        name, is_optional = _base_type_name(annotation)
        if name == _TTY_TYPE_NAME:
            if is_optional:
                markers["optional_tty"] = True
            else:
                markers["requires_tty"] = True
        elif name == _LIVE_TYPE_NAME:
            markers["uses_live"] = True

    markers["suppress_live"] = _extract_suppress_live(func)  # type: ignore[assignment]
    markers["surface_hint"] = _extract_surface_hint(func)  # type: ignore[assignment]
    return markers


def extract_ext_metadata(func: Callable[..., Any]) -> dict[str, Any]:
    """Collect plugin extension metadata from a job function (§A.6).

    Plugin decorators attach ``__functualize_ext_<namespace>__`` dunders with
    JSON-serializable values. This gathers them into the descriptor's
    ``metadata`` under ``{"plugins": {namespace: value}}`` so plugin middleware
    can read its per-job config, and so boot can flag orphaned metadata whose
    plugin is not loaded. Returns ``{}`` when the function declares none.
    """
    prefix = "__functualize_ext_"
    plugins: dict[str, Any] = {}
    for attr, value in getattr(func, "__dict__", {}).items():
        if attr.startswith(prefix) and attr.endswith("__"):
            namespace = attr[len(prefix) : -2]
            if namespace:
                plugins[namespace] = value
    return {"plugins": plugins} if plugins else {}


def _extract_surface_hint(func: Callable[..., Any]) -> str | None:
    """Read ``@surface_hint(...)``'s declaration off a job function.

    Cached into the descriptor because the surface-resolution ladder runs
    before the job is imported on a warm boot.
    """
    declared = getattr(func, "__functualize_surface_hint__", None)
    return declared if isinstance(declared, str) else None


def _extract_suppress_live(func: Callable[..., Any]) -> tuple[str, ...]:
    """Read ``@suppress_live(...)``'s declaration off a job function.

    Cached into the descriptor because the decision "which ambient constructs
    does this job opt out of" is made at surface-setup time, before the job is
    imported on a warm boot.
    """
    declared = getattr(func, "__functualize_suppress_live__", None)
    if declared is None:
        return ()
    if isinstance(declared, str):
        return (declared,)
    try:
        return tuple(str(name) for name in declared)
    except TypeError:
        return ()


def _annotation_to_type_str(annotation: Any) -> str:
    """Convert a type annotation to its string representation.

    Returns "str" for parameters without annotations or unresolvable types.
    """
    if annotation is inspect.Parameter.empty:
        return "str"

    # Handle string annotations
    if isinstance(annotation, str):
        return annotation

    # Handle None type
    if annotation is type(None):
        return "None"

    # Unwrap Optional[T] / T | None to inner type for display
    unwrapped = _unwrap_optional(annotation)
    if unwrapped is not annotation:
        inner_str = _annotation_to_type_str(unwrapped)
        return f"{inner_str} | None"

    # Handle generic types like list[str], dict[str, int], etc.
    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        if origin is list:
            if args:
                inner = _annotation_to_type_str(args[0])
                return f"list[{inner}]"
            return "list"
        if origin is dict:
            if len(args) == 2:
                k = _annotation_to_type_str(args[0])
                v = _annotation_to_type_str(args[1])
                return f"dict[{k}, {v}]"
            return "dict"
        # Fallback for other generics
        return str(annotation)

    # Handle basic types with __name__
    type_name: str | None = getattr(annotation, "__name__", None)
    if type_name:
        return type_name

    # Fallback
    return str(annotation)


def _unwrap_optional(annotation: Any) -> Any:
    """Unwrap Optional[T] or T | None to the inner type T.

    Returns the original annotation if it's not Optional.
    """
    origin = get_origin(annotation)
    args = get_args(annotation)

    # Python 3.10+ union syntax (X | Y) or typing.Union[X, Y]
    if origin is builtin_types.UnionType or (
        origin is not None and getattr(origin, "__name__", None) == "Union"
    ):
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            return non_none_args[0]

    return annotation


def _extract_enum_choices(annotation: Any) -> list[str] | None:
    """Extract enum member names if the annotation is an Enum type.

    Returns a list of enum member name strings, or None if not an Enum.
    """
    if annotation is inspect.Parameter.empty:
        return None

    # Unwrap Optional
    unwrapped = _unwrap_optional(annotation)
    if unwrapped is not annotation:
        annotation = unwrapped

    # Check if it's an Enum subclass
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return [member.name for member in annotation]

    return None


@dataclass(frozen=True)
class Job:
    """Explicit job definition with overrides.

    Used with StaticProvider to provide metadata overrides for a callable.
    When name is None, the function's __name__ is used.

    Attributes:
        function: The callable to wrap as a job.
        name: Override for the job name. Defaults to function.__name__.
        group: Override for the job group. Defaults to None.
    """

    function: Callable[..., Any]
    name: str | None = None
    group: str | None = None


class DirectoryScanProvider:
    """Scan filesystem directories for job modules.

    Scans top-level .py modules only (non-recursive), skipping sub-packages
    and underscore-prefixed files. Non-existent or unreadable directories are
    skipped with a warning log. Results are cached after the first scan.

    Satisfies the JobProvider Protocol via structural typing.

    Args:
        directories: List of directory paths to scan (at least 1 required).
        pre_filter: Optional ModulePreFilter to skip modules before import.
        job_filter: Optional JobFilter applied per extracted descriptor, for
            the ``require_job_*`` settings a file-level pre-filter cannot
            express.

    Raises:
        ValueError: If directories list is empty.
    """

    def __init__(
        self,
        directories: list[str],
        pre_filter: ModulePreFilter | None = None,
        job_filter: JobFilter | None = None,
    ) -> None:
        if not directories:
            raise ValueError("At least one directory path is required")
        self._directories = directories
        self._pre_filter = pre_filter
        self._job_filter = job_filter
        self._cache: list[JobDescriptor] | None = None

    def list_jobs(self) -> Sequence[JobDescriptor]:
        """Return all job descriptors from scanned directories.

        Results are cached after the first call.
        """
        if self._cache is None:
            self._cache = self._scan()
        return self._cache

    def get_job(self, name: str) -> JobDescriptor | None:
        """Retrieve a specific job by name. None if not found.

        Descriptors carry the canonical name, so the requested one is
        canonicalized before comparison — a caller holding the Python
        spelling is asking for a job that exists.
        """
        wanted = normalize_name(name)
        for desc in self.list_jobs():
            if desc.name in (name, wanted):
                return desc
        return None

    def _scan(self) -> list[JobDescriptor]:
        """Scan directories and return descriptors.

        Logs warning for non-existent/unreadable directories and skips them.
        """
        results: list[JobDescriptor] = []
        for dir_path in self._directories:
            path = Path(dir_path)
            if not path.exists() or not path.is_dir():
                logger.warning("Directory not found or not readable: %s", dir_path)
                continue
            results.extend(self._scan_directory(path))
        return results

    def _scan_directory(self, directory: Path) -> list[JobDescriptor]:
        """Scan a single directory for job modules and extract descriptors."""
        results: list[JobDescriptor] = []
        for module_file in iter_module_files(directory):
            # Apply pre-filter if configured
            if self._pre_filter is not None and not self._pre_filter.should_import(
                module_file
            ):
                continue
            descriptors = self._import_and_extract(module_file)
            if self._job_filter is not None:
                descriptors = [
                    d for d in descriptors if self._job_filter.should_register(d)
                ]
            results.extend(descriptors)
        return results

    def _import_and_extract(self, source_file: Path) -> list[JobDescriptor]:
        """Import a module and extract all public job descriptors."""
        try:
            module_name = source_file.stem
            unique_name = f"_functualize_discovery_.{module_name}_{id(source_file)}"

            spec = importlib.util.spec_from_file_location(unique_name, str(source_file))
            if spec is None or spec.loader is None:
                return []

            module = importlib.util.module_from_spec(spec)

            # Temporarily add module directory to sys.path
            module_dir = str(source_file.parent)
            path_added = False
            if module_dir not in sys.path:
                sys.path.insert(0, module_dir)
                path_added = True

            try:
                spec.loader.exec_module(module)
            finally:
                if path_added and module_dir in sys.path:
                    sys.path.remove(module_dir)

            return self._extract_descriptors(module, source_file)
        except Exception as e:
            logger.warning("Failed to import and extract from '%s': %s", source_file, e)
            return []

    def _extract_descriptors(
        self, module: Any, source_file: Path
    ) -> list[JobDescriptor]:
        """Extract JobDescriptors from all public functions in a module."""
        from pydantic import BaseModel

        from functualize._discovery.schema_extractor import extract_field_descriptors
        from functualize._primitives.pre_filter import extract_function_decorators

        results: list[JobDescriptor] = []
        module_file = getattr(module, "__file__", None)
        job_group_attr: str | None = getattr(module, "JOB_GROUP", None)
        # Decorators must come from the source AST: a transparent decorator
        # leaves nothing on the imported function to introspect.
        decorators_by_func = extract_function_decorators(source_file)

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue

            attr = getattr(module, attr_name, None)
            if attr is None or not callable(attr) or not inspect.isfunction(attr):
                continue

            # Verify function is defined in this module
            attr_module = inspect.getmodule(attr)
            if attr_module is not None and attr_module is not module:
                continue
            if attr_module is None and module_file is not None:
                try:
                    func_file = inspect.getfile(attr)
                    if os.path.abspath(func_file) != os.path.abspath(module_file):
                        continue
                except (TypeError, OSError):
                    continue

            # Extract parameters from function signature
            parameters = self._extract_parameters(attr)

            # Detect and extract config_fields from BaseModel parameter
            config_fields: list[FieldDescriptor] = []
            try:
                sig = inspect.signature(attr)
                hints = resolved_hints(attr)
                for name, param in sig.parameters.items():
                    annotation = hints.get(name, param.annotation)
                    if (
                        isinstance(annotation, type)
                        and issubclass(annotation, BaseModel)
                        and annotation is not BaseModel
                        # A GroupOptions parameter carries the *group's* flags,
                        # not this job's config fields (see sync.py).
                        and not is_group_options_subclass(annotation)
                    ):
                        with contextlib.suppress(Exception):
                            config_fields = extract_field_descriptors(annotation)
                        break
            except (ValueError, TypeError):
                pass

            declaration = getattr(attr, "__functualize_job__", None)
            workflow_shape = workflow_shape_of(attr)
            from_job_deps = from_job_names(attr)
            effective_group = (
                declaration.group
                if declaration is not None and declaration.group is not None
                else job_group_attr
            )
            # `@job(name=)` is gone: the address derives from `__name__` and
            # is normalized here so this provider agrees with the cached and
            # registry paths. Leaving it raw made the same job `test_suite`
            # through one door and `test-suite` through another.
            effective_name = normalize_segment(attr_name)

            results.append(
                JobDescriptor(
                    name=effective_name,
                    group=normalize_name(effective_group),
                    python_name=attr_name,
                    function=attr,
                    docstring=getattr(attr, "__doc__", None),
                    parameters=parameters,
                    source=str(source_file),
                    metadata=extract_ext_metadata(attr),
                    config_fields=config_fields if config_fields else parameters,
                    decorators=decorators_by_func.get(attr_name, ()),
                    declaration=declaration,
                    from_job_deps=from_job_deps,
                    workflow=workflow_shape,
                    **extract_capability_markers(attr),
                )
            )

        return results

    def _extract_parameters(self, func: Callable[..., Any]) -> list[FieldDescriptor]:
        """Extract FieldDescriptors from function signature via shared introspection."""
        return extract_parameters_from_signature(func)


class StaticProvider:
    """Wraps pre-imported callables as JobDescriptors with zero I/O.

    Accepts a list of plain callables or Job dataclass instances.
    Plain callables derive job name from function.__name__.
    Job instances allow overriding name and group.

    Satisfies the JobProvider Protocol via structural typing.

    Args:
        functions: List of callables or Job dataclass instances.
    """

    def __init__(self, functions: list[Callable[..., Any] | Job]) -> None:
        self._descriptors: list[JobDescriptor] = []
        self._by_name: dict[str, JobDescriptor] = {}

        for item in functions:
            descriptor = self._build_descriptor(item)
            self._descriptors.append(descriptor)
            self._by_name[descriptor.name] = descriptor

    def list_jobs(self) -> Sequence[JobDescriptor]:
        """Return all job descriptors from this source."""
        return self._descriptors

    def get_job(self, name: str) -> JobDescriptor | None:
        """Retrieve a specific job by name. None if not found."""
        found = self._by_name.get(name)
        if found is None:
            canonical = normalize_name(name) or name
            found = self._by_name.get(canonical) if canonical != name else None
        return found

    def _build_descriptor(self, item: Callable[..., Any] | Job) -> JobDescriptor:
        """Build a JobDescriptor from a callable or Job dataclass."""
        func = item.function if isinstance(item, Job) else item

        # @job(...) declaration on the function; explicit Job wiring wins for
        # identity, then the declaration, then the function convention.
        declaration = getattr(func, "__functualize_job__", None)
        workflow_shape = workflow_shape_of(func)
        # `@job(name=)` is gone; explicit `Job(name=)` wiring still wins for
        # identity, then the function's own name. All are canonicalized, so
        # this provider addresses jobs exactly as every other path does.
        decl_group = declaration.group if declaration is not None else None
        if isinstance(item, Job):
            name = normalize_name(item.name) or normalize_segment(func.__name__)
            group = normalize_name(item.group if item.group is not None else decl_group)
        else:
            name = normalize_segment(func.__name__)
            group = normalize_name(decl_group)

        # Extract parameters from function signature
        parameters = self._extract_parameters(func)

        return JobDescriptor(
            name=name,
            group=group,
            function=func,
            python_name=func.__name__,
            docstring=getattr(func, "__doc__", None),
            parameters=parameters,
            source="<static>",
            metadata=extract_ext_metadata(func),
            declaration=declaration,
            from_job_deps=from_job_names(func),
            workflow=workflow_shape,
            **extract_capability_markers(func),
        )

    def _extract_parameters(self, func: Callable[..., Any]) -> list[FieldDescriptor]:
        """Extract FieldDescriptors from function signature via shared introspection."""
        return extract_parameters_from_signature(func)


class EntryPointProvider:
    """Discover jobs from installed packages via entry points.

    Discovers and loads entry points registered under a specified group,
    building JobDescriptor instances from each successfully loaded object.
    Broken entry points are logged as warnings and skipped.

    Satisfies the JobProvider Protocol via structural typing.

    Results are cached after the first scan.

    Args:
        group: Entry point group name (default: "functualize.jobs").
    """

    def __init__(self, group: str = "functualize.jobs") -> None:
        self._group = group
        self._cache: list[JobDescriptor] | None = None

    def list_jobs(self) -> Sequence[JobDescriptor]:
        """Return all job descriptors discovered from entry points.

        Results are cached after the first scan.
        """
        if self._cache is None:
            self._cache = self._discover()
        return self._cache

    def get_job(self, name: str) -> JobDescriptor | None:
        """Retrieve a specific job by name, canonical or Python spelling."""
        wanted = normalize_name(name)
        for desc in self.list_jobs():
            if desc.name in (name, wanted):
                return desc
        return None

    def _discover(self) -> list[JobDescriptor]:
        """Load entry points and build descriptors."""
        results: list[JobDescriptor] = []
        for ep in importlib.metadata.entry_points(group=self._group):
            try:
                loaded = ep.load()
                results.append(self._build_descriptor(ep.name, loaded))
            except Exception as e:
                logger.warning(
                    "Failed to load entry point '%s' from group '%s': %s",
                    ep.name,
                    self._group,
                    e,
                )
        return results

    def _build_descriptor(self, name: str, obj: Any) -> JobDescriptor:
        """Build a JobDescriptor from a loaded entry point object."""
        func = obj if callable(obj) else lambda: None

        # Extract parameters from callable's signature
        parameters = extract_parameters_from_signature(func) if callable(obj) else []

        declaration = getattr(func, "__functualize_job__", None)
        workflow_shape = workflow_shape_of(func)
        effective_name = normalize_segment(name)
        effective_group = (
            normalize_name(declaration.group) if declaration is not None else None
        )

        return JobDescriptor(
            name=effective_name,
            group=effective_group,
            function=func,
            docstring=getattr(obj, "__doc__", None),
            parameters=parameters,
            source=getattr(obj, "__module__", "<entry_point>"),
            metadata=extract_ext_metadata(func),
            declaration=declaration,
            from_job_deps=from_job_names(func),
            workflow=workflow_shape,
            **extract_capability_markers(func),
        )
