"""What a run record's `scope_id` means, asserted rather than assumed.

`scope-record-lifecycle`/T6, AC-6, and review F6 — which asked whether the
field should be null for a non-workflow job, on the grounds that it "names a
scope that is not a workflow".

The answer is no, and T1 is why: `_ensure_scope` gives **every** run a scope
before the record is opened, so a null would mean "I did not look" rather than
"there was none". The field means *the scope this run ran in*, uniformly.

The obligation that moves to the reader is the one worth pinning: **a scope id
on a run record may have no record on disk.** A run that never touched state
leaves none — nothing is minted just so it can be marked finished, because that
is exactly how `scopes.json` grew to 2,188 records. Resolving such an id yields
"no records", which is an answer and not an error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from functualize import FunctualizeApp, RunContext
from functualize._engine.capabilities.state import State  # noqa: TC001
from functualize._primitives.run_format import RUNS_KEY
from functualize._primitives.scope_format import SCOPES_KEY
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.run_request import RunRequest


def _runs() -> dict[str, Any]:
    path = JsonFileSubstrate.for_project(Path.cwd()).path_for(RUNS_KEY)
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("runs", {})


def _scopes() -> dict[str, Any]:
    path = JsonFileSubstrate.for_project(Path.cwd()).path_for(SCOPES_KEY)
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get("scopes", {})


def _run_one(job_name: str, fn: Any) -> None:
    app = FunctualizeApp(name=f"scope-id-{job_name}")
    app.register_dynamic_job(job_name, fn)
    app.execute(RunRequest(job_name=job_name, surface="app.execute"))


class TestEveryRunRecordNamesItsScope:
    @pytest.mark.json_substrate
    def test_a_stateful_run_names_a_scope_that_exists(self) -> None:
        def stateful(rc: RunContext, state: State) -> str:
            state.set("k", 1)
            return "ok"

        _run_one("stateful", stateful)

        record = next(iter(_runs().values()))
        scope_id = record.get("scope_id")
        assert scope_id, "a run record carried no scope_id"
        assert scope_id in _scopes(), (
            "this run wrote state, so its scope must have a record on disk"
        )

    @pytest.mark.json_substrate
    def test_a_stateless_run_names_a_scope_with_no_record(self) -> None:
        """The dangling case, asserted deliberately rather than tolerated.

        This is F6's observation, and it is *intended*: the id identifies the
        scope the run executed in, and that scope existed for the run's
        duration. It left no durable trace because it accumulated nothing
        worth storing.
        """

        def stateless(rc: RunContext) -> str:
            return "ok"

        _run_one("stateless", stateless)

        record = next(iter(_runs().values()))
        scope_id = record.get("scope_id")
        assert scope_id, (
            "a stateless run still ran in a scope; a null here would mean "
            "'not looked up', which is a different claim"
        )
        assert scope_id not in _scopes(), (
            "a run that stored nothing minted a scope record anyway — that is "
            "the growth scope-record-lifecycle removes"
        )

    @pytest.mark.json_substrate
    def test_resolving_an_unrecorded_scope_id_is_an_answer_not_an_error(
        self,
    ) -> None:
        """The reader's side of the contract.

        A consumer that follows `scope_id` must get "no records" rather than an
        exception, or the dangling case above becomes a crash in every tool
        that walks the run log.
        """

        def stateless(rc: RunContext) -> str:
            return "ok"

        _run_one("stateless", stateless)
        scope_id = next(iter(_runs().values()))["scope_id"]

        store = ScopeStore.for_project(Path.cwd())
        assert store.get_scope(scope_id) is None

    @pytest.mark.json_substrate
    def test_a_child_run_names_the_same_scope_as_its_parent(self) -> None:
        """Uniform means uniform — a nested run is in its parent's scope.

        If `scope_id` meant something narrower for children, "the scope this
        ran in" would be false for exactly the runs that make a run tree worth
        having.
        """
        app = FunctualizeApp(name="scope-id-tree")

        def child(rc: RunContext, state: State) -> str:
            state.set("child", 1)
            return "ok"

        def parent(rc: RunContext, state: State) -> str:
            state.set("parent", 1)
            rc.invoke("child")
            return "ok"

        app.register_dynamic_job("child", child)
        app.register_dynamic_job("parent", parent)
        app.execute(RunRequest(job_name="parent", surface="app.execute"))

        scope_ids = {r["scope_id"] for r in _runs().values()}
        assert len(_runs()) == 2, "expected a record for both parent and child"
        assert len(scope_ids) == 1, (
            f"parent and child reported different scopes: {scope_ids}"
        )
