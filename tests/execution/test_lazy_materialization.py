"""Unit tests for LazyJobFunction and engine materialize-on-demand.

Covers Phase 1 of the true-lazy registration refactor:
1. LazyJobFunction construction performs NO module import
2. materialize() is idempotent and thread-safe (single import)
3. Import failure raises JobMaterializationError chaining the cause
4. Engine _ensure_materialized swaps the frozen entry in the engine
   registry AND in its host's copy; explicit config_class is preserved
5. get_job()/execute() materialize transparently
6. validate_di_bindings skips unmaterialized lazy entries
7. invoke-by-callable resolves against an unmaterialized proxy via
   module/qualname metadata fallback
"""

from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from functualize._discovery.lazy_wrapper import LazyJobFunction
from functualize._engine.capabilities.invoke import WiredInvoke
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize._primitives import DIRegistry
from functualize._types.descriptors import JobDescriptor, RegisteredJob
from functualize._types.errors import JobMaterializationError
from tests._support.engine_run import run_job
from tests._support.engine_storage import engine_storage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecordingHost:
    """The smallest host the materialization path needs.

    It stands in for the app registry, which the engine used to be handed by
    reference — the registry's own private dict, mirrored into the engine so a
    materialized entry could be written back into it. Now the engine *reports*
    the swap instead, and this records what it was told.
    """

    def __init__(self) -> None:
        self.jobs: dict[str, RegisteredJob] = {}

    def replace_job(self, current: RegisteredJob, replacement: RegisteredJob) -> None:
        if self.jobs.get(current.name) is current:
            self.jobs[current.name] = replacement


def _make_engine(host: object | None = None) -> JobExecutionEngine:
    return JobExecutionEngine(
        di_registry=MagicMock(spec=DIRegistry),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
        host=host,
        **engine_storage(),
    )


def _write_job_module(
    tmp_path: Path, func_name: str, body: str = "    return x\n"
) -> tuple[JobDescriptor, Path]:
    """Write a job module with an import-side-effect marker file.

    The module appends a line to <module>.imports.log on every import,
    letting tests count how many times the module body executed.
    """
    module_name = f"lazymod_{uuid.uuid4().hex[:12]}"
    marker = tmp_path / f"{module_name}.imports.log"
    source = tmp_path / f"{module_name}.py"
    source.write_text(
        f"from pathlib import Path\n"
        f"Path({str(marker)!r}).open('a').write('imported\\n')\n"
        f"def {func_name}(x: int = 1):\n"
        f'    """A lazy test job."""\n'
        f"{body}"
    )
    descriptor = JobDescriptor(
        name=func_name,
        group=None,
        module_path=module_name,
        source_file=str(source),
        docstring="cached docstring",
    )
    return descriptor, marker


def _import_count(marker: Path) -> int:
    if not marker.exists():
        return 0
    return len(marker.read_text().splitlines())


def _lazy_entry(descriptor: JobDescriptor) -> RegisteredJob:
    return RegisteredJob(
        name=descriptor.name,
        function=LazyJobFunction(descriptor),
        config_class=None,
        group=descriptor.group,
        module_path=descriptor.module_path,
    )


@pytest.fixture(autouse=True)
def _restore_sys_modules():
    before = set(sys.modules)
    yield
    for name in set(sys.modules) - before:
        if name.startswith("lazymod_"):
            del sys.modules[name]


# ---------------------------------------------------------------------------
# LazyJobFunction unit behavior
# ---------------------------------------------------------------------------


