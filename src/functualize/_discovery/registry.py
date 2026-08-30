"""Job auto-discovery and registration system.

Scans configured directories for job modules and registers discovered
functions, with support for JOB_GROUP grouping, RunContext injection,
JobConfig resolution, and duplicate detection.

Note: All CLI wiring logic has been moved to ``app/adapters/cli.py``.
This module handles only discovery and registration — zero CLI imports.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import logging
import os
import pkgutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from functualize._discovery.ast_extractor import extract_first_level_dependencies
from functualize._discovery.naming import (
    normalize_name,
    qualified_name,
)
from functualize._discovery.schema_extractor import extract_field_descriptors
from functualize._primitives.config_class_detection import detect_config_class
from functualize._types.descriptors import JobDescriptor, RegisteredJob
from functualize._types.errors import JobNotFoundError
from functualize._types.from_job import declared_dependency_names
from functualize._types.naming import is_valid_job_group
from functualize._types.workflow import workflow_shape_of

if TYPE_CHECKING:
    from functualize._events.hooks import HookRegistry
    from functualize.app.core import FunctualizeApp
    from functualize.job.context import RunContext

logger = logging.getLogger(__name__)


class JobRegistry:
    """Scans directories for job modules and registers them as CLI commands.

    The registry handles:
    - Scanning directories using pkgutil.iter_modules
    - Filtering functions: public (no underscore prefix), defined in module, callable
    - JOB_GROUP grouping: sub-group for grouped, top-level for ungrouped
    - RunContext injection: excludes RunContext param from CLI, injects at invocation
    - Lifecycle hook invocation around job execution
    - Duplicate command detection with warning
    """

    def __init__(
        self,
        hook_registry: HookRegistry | None = None,
        app: FunctualizeApp | None = None,
        config_validator: Callable[[type], None] | None = None,
        cli_wiring_factory: dict[str, Callable[..., Any]] | None = None,
    ):
        self._registered_commands: dict[str, str] = {}  # name -> module path
        self._registered_jobs: dict[str, RegisteredJob] = {}
        self._run_contexts: list[RunContext] = []
        self._hook_registry: HookRegistry | None = hook_registry
        self._app: FunctualizeApp | None = app
        self._job_descriptors: list[JobDescriptor] = []
        self._config_validator = config_validator
        self._cli_wiring_factory = cli_wiring_factory

    def get_job(self, name: str) -> RegisteredJob:
        """Look up a registered job by name for programmatic invocation.

        Args:
            name: The registered job name to look up.

        Returns:
            The RegisteredJob entry for the given name.

        Raises:
            JobNotFoundError: If the job name is not registered.
        """
        if name in self._registered_jobs:
            return self._registered_jobs[name]

        # Jobs register under the canonical name, so resolve through the one
        # naming policy before declaring the job missing — a caller holding the
        # Python spelling is asking for a job that exists.
        from functualize._types.naming import resolve_name

        try:
            return self._registered_jobs[resolve_name(name, self._registered_jobs)]
        except LookupError:
            raise JobNotFoundError(name) from None

    def get_descriptors(self) -> list[JobDescriptor]:
        """Return all retained JobDescriptor instances.

        Returns all descriptors produced during scan_and_register() or
        dynamic registration. Returns an empty list if no descriptors
        have been registered.

        Returns:
            List of all retained JobDescriptor instances.
        """
        return list(self._job_descriptors)

    def get_descriptor(self, job_name: str) -> JobDescriptor:
        """Return the JobDescriptor matching the given job name.

        Args:
            job_name: The job name to look up.

        Returns:
            The JobDescriptor whose name attribute matches job_name.

        Raises:
            KeyError: If no descriptor matches the given name.
        """
        by_name = {descriptor.name: descriptor for descriptor in self._job_descriptors}
        if job_name in by_name:
            return by_name[job_name]

        # Descriptors carry the canonical name; resolve through the one naming
        # policy so a caller holding the Python spelling is not told the job
        # does not exist.
        from functualize._types.naming import resolve_name

        try:
            return by_name[resolve_name(job_name, by_name)]
        except LookupError:
            raise KeyError(
                f"No JobDescriptor found for job name '{job_name}'"
            ) from None

    def scan_and_register(
        self,
        app: Any,
        jobs_paths: list[str],
        module_filter: set[str] | None = None,
    ) -> None:
        """Scan all job directories and register discovered functions.

        Iterates over each path in jobs_paths, uses pkgutil.iter_modules to
        find modules (skipping sub-packages), imports each module, and records
        qualifying functions as job commands.

        Discovery records identity only — delivery-layer CLI wiring is the
        adapter's responsibility (app/adapters/cli.py), so commands are tracked
        in _registered_commands for duplicate detection and lookup.

        Args:
            app: Retained for call-site compatibility; the registry no longer
                wires commands onto a delivery surface.
            jobs_paths: List of filesystem paths to scan for job modules.
            module_filter: Optional set of module names to restrict imports to.
                When provided, only modules whose names are in this set will be
                imported and registered. Applied after pkgutil enumeration but
                before module import.
        """
        for jobs_path in jobs_paths:
            self._scan_directory(app, jobs_path, module_filter=module_filter)

    def scan_and_register_headless(
        self,
        jobs_paths: list[str],
        module_filter: set[str] | None = None,
    ) -> None:
        """Scan all job directories and register discovered functions (no CLI wiring).

        Same as scan_and_register but without CLI command registration.
        Used by the kernel when running in adapter-agnostic mode.

        Args:
            jobs_paths: List of filesystem paths to scan for job modules.
            module_filter: Optional set of module names to restrict imports to.
        """
        for jobs_path in jobs_paths:
            self._scan_directory_headless(jobs_path, module_filter=module_filter)

    @staticmethod
    def _import_module_from_dir(module_name: str, jobs_path: str) -> Any:
        """Import (or refresh) a module, ensuring it comes from jobs_path.

        A same-named module cached in sys.modules may originate from a
        different directory (an earlier scan of another project, possibly
        a deleted tmp dir) — reloading it would re-execute the WRONG file
        or fail on the missing one. Reload only when the cached module's
        file lives at the expected jobs_path location; otherwise load
        fresh from the expected source file and replace the sys.modules
        entry.
        """
        expected = (Path(jobs_path) / f"{module_name}.py").resolve()
        existing = sys.modules.get(module_name)
        if existing is None:
            return importlib.import_module(module_name)

        existing_file = getattr(existing, "__file__", None)
        if existing_file and Path(existing_file).resolve() == expected:
            # Same source file — reload for fresh state (legacy semantics)
            return importlib.reload(existing)

        if expected.exists():
            import importlib.util as _importlib_util

            spec = _importlib_util.spec_from_file_location(module_name, str(expected))
            if spec and spec.loader:
                module = _importlib_util.module_from_spec(spec)
                spec.loader.exec_module(module)
                sys.modules[module_name] = module
                return module

        # Last resort: legacy behavior
        return importlib.reload(existing)

    def _scan_directory_headless(
        self,
        jobs_path: str,
        module_filter: set[str] | None = None,
    ) -> None:
        """Scan a single directory for job modules without CLI wiring.

        Performs discovery and registration only — no CLI command creation.

        Args:
            jobs_path: Filesystem path to scan.
            module_filter: Optional set of module names to restrict imports to.
        """
        path_added = False
        if jobs_path not in sys.path:
            sys.path.insert(0, jobs_path)
            path_added = True

        try:
            for _importer, module_name, is_pkg in pkgutil.iter_modules([jobs_path]):
                if is_pkg:
                    continue

                if module_filter is not None and module_name not in module_filter:
                    continue

                try:
                    module = self._import_module_from_dir(module_name, jobs_path)
                except Exception as e:
                    logger.warning(
                        f"Failed to import module '{module_name}' from '{jobs_path}': {e}"
                    )
                    continue

                self._extract_descriptors_from_module(module)

                # Register commands in the _registered_commands index
                # for show-info and lookup purposes (without CLI wiring)
                job_group: str | None = getattr(module, "JOB_GROUP", None)
                for attr_name in dir(module):
                    if attr_name.startswith("_"):
                        continue
                    attr = getattr(module, attr_name)
                    if not self._is_registerable_function(attr, module):
                        continue
                    registry_key = f"{job_group or '__top__'}::{attr_name}"
                    if registry_key not in self._registered_commands:
                        self._registered_commands[registry_key] = module.__name__
        finally:
            if path_added and jobs_path in sys.path:
                sys.path.remove(jobs_path)

    def _scan_directory(
        self,
        app: Any,
        jobs_path: str,
        module_filter: set[str] | None = None,
    ) -> None:
        """Scan a single directory for job modules.

        Args:
            app: The Click application to register commands on.
            jobs_path: Filesystem path to scan.
            module_filter: Optional set of module names to restrict imports to.
                When provided, only modules whose names are in this set will be
                imported and registered. Applied after pkgutil enumeration but
                before module import.
        """
        # Ensure the jobs_path is on sys.path so importlib can find modules
        path_added = False
        if jobs_path not in sys.path:
            sys.path.insert(0, jobs_path)
            path_added = True

        try:
            for _importer, module_name, is_pkg in pkgutil.iter_modules([jobs_path]):
                if is_pkg:
                    continue

                # Apply module filter: skip modules not in the filter set
                if module_filter is not None and module_name not in module_filter:
                    continue

                try:
                    # Import fresh, reload, or recover from a same-named
                    # module cached from a different directory
                    module = self._import_module_from_dir(module_name, jobs_path)
                except Exception as e:
                    logger.warning(
                        f"Failed to import module '{module_name}' from '{jobs_path}': {e}"
                    )
                    continue

                self._extract_descriptors_from_module(module)

                # Track commands (for duplicate detection). Delivery-layer CLI
                # wiring is the adapter's job (app/adapters/cli.py), not the
                # registry's — the registry only records identity.
                job_group: str | None = getattr(module, "JOB_GROUP", None)
                for attr_name in dir(module):
                    if attr_name.startswith("_"):
                        continue
                    attr = getattr(module, attr_name)
                    if not self._is_registerable_function(attr, module):
                        continue
                    registry_key = f"{job_group or '__top__'}::{attr_name}"
                    if registry_key not in self._registered_commands:
                        self._registered_commands[registry_key] = module.__name__
        finally:
            # Clean up sys.path if we added to it
            if path_added and jobs_path in sys.path:
                sys.path.remove(jobs_path)

    def extract_descriptors(self, module_name: str) -> list[JobDescriptor]:
        """Extract job descriptors from a module without any CLI wiring.

        Imports the named module, scans its qualifying functions, creates
        RegisteredJob entries, emits JOB_REGISTERED hooks, and returns
        JobDescriptor instances. Does NOT perform CLI wiring.

        Public for testing; not part of the end-user API.

        Args:
            module_name: Fully-qualified module name to import and describe.

        Returns:
            List of JobDescriptor instances for all qualifying functions.
        """
        if module_name in sys.modules:
            module = importlib.reload(sys.modules[module_name])
        else:
            module = importlib.import_module(module_name)
        return self._extract_descriptors_from_module(module)

    def _extract_descriptors_from_module(self, module: Any) -> list[JobDescriptor]:
        """Extract descriptors from an already-imported module (L1 work only).

        Args:
            module: Already-imported module to scan.

        Returns:
            List of JobDescriptor instances for all qualifying functions.
        """
        job_group: str | None = getattr(module, "JOB_GROUP", None)

        # Validate JOB_GROUP segments at discovery time
        if job_group is not None and not is_valid_job_group(job_group):
            logger.warning(
                "Module '%s' has invalid JOB_GROUP %r: each segment must be a "
                "valid Python identifier with no empty segments. Skipping module.",
                getattr(module, "__name__", "<unknown>"),
                job_group,
            )
            return []

        # Compute source file metadata for JobDescriptor production
        source_file_path: Path | None = None
        content_hash: str | None = None
        source_mtime: float | None = None
        module_file = getattr(module, "__file__", None)
        if module_file:
            source_file_path = Path(module_file).resolve()
            try:
                content_hash = hashlib.sha256(source_file_path.read_bytes()).hexdigest()
                source_mtime = os.path.getmtime(source_file_path)
            except OSError:
                source_file_path = None

        descriptors: list[JobDescriptor] = []

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue

            attr = getattr(module, attr_name)

            if not self._is_registerable_function(attr, module):
                continue

            # @job(...) declaration: identity overrides (name/group) applied
            # before the registry key is computed, plus the cached contract.
            declaration = getattr(attr, "__functualize_job__", None)
            workflow_shape = workflow_shape_of(attr)
            raw_group = (
                declaration.group
                if declaration is not None and declaration.group is not None
                else job_group
            )
            effective_group = normalize_name(raw_group)
            # Each function gets its own distinct qualified name as registry key.
            # `qualified_name` normalizes internally and validates the group it
            # is handed as a Python identifier, so it must see the *raw*
            # spelling — handing it `effective_group` made it reject the very
            # form this line had just produced, and any multi-word JOB_GROUP
            # ("data_ops", "dataOps") failed registration.
            registry_key = qualified_name(raw_group, attr_name)

            # Detect JobConfig parameter (Pydantic BaseModel subclass in signature)
            job_config_class = self._detect_job_config_class(attr)

            # Validate JobConfig types at registration time (fail fast)
            if job_config_class is not None and self._config_validator is not None:
                self._config_validator(job_config_class)

            # Retain callable reference for programmatic invocation
            entry = RegisteredJob(
                name=registry_key,
                function=attr,
                config_class=job_config_class,
                group=effective_group,
                module_path=module.__name__,
                dependencies=declared_dependency_names(
                    getattr(attr, "__functualize_job__", None), attr
                ),
            )
            # Normalization can map two distinct functions onto one name —
            # `build_wheel` and `buildWheel` both become `build-wheel`. Without
            # this the second silently replaces the first and one job vanishes
            # with no diagnostic anywhere. Two functions cannot share an
            # address, so this is an authoring error and says so.
            existing = self._registered_jobs.get(registry_key)
            existing_raw = getattr(
                getattr(existing, "function", None), "__name__", None
            )
            if (
                existing is not None
                and existing.function is not attr
                # Same spelling from two modules is the *pre-existing* duplicate
                # case, which warns and skips further down. Only a collision
                # normalization itself created — two different spellings landing
                # on one address — is new, and only that is an error here.
                and existing_raw != attr_name
            ):
                raise ValueError(
                    f"Two jobs normalize to the same name {registry_key!r}: "
                    f"{getattr(existing.function, '__name__', existing.function)!r} "
                    f"(from {existing.module_path}) and {attr_name!r} "
                    f"(from {module.__name__}). Job names are normalized to "
                    f"lowercase-hyphenated form, so these are the same address. "
                    f"Rename one."
                )
            self._registered_jobs[registry_key] = entry

            # Emit JOB_REGISTERED hook event
            if self._hook_registry is not None:
                hook_group = effective_group if effective_group is not None else ""
                hook_metadata: dict[str, Any] = {
                    "name": attr_name,
                    "group": hook_group,
                    "config_schema": job_config_class,
                    "docstring": attr.__doc__,
                }
                self._hook_registry.invoke_job_registered(hook_metadata)

            # Produce JobDescriptor
            if (
                source_file_path is not None
                and content_hash is not None
                and source_mtime is not None
            ):
                config_fields: list[Any] = []
                if job_config_class is not None:
                    try:
                        config_fields = extract_field_descriptors(job_config_class)
                    except Exception:
                        logger.debug(
                            f"Failed to extract field descriptors for '{attr_name}' "
                            f"config class: {job_config_class.__name__}"
                        )

                project_root = source_file_path.parent.parent
                extract_first_level_dependencies(source_file_path, project_root)

                # Extract parameters from function signature
                from functualize._discovery.providers import (
                    extract_capability_markers,
                    extract_ext_metadata,
                    extract_parameters_from_signature,
                )

                parameters = extract_parameters_from_signature(attr)

                descriptor = JobDescriptor(
                    name=registry_key,
                    group=effective_group,
                    function=attr,
                    docstring=attr.__doc__,
                    parameters=parameters,
                    source=str(source_file_path),
                    metadata=extract_ext_metadata(attr),
                    module_path=module.__name__,
                    source_file=str(source_file_path),
                    source_mtime=source_mtime,
                    content_hash=content_hash,
                    config_fields=config_fields if config_fields else parameters,
                    declaration=declaration,
                    workflow=workflow_shape,
                    **extract_capability_markers(attr),
                )
                descriptors.append(descriptor)
                self._job_descriptors.append(descriptor)

        return descriptors

    def create_job_command(
        self,
        name: str,
        function: Callable[..., Any],
        job_config_class: type[BaseModel] | None = None,
    ) -> Callable[..., Any]:
        """Wrap a job function, injecting RunContext and resolving JobConfig.

        Delegates to the CLI wiring factory's create_job_command.

        Args:
            name: The job name (used as config section prefix and env var prefix).
            function: The original job function.
            job_config_class: Optional Pydantic model class for job config.

        Returns:
            A wrapped callable with RunContext excluded and JobConfig options added.

        Raises:
            RuntimeError: If cli_wiring_factory was not injected.
        """
        if self._cli_wiring_factory is None:
            raise RuntimeError(
                "JobRegistry.create_job_command() requires cli_wiring_factory "
                "to be injected at construction time."
            )

        _create_job_command = self._cli_wiring_factory["create_job_command"]
        command: Callable[..., Any] = _create_job_command(
            name=name,
            function=function,
            job_config_class=job_config_class,
            app=self._app,
        )
        return command

    @staticmethod
    def _is_registerable_function(attr: Any, module: Any) -> bool:
        """Check if an attribute qualifies for registration.

        A function is registerable if:
        1. It is callable
        2. It is a function (not a class or other callable)
        3. It is defined in the given module (not imported)

        Args:
            attr: The attribute to check.
            module: The module the attribute was found in.

        Returns:
            True if the attribute should be registered.
        """
        if not callable(attr):
            return False
        if not inspect.isfunction(attr):
            return False
        return inspect.getmodule(attr) is module

    @staticmethod
    def _detect_job_config_class(
        function: Callable[..., Any],
    ) -> type[BaseModel] | None:
        """The cold-boot entry point to the one config-class rule.

        Delegates to ``_primitives.config_class_detection``. This was the
        correct copy of three; the rule now lives in one place so the warm and
        single-file paths cannot drift from it again.

        Args:
            function: The function to inspect.

        Returns:
            The Pydantic BaseModel subclass if found, None otherwise.
        """
        return detect_config_class(function)

    def update_config_paths(self) -> None:
        """Re-resolve configurations after global options are processed.

        Called when global options (like --config-directory) change the
        config path after initial registration. Delegates to the app
        which has access to the config layer.
        """
        if self._app is None:
            return
        # Delegate config re-resolution to the app (composition root)
        # which can access _config layer directly
        if hasattr(self._app, "_update_run_context_configs"):
            self._app._update_run_context_configs(self._run_contexts)
