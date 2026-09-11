"""The suite must not write into the checkout's own `.functualize/`.

`capability-duality`/T10. `resolve_fresh_location` walks **upward**, so before
`tests/conftest.py::_isolate_state_root` every test that did not `chdir`
resolved to the repository's state root and wrote there. Measured immediately
before the fixture landed: **3,212 scope records** in this worktree's
`scopes.json`, 1.6 MB of suite residue.

The cost was never a dirty tree — the directory is gitignored. It was that
tests stopped being independent: a run inherits the previous run's records, so
a test asserting "this is invocation 1" passes alone and fails second.

These tests assert the sandbox from the outside, by running a real job that
writes state and then looking at where the bytes landed. A test that asserted
the fixture's *existence* would keep passing if the redirect broke.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from functualize import FunctualizeApp, RunContext
from functualize._engine.capabilities.state import State  # noqa: TC001
from functualize._primitives.scope_format import SCOPES_KEY
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.run_request import RunRequest

#: The checkout's own state root — what the suite used to fill up. Resolved
#: from this file rather than from `Path.cwd()`, which a test may have changed.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_SCOPES = _REPO_ROOT / ".functualize" / "scopes.json"


def _record_count(path: Path) -> int:
    """How many scope records a scopes.json holds, 0 if it does not exist."""
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text()).get("scopes", {}))
    except (OSError, ValueError):
        return 0


def _run_a_job_that_writes_state(app_name: str) -> Any:
    """Execute one real job that puts a key in the run's durable state."""
    app = FunctualizeApp(name=app_name)

    def writer(rc: RunContext, state: State) -> str:
        state.set("marker", "written")
        return "ok"

    app.register_dynamic_job("writer", writer)
    return app.execute(RunRequest(job_name="writer", surface="app.execute"))


class TestTheSuiteDoesNotWriteIntoTheRepository:
    """A job that writes durable state leaves the checkout's root alone."""

    def test_running_a_job_adds_no_record_to_the_real_state_root(self) -> None:
        """The assertion that fails if the redirect is removed.

        Deliberately a *delta* rather than `not _REPO_SCOPES.exists()`: a
        developer may have run `func` by hand in this checkout, and the file's
        mere presence is not a defect. Growth caused by this test is.
        """
        before = _record_count(_REPO_SCOPES)

        result = _run_a_job_that_writes_state("no-repo-writes")
        assert result.status.value == "Success"

        after = _record_count(_REPO_SCOPES)
        assert after == before, (
            f"running a job added {after - before} record(s) to "
            f"{_REPO_SCOPES} — the suite is writing into the checkout's own "
            f"state root (tests/conftest.py::_isolate_state_root)"
        )

    def test_the_state_actually_went_somewhere(self, tmp_path: Path) -> None:
        """Redirected, not discarded.

        Without this, a fixture that pointed the state root at `/dev/null` — or
        one that broke writing altogether — would satisfy the test above. The
        run's state has to be *somewhere*, and that somewhere has to be this
        test's own `tmp_path`.
        """
        result = _run_a_job_that_writes_state("state-lands-in-tmp")
        assert result.status.value == "Success"

        sandbox_root = tmp_path.resolve() / ".functualize"
        assert (sandbox_root / "scopes.json").exists(), (
            f"no scopes.json under {tmp_path} — the run went neither to the "
            f"repo nor to the sandbox"
        )
        # The state itself is in `scope-state/<id>.json`, not in the record:
        # `scope-record-lifecycle`/T3 moved it there so a write stops costing
        # the whole project's history. This test read the record before that,
        # and the move is exactly why it had to change.
        state_files = sorted((sandbox_root / "scope-state").glob("*.json"))
        assert state_files, (
            f"no per-scope state file under {sandbox_root} — the run's state "
            f"went somewhere else"
        )
        written = [
            key
            for path in state_files
            for key in (json.loads(path.read_text()).get("state") or {})
            if key == "marker"
        ]
        assert written, (
            f"{len(state_files)} state file(s) in the sandbox but none carries "
            f"the key the job wrote"
        )

    def test_each_test_gets_its_own_root(self, tmp_path: Path) -> None:
        """Isolation is per test, which is the part that fixes ordering.

        A shared-but-not-the-repo root would still leak between tests. This
        asserts the resolved path is inside *this* test's `tmp_path`, so the
        record written by the test above is not visible here.
        """
        resolved = (
            JsonFileSubstrate.for_project(Path.cwd()).path_for(SCOPES_KEY).resolve()
        )
        assert resolved.is_relative_to(tmp_path.resolve()), (
            f"state resolved to {resolved}, which is outside this test's "
            f"{tmp_path} — the sandbox is shared, so tests can still see each "
            f"other's records"
        )
        assert _record_count(resolved) == 0, (
            "this test's root already holds records before it ran anything"
        )


class TestTheOptOutWorks:
    """`real_state_root` returns a test to the real upward walk."""

    @pytest.mark.real_state_root
    def test_marked_tests_resolve_to_the_real_root(self) -> None:
        """For a test whose subject *is* the upward walk.

        Asserted so the escape hatch is known to work before anyone needs it —
        an opt-out nobody has exercised is an opt-out that silently does
        nothing.
        """
        resolved = (
            JsonFileSubstrate.for_project(_REPO_ROOT).path_for(SCOPES_KEY).resolve()
        )
        assert resolved == _REPO_SCOPES.resolve(), (
            f"the marker did not restore the real walk: got {resolved}"
        )
