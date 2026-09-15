"""The run log is readable — through the projection, the CLI and MCP.

`durable-run-layer`/T3. `runs.json` has been written since T2 and read by
nothing: every run's origin, parentage and outcome was recorded and there was
no way to ask about it.

Every assertion here goes through a **real run**, never a hand-built record.
A projection tested against fixtures it also shaped proves only that the
fixture matches itself; what matters is that the fields the engine actually
writes are the fields this reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from functualize import FunctualizeApp, RunContext
from functualize._engine.capabilities.state import State  # noqa: TC001
from functualize._primitives.run_store import RunStore
from functualize._types.run_request import RunRequest
from functualize.app.utils import (
    RUN_STATES,
    describe_run,
    list_runs,
    run_events,
    run_tree,
)


def _store() -> RunStore:
    return RunStore.for_project(Path.cwd())


@pytest.fixture
def app() -> FunctualizeApp:
    """An app whose jobs exercise every field the projection reports."""
    application = FunctualizeApp(name="run-view")

    def child(rc: RunContext, state: State) -> str:
        state.set("child", 1)
        return "child-ok"

    def parent(rc: RunContext, state: State) -> str:
        state.set("parent", 1)
        rc.invoke("child")
        return "parent-ok"

    def boom(rc: RunContext) -> str:
        raise RuntimeError("nope")

    application.register_dynamic_job("child", child)
    application.register_dynamic_job("parent", parent)
    application.register_dynamic_job("boom", boom)
    return application


def _run(app: FunctualizeApp, job: str, surface: str = "app.execute") -> Any:
    return app.execute(RunRequest(job_name=job, surface=surface))


class TestTheProjectionReportsWhatTheEngineWrote:
    def test_a_successful_run_is_listed(self, app: FunctualizeApp) -> None:
        _run(app, "child")
        rows = list_runs(_store())
        assert len(rows) == 1
        row = rows[0]
        assert row["job"] == "child"
        assert row["state"] == "success"
        assert row["surface"] == "app.execute"
        assert row["duration_ms"] is not None

    def test_a_failing_run_reports_failure(self, app: FunctualizeApp) -> None:
        _run(app, "boom")
        assert list_runs(_store())[0]["state"] == "failure"

    def test_newest_first(self, app: FunctualizeApp) -> None:
        """The opposite order from `list_scopes`, and the reason is the question.

        A scope list answers "what is waiting on me", where order is
        incidental. A run list answers "what just happened", where it is the
        whole question.
        """
        _run(app, "child")
        _run(app, "boom")
        assert [r["job"] for r in list_runs(_store())][:2] == ["boom", "child"]

    def test_a_missing_run_is_none_not_an_error(self, app: FunctualizeApp) -> None:
        """So a caller renders its own not-found with its own exit code."""
        assert describe_run(_store(), "run-does-not-exist") is None
        assert run_events(_store(), "run-does-not-exist") is None
        assert run_tree(_store(), "run-does-not-exist") is None


class TestFilters:
    def test_by_job(self, app: FunctualizeApp) -> None:
        _run(app, "child")
        _run(app, "boom")
        assert [r["job"] for r in list_runs(_store(), job="boom")] == ["boom"]

    def test_by_surface(self, app: FunctualizeApp) -> None:
        """Origin is *carried* by the request, not reconstructed.

        That is what makes it answerable at all — the same job through two
        doors is two rows that differ only here.
        """
        _run(app, "child", surface="app.execute")
        _run(app, "child", surface="app.cli")
        rows = list_runs(_store(), surface="app.cli")
        assert len(rows) == 1
        assert rows[0]["surface"] == "app.cli"

    def test_by_state(self, app: FunctualizeApp) -> None:
        _run(app, "child")
        _run(app, "boom")
        assert [r["job"] for r in list_runs(_store(), state="failure")] == ["boom"]

    def test_by_scope(self, app: FunctualizeApp) -> None:
        """The join between the two projections.

        A workflow that blocked and resumed three times is one scope and four
        runs; this is how the four are found.
        """
        _run(app, "parent")
        rows = list_runs(_store())
        scope_id = rows[0]["scope_id"]
        assert scope_id
        in_scope = list_runs(_store(), scope_id=scope_id)
        assert {r["job"] for r in in_scope} == {"parent", "child"}, (
            "a parent and the child it invoked ran in one scope and must be "
            "findable by it"
        )

    def test_limit_applies_after_filtering(self, app: FunctualizeApp) -> None:
        """Not before, or a narrow filter starves behind unrelated recent runs."""
        for _ in range(5):
            _run(app, "child")
        _run(app, "boom")
        for _ in range(5):
            _run(app, "child")

        assert [r["job"] for r in list_runs(_store(), job="boom", limit=3)] == ["boom"]

    def test_every_declared_state_is_a_legal_filter(self, app: FunctualizeApp) -> None:
        """`RUN_STATES` is what a surface enumerates, so it must be accepted.

        Derived from `RunStatus` rather than hand-written: the first version of
        that tuple guessed six values where there are ten, which would have had
        the CLI reject four legal filters.
        """
        _run(app, "child")
        for state in RUN_STATES:
            list_runs(_store(), state=state)  # must not raise


class TestParentage:
    """What the history ring dropped and the run log keeps."""

    def test_an_invoked_child_names_its_parent(self, app: FunctualizeApp) -> None:
        _run(app, "parent")
        rows = {r["job"]: r for r in list_runs(_store())}
        assert rows["child"]["parent_run_id"] == rows["parent"]["run_id"]
        assert rows["child"]["invoke_depth"] > rows["parent"]["invoke_depth"]

    def test_the_tree_nests_descendants(self, app: FunctualizeApp) -> None:
        _run(app, "parent")
        parent_id = next(
            r["run_id"] for r in list_runs(_store()) if r["job"] == "parent"
        )
        tree = run_tree(_store(), parent_id)
        assert tree is not None
        assert [c["job"] for c in tree["children"]] == ["child"]

    def test_a_leaf_has_an_empty_child_list(self, app: FunctualizeApp) -> None:
        _run(app, "child")
        run_id = list_runs(_store())[0]["run_id"]
        tree = run_tree(_store(), run_id)
        assert tree is not None
        assert tree["children"] == []


class TestTheCliRendersTheProjection:
    """Thin callers: the CLI must not reach past the projection."""

    def test_list_shows_the_rows(self, app: FunctualizeApp) -> None:
        _run(app, "child")
        result = CliRunner().invoke(
            app.cli_command, ["builtin", "run", "list"], catch_exceptions=False
        )
        assert "child" in result.output
        assert "success" in result.output

    def test_list_json_is_the_projection_verbatim(self, app: FunctualizeApp) -> None:
        """The check that stops a second shape appearing.

        A one-line summary is a *rendering* of the shared projection. The
        moment it had its own shape, `--format json` and the MCP survey stopped
        being the same rows — which is the drift these modules exist to end.
        """
        _run(app, "child")
        result = CliRunner().invoke(
            app.cli_command,
            ["builtin", "run", "list", "--format", "json"],
            catch_exceptions=False,
        )
        assert json.loads(result.output)["runs"] == list_runs(_store())

    def test_show_json_is_the_projection_verbatim(self, app: FunctualizeApp) -> None:
        _run(app, "child")
        run_id = list_runs(_store())[0]["run_id"]
        result = CliRunner().invoke(
            app.cli_command,
            ["builtin", "run", "show", run_id, "--format", "json"],
            catch_exceptions=False,
        )
        assert json.loads(result.output) == describe_run(_store(), run_id)

    def test_show_of_a_missing_run_exits_nonzero(self, app: FunctualizeApp) -> None:
        result = CliRunner().invoke(app.cli_command, ["builtin", "run", "show", "nope"])
        assert result.exit_code != 0
        assert "no run" in result.output.lower()

    def test_no_matches_says_so(self, app: FunctualizeApp) -> None:
        result = CliRunner().invoke(
            app.cli_command,
            ["builtin", "run", "list", "--job", "never-ran"],
            catch_exceptions=False,
        )
        assert "No matching runs" in result.output


class TestTheMcpToolsReturnTheSameRows:
    """Decision A3 — verb for verb, over one projection.

    The parity test enumerates that the verbs *exist* on both surfaces. This
    asserts they return the same thing, which parity of signatures cannot.
    """

    @pytest.fixture
    def provider(self, app: FunctualizeApp) -> Any:
        from functualize_mcp._workflow_tools import WorkflowToolProvider

        return WorkflowToolProvider(app)

    @pytest.mark.anyio
    async def test_list_runs_matches_the_projection(
        self, app: FunctualizeApp, provider: Any
    ) -> None:
        _run(app, "child")
        _run(app, "boom")
        assert (await provider._list_runs())["runs"] == list_runs(_store())

    @pytest.mark.anyio
    async def test_get_run_matches_the_projection(
        self, app: FunctualizeApp, provider: Any
    ) -> None:
        _run(app, "child")
        run_id = list_runs(_store())[0]["run_id"]
        assert await provider._get_run(run_id) == describe_run(_store(), run_id)

    @pytest.mark.anyio
    async def test_get_run_refuses_a_missing_run(self, provider: Any) -> None:
        result = await provider._get_run("nope")
        assert result.get("error") == "run_not_found"

    @pytest.mark.anyio
    async def test_get_run_events_refuses_a_missing_run(self, provider: Any) -> None:
        """An empty list and a missing run are different answers."""
        result = await provider._get_run_events("nope")
        assert result.get("error") == "run_not_found"

    @pytest.mark.anyio
    async def test_events_for_a_real_run_is_a_list(
        self, app: FunctualizeApp, provider: Any
    ) -> None:
        _run(app, "child")
        run_id = list_runs(_store())[0]["run_id"]
        result = await provider._get_run_events(run_id)
        assert result["run_id"] == run_id
        assert isinstance(result["events"], list)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
