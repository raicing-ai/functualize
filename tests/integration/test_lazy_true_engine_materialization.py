"""App-level guardrails for true-lazy job registration (Phase 2).

Unlike tests/discovery/test_warm_boot_zero_imports_property.py (provider
layer only), these tests boot a real FunctualizeApp and prove:

(a) Warm boot imports ZERO job modules at the APP level — the eager
    import formerly hidden in register_descriptors is gone — and
    invoking one job imports exactly that one module, swapping the
    entry consistently in the engine AND the JobRegistry.
(b) rc.invoke() of a warm-cached job with a Pydantic config parameter
    gets its config injected (regression for the config_class=None bug).
(c) invoke-by-callable resolves against an unmaterialized proxy.
(e) DI validation for warm-cached jobs is deferred to first invocation;
    eager boots (cold / lazy=False) still validate at boot.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from functualize._discovery.lazy_wrapper import LazyJobFunction
from functualize._primitives.di import DIValidationError
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODULE_PREFIX = "lazyapp"


def _write_marker_job(jobs_dir: Path, stem: str, func_name: str) -> Path:
    """Create a job module that logs a line to <stem>.imports.log on import."""
    marker = jobs_dir / f"{stem}.imports.log"
    source = jobs_dir / f"{stem}.py"
    source.write_text(
        f"from pathlib import Path\n"
        f"Path({str(marker)!r}).open('a').write('imported\\n')\n"
        f"def {func_name}(x: int = 1):\n"
        f'    """Marker job."""\n'
        f"    return x\n",
        encoding="utf-8",
    )
    return marker


def _imports(marker: Path) -> int:
    return len(marker.read_text().splitlines()) if marker.exists() else 0


def _purge_job_modules() -> None:
    """Drop job modules from sys.modules to simulate a fresh process."""
    for name in [m for m in sys.modules if m.startswith(_MODULE_PREFIX)]:
        del sys.modules[name]


def _boot(jobs_dir: Path, *, lazy: bool = True) -> FunctualizeApp:
    return FunctualizeApp(
        name="lazytest",
        job_sources=JobSources(directories=[str(jobs_dir)], lazy=lazy),
    )


# ---------------------------------------------------------------------------
# (a) Warm boot: zero imports at app level; single import on invocation
# ---------------------------------------------------------------------------


class TestWarmBootZeroImportsAppLevel:
    def test_warm_boot_imports_nothing_and_invocation_imports_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        markers = {
            name: _write_marker_job(jobs_dir, f"{_MODULE_PREFIX}_{name}", name)
            for name in ("job_a", "job_b", "job_c")
        }

        # Cold boot: builds the cache; every module imported once
        app_cold = _boot(jobs_dir)
        assert {j.name for j in app_cold.get_jobs()} >= {"job-a", "job-b", "job-c"}
        cold_counts = {n: _imports(m) for n, m in markers.items()}
        assert all(c >= 1 for c in cold_counts.values())

        # Fresh "process": purge job modules, boot again on the warm cache
        _purge_job_modules()
        app_warm = _boot(jobs_dir)
        assert {j.name for j in app_warm.get_jobs()} >= {"job-a", "job-b", "job-c"}

        # ZERO new imports at warm boot — this is the core guarantee
        warm_counts = {n: _imports(m) for n, m in markers.items()}
        assert warm_counts == cold_counts, (
            f"Warm boot must not import job modules: {warm_counts} vs {cold_counts}"
        )
        # Entries are unmaterialized proxies
        entry_b = app_warm.job_registry._registered_jobs["job-b"]
        assert isinstance(entry_b.function, LazyJobFunction)

        # Invoking ONE job imports exactly that one module
        result = app_warm.execute("job-b", x=5)
        assert result.return_value == 5
        after = {n: _imports(m) for n, m in markers.items()}
        assert after["job_b"] == cold_counts["job_b"] + 1
        assert after["job_a"] == cold_counts["job_a"]
        assert after["job_c"] == cold_counts["job_c"]

        # Engine and JobRegistry converge on the SAME materialized entry
        engine_entry = app_warm._execution_engine._registered_jobs["job-b"]
        registry_entry = app_warm.job_registry._registered_jobs["job-b"]
        assert engine_entry is registry_entry
        assert not isinstance(engine_entry.function, LazyJobFunction)
        assert engine_entry.function.__name__ == "job_b"


# ---------------------------------------------------------------------------
# (b) rc.invoke + Pydantic config on the warm path (config_class bug fix)
# ---------------------------------------------------------------------------


class TestInvokeConfigInjectionWarmPath:
    def test_invoked_child_with_pydantic_config_gets_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / f"{_MODULE_PREFIX}_child.py").write_text(
            "from pydantic import BaseModel\n"
            "class ChildConfig(BaseModel):\n"
            "    env: str = 'dev'\n"
            "def child_job(config: ChildConfig):\n"
            '    """Child with config."""\n'
            "    return config.env\n",
            encoding="utf-8",
        )
        (jobs_dir / f"{_MODULE_PREFIX}_parent.py").write_text(
            "from functualize import RunContext\n"
            "def parent_job(rc: RunContext):\n"
            '    """Parent invoking child."""\n'
            "    return rc.invoke('child_job').return_value\n",
            encoding="utf-8",
        )

        # Cold boot builds cache; purge to get the warm/proxy path
        _boot(jobs_dir)
        _purge_job_modules()
        app = _boot(jobs_dir)

        assert isinstance(
            app.job_registry._registered_jobs["child-job"].function,
            LazyJobFunction,
        )

        result = app.execute("parent_job")
        assert result.exception is None, f"parent failed: {result.exception!r}"
        # Config model was detected at materialization and injected
        assert result.return_value == "dev"
        # Materialized child entry carries the detected config_class
        child_entry = app._execution_engine._registered_jobs["child-job"]
        assert child_entry.config_class is not None
        assert child_entry.config_class.__name__ == "ChildConfig"


# ---------------------------------------------------------------------------
# (c) invoke-by-callable against an unmaterialized proxy (app level)
# ---------------------------------------------------------------------------


class TestInvokeByCallableAppLevel:
    def test_callable_reference_resolves_via_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        (jobs_dir / f"{_MODULE_PREFIX}_target.py").write_text(
            'def target_job(x: int = 1):\n    """Target."""\n    return x * 2\n',
            encoding="utf-8",
        )
        (jobs_dir / f"{_MODULE_PREFIX}_caller.py").write_text(
            f"from functualize import RunContext\n"
            f"from {_MODULE_PREFIX}_target import target_job\n"
            f"def caller_job(rc: RunContext):\n"
            f'    """Invokes by callable ref."""\n'
            f"    return rc.invoke(target_job, x=4).return_value\n",
            encoding="utf-8",
        )

        _boot(jobs_dir)
        _purge_job_modules()
        app = _boot(jobs_dir)

        result = app.execute("caller_job")
        assert result.exception is None, f"caller failed: {result.exception!r}"
        assert result.return_value == 8


# ---------------------------------------------------------------------------
# (e) Deferred DI validation semantics + lazy=False escape hatch
# ---------------------------------------------------------------------------


class TestDeferredDiValidation:
    def _write_bad_di_job(self, jobs_dir: Path) -> None:
        (jobs_dir / f"{_MODULE_PREFIX}_baddi.py").write_text(
            "class UnprovidedService:\n"
            "    pass\n"
            "def needs_service(svc: UnprovidedService):\n"
            '    """Job with unsatisfiable DI binding."""\n'
            "    return svc\n",
            encoding="utf-8",
        )

    def test_cold_boot_still_validates_at_boot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        self._write_bad_di_job(jobs_dir)

        # Cold boot registers live functions → boot-time validation fires
        with pytest.raises(DIValidationError):
            _boot(jobs_dir)

    def test_warm_boot_defers_validation_to_first_invocation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        self._write_bad_di_job(jobs_dir)

        # Cold boot fails at validation, but the cache was persisted first
        with pytest.raises(DIValidationError):
            _boot(jobs_dir)

        _purge_job_modules()
        # Warm boot succeeds: lazy entry, validation deferred
        app = _boot(jobs_dir)
        assert "needs-service" in app._execution_engine._registered_jobs

        # First use surfaces the deferred DI error
        with pytest.raises(DIValidationError):
            app._execution_engine.materialize_job("needs-service")

    def test_lazy_false_escape_hatch_validates_at_boot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        jobs_dir = tmp_path / "jobs"
        jobs_dir.mkdir()
        self._write_bad_di_job(jobs_dir)

        with pytest.raises(DIValidationError):
            _boot(jobs_dir, lazy=False)
