"""Materialisation resolves a method, not an attribute (C3; AC-13).

A class job's descriptor names a *class* and a *method*, but the one resolver
every lazy path shares — ``_import_real_function`` — historically looked up a
single module attribute. Warm boot is where that bites: the cached descriptor
carries no attached function, so the first materialisation is the only place
the class meets a function-shaped resolver.

Three things are asserted here:

* the resolver builds the receiver-less proxy from the **descriptor's own**
  declaration, so a warm run and a cold run see the same merged ``@job`` —
  recomputing it from the method's unmerged decorator would silently disagree;
* ``config_class`` for a class descriptor is the class itself, and no
  detection runs on a proxy (a proxy's return annotation is not a config);
* a class reached where a function was expected raises the materialisation
  error naming the entry point and the class, and never becomes a descriptor
  by way of ``_build_descriptor`` — whose ``callable()`` test accepts a class.

No test here touches the import lock or ``sys.path``: the class branch sits
*after* the import, inside the same locked region, so it adds neither.
"""

from __future__ import annotations

import sys
import textwrap
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from functualize._discovery.lazy_wrapper import LazyJobFunction
from functualize._discovery.providers import EntryPointProvider
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize._primitives import DIRegistry
from functualize._types.class_job import ClassJobMethod
from functualize._types.descriptors import JobDescriptor, RegisteredJob
from functualize._types.errors import JobMaterializationError
from functualize._types.job_declaration import JobDeclaration
from tests._support.engine_storage import engine_storage

_CLASS_MODULE = """
from pydantic import BaseModel

from functualize.job import job

JOB_GROUP = "svc"

@job
class Postgres(BaseModel):
    \"\"\"A database.\"\"\"

    host: str = "localhost"

    def start(self, force: bool = False) -> None:
        \"\"\"Start it.\"\"\"

    @job(tags=["slow"])
    def stop(self) -> None: ...
"""

_FUNCTION_MODULE = """
from functualize.job import job

@job
def backup(target: str = "all") -> None:
    \"\"\"Back up.\"\"\"
"""

#: A class with no ``@job``: ``class_in_source`` declines it, so an entry point
#: naming it keeps the ordinary lazy descriptor and the class surfaces only at
#: materialisation.
_PLAIN_CLASS_MODULE = """
class Postgres:
    def start(self) -> None: ...
"""


@dataclass
class _FakeEntryPoint:
    name: str
    value: str
    group: str = "functualize.jobs"


@contextmanager
def _with_entry_points(*eps: _FakeEntryPoint) -> Iterator[None]:
    """Patch every binding of ``entry_points`` the provider reads."""
    targets = (
        "functualize._discovery.providers.entry_points",
        "functualize._primitives.entry_points.entry_points",
    )
    with ExitStack() as stack:
        for target in targets:
            stack.enter_context(patch(target, return_value=tuple(eps)))
        yield


@contextmanager
def _module(root: Path, source: str) -> Iterator[tuple[str, Path]]:
    """Write ``source`` under ``root`` as a uniquely named importable module."""
    name = f"classjobmod_{uuid.uuid4().hex[:12]}"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.py"
    path.write_text(textwrap.dedent(source))
    saved = sys.path[:]
    sys.path.insert(0, str(root))
    sys.modules.pop(name, None)
    try:
        yield name, path
    finally:
        sys.path[:] = saved
        sys.modules.pop(name, None)


def _declaration() -> JobDeclaration:
    return JobDeclaration(group="svc", tags=("slow",), visibility="external")


def _class_descriptor(
    module_name: str, source: Path, method: str, *, declaration: JobDeclaration
) -> JobDescriptor:
    """A warm cache descriptor: class job, no attached function."""
    return JobDescriptor(
        name=f"svc.postgres.{method}",
        group="svc",
        module_path=module_name,
        source_file=str(source),
        python_name=method,
        owner_class="Postgres",
        declaration=declaration,
    )


def _engine() -> JobExecutionEngine:
    return JobExecutionEngine(
        di_registry=MagicMock(spec=DIRegistry),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
        **engine_storage(),
    )


def _entry(descriptor: JobDescriptor) -> RegisteredJob:
    return RegisteredJob(
        name=descriptor.name,
        function=LazyJobFunction(descriptor),
        config_class=None,
        group=descriptor.group,
        module_path=descriptor.module_path,
    )


