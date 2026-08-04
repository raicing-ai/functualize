"""Guardrail tests: child projects under lazy boot via the single pipeline path.

After the child-discovery consolidation, child projects are wired only through
``wire_children_to_pipeline`` (no second ``mount_children`` pass, no
``ChildProjectComposer``). Under lazy boot their jobs must register as
materialize-on-demand ``LazyJobFunction`` proxies — imported only at dispatch —
exactly like parent jobs, with no double-registration, and be recorded on
``app.child_projects`` for diagnostics/provenance.
"""

from __future__ import annotations

from pathlib import Path

from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp


def _create_job_module(directory: Path, name: str) -> None:
    (directory / f"{name}.py").write_text(
        f'def {name}():\n    """{name.title()} job."""\n    return "{name}"\n',
        encoding="utf-8",
    )


def _make_child(root: Path, ns_dir: str, *jobs: str) -> Path:
    child_dir = root / ns_dir
    (child_dir / "jobs").mkdir(parents=True)
    for j in jobs:
        _create_job_module(child_dir / "jobs", j)
    return child_dir


def test_child_jobs_register_namespaced_exactly_once(tmp_path: Path) -> None:
    child_dir = _make_child(tmp_path, "child_project", "task_a", "task_b")

    app = FunctualizeApp(
        name="parent",
        job_sources=JobSources(children={"myns": str(child_dir)}, lazy=True),
    )

    registry = app.job_registry._registered_jobs
    names = list(registry.keys())

    # Namespaced and registered exactly once each — the consolidation removed
    # the second (mount_children) pass, so no double-registration.
    assert "myns.task-a" in registry
    assert "myns.task-b" in registry
    assert names.count("myns.task-a") == 1
    assert names.count("myns.task-b") == 1


def test_child_uses_cache_first_provider_under_lazy_boot(tmp_path: Path) -> None:
    """Child dirs are wired through the cache-first provider when lazy."""
    from functualize._discovery.cached_provider import CachedDirectoryScanProvider

    child_dir = _make_child(tmp_path, "child_project", "task_a")

    app = FunctualizeApp(
        name="parent",
        job_sources=JobSources(children={"myns": str(child_dir)}, lazy=True),
    )

    providers = [entry.provider for entry in app._resolution_pipeline._providers]
    assert any(isinstance(p, CachedDirectoryScanProvider) for p in providers), (
        "child project should be wired via CachedDirectoryScanProvider under lazy boot"
    )


def test_child_uses_eager_provider_when_lazy_disabled(tmp_path: Path) -> None:
    from functualize._discovery.providers import DirectoryScanProvider

    child_dir = _make_child(tmp_path, "child_project", "task_a")

    app = FunctualizeApp(
        name="parent",
        job_sources=JobSources(children={"myns": str(child_dir)}, lazy=False),
    )

    providers = [entry.provider for entry in app._resolution_pipeline._providers]
    assert any(isinstance(p, DirectoryScanProvider) for p in providers)


def test_child_projects_recorded_for_diagnostics(tmp_path: Path) -> None:
    child_dir = _make_child(tmp_path, "svc", "deploy")

    app = FunctualizeApp(
        name="parent",
        job_sources=JobSources(children={"svc": str(child_dir)}, lazy=True),
    )

    recorded = {c.name: c for c in app.child_projects}
    assert "svc" in recorded
    assert recorded["svc"].path == str(child_dir)


def test_child_dispatch_materializes_the_job(tmp_path: Path) -> None:
    child_dir = _make_child(tmp_path, "svc", "deploy")

    app = FunctualizeApp(
        name="parent",
        job_sources=JobSources(children={"svc": str(child_dir)}, lazy=True),
    )

    # Invoking the namespaced child job materializes + runs the real function.
    result = app.execute("svc.deploy")
    assert result.status.name in {"SUCCESS", "COMPLETED"}


def test_missing_child_path_skipped_without_crashing(tmp_path: Path) -> None:
    # A non-existent child path is skipped (warning) — boot still succeeds.
    app = FunctualizeApp(
        name="parent",
        job_sources=JobSources(
            children={"ghost": str(tmp_path / "does_not_exist")}, lazy=True
        ),
    )
    assert all(not n.startswith("ghost.") for n in app.job_registry._registered_jobs)
    assert app.child_projects == []
