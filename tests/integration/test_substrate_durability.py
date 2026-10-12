"""A gate blocked in one process is resumed by another that shares no project.

`store-substrate`/T7. Spec AC-3 — the criterion the whole feature exists for,
and the easiest to fake.

## What "no shared disk" means here, exactly

The honest version of this test is two machines and a network database, which a
unit suite cannot run. So the property is reproduced the strongest way one
machine allows: **the two processes have different working directories and
different `.functualize/` directories**, and the only thing joining them is the
store this project's config selects — `runtime_store.url = "sqlite:///…"`,
prepared by the shipped plugin's factory when boot selects it.

That is the real claim. The framework's own file layout — one upward walk to a
`.functualize/`, `scopes.json` and `scope-state/` beside each other — is what a
resumed run used to depend on. If any of it still carried the state, the second
process would find nothing: it is looking in a different directory. Passing
means the substrate is the only channel, which is what a network backend needs
and what a shared filesystem would hide.

## What this does **not** prove

That a *remote* substrate works. SQLite is still a local file, so this shows the
store stack is substrate-addressed, not that any particular backend is reachable
over a network. Those are different claims and only the first is testable here.

## Why swapping the substrate in-process would prove nothing

The stores would be the same objects, in the same process, holding the same
dictionaries. Every interesting failure — a scope registry reset at boot, an
in-memory tier, a path resolved from the cwd — survives that and is caught by
this.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent

_JOBS = '''
from pydantic import BaseModel, Field

from functualize import workflow
from functualize.job import Log, State, job
from functualize.workflow import END, Edge, Gate, Step


class Ask(BaseModel):
    approved: str = Field(description="anything")


@job
def first(log: Log, state: State) -> str:
    """Writes job state as well as a step record.

    Both halves matter: the record says the step ran, the state is what the
    job put there. A substrate that carried one and not the other is the
    split brain this feature exists to make unreachable, and a test that only
    checked the record would not see it.
    """
    state.set("rows", 500)
    log("FIRST RAN")
    return "one"


@job
def last(log: Log, state: State) -> str:
    log(f"LAST SAW rows={state.get('rows')}")
    return "two"


@workflow(
    steps=[Step(first), Gate(name="pause", awaits=Ask), Step(last)],
    edges=[Edge("first", "pause"), Edge("pause", "last"), Edge("last", END)],
)
def walk(log: Log) -> str:
    log("WALK BODY RAN")
    return "done"
'''

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

# No substrate is installed here, and none can be: `FunctualizeApp.__init__`
# boots, and boot step 6.5 builds the engine *with* the store it selects — so
# an `install_substrate` after construction is refused by design. Storage is
# chosen the way a user chooses it: `config.base.toml` sets
# `runtime_store.url`, the shipped `substrate-sqlite` plugin registers its
# factory, and boot selects and prepares it at 6.5.
app = FunctualizeApp("w", job_sources=JobSources(directories=["jobs"]))

adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""


def _worker(root: Path, db: Path) -> Path:
    """A complete project, with its own `.functualize/` nobody else can see."""
    root.mkdir(parents=True)
    (root / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    # The only thing naming the store: `runtime_store.url`, read at step 6.5. The plugin is installed in this
    # workspace's venv, so entry-point discovery loads it with nothing else
    # to declare.
    (root / "config.base.toml").write_text(
        "[general]\n"
        'app_name = "w"\n'
        "\n"
        "[runtime_store]\n"
        f"url = {json.dumps('sqlite://' + str(db))}\n"
    )
    (root / ".functualize").mkdir()
    (root / "main.py").write_text(_MAIN)
    jobs = root / "jobs"
    jobs.mkdir()
    (jobs / "w.py").write_text(_JOBS)
    return root


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(PROJECT_ROOT),
            sys.executable.rsplit("/", 1)[-1],
            "main.py",
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=str(project),
        timeout=180,
    )


@pytest.fixture
def two_workers(tmp_path: Path) -> tuple[Path, Path, Path]:
    db = tmp_path / "shared" / "state.db"
    db.parent.mkdir()
    first = _worker(tmp_path / "worker-a", db)
    second = _worker(tmp_path / "worker-b", db)
    return first, second, db


@pytest.mark.slow
class TestAGateCrossesTheProcessBoundary:
    @pytest.mark.xfail(
        strict=True,
        reason="the --wf-resume flag still reads the legacy ScopeStore; W17 reads it through the port",
    )
    def test_the_second_worker_resumes_what_the_first_blocked(
        self, two_workers: tuple[Path, Path, Path]
    ) -> None:
        """AC-3. Neither worker can see the other's project directory."""
        first, second, _db = two_workers

        blocked = _run(first, "walk")
        blob = blocked.stdout + blocked.stderr
        assert blocked.returncode == 5, blob
        scope = _scope_id_from(blob)

        resumed = _run(
            second, "walk", "--wf-resume", scope, "--wf-input", '{"approved": "yes"}'
        )
        after = resumed.stdout + resumed.stderr
        assert resumed.returncode == 0, after
        assert "LAST SAW rows=500" in after, (
            "the second worker resumed the walk but the job state did not "
            "arrive — records and state are in different backends, which is "
            "the split brain AC-4 forbids"
        )
        assert "WALK BODY RAN" in after

    def test_neither_worker_wrote_the_frameworks_own_files(
        self, two_workers: tuple[Path, Path, Path]
    ) -> None:
        """The falsifier. If the JSON files carry it, this test proves nothing.

        A shared filesystem would let the first worker's `scopes.json` be what
        the second reads — and every claim above would hold for the wrong
        reason. So: after a full block-and-resume, neither project directory
        may contain a scope record or any scope state.
        """
        first, second, _db = two_workers

        blocked = _run(first, "walk")
        scope = _scope_id_from(blocked.stdout + blocked.stderr)
        _run(second, "walk", "--wf-resume", scope, "--wf-input", '{"approved": "y"}')

        # The documents the stores keep. **Not** every file: `cache.json` is the
        # discovery cache, which is derived from *this* checkout's own source
        # files and is correctly per-worker — it has a different lifecycle from
        # run state and always has. Asserting "no .json at all" would have
        # failed on it and said nothing true.
        state_documents = {
            "fresh.json",
            "scopes.json",
            "runs.json",
            "shell-history.json",
        }
        for worker in (first, second):
            present = {
                p.name for p in (worker / ".functualize").rglob("*") if p.is_file()
            }
            assert not (present & state_documents), (
                f"{worker.name} kept run state on its own disk "
                f"({sorted(present & state_documents)}); the resume may have "
                f"worked through the filesystem rather than the substrate"
            )
            assert not (worker / ".functualize" / "scope-state").exists(), (
                f"{worker.name} wrote scope state locally — the records could "
                f"cross while the state inside them did not, which is the "
                f"split brain with extra steps"
            )

    def test_the_substrate_is_where_the_records_actually_are(
        self, two_workers: tuple[Path, Path, Path]
    ) -> None:
        """Positive half of the falsifier: the database really holds them."""
        first, _second, db = two_workers

        blocked = _run(first, "walk")
        assert blocked.returncode == 5, blocked.stdout + blocked.stderr
        scope = _scope_id_from(blocked.stdout + blocked.stderr)

        with sqlite3.connect(db) as connection:
            row = connection.execute(
                "SELECT status, position FROM workflow_scopes WHERE id = ?", (scope,)
            ).fetchone()
            steps = connection.execute(
                "SELECT step_key, status FROM workflow_steps WHERE scope_id = ?",
                (scope,),
            ).fetchall()
            state = connection.execute(
                "SELECT value FROM scope_state WHERE scope_id = ? AND key = 'rows'",
                (scope,),
            ).fetchone()
            request = connection.execute(
                "SELECT status FROM input_requests WHERE scope_id = ? AND gate_key = 'pause'",
                (scope,),
            ).fetchone()
        assert row == ("blocked", "pause"), row
        assert any(
            key.startswith("first") and status == "success" for key, status in steps
        ), steps
        assert state is not None and json.loads(state[0]) == 500, state
        assert request == ("open",), request


