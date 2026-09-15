"""The freshness lab, driven end to end as a real process.

`jobs/self_caching_job.py` is the worked example: a job that declares
``Fingerprint(decides=True)``, reads its own verdict, and hands back the artifact
it built instead of rebuilding it. This file runs it through the real `func` CLI
and checks what actually happens, including the part that is easy to get wrong —
that the *second* run enters the body at all.

Why subprocesses rather than calls into the job functions:

* **Freshness is a fact about a previous process.** A verdict is read from the
  state store a *previous run* wrote, so a test that never leaves the
  interpreter cannot observe the thing this feature is about.
* **`decides` is honoured by the engine**, one layer down from the body. Calling
  ``report()`` directly would run the body unconditionally and prove nothing.

Each test gets its own copy of the lab with its own ``XDG_CACHE_HOME``: with no
``.functualize/`` directory the state store falls back to a cache directory
keyed by project path, and without the redirect one test would read another's
fingerprint records.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_LAB = Path(__file__).parent.parent
_BIN = Path(sys.executable).parent

#: Never copied into a test's lab. `build/` is where the job puts its artifact,
#: so a copy of it would make every freshness assertion depend on whether the
#: machine running the tests had ever run the example.
_GENERATED = shutil.ignore_patterns("tests", "__pycache__", "build", ".functualize")


class Lab:
    """An isolated copy of the lab, driven through the real CLI."""

    def __init__(self, root: Path, cache: Path) -> None:
        self.root = root
        self.env = {**os.environ, "XDG_CACHE_HOME": str(cache)}

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(_BIN / "func"), *args],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def ok(self, *args: str) -> subprocess.CompletedProcess[str]:
        proc = self.run(*args)
        assert proc.returncode == 0, (
            f"`func {' '.join(args)}` exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
        return proc

    @staticmethod
    def both(proc: subprocess.CompletedProcess[str]) -> str:
        """A job's `log` goes to stderr and its `print` to stdout, so a
        stdout-only assertion silently drops half of what the run published."""
        return proc.stdout + proc.stderr

    def artifact(self, name: str = "report.json") -> dict:
        return json.loads((self.root / "build" / name).read_text())


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    root = tmp_path / "lab"
    shutil.copytree(_LAB, root, ignore=_GENERATED)
    return Lab(root, tmp_path / "cache")


def token(proc: subprocess.CompletedProcess[str], marker: str) -> str:
    """The `built=<token>` a marker line published — the build's identity."""
    line = next(line for line in proc.stdout.splitlines() if line.startswith(marker))
    return line.split("built=")[1].split()[0]


class TestTheJobThatDecides:
    def test_a_cold_run_builds_and_writes_its_own_artifact(self, lab: Lab) -> None:
        proc = lab.ok("lab", "report")

        assert "BUILT" in proc.stdout
        # The verdict the job read is the pre-flight's own, and on a cold tree
        # it says the inputs are not current.
        assert "state=run" in proc.stdout
        artifact = lab.artifact()
        assert artifact["total"] == 27
        assert artifact["built"] == token(proc, "BUILT")

    def test_a_fresh_run_enters_the_body_and_returns_the_artifact(
        self, lab: Lab
    ) -> None:
        built = lab.ok("lab", "report")
        warm = lab.ok("lab", "report")

        # The engine decided SKIP_FRESH, `decides=True` entered the body anyway,
        # and the body read that verdict — this is the whole feature.
        assert "CACHED" in warm.stdout
        assert "state=skip_fresh" in warm.stdout
        # ...and it returned the artifact rather than building a second one.
        assert "BUILT" not in warm.stdout
        assert token(warm, "CACHED") == token(built, "BUILT")
        assert lab.artifact()["built"] == token(built, "BUILT")

    def test_removing_the_declared_artifact_forces_a_rebuild(self, lab: Lab) -> None:
        first = token(lab.ok("lab", "report"), "BUILT")
        (lab.root / "build/report.json").unlink()

        rebuilt = lab.ok("lab", "report")

        assert "BUILT" in rebuilt.stdout
        assert token(rebuilt, "BUILT") != first

    def test_a_changed_input_forces_a_rebuild(self, lab: Lab) -> None:
        first = token(lab.ok("lab", "report"), "BUILT")
        (lab.root / "inputs/alpha.md").write_text("# Alpha\n\nalpha changed its tune\n")

        rebuilt = lab.ok("lab", "report")

        assert token(rebuilt, "BUILT") != first
        assert lab.artifact()["inputs"]["inputs/alpha.md"] == 6


class TestTheBoundaryThisExistsToMakeUsable:
    def test_the_framework_never_reads_the_artifact(self, lab: Lab) -> None:
        """The verdict is about the declared inputs, never the artifact's bytes.

        The job owns the format, the location and the contents; the framework's
        only interest is whether the declared ``generates`` path exists. Rewrite
        that file by hand and the job is still fresh — which is what makes
        "storing an artifact is the job's business" a boundary rather than a
        slogan. A framework-owned store could not be tested this way, because it
        would have to read the artifact to know it was valid.
        """
        lab.ok("lab", "report")
        (lab.root / "build/report.json").write_text(
            json.dumps({"built": "hand-edited", "inputs": {}, "total": 0})
        )

        warm = lab.ok("lab", "report")

        assert "state=skip_fresh" in warm.stdout
        assert token(warm, "CACHED") == "hand-edited"

    def test_a_job_without_the_opt_in_never_enters_its_body(self, lab: Lab) -> None:
        """The default is unchanged: a fresh job is skipped into silence."""
        lab.ok("lab", "baseline")

        skipped = lab.ok("lab", "baseline")

        assert "BUILT-BASELINE" not in skipped.stdout
        assert skipped.stdout.strip() == ""


class TestTheVerdictAndWhyAgree:
    def test_they_describe_the_same_run(self, lab: Lab) -> None:
        """A job and the person reading `func builtin why` must not disagree.

        `why` renders the guard pipeline's `GuardState`; the job reads the same
        state off `Freshness`. Both runs below are the same run described twice.
        """
        # Nothing has run yet, so the pipeline says WOULD RUN — and the run that
        # follows reads exactly that off its own verdict.
        stale = lab.run("builtin", "why", "lab.report")
        assert "WOULD RUN" in stale.stdout
        assert stale.returncode == 4  # ExitCode.STALE — `why` exits on its verdict
        cold = lab.ok("lab", "report")
        assert "state=run" in cold.stdout

        warm = lab.ok("lab", "report")
        assert "state=skip_fresh" in warm.stdout
        fresh = lab.ok("builtin", "why", "lab.report")
        assert "SKIP (up to date)" in fresh.stdout