class TestLazyJobFunction:
    def test_construction_does_not_import(self, tmp_path: Path) -> None:
        descriptor, marker = _write_job_module(tmp_path, "myjob")
        proxy = LazyJobFunction(descriptor)
        assert _import_count(marker) == 0
        assert proxy.__name__ == "myjob"
        assert proxy.__module__ == descriptor.module_path
        assert proxy.__doc__ == "cached docstring"
        assert getattr(proxy, "__functualize_lazy__", False) is True

    def test_materialize_imports_once_and_is_idempotent(self, tmp_path: Path) -> None:
        descriptor, marker = _write_job_module(tmp_path, "myjob")
        proxy = LazyJobFunction(descriptor)

        fn1, cfg1 = proxy.materialize()
        fn2, cfg2 = proxy.materialize()

        assert fn1 is fn2
        assert fn1.__name__ == "myjob"
        assert cfg1 is None and cfg2 is None
        assert _import_count(marker) == 1
        assert proxy.__wrapped__ is fn1
        # Docstring refreshed from the real function
        assert proxy.__doc__ == "A lazy test job."

    def test_call_forwards_to_real_function(self, tmp_path: Path) -> None:
        descriptor, marker = _write_job_module(tmp_path, "myjob")
        proxy = LazyJobFunction(descriptor)
        assert proxy(x=41) == 41
        assert _import_count(marker) == 1

    def test_materialize_detects_pydantic_config_class(self, tmp_path: Path) -> None:
        module_name = f"lazymod_{uuid.uuid4().hex[:12]}"
        source = tmp_path / f"{module_name}.py"
        source.write_text(
            "from pydantic import BaseModel\n"
            "class DeployConfig(BaseModel):\n"
            "    env: str = 'dev'\n"
            "def deploy(config: DeployConfig):\n"
            "    return config.env\n"
        )
        descriptor = JobDescriptor(
            name="deploy",
            group=None,
            module_path=module_name,
            source_file=str(source),
        )
        proxy = LazyJobFunction(descriptor)
        fn, cfg = proxy.materialize()
        assert cfg is not None and cfg.__name__ == "DeployConfig"

    def test_materialize_thread_safe_single_import(self, tmp_path: Path) -> None:
        descriptor, marker = _write_job_module(tmp_path, "myjob")
        proxy = LazyJobFunction(descriptor)
        results: list = []
        barrier = threading.Barrier(16)

        def _hit() -> None:
            barrier.wait()
            results.append(proxy.materialize()[0])

        threads = [threading.Thread(target=_hit) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 16
        assert all(fn is results[0] for fn in results)
        assert _import_count(marker) == 1

    def test_materialize_failure_raises_with_cause(self, tmp_path: Path) -> None:
        descriptor = JobDescriptor(
            name="ghost",
            group=None,
            module_path="lazymod_does_not_exist_anywhere",
            source_file=str(tmp_path / "missing.py"),
        )
        proxy = LazyJobFunction(descriptor)
        with pytest.raises(JobMaterializationError) as excinfo:
            proxy.materialize()
        assert excinfo.value.job_name == "ghost"
        assert excinfo.value.__cause__ is not None

    def test_materialize_uses_attached_descriptor_function(self) -> None:
        def live_fn(x: int = 1):
            return x

        descriptor = JobDescriptor(
            name="live",
            group=None,
            function=live_fn,
            module_path="not_importable_module",
        )
        proxy = LazyJobFunction(descriptor)
        fn, _ = proxy.materialize()
        assert fn is live_fn


# ---------------------------------------------------------------------------
# Engine materialization
# ---------------------------------------------------------------------------


class TestEngineMaterialization:
    def test_get_job_materializes_and_swaps_engine_and_host(
        self, tmp_path: Path
    ) -> None:
        descriptor, marker = _write_job_module(tmp_path, "myjob")
        host = _RecordingHost()
        engine = _make_engine(host=host)
        entry = _lazy_entry(descriptor)
        engine.register_job(entry)
        host.jobs[entry.name] = entry

        assert _import_count(marker) == 0
        resolved = engine.get_job("myjob")

        assert _import_count(marker) == 1
        assert not isinstance(resolved.function, LazyJobFunction)
        assert resolved.function.__name__ == "myjob"
        # Both the engine and the host converge on the SAME new entry
        assert engine._registered_jobs["myjob"] is resolved
        assert host.jobs["myjob"] is resolved

    def test_materialize_job_public_api(self, tmp_path: Path) -> None:
        descriptor, _ = _write_job_module(tmp_path, "myjob")
        engine = _make_engine()
        engine.register_job(_lazy_entry(descriptor))
        resolved = engine.materialize_job("myjob")
        assert callable(resolved.function)
        assert not isinstance(resolved.function, LazyJobFunction)

    def test_explicit_config_class_not_clobbered(self, tmp_path: Path) -> None:
        from pydantic import BaseModel

        class ExplicitConfig(BaseModel):
            env: str = "dev"

        descriptor, _ = _write_job_module(tmp_path, "myjob")
        engine = _make_engine()
        entry = RegisteredJob(
            name=descriptor.name,
            function=LazyJobFunction(descriptor),
            config_class=ExplicitConfig,
            group=None,
            module_path=descriptor.module_path,
        )
        engine.register_job(entry)
        resolved = engine.get_job("myjob")
        assert resolved.config_class is ExplicitConfig

    def test_execute_materializes_registered_proxy(self, tmp_path: Path) -> None:
        descriptor, marker = _write_job_module(tmp_path, "myjob")
        engine = _make_engine()
        entry = _lazy_entry(descriptor)
        engine.register_job(entry)

        result = run_job(engine, "myjob", entry.function, kwargs={"x": 7})

        assert result.return_value == 7
        assert _import_count(marker) == 1
        assert not isinstance(
            engine._registered_jobs["myjob"].function, LazyJobFunction
        )

    def test_validate_di_bindings_skips_lazy_entries(self, tmp_path: Path) -> None:
        descriptor = JobDescriptor(
            name="ghost",
            group=None,
            module_path="lazymod_never_importable",
            source_file=str(tmp_path / "ghost.py"),
        )
        engine = _make_engine()
        engine.register_job(_lazy_entry(descriptor))
        # Must neither raise nor attempt the import
        engine.validate_di_bindings()

    def test_materialization_error_propagates_from_get_job(
        self, tmp_path: Path
    ) -> None:
        descriptor = JobDescriptor(
            name="ghost",
            group=None,
            module_path="lazymod_never_importable",
            source_file=str(tmp_path / "ghost.py"),
        )
        engine = _make_engine()
        engine.register_job(_lazy_entry(descriptor))
        with pytest.raises(JobMaterializationError):
            engine.get_job("ghost")


# ---------------------------------------------------------------------------
# Warm-cache parallel materialization (same-module sys.path race)
# ---------------------------------------------------------------------------


def _wait_for_file(path: Path, timeout: float = 10.0) -> None:
    """Block until ``path`` exists, on a deadline."""
    import time

    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {path}")
        time.sleep(0.005)


def _write_paced_two_job_module(
    tmp_path: Path,
    *,
    started: Path | None = None,
    release: Path | None = None,
    body_sleep: float = 0.0,
    names: tuple[str, str] = ("alpha", "beta"),
) -> tuple[list[JobDescriptor], str]:
    """A module with two jobs whose body can be paced mid-import.

    The body writes ``started`` (if given), optionally sleeps, then blocks
    until ``release`` exists (if given), and only then binds both job
    functions — so a concurrent importer that reads the module before the
    release file appears sees a half-initialized module with neither job
    bound. That is exactly what a second warm-cache proxy does today when
    the first proxy's import is still in flight.
    """
    module_name = f"lazymod_{uuid.uuid4().hex[:12]}"
    source = tmp_path / f"{module_name}.py"
    lines = ["import time", "from pathlib import Path"]
    if started is not None:
        lines.append(f"Path({str(started)!r}).touch()")
    if body_sleep:
        lines.append(f"time.sleep({body_sleep!r})")
    if release is not None:
        lines.append(
            f"while not Path({str(release)!r}).exists():\n    time.sleep(0.005)"
        )
    for name in names:
        lines.append(f"def {name}(x: int = 1):")
        lines.append("    return x")
    source.write_text("\n".join(lines) + "\n")

    descriptors = [
        JobDescriptor(
            name=name,
            group=None,
            module_path=module_name,
            source_file=str(source),
        )
        for name in names
    ]
    return descriptors, module_name


class TestWarmParallelMaterialization:
    """Two same-module jobs, warm cache, concurrent first materialization.

    Warm boot registers one LazyJobFunction proxy per job
    (``register_descriptors``, function=None), so two jobs of one module
    are two proxies with two per-instance locks. A parallel batch hits
    both at once; the shared ``sys.path`` region must not let one proxy
    read the module while the other's import is still in flight.
    """

    def test_same_module_concurrent_first_materialization_both_succeed(
        self, tmp_path: Path
    ) -> None:
        started = tmp_path / "started.marker"
        release = tmp_path / "release.marker"
        descriptors, _ = _write_paced_two_job_module(
            tmp_path, started=started, release=release
        )
        engine = _make_engine()
        for descriptor in descriptors:
            engine.register_job(_lazy_entry(descriptor))
        path_before = list(sys.path)

        outcomes: dict[str, BaseException | None] = {}

        def _materialize(name: str) -> None:
            try:
                engine.get_job(name)
                outcomes[name] = None
            except BaseException as exc:  # noqa: BLE001 - recorded, asserted below
                outcomes[name] = exc

        thread_a = threading.Thread(target=_materialize, args=("alpha",))
        thread_a.start()
        # Thread A is now provably mid-import: its module body has run far
        # enough to touch the marker and is blocked before either job is
        # bound, with the directory still inserted by A.
        _wait_for_file(started)

        thread_b = threading.Thread(target=_materialize, args=("beta",))
        thread_b.start()
        thread_b.join(timeout=2.0)
        # Pre-fix, B has already failed on the half-initialized module by
        # now (nothing blocks it). Post-fix, B is waiting at the region
        # for A to finish — either way, releasing A lets both complete.
        release.touch()
        thread_a.join(timeout=10.0)
        thread_b.join(timeout=10.0)

        assert outcomes["alpha"] is None, repr(outcomes["alpha"])
        assert outcomes["beta"] is None, repr(outcomes["beta"])
        assert sys.path == path_before

    def test_parallel_batches_same_module_never_fail_materialization(
        self, tmp_path: Path
    ) -> None:
        from functualize._engine.capabilities.invoke import WiredInvoke

        engine = _make_engine()
        path_before = list(sys.path)

        for _ in range(30):
            descriptors, _ = _write_paced_two_job_module(tmp_path, body_sleep=0.005)
            for descriptor in descriptors:
                engine.register_job(_lazy_entry(descriptor))
            invoke = WiredInvoke(
                execution_engine=engine,
                run_context=MagicMock(),
                invoke_depth=0,
                max_invoke_depth=10,
            )
            results = invoke.parallel([("alpha", {}), ("beta", {})])
            for result in results:
                # A spurious JobMaterializationError from the race lands
                # here; repr names it in the failure output.
                assert result.exception is None, repr(result.exception)

        assert sys.path == path_before

    def test_warm_single_and_repeat_and_different_module_batches(
        self, tmp_path: Path
    ) -> None:
        from functualize._engine.capabilities.invoke import WiredInvoke

        engine = _make_engine()
        invoke = WiredInvoke(
            execution_engine=engine,
            run_context=MagicMock(),
            invoke_depth=0,
            max_invoke_depth=10,
        )

        # Same module, warm: single-job batches, then a repeat batch.
        descriptors, _ = _write_paced_two_job_module(tmp_path)
        for descriptor in descriptors:
            engine.register_job(_lazy_entry(descriptor))
        for name in ("alpha", "beta"):
            result = invoke.parallel([(name, {"x": 41})])
            assert result[0].exception is None, repr(result[0].exception)
            assert result[0].return_value == 41
        repeat = invoke.parallel([("alpha", {}), ("beta", {})])
        assert all(r.exception is None for r in repeat)

        # A second module in another directory, its own job names: one
        # batch mixing both modules behaves exactly as today.
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        other_descriptors, _ = _write_paced_two_job_module(
            other_dir, names=("gamma", "delta")
        )
        for descriptor in other_descriptors:
            engine.register_job(_lazy_entry(descriptor))
        mixed = invoke.parallel([("alpha", {}), ("gamma", {})])
        assert all(r.exception is None for r in mixed)

    def test_sys_path_restored_on_success_and_failure(self, tmp_path: Path) -> None:
        # Success path.
        descriptors, _ = _write_paced_two_job_module(tmp_path)
        path_before = list(sys.path)
        engine = _make_engine()
        engine.register_job(_lazy_entry(descriptors[0]))
        engine.get_job("alpha")
        assert sys.path == path_before

        # Import-time exception in the module body.
        module_name = f"lazymod_{uuid.uuid4().hex[:12]}"
        source = tmp_path / f"{module_name}.py"
        source.write_text("raise RuntimeError('boom during import')\n")
        broken = JobDescriptor(
            name="broken",
            group=None,
            module_path=module_name,
            source_file=str(source),
        )
        engine.register_job(_lazy_entry(broken))
        with pytest.raises(JobMaterializationError):
            engine.get_job("broken")
        assert sys.path == path_before

        # Missing module.
        missing = JobDescriptor(
            name="ghost",
            group=None,
            module_path=f"lazymod_{uuid.uuid4().hex[:12]}",
            source_file=str(tmp_path / "ghost.py"),
        )
        engine.register_job(_lazy_entry(missing))
        with pytest.raises(JobMaterializationError):
            engine.get_job("ghost")
        assert sys.path == path_before


# ---------------------------------------------------------------------------
# invoke-by-callable metadata fallback
# ---------------------------------------------------------------------------


class TestInvokeByCallableFallback:
    def test_unmaterialized_proxy_resolves_by_metadata(self, tmp_path: Path) -> None:
        descriptor, _ = _write_job_module(tmp_path, "myjob")
        engine = _make_engine()
        engine.register_job(_lazy_entry(descriptor))

        # Caller imports the real function themselves (identity mismatch)
        sys.path.insert(0, str(tmp_path))
        try:
            import importlib

            module = importlib.import_module(descriptor.module_path)
        finally:
            sys.path.remove(str(tmp_path))
        real_fn = module.myjob

        invoke = WiredInvoke(
            execution_engine=engine,
            run_context=MagicMock(),
            invoke_depth=0,
            max_invoke_depth=10,
        )
        assert invoke._resolve_job_name(real_fn) == "myjob"

    def test_live_entries_keep_strict_identity(self) -> None:
        engine = _make_engine()

        def job_a(x: int = 1):
            return x

        engine.register_job(
            RegisteredJob(
                name="job_a",
                function=job_a,
                config_class=None,
                group=None,
                module_path="somewhere",
            )
        )
        invoke = WiredInvoke(
            execution_engine=engine,
            run_context=MagicMock(),
            invoke_depth=0,
            max_invoke_depth=10,
        )

        def job_a_imposter(x: int = 1):  # same __qualname__? no — different
            return x

        from functualize._types.errors import JobNotFoundError

        with pytest.raises(JobNotFoundError):
            invoke._resolve_job_name(job_a_imposter)
