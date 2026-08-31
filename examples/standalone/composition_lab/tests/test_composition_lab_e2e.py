"""The composition lab, driven end to end as a real process, on both surfaces.

`test_composition_lab.py` pins what each job *declares*. This file runs them and
checks what actually happens — and runs everything **twice**, once through the
bare `func` CLI and once through the `main.py` app entry point.

Why both, and why subprocesses:

* **Two builders, one declaration set.** `func` has a pre-boot dispatch layer
  and builds job commands from the live signature; an app entry point has none
  of it, and builds them from cached descriptors on a warm boot. Those two have
  disagreed — on a config field's default, and on whether `--scope-id` existed
  at all, which left a gated walk on an app permanently unresumable. Anything
  that passes on one surface and fails on the other is the finding.
* **Freshness is only observable across processes.** A capability instance's
  ``repr`` carries its memory address, so an args-hash that embeds one is stable
  within a single interpreter and unstable between runs. An in-process test
  cannot see the defect that made every job re-run forever.
* Two ``FunctualizeApp`` instances over different directories in one interpreter
  leave the second discovering no jobs at all, so an in-process version passes
  alone and fails whenever another example's app is built first.

``XDG_CACHE_HOME`` is redirected per test: in standalone mode the runtime state
store lives under the user cache keyed by project path, not inside the project.
Without it one test would read another's freshness records.

The same sequences, as a readable transcript rather than assertions, are in
`../demo.sh`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_LAB = Path(__file__).parent.parent
_BIN = Path(sys.executable).parent

#: How each surface is invoked. The lab ships both, and every test below runs
#: against each in turn.
SURFACES = {
    "func": [str(_BIN / "func")],
    "app": [sys.executable, "main.py"],
}


class Lab:
    """An isolated copy of the lab, driven through one surface."""

    def __init__(self, root: Path, cache: Path, surface: str) -> None:
        self.root = root
        self.surface = surface
        self.argv = SURFACES[surface]
        self.env = {**os.environ, "XDG_CACHE_HOME": str(cache)}

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.argv, *args],
            cwd=self.root,
            env={**self.env, **env},
            capture_output=True,
            text=True,
        )

    def ok(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        proc = self.run(*args, **env)
        assert proc.returncode == 0, (
            f"[{self.surface}] `{' '.join(args)}` exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
        return proc

    @staticmethod
    def both(proc: subprocess.CompletedProcess[str]) -> str:
        """A job's `Log` goes to stderr and its `print` to stdout, so a
        stdout-only assertion silently drops half of what a command published."""
        return proc.stdout + proc.stderr

    @staticmethod
    def emitted(proc: subprocess.CompletedProcess[str]) -> list:
        """Every JSON document `Stdout.emit` wrote, in order."""
        docs = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith(("{", "[")):
                docs.append(json.loads(line))
        return docs


#: Never copied into a test's lab. `build/`, `dist/` and `.functualize/` are
#: gitignored, so they are absent in CI and present on the disk of anyone who
#: has run `demo.sh` — copying them would make every freshness assertion below
#: pass or fail depending on whose machine it ran on.
_GENERATED = shutil.ignore_patterns(
    "tests", "__pycache__", "build", "dist", ".functualize"
)


@pytest.fixture(params=sorted(SURFACES))
def lab(request: pytest.FixtureRequest, tmp_path: Path) -> Lab:
    """A clean lab per test, per surface."""
    root = tmp_path / "lab"
    shutil.copytree(_LAB, root, ignore=_GENERATED)
    return Lab(root, tmp_path / "cache", request.param)


class TestTheGraphRunsFromDeclarationsAlone:
    def test_a_cold_run_walks_the_whole_chain(self, lab: Lab) -> None:
        out = lab.both(lab.ok("lab", "publish"))
        assert "PARSED n=2 total=8" in out
        assert "REPORT title='Composition Lab' items=2" in out
        assert "PUBLISHED" in out
        assert (lab.root / "build/publish.stamp").is_file()

    def test_a_second_run_rebuilds_nothing(self, lab: Lab) -> None:
        """The defect the lab was extended for: a job taking `Log`/`Sources`
        could never report fresh, because the fingerprint key hashed the
        injected capability instances along with the real arguments."""
        lab.ok("lab", "publish")
        stamp = lab.root / "build/publish.stamp"
        first = stamp.stat().st_mtime_ns

        out = lab.both(lab.ok("lab", "publish"))
        assert "PUBLISHED" not in out, "the second run re-published"
        assert stamp.stat().st_mtime_ns == first

    def test_why_agrees_with_what_the_run_did(self, lab: Lab) -> None:
        """`why` used to hash `config=None` while the executor hashed the
        resolved config, so it reported "no previous run" after a real run."""
        lab.ok("lab", "publish")
        assert "up to date" in lab.both(lab.ok("builtin", "why", "lab.parse"))


class TestGeneratesIsAGlob:
    """`generates` entries are patterns, exactly as `sources` entries are.
    Tested as literal paths, `dist/*.whl` never exists, so the job reports
    "output missing" forever and rebuilds on every invocation."""

    def test_a_glob_target_makes_the_job_fresh_once_it_matches(self, lab: Lab) -> None:
        lab.ok("lab", "publish")
        first = lab.both(lab.ok("lab", "bundle"))
        assert "BUNDLED lab-0.1.0.tar.gz" in first
        assert (lab.root / "dist/lab-0.1.0.tar.gz").is_file()

        assert "BUNDLED" not in lab.both(lab.ok("lab", "bundle"))

    def test_deleting_the_matched_artifact_forces_a_rebuild(self, lab: Lab) -> None:
        lab.ok("lab", "publish")
        lab.ok("lab", "bundle")
        (lab.root / "dist/lab-0.1.0.tar.gz").unlink()

        assert "BUNDLED" in lab.both(lab.ok("lab", "bundle"))


class TestGroupOptionsAndForce:
    def test_force_overrides_freshness_and_the_group_flag_reaches_the_body(
        self, lab: Lab
    ) -> None:
        """`--strict` is declared once on the group and typed *mid-path*;
        `--force` runs a job that freshness would otherwise skip."""
        lab.ok("lab", "publish")
        lab.ok("lab", "bundle")
        assert "BUNDLED" not in lab.both(lab.ok("lab", "bundle"))

        out = lab.both(lab.ok("--force", "lab", "--strict", "bundle"))
        assert "BUNDLED lab-0.1.0.tar.gz strict=True" in out

    def test_force_alone_reruns_without_setting_the_flag(self, lab: Lab) -> None:
        lab.ok("lab", "publish")
        lab.ok("lab", "bundle")
        out = lab.both(lab.ok("--force", "lab", "bundle"))
        assert "strict=False" in out

    def test_a_second_group_reads_the_group_option_from_the_environment(
        self, lab: Lab
    ) -> None:
        """`check.signoff` accepts `LabOptions` but lives outside the `lab`
        group, so the mid-path flag is not on its command line. A `GroupOptions`
        subclass is a type any job may accept; `group=` decides only where the
        flag is *parsed*. The other layers of the ladder still reach it."""
        lab.ok("lab", "publish")
        lab.ok("lab", "bundle")

        plain = lab.emitted(lab.ok("check", "signoff"))[-1]
        assert [v["verdict"] for v in plain] == ["unapproved"]

        # `GROUP__FIELD`, with a DOUBLE underscore: the prefix is the class's
        # `group=`, not the job's name. The single-underscore spelling also
        # resolves, but it is the job-config form and not what a group option
        # documents — asserting the documented one is the point.
        strict = lab.emitted(lab.ok("check", "signoff", LAB__STRICT="true"))[-1]
        assert [v["verdict"] for v in strict] == ["unapproved", "strict-mode"]


class TestRefusalIsNeitherACrashNorASkip:
    def test_a_failing_precondition_refuses_with_exit_3(self, lab: Lab) -> None:
        proc = lab.run("lab", "gated")
        assert proc.returncode == 3
        assert "GATED BODY RAN" not in proc.stdout
        assert "Refused" in lab.both(proc)

    def test_declared_sources_matching_nothing_also_refuse(self, lab: Lab) -> None:
        proc = lab.run("lab", "verify")
        assert proc.returncode == 3
        assert "VERIFY BODY RAN" not in proc.stdout

    def test_declaring_no_sources_is_unaffected(self, lab: Lab) -> None:
        """The distinction: "declared and matched nothing" refuses, "declared
        nothing" does not."""
        assert "COUNTER n=" in lab.both(lab.ok("lab", "counter"))

    def test_a_dependency_is_not_a_precondition(self, lab: Lab) -> None:
        """`check.signoff` declares `Deps("lab.bundle")` and no guard for the
        archive's presence, because such a guard could never fire: the
        dependency has already produced it by the time guards are evaluated.

        Run cold, from a tree with no `build/` and no `dist/`, `check signoff`
        therefore succeeds — and pulls the entire `lab` chain across the group
        boundary to do it."""
        assert not (lab.root / "dist").exists()

        out = lab.both(lab.ok("check", "signoff"))

        assert "PARSED" in out and "PUBLISHED" in out and "BUNDLED" in out
        assert "SIGNOFF verdicts=1" in out
        assert (lab.root / "dist/lab-0.1.0.tar.gz").is_file()


