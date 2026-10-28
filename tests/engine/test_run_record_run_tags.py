"""The run record carries the request's run tags, and nothing else does.

`_open_run_record` writes one more key — ``"run_tags": dict(request.run_tags)``
— into the dict it already builds. The document store keeps the dict as given,
so the map a run started with is the map its record carries, and nothing ever
rewrites it.

The other half is what the key must *not* do. Tags are an observation about a
run, never an input to it: they are not in ``args_hash`` (so a tagged and an
untagged invocation share a cache entry), and they never reach the job's
``RunContext``, its kwargs, its return value or its exit code.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from tests._support.engine_run import register

from functualize import FunctualizeApp
from functualize._app.state import AppState
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize._primitives.di import DIRegistry
from functualize._primitives.run_store import RunStore
from functualize._primitives.scope_store import ScopeStore
from functualize._types.enums import RunStatus
from functualize._types.run_request import RunRequest
from functualize.job import Fingerprint, RunContext, job

THREE_TAGS = {"harness": "claude", "model": "opus", "session-id": "abc"}


@pytest.fixture(autouse=True)
def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A throwaway project with a state directory, like any real one."""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield project
    AppState.reset()


@pytest.fixture
def substrate(_project: Path) -> Any:
    return ScopeStore.for_project(_project).substrate


@pytest.fixture
def engine(_project: Path, substrate: Any) -> JobExecutionEngine:
    from functualize._primitives.document_store import DocumentRuntimeStore

    return JobExecutionEngine(
        di_registry=DIRegistry(),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
        fresh_root=_project,
        runtime_store=DocumentRuntimeStore(substrate),
        substrate=substrate,
    )


@pytest.fixture
def runs(substrate: Any) -> RunStore:
    return RunStore(substrate)


def _only_record(runs: RunStore) -> dict[str, Any]:
    run_ids = runs.run_ids()
    assert len(run_ids) == 1, f"expected exactly one run record, got {run_ids}"
    record = runs.get_run(run_ids[0])
    assert record is not None
    return record


class TestTheRecordCarriesTheMap:
    def test_three_tags_are_exactly_the_three_stored(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """AC13: the run entry carries exactly the merged map."""

        def build() -> str:
            return "built"

        register(engine, "build", build)
        engine.run(
            RunRequest(
                job_name="build",
                surface="func.job",
                run_tags=MappingProxyType(dict(THREE_TAGS)),
            )
        )

        assert _only_record(runs)["run_tags"] == THREE_TAGS

    def test_an_untagged_run_stores_an_empty_map(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """The key is written for every new run, `{}` when no tag was given."""

        def build() -> str:
            return "built"

        register(engine, "build", build)
        engine.run(RunRequest(job_name="build", surface="func.job"))

        assert _only_record(runs)["run_tags"] == {}

    def test_the_stored_map_is_a_plain_copy(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """A `MappingProxyType` is not JSON; the record holds a plain dict."""

        def build() -> str:
            return "built"

        register(engine, "build", build)
        engine.run(
            RunRequest(
                job_name="build",
                surface="func.job",
                run_tags=MappingProxyType({"harness": "claude"}),
            )
        )

        stored = _only_record(runs)["run_tags"]
        assert type(stored) is dict
        assert stored == {"harness": "claude"}

    def test_the_other_keys_are_untouched(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """Adding tags changes one key; every other key reads as untagged."""

        def build() -> str:
            return "built"

        register(engine, "build", build)
        engine.run(RunRequest(job_name="build", surface="func.job"))
        engine.run(
            RunRequest(
                job_name="build",
                surface="func.job",
                run_tags=MappingProxyType(dict(THREE_TAGS)),
            )
        )

        untagged, tagged = (runs.get_run(rid) for rid in runs.run_ids())
        assert untagged is not None and tagged is not None
        varying = {"started_at", "ended_at", "duration_ms", "scope_id", "run_tags"}
        assert {k: v for k, v in untagged.items() if k not in varying} == {
            k: v for k, v in tagged.items() if k not in varying
        }
        assert set(untagged) == set(tagged)


class TestTagsAreNotAnInput:
    def test_args_hash_ignores_tags_and_the_cache_is_shared(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC27: a tagged and an untagged invocation are one cache entry.

        Tagged first, untagged second: the second is the fresh-skip it would be
        had neither been tagged, and both records carry the same `args_hash`.
        """
        project = tmp_path / "cached"
        (project / ".functualize").mkdir(parents=True)
        (project / "data.txt").write_text("input\n")
        monkeypatch.chdir(project)
        bodies: list[int] = []

        @job(cache=Fingerprint(sources=["data.txt"]))
        def build(n: int = 1) -> str:
            bodies.append(n)
            return "built"

        app = FunctualizeApp(name="cached")
        app.register_dynamic_job("build", build)
        first = app.execute(
            RunRequest(
                job_name="build",
                surface="func.job",
                run_tags=MappingProxyType({"x": "1"}),
            )
        )
        second = app.execute(RunRequest(job_name="build", surface="func.job"))

        assert first.status is RunStatus.SUCCESS
        assert second.status is RunStatus.SKIPPED, "the untagged run should be fresh"
        assert bodies == [1], "the body must run once across the two invocations"

        store = RunStore(app.execution_engine._state_store().substrate)
        records = [store.get_run(rid) for rid in store.run_ids()]
        assert [r["run_tags"] for r in records if r] == [{"x": "1"}, {}]
        hashes = {r["args_hash"] for r in records if r}
        assert len(hashes) == 1, f"tags leaked into args_hash: {hashes}"

    def test_no_tag_reaches_the_job(
        self, engine: JobExecutionEngine, runs: RunStore
    ) -> None:
        """AC28: not the kwargs, not `RunContext`, not the return value."""
        seen: dict[str, Any] = {}

        def build(rc: RunContext, n: int = 7) -> str:
            seen["n"] = n
            seen["public"] = [name for name in dir(rc) if not name.startswith("_")]
            return "built"

        register(engine, "build", build)
        result = engine.run(
            RunRequest(
                job_name="build",
                surface="func.job",
                run_tags=MappingProxyType(dict(THREE_TAGS)),
            )
        )

        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "built"
        assert seen["n"] == 7
        assert not [name for name in seen["public"] if "tag" in name], seen["public"]
        assert "run_tags" not in (result.metadata or {})
        assert _only_record(runs)["run_tags"] == THREE_TAGS


def test_a_failing_store_still_does_not_fail_the_run(
    engine: JobExecutionEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `except Exception` swallow around `open_run` keeps its rule."""
    import functualize._primitives.run_store as run_store

    def _explode(*_a: Any, **_kw: Any) -> Any:
        raise OSError("disk on fire")

    monkeypatch.setattr(run_store.RunStore, "open_run", _explode)

    def build() -> str:
        return "built"

    register(engine, "build", build)
    result = engine.run(
        RunRequest(
            job_name="build",
            surface="func.job",
            run_tags=MappingProxyType(dict(THREE_TAGS)),
        )
    )

    assert result.status is RunStatus.SUCCESS
    assert result.return_value == "built"
