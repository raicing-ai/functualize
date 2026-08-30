"""A job reads the inputs its own ``Fingerprint`` declared (ADR-012).

The risk this file exists for is not "does `Sources` compute the right thing" —
it computes nothing; the pre-flight already built the map. It is **"does the
value ever arrive"**. DI resolves *before* the pre-flight runs, so the instance
is injected empty and filled in afterwards; drop that one call and every job
sees an empty mapping, with no error anywhere. `AGENTS.md` names that failure
four times, and `contributor/guides/wiring-discipline.md` exists for it.

So every test here runs a real job through the CLI and reads what the **body**
saw, cold and warm. A unit test on the class would pass with the wiring
removed.

The second thing under test is a distinction, not a value: "declared no
sources" must not look like "declared sources that matched nothing". An empty
mapping cannot express that, and the R3 refusal turns on the same distinction —
one mechanism, two consumers.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("s", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = """
from pathlib import Path

from functualize.job import Fingerprint, Sources, job

JOB_GROUP = "s"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["inputs/*.txt"], generates=["out.txt"]))
def scan(sources: Sources) -> None:
    print(f"DECLARED {sources.declared}")
    print(f"KEYS {sorted(sources.keys())}")
    print(f"GENERATES {list(sources.generates)}")
    print(f"LEN {len(sources)}")
    print(f"CONTAINS {'inputs/a.txt' in sources}")
    for path in sorted(sources.keys()):
        e = sources[path]
        print(f"ENTRY {path} size={e['size']} sha={e['sha256'][:12]} mtime={e['mtime']}")
    # Reading through the declaration, never re-globbing.
    Path("out.txt").write_text(
        "".join(Path(p).read_text() for p in sorted(sources.keys()))
    )


@job(group=JOB_GROUP)
def nodecl(sources: Sources) -> None:
    print(f"DECLARED {sources.declared}")
    print(f"LEN {len(sources)}")
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "main.py").write_text(_MAIN)
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "s"\n')
    (tmp_path / ".functualize").mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "a.txt").write_text("alpha\n")
    (inputs / "b.txt").write_text("beta\n")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "s.py").write_text(_JOBS)
    return tmp_path


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "python", "main.py", *args],
        capture_output=True,
        text=True,
        cwd=str(project),
        timeout=120,
    )


def test_the_body_receives_the_resolved_map(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = _run(project, "s", "scan")
    assert result.returncode == 0, result.stderr
    out = result.stdout

    assert "DECLARED True" in out
    assert "KEYS ['inputs/a.txt', 'inputs/b.txt']" in out
    assert "GENERATES ['out.txt']" in out
    assert "LEN 2" in out
    assert "CONTAINS True" in out
    # The per-input record — the provenance the framework computes and used to
    # discard. `alpha\n` is 6 bytes.
    assert "ENTRY inputs/a.txt size=6 sha=" in out
    assert "mtime=" in out
    assert (project / "out.txt").read_text() == "alpha\nbeta\n"


def test_it_arrives_on_the_warm_path_too(tmp_path: Path) -> None:
    """The wiring must survive a warm boot.

    Every second-and-later invocation builds its command from the cache, not
    from the live signature. A capability wired on only one of those paths is
    the recurring failure this repository is named for — and the first run is
    the one a naive test asserts.
    """
    project = _project(tmp_path)
    assert _run(project, "s", "scan").returncode == 0

    # Add an input so the job is stale and its body runs again — this time
    # from a warm boot.
    (project / "inputs" / "c.txt").write_text("gamma\n")
    second = _run(project, "s", "scan")
    assert second.returncode == 0, second.stderr
    assert "KEYS ['inputs/a.txt', 'inputs/b.txt', 'inputs/c.txt']" in second.stdout
    assert "LEN 3" in second.stdout
    assert (project / "out.txt").read_text() == "alpha\nbeta\ngamma\n"


def test_declaring_no_sources_is_not_an_empty_map(tmp_path: Path) -> None:
    """The distinction an empty mapping cannot carry.

    "I declared nothing" and "I declared something and it matched nothing" are
    different facts, and only the second is a refusal (A8). Collapsing them is
    how a stage certifies success having verified nothing.
    """
    project = _project(tmp_path)
    result = _run(project, "s", "nodecl")
    assert result.returncode == 0, result.stderr
    assert "DECLARED False" in result.stdout
    assert "LEN 0" in result.stdout


def test_sources_is_not_a_cli_parameter(tmp_path: Path) -> None:
    """A capability parameter must never surface as an argument.

    It did: the discovery scan's exclusion list was a fourth copy of the
    injected-type names, and `Sources` — like `Shell` and `Stdout` before it —
    was missing from it, so the job grew a required positional ``SOURCES``.
    """
    project = _project(tmp_path)
    help_text = _run(project, "s", "scan", "--help")
    assert help_text.returncode == 0, help_text.stderr
    assert "SOURCES" not in help_text.stdout
    assert "[OPTIONS]" in help_text.stdout


def test_sources_does_not_enter_the_jobs_own_fingerprint_key(tmp_path: Path) -> None:
    """A job's own resolved inputs must not be hashed into its own key.

    `Sources` is DI-injected, so the key rule that subtracts injected
    parameters covers it — but the consequence is worth pinning: a live
    capability instance in the key means a new key every run.
    """
    import json

    project = _project(tmp_path)
    for _ in range(3):
        assert _run(project, "s", "scan").returncode == 0

    state = json.loads((project / ".functualize" / "state.json").read_text())
    keys = [k for k in state.get("fingerprints", {}) if k.startswith("s.scan::")]
    assert len(keys) == 1, keys