class TestTheStatusGuardAndsWithStaleness:
    def test_a_satisfied_status_guard_does_not_mask_changed_sources(
        self, lab: Lab
    ) -> None:
        lab.ok("lab", "publish")
        report = lab.root / "build/report.md"
        report.write_text(report.read_text() + "# touched\n")

        why = lab.run("builtin", "why", "lab.publish")
        assert "status satisfied, but sources changed" in lab.both(why)
        assert why.returncode == 4, (
            "`why` reports a stale job with ExitCode.STALE, so a script can "
            "branch on it"
        )
        assert "PUBLISHED" in lab.both(lab.ok("lab", "publish"))


class TestTheGatedWalk:
    """The defect that made this lab need a second surface at all: `--scope-id`
    was a pre-command global of `func` only, so a gated walk on an app entry
    point blocked, accepted a deposit, and could never be run with that scope.
    """

    GATE = "approval-gate"

    def _scope_of(self, proc: subprocess.CompletedProcess[str]) -> str:
        match = re.search(r"scope '([0-9a-f]+)'", Lab.both(proc))
        assert match, Lab.both(proc)
        return match.group(1)

    def test_the_walk_blocks_with_a_runnable_command(self, lab: Lab) -> None:
        proc = lab.run("lab", "release")
        assert proc.returncode == 5, f"expected BLOCKED (5), got {proc.returncode}"
        out = lab.both(proc)
        assert f"gate '{self.GATE}'" in out
        # The message must name the flag AND its position, or a reader cannot
        # act on it. `--scope-id` is post-command on both surfaces.
        assert re.search(r"lab release --scope-id [0-9a-f]+", out), out

    def test_a_deposited_input_lets_the_same_walk_finish(self, lab: Lab) -> None:
        blocked = lab.run("lab", "release")
        assert blocked.returncode == 5
        scope = self._scope_of(blocked)

        lab.ok(
            "builtin",
            "workflow",
            "resume",
            scope,
            self.GATE,
            "--input",
            json.dumps({"note": "ship it", "author": "ai"}),
        )

        resumed = lab.run("lab", "release", "--scope-id", scope)
        assert resumed.returncode == 0, (
            f"[{lab.surface}] the deposited input was never read\n"
            f"{resumed.stdout}\n{resumed.stderr}"
        )
        assert "RELEASE complete" in lab.both(resumed)

    def test_a_bare_rerun_opens_a_new_scope_instead_of_continuing(
        self, lab: Lab
    ) -> None:
        """Resuming is opt-in. Without `--scope-id` the walk starts over, which
        is why the flag not existing on a surface was fatal rather than
        cosmetic."""
        first = lab.run("lab", "release")
        second = lab.run("lab", "release")
        assert first.returncode == second.returncode == 5
        assert self._scope_of(first) != self._scope_of(second)
