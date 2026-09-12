"""A gate blocked in one process is resumed by another that shares no project.

`store-substrate`/T7. Spec AC-3 — the criterion the whole feature exists for,
and the easiest to fake.

## What "no shared disk" means here, exactly

The honest version of this test is two machines and a network database, which a
unit suite cannot run. So the property is reproduced the strongest way one
machine allows: **the two processes have different working directories and
different `.functualize/` directories**, and the only thing joining them is the
substrate a plugin installed.

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
import sys
from pathlib import Path

from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("w", job_sources=JobSources(directories=["jobs"]))

# The substrate a plugin would install, installed here directly so the test
# does not also depend on entry-point discovery. `EngineHost.substrate` is the
# member; `APP_READY` is when a real plugin sets it.
sys.path.insert(0, {plugin_src!r})
from functualize_state_sqlite.substrate import SQLiteSubstrate

app.substrate = SQLiteSubstrate({db!r})

adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""


def _worker(root: Path, db: Path, plugin_src: Path) -> Path:
    """A complete project, with its own `.functualize/` nobody else can see."""
    root.mkdir(parents=True)
    (root / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    (root / "config.base.toml").write_text('[general]\napp_name = "w"\n')
    (root / ".functualize").mkdir()
    (root / "main.py").write_text(_MAIN.format(db=str(db), plugin_src=str(plugin_src)))
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
    plugin_src = PROJECT_ROOT / "plugins" / "functualize-state-sqlite" / "src"
    first = _worker(tmp_path / "worker-a", db, plugin_src)
    second = _worker(tmp_path / "worker-b", db, plugin_src)
    return first, second, db


@pytest.mark.slow
class TestAGateCrossesTheProcessBoundary:
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

        _run(first, "walk")

        sys.path.insert(
            0, str(PROJECT_ROOT / "plugins" / "functualize-state-sqlite" / "src")
        )
        from functualize_state_sqlite.substrate import SQLiteSubstrate

        substrate = SQLiteSubstrate(db)
        scopes = substrate.read("scopes")
        assert scopes is not None, "no scope records reached the database"
        assert scopes.data["scopes"], "the scope envelope is empty"

        scope_id = next(iter(scopes.data["scopes"]))
        state = substrate.read(f"scope-state/{scope_id}")
        assert state is not None and state.data["state"]["rows"] == 500, (
            "the record reached the database but the job state did not"
        )


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
    _run(second, "walk", "--wf-resume", scope, "--wf-input", '{"approved": "sam"}')

    sys.path.insert(
        0, str(PROJECT_ROOT / "plugins" / "functualize-state-sqlite" / "src")
    )
    from functualize_state_sqlite.substrate import SQLiteSubstrate

    stored = SQLiteSubstrate(db).read("scopes")
    assert stored is not None
    record = stored.data["scopes"][scope]
    assert "sam" in json.dumps(record.get("gates", {})), (
        f"the deposited gate payload is not in the record: {record.get('gates')}"
    )
