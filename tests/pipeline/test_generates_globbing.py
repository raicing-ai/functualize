"""``Fingerprint.generates`` entries are glob patterns, not literal paths (D-1).

``generates`` was tested with ``(root / entry).exists()``, which is always False
for ``dist/*.whl`` — the form the ``@job`` decorator's own docstring advertises.
The job reported ``output missing: dist/*.whl`` on every run and rebuilt
forever, and the failure mode was never an error, only "always rebuild". It
became reachable from the *default* method when `checksum` started consulting
outputs; before that a glob-shaped declaration was merely inert.

Every test here runs its job **twice**, through the real entry point. A single
run cannot see this defect at all: run 1 is supposed to run.

The last test is the docstring itself, declared byte-for-byte, because "the
example in our own documentation is correct" is a claim that has to be executed
rather than read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("g", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

# `build_glob` declares exactly what `job/decorators.py` advertises. The others
# are the controls: a literal path (which always worked), a pattern that matches
# nothing, and a directory (which `.exists()` accepts and globbing must not
# start rejecting).
_JOBS = """
from pathlib import Path

from functualize.job import Fingerprint, job

JOB_GROUP = "g"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["src/**/*.py"], generates=["dist/*.whl"]))
def build_glob() -> None:
    print("RAN build-glob")
    Path("dist").mkdir(exist_ok=True)
    Path("dist/app-1.0.whl").write_bytes(b"wheel")


@job(group=JOB_GROUP, cache=Fingerprint(sources=["src/**/*.py"], generates=["dist/app.whl"]))
def build_literal() -> None:
    print("RAN build-literal")
    Path("dist").mkdir(exist_ok=True)
    Path("dist/app.whl").write_bytes(b"wheel")


@job(group=JOB_GROUP, cache=Fingerprint(sources=["src/**/*.py"], generates=["nope/*.zip"]))
def build_nomatch() -> None:
    print("RAN build-nomatch")


@job(group=JOB_GROUP, cache=Fingerprint(sources=["src/**/*.py"], generates=["site"]))
def build_dir() -> None:
    print("RAN build-dir")
    Path("site").mkdir(exist_ok=True)
    (Path("site") / "index.html").write_text("<p>hi</p>")
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "main.py").write_text(_MAIN)
    (tmp_path / "config.base.toml").write_text('[general]\napp_name = "g"\n')
    (tmp_path / ".functualize").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("print(1)\n")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "g.py").write_text(_JOBS)
    return tmp_path


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "python", "main.py", *args],
        capture_output=True,
        text=True,
        cwd=str(project),
        timeout=120,
    )


def _ran(project: Path, command: str) -> bool:
    result = _run(project, "g", command)
    assert result.returncode == 0, result.stderr
    return f"RAN {command}" in result.stdout


def test_a_glob_generates_target_is_fresh_on_the_second_run(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert _ran(project, "build-glob") is True
    assert _ran(project, "build-glob") is False, (
        "`generates=['dist/*.whl']` was tested as a literal path, so the "
        "wheel it just wrote never satisfied it and the job rebuilt forever"
    )


def test_deleting_the_matched_output_forces_a_rebuild(tmp_path: Path) -> None:
    """The point of consulting outputs at all — and it must survive globbing.

    Making the pattern resolve is only half the fix. If a matched-then-deleted
    output stopped forcing a run, D-1 would have reintroduced exactly the false
    clean that consulting `generates` from the default method exists to close.
    """
    project = _project(tmp_path)
    assert _ran(project, "build-glob") is True
    assert _ran(project, "build-glob") is False

    (project / "dist" / "app-1.0.whl").unlink()
    assert _ran(project, "build-glob") is True


def test_a_pattern_matching_nothing_is_a_missing_output(tmp_path: Path) -> None:
    """Zero matches and an absent literal are the same verdict, deliberately.

    This is the sub-question D-1 left to the spec. Any answer other than "not
    fresh" would let a job declare an output it never produces and be skipped
    for it.
    """
    project = _project(tmp_path)
    assert _ran(project, "build-nomatch") is True
    assert _ran(project, "build-nomatch") is True


def test_the_reason_names_the_pattern_as_declared(tmp_path: Path) -> None:
    """An expansion of nothing has nothing to show the reader.

    The verdict quotes the string they wrote, not the empty set it resolved to.
    """
    project = _project(tmp_path)
    assert _ran(project, "build-nomatch") is True

    why = _run(project, "builtin", "why", "g.build-nomatch")
    assert "nope/*.zip" in why.stdout, why.stdout


def test_a_literal_generates_path_is_unchanged(tmp_path: Path) -> None:
    project = _project(tmp_path)
    assert _ran(project, "build-literal") is True
    assert _ran(project, "build-literal") is False


def test_a_directory_still_counts_as_an_output(tmp_path: Path) -> None:
    """`generates=["site"]` is legal today and has nothing to do with globbing.

    `.exists()` is true for a directory, so narrowing the check to files while
    fixing D-1 would silently break a declaration nobody was asked about.
    """
    project = _project(tmp_path)
    assert _ran(project, "build-dir") is True
    assert _ran(project, "build-dir") is False


def test_the_decorator_docstrings_own_example_works(tmp_path: Path) -> None:
    """AC-25's executed proof.

    `job/decorators.py` advertises
    ``Fingerprint(sources=["src/**/*.py"], generates=["dist/*.whl"])``. That is
    `build_glob` above, byte-for-byte. Anyone who copied the docstring had a
    cache that silently stopped working; this test is what stops that being
    true again, and it is the reason the docstring may be called correct.
    """
    project = _project(tmp_path)
    assert _ran(project, "build-glob") is True
    assert _ran(project, "build-glob") is False
