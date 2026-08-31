"""Declared inputs may live outside the project (D-2, ADR-013).

``expand_sources`` globbed a pattern and then threw the matches away::

    relative = match.resolve().relative_to(base)   # ValueError -> continue

``resolve()`` follows symlinks, so a file matched *through* a symlinked
directory resolved to its real location outside ``base`` and was discarded
**after the glob had already found it**. Absolute patterns died on the same
check, and ``Path.glob`` never matched ``..`` at all. So there was no way to
declare an input that did not live under the project — which is the single most
important declaration in the domain this framework is modelled on, where every
unit reaches its reference checkouts through paths outside itself.

The restriction was never designed: it was in ``expand_sources`` from the
initial commit, justified by one docstring line about the storage format, and
applied inconsistently — absolute ``generates`` paths worked, because
``Path(base) / "/abs"`` yields ``/abs``.

Two halves are tested here, and the second is the one that is easy to forget:

1. the three previously-undeclarable forms now resolve, and behave correctly
   across a cold and a warm run;
2. an ordinary in-project declaration records a **byte-identical** key to
   before. That is the compatibility claim the change rests on, and asserting
   it is what stops it being an assumption.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from functualize._primitives.fingerprint import expand_sources

PROJECT_ROOT = Path(__file__).parent.parent.parent


# ─── unit level: what key does each declared form record? ──────────────────


def test_a_relative_declaration_records_the_relative_path(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("1\n")

    assert expand_sources(tmp_path, ["src/**/*.py"]) == ["src/a.py"]


def test_an_absolute_declaration_records_the_absolute_path(tmp_path: Path) -> None:
    """D-2's named trade, made visible.

    An absolute key does not match on another machine, so that machine re-runs
    the job once and writes its own. Nothing breaks; the work is simply not
    shared. That is the honest behaviour, and it is why the key is not rewritten
    into some machine-independent label.
    """
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "world.tf").write_text("x = 1\n")
    unit = tmp_path / "unit"
    unit.mkdir()

    found = expand_sources(unit, [str(outside / "**" / "*.tf")])

    assert found == [(outside / "world.tf").as_posix()]
    assert found[0].startswith("/")


def test_a_parent_relative_declaration_keeps_its_dot_dot(tmp_path: Path) -> None:
    """``../`` stays ``../``, which is what keeps the key portable.

    ``Path.relative_to`` cannot produce a ``..`` segment and ``Path.glob`` does
    not match one, so this form needs its own walker. Rendering it absolute
    instead would silently convert a machine-independent declaration into a
    machine-specific one.
    """
    shared = tmp_path / "repos" / "prod"
    shared.mkdir(parents=True)
    (shared / "main.tf").write_text("cluster = 1\n")
    unit = tmp_path / "unit"
    unit.mkdir()

    assert expand_sources(unit, ["../repos/**/*.tf"]) == ["../repos/prod/main.tf"]


def test_a_symlinked_subtree_keeps_the_name_the_declaration_used(
    tmp_path: Path,
) -> None:
    """The exact shape of the defect: globbed, then discarded.

    ``Path.glob`` finds the file through the symlink. The old code then called
    ``resolve()`` on the match, landed outside ``base``, and dropped it. The key
    is the unresolved path because that is the name the author wrote.
    """
    outside = tmp_path / "world" / "prod"
    outside.mkdir(parents=True)
    (outside / "main.tf").write_text('cluster = "prod0"\n')
    unit = tmp_path / "unit"
    unit.mkdir()
    (unit / "repos").symlink_to(tmp_path / "world", target_is_directory=True)

    assert expand_sources(unit, ["repos/**/*.tf"]) == ["repos/prod/main.tf"]


def test_an_in_project_key_is_byte_identical_to_before(tmp_path: Path) -> None:
    """The compatibility claim, asserted rather than assumed.

    Every fingerprint key that exists in the wild today came from an in-project
    relative declaration whose match resolved inside the root. If any of those
    changed shape, every project would silently re-run every job once. They do
    not: for this case the new rule and the old one compute the same string.
    """
    for relative in ("a.py", "pkg/b.py", "pkg/deep/c.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("1\n")

    assert expand_sources(tmp_path, ["**/*.py"]) == [
        "a.py",
        "pkg/b.py",
        "pkg/deep/c.py",
    ]


def test_a_directory_match_is_still_not_a_source(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("1\n")

    assert expand_sources(tmp_path, ["*"]) == []
    assert expand_sources(tmp_path, ["**/*"]) == ["pkg/a.py"]


# ─── end to end: does it survive a real cold and warm run? ─────────────────

_MAIN = """
from functualize.app import FunctualizeApp, JobSources
from functualize.app.adapters import CliAdapter

