"""Tests for the public API long-lived consumers (TUI, MCP) depend on.

Covers ``refresh()``, ``resolution_chain()``, and ``extension_state`` — the
surface that exists so persistent processes stop reaching into kernel
privates. The refresh tests are the load-bearing ones: they write to disk
after boot and assert the app observes the change, which is the whole reason
the method exists.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize.app.config import ConfigSources, JobSources
from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


def _write_job(jobs_dir: Path, module: str, job_name: str) -> None:
    """Write a discoverable job module with a single job function."""
    (jobs_dir / f"{module}.py").write_text(
        f"def {job_name}() -> str:\n"
        f'    """Job {job_name}."""\n'
        f'    return "{job_name}"\n'
    )


@pytest.fixture
def jobs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "jobs"
    directory.mkdir()
    return directory


class TestExtensionState:
    """The sanctioned slot replacing monkey-patched private attributes."""

    def test_starts_empty_and_is_mutable(self) -> None:
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))

        assert app.extension_state == {}

        app.extension_state["mcp"] = {"checkpoints": {}}
        assert app.extension_state["mcp"] == {"checkpoints": {}}

    def test_same_dict_across_accesses(self) -> None:
        """Consumers must be able to stash state and find it again."""
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))

        app.extension_state.setdefault("orchestrator", {})["surface"] = "panel"

        assert app.extension_state["orchestrator"]["surface"] == "panel"

    def test_isolated_between_apps(self) -> None:
        """State must not leak via a shared class-level default."""
        first = FunctualizeApp(name="first", job_sources=JobSources(directories=[]))
        second = FunctualizeApp(name="second", job_sources=JobSources(directories=[]))

        first.extension_state["mcp"] = {"a": 1}

        assert second.extension_state == {}


class TestResolutionChain:
    """Public provenance accessor — replaces `app._resolution_chain` reach-ins."""

    def test_returns_the_active_chain(self) -> None:
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))

        assert app.resolution_chain() is app._resolution_chain

    def test_chain_has_sources(self) -> None:
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))

        assert app.resolution_chain().sources


class TestRefreshDiscovery:
    """refresh() must make a job added after boot visible."""

    def test_job_added_after_boot_is_discovered(self, jobs_dir: Path) -> None:
        _write_job(jobs_dir, "first", "alpha")
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        assert {j.name for j in app.get_jobs()} == {"alpha"}

        _write_job(jobs_dir, "second", "beta")
        # Without refresh the memo still answers with the boot-time view.
        assert {j.name for j in app.get_jobs()} == {"alpha"}

        app.refresh()

        assert {j.name for j in app.get_jobs()} == {"alpha", "beta"}

    def test_job_removed_after_boot_disappears(self, jobs_dir: Path) -> None:
        _write_job(jobs_dir, "first", "alpha")
        _write_job(jobs_dir, "second", "beta")
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )
        assert {j.name for j in app.get_jobs()} == {"alpha", "beta"}

        (jobs_dir / "second.py").unlink()
        app.refresh()

        assert {j.name for j in app.get_jobs()} == {"alpha"}

    def test_refresh_is_idempotent(self, jobs_dir: Path) -> None:
        _write_job(jobs_dir, "first", "alpha")
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        app.refresh()
        app.refresh()

        assert {j.name for j in app.get_jobs()} == {"alpha"}

    def test_no_duplicate_descriptors_after_refresh(self, jobs_dir: Path) -> None:
        """Registration appends descriptors — refresh must retire the old
        generation, not stack a second copy on top of it."""
        _write_job(jobs_dir, "first", "alpha")
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        app.refresh()

        names = [j.name for j in app.get_jobs()]
        assert names.count("alpha") == 1

    def test_dynamic_job_survives_refresh(self, jobs_dir: Path) -> None:
        """A job registered from code is not something re-reading the disk
        can rediscover — refresh must leave it alone."""
        _write_job(jobs_dir, "first", "alpha")
        app = FunctualizeApp(
            name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
        )

        def dynamic_job() -> str:
            """A programmatically registered job."""
            return "dynamic"

        app.register_dynamic_job("dynamic_job", dynamic_job)
        assert {j.name for j in app.get_jobs()} == {"alpha", "dynamic-job"}

        app.refresh()

        assert {j.name for j in app.get_jobs()} == {"alpha", "dynamic-job"}
        # And it must still be executable, not just listed.
        assert app.job_registry.get_job("dynamic_job").function is dynamic_job


class TestRefreshConfig:
    """refresh() must rebuild config resolution — and respect an explicit chain."""

    def test_rebuilds_the_resolution_chain(self) -> None:
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))
        before = app.resolution_chain()

        app.refresh()

        assert app.resolution_chain() is not before
        assert app.resolution_chain().sources

    def test_propagates_new_chain_to_execution_engine(self) -> None:
        app = FunctualizeApp(name="testapp", job_sources=JobSources(directories=[]))

        app.refresh()

        assert app._execution_engine._resolution_chain is app.resolution_chain()

    def test_explicit_chain_is_left_alone(self) -> None:
        """A caller-supplied chain is theirs to manage — refresh must not
        discard it (env_only()/twelve_factor() presets rely on this)."""
        from functualize.app.presets import env_only

        sources = env_only()
        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[]),
            config_sources=sources,
        )
        before = app.resolution_chain()

        app.refresh()

        assert app.resolution_chain() is before

    def test_rebuilt_chain_excludes_inactive_environment_files(
        self, tmp_path: Path
    ) -> None:
        """A rebuilt chain must still band files by environment.

        `_build_resolution_chain` has to pass `environment` exactly like the
        boot path does. Omitting it makes `roles.classify()` return BASE
        ("always merged") for *every* slot, so a non-active environment's
        file leaks into the merged view — under environment=DEV, prod's keys
        would appear and prod's values would fight base's on discovery order.
        """
        (tmp_path / "config.base.toml").write_text(
            '[testapp]\nregion = "base-region"\ncommon = "from-base"\n'
        )
        (tmp_path / "config.dev.toml").write_text('[testapp]\nregion = "dev-region"\n')
        (tmp_path / "config.prod.toml").write_text(
            '[testapp]\nregion = "prod-region"\nprod_only = "from-prod"\n'
        )

        app = FunctualizeApp(
            name="testapp",
            job_sources=JobSources(directories=[]),
            config_sources=ConfigSources(dotenv=False),
        )
        assert app.active_environment().casefold() == "dev"
        app._config_path = str(tmp_path)
        app.refresh()

        merged = app.resolution_chain().resolve_section("testapp")

        # base is common to every environment — its keys survive.
        assert merged["common"].value == "from-base"
        # The active environment's overlay wins conflicts with base.
        assert merged["region"].value == "dev-region"
        # The inactive environment's file is never merged.
        assert "prod_only" not in merged, (
            "prod's config leaked into a DEV run — environment banding was "
            "lost when the chain was rebuilt"
        )
