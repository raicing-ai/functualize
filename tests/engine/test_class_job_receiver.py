"""A class job runs on the instance its configuration resolved to (C1, C6).

Three claims, all about the one seam where a class job differs from a function
job at run time:

* registration keeps the class as ``config_class`` and the method as
  ``method_name``, and does neither for a function job;
* ``_resolve_config_model`` ends by rebinding ``context.function`` to
  ``getattr(cls, method)(instance)``, so the method's receiver *is* the model
  built from ``[pg]`` — one instance per invocation, not a copy and not a
  second construction;
* a class job's config section is its group's (``[pg]``, ``PG__HOST``), while
  a function job keeps its own name as the section.

The module is written with ``from __future__ import annotations`` on purpose:
under PEP 563 the receiver rebind must not cost a ``GroupOptions`` parameter
its place in the freshness hash, which is read off ``context.function`` after
the rebind.
"""

from __future__ import annotations

import functools
import inspect
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from functualize._app.boot import register_descriptors
from functualize._app.state import AppState
from functualize._config.chain import ResolutionChain
from functualize._config.job_config import JobConfigView
from functualize._discovery.cached_provider import CachedDirectoryScanProvider
from functualize._engine.capabilities.runcontext import RunContext
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize._primitives import DIRegistry
from functualize._primitives.locator import ResourceLocator
from functualize._types.run_request import RunRequest

if TYPE_CHECKING:
    from functualize._engine.context import ExecutionContext
    from functualize._engine.result import JobResult
    from functualize._types.descriptors import JobDescriptor

from tests._support.engine_storage import engine_storage

#: ``CONSTRUCTED``/``CALLS`` are ``ClassVar`` so pydantic does not turn them
#: into model fields; they are the only channel the module has back to the test.
_MODULE = '''
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from functualize.job import GroupOptions, job

class PgOptions(GroupOptions, group="pg"):
    """A group option, declared beside the class job that consumes it."""

    region: str = "us-east-1"

@job(group="pg")
class Postgres(BaseModel):
    CONSTRUCTED: ClassVar[list[str]] = []
    CALLS: ClassVar[list[tuple[object, ...]]] = []

    host: str = "localhost"

    def start(self, force: bool = False, opts: PgOptions = None) -> None:
        Postgres.CALLS.append((self, force, opts))

    def stop(self) -> None:
        Postgres.CALLS.append((self,))

class ProbeConfig(BaseModel):
    host: str = "default-host"

JOB_GROUP = "pg"

PROBES: list[tuple[object, ...]] = []

@job
def probe(cfg: ProbeConfig) -> None:
    PROBES.append((cfg,))
'''


@pytest.fixture(autouse=True)
def _app_state() -> None:
    AppState.reset()
    AppState.set("config_directory", ".")
    AppState.set("environment", "DEV")