app = FunctualizeApp("d", job_sources=JobSources(directories=["jobs"]))
adapter = CliAdapter()

if __name__ == "__main__":
    adapter(app)
    adapter.run()
"""

_JOBS = """
from functualize.job import Fingerprint, job

JOB_GROUP = "d"


@job(group=JOB_GROUP, cache=Fingerprint(sources=["repos/**/*.tf"]))
def viasymlink() -> None:
    print("RAN viasymlink")


@job(group=JOB_GROUP, cache=Fingerprint(sources=["../shared/**/*.tf"]))
def viaparent() -> None:
    print("RAN viaparent")


@job(group=JOB_GROUP, cache=Fingerprint(sources=["nothing/**/*.tf"]))
def viamissing() -> None:
    print("RAN viamissing")
"""


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """A unit whose declared inputs all live outside it. Returns (unit, world)."""
    world = tmp_path / "world" / "prod"
    world.mkdir(parents=True)
    (world / "main.tf").write_text('cluster = "prod0"\n')

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "net.tf").write_text("cidr = 1\n")

    unit = tmp_path / "unit"
    unit.mkdir()
    (unit / "main.py").write_text(_MAIN)
    (unit / "config.base.toml").write_text('[general]\napp_name = "d"\n')
    (unit / ".functualize").mkdir()
    (unit / "repos").symlink_to(tmp_path / "world", target_is_directory=True)
    jobs = unit / "jobs"
    jobs.mkdir()
    (jobs / "d.py").write_text(_JOBS)
    return unit, world


def _run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "python", "main.py", *args],
        capture_output=True,
        text=True,
        cwd=str(project),
        timeout=120,
    )


def _ran(project: Path, command: str) -> bool:
    result = _run(project, "d", command)
    assert result.returncode == 0, result.stdout + result.stderr
    return f"RAN {command}" in result.stdout


def test_an_external_input_is_fingerprinted_cold_and_warm(tmp_path: Path) -> None:
    """Cold, warm, then changed — the three runs that matter.

    Run 2 is the one a naive test omits, and it is the only run that proves the
    external path reached the *record* rather than merely the glob.
    """
    unit, world = _project(tmp_path)

    assert _ran(unit, "viasymlink") is True
    assert _ran(unit, "viasymlink") is False

    (world / "main.tf").write_text('cluster = "prod1"\n')
    assert _ran(unit, "viasymlink") is True


def test_a_parent_relative_input_is_fingerprinted_cold_and_warm(
    tmp_path: Path,
) -> None:
    unit, _world = _project(tmp_path)
    shared = tmp_path / "shared" / "net.tf"

    assert _ran(unit, "viaparent") is True
    assert _ran(unit, "viaparent") is False

    shared.write_text("cidr = 2\n")
    assert _ran(unit, "viaparent") is True


def test_declared_sources_matching_nothing_still_refuse(tmp_path: Path) -> None:
    """D-2 must not weaken D5.

    Removing containment makes the refusal *rarer* — several patterns that
    triggered it were legal declarations being silently discarded — but a job
    whose declared inputs genuinely are not there must still decline to run,
    with exit 3, rather than certify success having verified nothing.
    """
    unit, _world = _project(tmp_path)

    result = _run(unit, "d", "viamissing")

    assert result.returncode == 3, result.stdout + result.stderr
    assert "declared sources resolved to no files" in result.stdout + result.stderr
