"""Unit tests for LazyJobFunction and engine materialize-on-demand.

Covers Phase 1 of the true-lazy registration refactor:
1. LazyJobFunction construction performs NO module import
2. materialize() is idempotent and thread-safe (single import)
3. Import failure raises JobMaterializationError chaining the cause
4. Engine _ensure_materialized swaps the frozen entry in the engine
   registry AND registered mirrors; explicit config_class is preserved
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> JobExecutionEngine:
    return JobExecutionEngine(
        di_registry=MagicMock(spec=DIRegistry),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
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
    def test_get_job_materializes_and_swaps_engine_and_mirror(
        self, tmp_path: Path
    ) -> None:
        descriptor, marker = _write_job_module(tmp_path, "myjob")
        engine = _make_engine()
        entry = _lazy_entry(descriptor)
        engine.register_job(entry)
        mirror: dict[str, RegisteredJob] = {entry.name: entry}
        engine.add_registry_mirror(mirror)

        assert _import_count(marker) == 0
        resolved = engine.get_job("myjob")

        assert _import_count(marker) == 1
        assert not isinstance(resolved.function, LazyJobFunction)
        assert resolved.function.__name__ == "myjob"
        # Both dicts converge on the SAME new entry
        assert engine._registered_jobs["myjob"] is resolved
        assert mirror["myjob"] is resolved

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

        result = engine.execute("myjob", entry.function, kwargs={"x": 7})

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