def _scan(tmp_path: Path) -> list[JobDescriptor]:
    """Cold descriptors, through the provider the boot actually scans with."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / "pg.py").write_text(textwrap.dedent(_MODULE))
    locator = (
        ResourceLocator()
        .search_explicit(tmp_path / "cache")
        .write_to_explicit(tmp_path / "cache")
    )
    provider = CachedDirectoryScanProvider(
        directories=[str(jobs_dir)], locator=locator, project_root=tmp_path
    )
    return list(provider.list_jobs())


def _setup(tmp_path: Path, recording: _Recording | None = None) -> Any:
    """One cold scan, registered on one engine.

    The scan is a *cold* one: a second scan over the same directory answers
    from the cache it just wrote, with ``function=None``. Anything the tests
    need about the class is read from the registered entry, which is what a
    run reads.
    """
    descriptors = _scan(tmp_path)
    engine = _engine(recording or _Recording())
    _register(engine, descriptors)
    return engine, descriptors


class _Recording:
    """The host's view factory and config resolver, recording what they are asked.

    The views are the real ones — ``JobConfigView`` over an empty chain — so a
    run's ``set_prefix``/``scope`` handling is the production one; only the
    *resolution* is stubbed, because the claim under test is identity (the
    receiver is the resolved instance), not the configuration ladder, which
    the CLI acceptance test exercises against real files.
    """

    def __init__(self) -> None:
        self.chain = ResolutionChain([])
        self.views: dict[int, tuple[str, str]] = {}
        self.resolved: list[tuple[type, str, Any, dict[str, Any]]] = []

    def factory(self, *, section_prefix: str, scope: str = "job") -> Any:
        view = JobConfigView(
            resolution_chain=self.chain,
            default_section_prefix=section_prefix,
            scope=scope,  # type: ignore[arg-type]
        )
        self.views[id(view)] = (section_prefix, scope)
        return view

    def resolver(
        self,
        *,
        config_class: type,
        job_name: str,
        config_view: Any,
        cli_values: dict[str, Any],
    ) -> Any:
        self.resolved.append((config_class, job_name, config_view, cli_values))
        return config_class(host="db.internal")

    def section_of(self, view: Any) -> tuple[str, str]:
        return self.views[id(view)]


def _engine(recording: _Recording) -> JobExecutionEngine:
    return JobExecutionEngine(
        di_registry=DIRegistry(),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
        config_view_factory=recording.factory,
        config_resolver=recording.resolver,
        **engine_storage(),  # type: ignore[arg-type]
    )


def _register(engine: JobExecutionEngine, descriptors: list[JobDescriptor]) -> None:
    """The boot's own registration function, over a stub app's two registries."""
    app = SimpleNamespace(
        job_registry=SimpleNamespace(
            _registered_jobs={},
            _job_descriptors=[],
            _registered_commands={},
        ),
        _execution_engine=engine,
    )
    register_descriptors(app, descriptors)


class _Capture:
    """Stash the ``ExecutionContext`` the run assembled, once."""

    def __init__(self, engine: JobExecutionEngine) -> None:
        self.context: ExecutionContext | None = None
        self._inner = engine._execute_with_lifecycle  # noqa: SLF001

        def _wrapper(context: ExecutionContext) -> JobResult:
            self.context = context
            return self._inner(context)  # type: ignore[no-any-return]

        engine._execute_with_lifecycle = _wrapper  # type: ignore[method-assign] # noqa: SLF001


def _run(engine: JobExecutionEngine, name: str) -> tuple[Any, _Capture]:
    capture = _Capture(engine)
    result = engine.run(RunRequest(job_name=name, surface="app.execute"))
    return result, capture


class TestRegistration:
    def test_a_class_job_registers_the_class_and_the_method(
        self, tmp_path: Path
    ) -> None:
        engine, descriptors = _setup(tmp_path)

        entry = engine.get_job("pg.start")
        assert entry.method_name == "start"
        assert entry.config_class is descriptors[0].function.job_class
        assert issubclass(entry.config_class, BaseModel)
        assert entry.group == "pg"
        # The method, not the class, names the job; the class names the config.
        assert entry.config_class.__name__ == "Postgres"
        assert descriptors[0].owner_class == "Postgres"
        assert descriptors[0].python_name == "start"

    def test_a_function_job_registers_neither(self, tmp_path: Path) -> None:
        engine, _ = _setup(tmp_path)

        entry = engine.get_job("pg.probe")
        assert entry.method_name is None
        assert entry.config_class is not None
        assert entry.config_class.__name__ == "ProbeConfig"


class TestTheReceiver:
    def test_the_receiver_is_the_instance_the_run_resolved(
        self, tmp_path: Path
    ) -> None:
        recording = _Recording()
        engine, _ = _setup(tmp_path, recording)
        job_class = engine.get_job("pg.start").config_class

        result, capture = _run(engine, "pg.start")

        assert result.status.name == "SUCCESS", result.exception
        ((receiver, force, options),) = job_class.CALLS
        assert type(receiver) is job_class
        assert receiver.host == "db.internal"
        assert force is False
        # Group options still resolve: the rebind does not cost the method its
        # injection, only its `self`.
        assert options is not None
        assert type(options).__name__ == "PgOptions"
        assert options.region == "us-east-1"
        # The one instance: what the resolver built is the receiver and the
        # RunContext's config, not a copy of it.
        assert capture.context is not None
        rc = capture.context.capabilities[RunContext]
        assert rc.job_config is receiver

    def test_the_rebound_callable_binds_the_receiver_positionally(
        self, tmp_path: Path
    ) -> None:
        recording = _Recording()
        engine, _ = _setup(tmp_path, recording)

        result, capture = _run(engine, "pg.start")

        assert result.status.name == "SUCCESS", result.exception
        assert capture.context is not None
        rebound = capture.context.function
        assert isinstance(rebound, functools.partial)
        assert rebound.func.__qualname__ == "Postgres.start"
        # The receiver is the partial's first argument; `self` is therefore
        # neither a keyword the caller passed nor one it could have.
        assert rebound.args[0] is capture.context.capabilities[RunContext].job_config
        assert "self" in inspect.signature(rebound.func).parameters
        assert "self" not in inspect.signature(rebound).parameters

    def test_the_receiver_never_enters_call_kwargs_or_injected(
        self, tmp_path: Path
    ) -> None:
        engine, _ = _setup(tmp_path)

        result, capture = _run(engine, "pg.start")

        assert result.status.name == "SUCCESS", result.exception
        assert capture.context is not None
        assert "self" not in capture.context.call_kwargs
        assert "self" not in capture.context.injected
        # Injection is unchanged by the rebind: the receiver is passed
        # positionally, so the only keyword the run carries is the group
        # option, and no config parameter is injected — a class job's receiver
        # *is* its config.
        assert set(capture.context.call_kwargs) == {"opts"}
        assert set(capture.context.injected) == {"opts"}
        assert "self" not in inspect.signature(capture.context.function).parameters
        assert list(inspect.signature(capture.context.function).parameters) == [
            "force",
            "opts",
        ]


class TestTheSection:
    def test_a_class_job_reads_its_group_section(self, tmp_path: Path) -> None:
        recording = _Recording()
        engine, _ = _setup(tmp_path, recording)

        result, capture = _run(engine, "pg.start")

        assert result.status.name == "SUCCESS", result.exception
        assert capture.context is not None
        ((config_class, job_name, view, cli_values),) = [
            call
            for call in recording.resolved
            if call[0] is capture.context.config_class
        ]
        assert config_class is capture.context.config_class
        assert job_name == "pg"
        assert recording.section_of(view) == ("pg", "group")
        assert cli_values == {}
        # `[pg.start]` is a section no class-job author writes.
        assert ("pg.start", "job") not in recording.views.values()

    def test_a_function_job_keeps_its_own_section(self, tmp_path: Path) -> None:
        recording = _Recording()
        engine, _ = _setup(tmp_path, recording)

        result, _ = _run(engine, "pg.probe")

        assert result.status.name == "SUCCESS", result.exception
        ((_, job_name, view, _),) = recording.resolved
        assert job_name == "pg.probe"
        assert recording.section_of(view) == ("pg.probe", "job")


class TestIntrospectionConstructsNothing:
    def test_listing_and_lookup_construct_no_instance(self, tmp_path: Path) -> None:
        engine, descriptors = _setup(tmp_path)
        job_class = engine.get_job("pg.start").config_class

        for descriptor in descriptors:
            engine.get_job(descriptor.name)

        assert job_class.CONSTRUCTED == []


class TestFreshnessKey:
    def test_the_args_hash_computes_after_the_rebind(self, tmp_path: Path) -> None:
        engine, _ = _setup(tmp_path)

        result, capture = _run(engine, "pg.start")

        assert result.status.name == "SUCCESS", result.exception
        assert capture.context is not None
        # Read through `context.function`, which the rebind replaced: a hash
        # that raised here would fail the run's fingerprint, and one that
        # silently dropped a `GroupOptions` parameter would merge two
        # different invocations into one key.
        assert engine._args_hash_for(capture.context)  # noqa: SLF001

    def test_a_group_options_parameter_survives_the_rebind(
        self, tmp_path: Path
    ) -> None:
        engine, descriptors = _setup(tmp_path)
        proxy = next(job.function for job in descriptors if job.name == "pg.start")

        # The proxy, before the rebind, is what the hash sees for the
        # declaration; after it, the same parameter must still be found
        # through a PEP 563 annotation.
        declared = engine._group_options_params(proxy)  # noqa: SLF001
        assert [name for name, _ in declared] == ["opts"]

        result, capture = _run(engine, "pg.start")
        assert result.status.name == "SUCCESS", result.exception
        assert capture.context is not None
        assert isinstance(capture.context.function, functools.partial)
        assert [
            name
            for name, _ in engine._group_options_params(capture.context.function)  # noqa: SLF001
        ] == ["opts"]