class TestWarmClassDescriptor:
    def test_materialises_to_a_proxy_built_from_the_descriptor(
        self, tmp_path: Path
    ) -> None:
        declaration = _declaration()
        with _module(tmp_path, _CLASS_MODULE) as (module_name, source):
            descriptor = _class_descriptor(
                module_name, source, "start", declaration=declaration
            )
            # Detection is a function-only question. A proxy would answer it
            # from the method's return annotation, so it must not run at all.
            with patch(
                "functualize._discovery.lazy_wrapper._detect_config_class",
                side_effect=AssertionError("detection ran on a class descriptor"),
            ):
                proxy, config = LazyJobFunction(descriptor).materialize()

        assert isinstance(proxy, ClassJobMethod)
        assert proxy.job_class.__name__ == "Postgres"
        assert proxy.method_name == "start"
        # The merged declaration, by identity: a freshly computed one would be
        # equal but not the same object, and 3.1's merge is what cold runs read.
        assert proxy.__functualize_job__ is declaration
        assert config is proxy.job_class

    def test_engine_keeps_the_job_class_as_config_class(self, tmp_path: Path) -> None:
        with _module(tmp_path, _CLASS_MODULE) as (module_name, source):
            descriptor = _class_descriptor(
                module_name, source, "stop", declaration=_declaration()
            )
            engine = _engine()
            resolved = engine._ensure_materialized(_entry(descriptor))

        assert isinstance(resolved.function, ClassJobMethod)
        assert resolved.function.method_name == "stop"
        assert resolved.config_class is resolved.function.job_class
        assert resolved.config_class is not None
        assert resolved.config_class.__name__ == "Postgres"

    def test_a_missing_class_raises_with_the_descriptor_identity(
        self, tmp_path: Path
    ) -> None:
        with _module(tmp_path, _CLASS_MODULE) as (module_name, source):
            descriptor = JobDescriptor(
                name="svc.missing.start",
                group="svc",
                module_path=module_name,
                source_file=str(source),
                python_name="start",
                owner_class="Missing",
                declaration=_declaration(),
            )
            with pytest.raises(JobMaterializationError) as excinfo:
                LazyJobFunction(descriptor).materialize()

        assert excinfo.value.job_name == "svc.missing.start"
        assert excinfo.value.module_path == module_name
        # The unresolved-name path keeps the shared error's generic wording and
        # chains the cause that says which name was missing.
        assert "no job class named 'Missing'" in str(excinfo.value.__cause__)
        assert excinfo.value.__cause__ is not None

    def test_a_missing_method_raises_with_the_descriptor_identity(
        self, tmp_path: Path
    ) -> None:
        with _module(tmp_path, _CLASS_MODULE) as (module_name, source):
            descriptor = _class_descriptor(
                module_name, source, "restart", declaration=_declaration()
            )
            with pytest.raises(JobMaterializationError) as excinfo:
                LazyJobFunction(descriptor).materialize()

        assert excinfo.value.job_name == "svc.postgres.restart"
        assert "'Postgres'" in str(excinfo.value.__cause__)
        assert "'restart'" in str(excinfo.value.__cause__)


class TestFunctionDescriptorsAreUntouched:
    def test_a_plain_function_takes_the_function_path(self, tmp_path: Path) -> None:
        with _module(tmp_path, _FUNCTION_MODULE) as (module_name, source):
            descriptor = JobDescriptor(
                name="backup",
                group=None,
                module_path=module_name,
                source_file=str(source),
                python_name="backup",
            )
            real_fn, config = LazyJobFunction(descriptor).materialize()

        assert not isinstance(real_fn, ClassJobMethod)
        assert real_fn.__name__ == "backup"
        assert config is None

    def test_a_class_where_a_function_was_expected_is_never_a_descriptor(
        self, tmp_path: Path
    ) -> None:
        with _module(tmp_path, _PLAIN_CLASS_MODULE) as (module_name, source):
            # No `@job` on the class, so an entry point naming it was enumerated
            # as an ordinary job function; only materialisation can see
            # otherwise.
            descriptor = JobDescriptor(
                name="pg",
                group=None,
                module_path=module_name,
                source_file=str(source),
                python_name="Postgres",
            )
            with pytest.raises(JobMaterializationError) as excinfo:
                LazyJobFunction(descriptor).materialize()

        message = str(excinfo.value)
        assert "'pg'" in message
        assert "'Postgres'" in message
        assert module_name in message
        assert "failed to import module" not in message
        assert excinfo.value.job_name == "pg"

    def test_the_provider_never_builds_a_descriptor_from_a_class(
        self, tmp_path: Path
    ) -> None:
        with _module(tmp_path, _PLAIN_CLASS_MODULE) as (module_name, _source):
            provider = EntryPointProvider()
            with (
                _with_entry_points(_FakeEntryPoint("pg", f"{module_name}:Postgres")),
                patch.object(
                    EntryPointProvider,
                    "_build_descriptor",
                    side_effect=AssertionError("a class reached _build_descriptor"),
                ) as build,
                pytest.raises(JobMaterializationError) as excinfo,
            ):
                provider.get_job("pg")

        build.assert_not_called()
        assert "'Postgres'" in str(excinfo.value)