def _scope_id_from(output: str) -> str:
    """The scope id from the blocked run's own resume instruction.

    Read from the message rather than from a store, because the message is what
    a human is told to use — a test that reconstructed the id another way would
    pass while that instruction was wrong.
    """
    import re

    match = re.search(r"--wf-resume ([\w.-]+)", output)
    assert match is not None, f"no resume instruction in:\n{output}"
    return match.group(1)


@pytest.mark.slow
@pytest.mark.xfail(
    strict=True,
    reason="the --wf-resume flag still reads the legacy ScopeStore; W17 reads it through the port",
)
def test_the_gate_payload_survives_the_crossing(
    two_workers: tuple[Path, Path, Path],
) -> None:
    """What a human approved is the one record that must not be lost.

    A step record can be recomputed by running the step again. An approval
    cannot: losing it spends a person's decision on a run that no longer
    exists, which is why `scopes.json` refuses an unreadable file rather than
    degrading to empty.
    """
    first, second, db = two_workers

    blocked = _run(first, "walk")
    scope = _scope_id_from(blocked.stdout + blocked.stderr)
    resumed = _run(
        second, "walk", "--wf-resume", scope, "--wf-input", '{"approved": "sam"}'
    )
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr

    with sqlite3.connect(db) as connection:
        request = connection.execute(
            "SELECT id, status FROM input_requests WHERE scope_id = ? AND gate_key = 'pause'",
            (scope,),
        ).fetchone()
        candidates = connection.execute(
            "SELECT c.outcome, c.payload FROM input_candidates AS c "
            "JOIN input_requests AS r ON r.id = c.request_id "
            "WHERE r.scope_id = ? AND r.gate_key = 'pause' ORDER BY c.ordinal",
            (scope,),
        ).fetchall()
        status = connection.execute(
            "SELECT status FROM workflow_scopes WHERE id = ?", (scope,)
        ).fetchone()
    assert request is not None and request[1] == "consumed", request
    assert any(
        outcome == "accepted" and json.loads(payload) == {"approved": "sam"}
        for outcome, payload in candidates
    ), candidates
    assert status == ("completed",), status
