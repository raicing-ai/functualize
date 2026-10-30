"""The job-classes lab, driven as a real process.

`jobs/pg.py`, `jobs/legacy.py` and `jobs/reports.py` declare three things a job
class has to get right: methods becoming names, one configuration section shared
by every method of a class, tags merging outward, and a name two definitions
claim. This file runs the real `func` CLI over a copy of the lab and checks what
actually happens — including the surfaces where the collision has to be visible
and the one where it must not be.

Why a subprocess rather than calls into the class:

* A job class's instance is built by the engine from resolved configuration, so
  calling a method by hand would skip the configuration resolution this form
  exists to provide.
* The collision is a discovery-level verdict with three visible surfaces (exit
  code, the `builtin info` listing, the absence of a command). None of them
  exists inside a direct call.

Each test copies the lab into `tmp_path` with its own `XDG_CACHE_HOME` and
`XDG_CONFIG_HOME`: the scan writes a cache, and a shared one would let one
test's listing answer another's question.
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
_FUNC = Path(sys.executable).parent / "func"

#: Never copied into a test's lab: the tests themselves, bytecode, and any cache
#: an earlier manual run of the README left behind.
_GENERATED = shutil.ignore_patterns("tests", "__pycache__", ".functualize", ".venv")


class Lab:
    """An isolated copy of the lab, driven through the real CLI."""

    def __init__(self, root: Path, cache: Path, config: Path) -> None:
        self.root = root
        # `plain` keeps the output stable off a TTY; the two XDG roots keep the
        # scan cache and any user config out of the assertions.
        self.env = {
            **os.environ,
            "XDG_CACHE_HOME": str(cache),
            "XDG_CONFIG_HOME": str(config),
            "FUNCTUALIZE_CLI_OUTPUT": "plain",
        }

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(_FUNC), *args],
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

    def jobs(self) -> dict[str, dict]:
        """`builtin info --json` rows by name — the listing every surface shares."""
        proc = self.ok("builtin", "info", "--json")
        return {row["name"]: row for row in json.loads(proc.stdout)["jobs"]}


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    root = tmp_path / "lab"
    shutil.copytree(_LAB, root, ignore=_GENERATED)
    return Lab(root, tmp_path / "cache", tmp_path / "config")


class TestAJobClassRuns:
    def test_a_method_runs_against_the_class_configuration_section(
        self, lab: Lab
    ) -> None:
        """`host` and `port` are fields of the class, resolved from `[pg]`.

        The body receives only what the method declares — `force` — so a value
        that arrived from `config.base.toml` proves the engine built the instance
        from the class's own section rather than passing defaults.
        """
        proc = lab.ok("pg", "stop", "--force")

        assert proc.stdout.strip() == "stopped db.internal:6543 (force=True)"

    def test_a_second_method_of_the_same_class_shares_that_section(
        self, lab: Lab
    ) -> None:
        proc = lab.ok("pg", "backup")

        assert proc.stdout.strip() == "backed up db.internal:6543 to s3://backups"

    def test_a_class_named_by_its_own_group_nests_under_the_module_group(
        self, lab: Lab
    ) -> None:
        """`Reports` has a bare `@job`, so its group is its class name.

        `JOB_GROUP = "data"` in the module stays the namespace above it, which is
        why this takes two words on the command line.
        """
        proc = lab.ok("data", "reports", "generate", "--kind", "csv")

        assert proc.stdout.strip() == "generated 2026-09 report as csv"


class TestTagsMergeOutward:
    def test_tags_are_the_method_then_the_class_then_the_base(self, lab: Lab) -> None:
        """Method → class `@job(tags=…)` → `JOB_TAGS` along the MRO, nearest first."""
        assert lab.jobs()["pg.backup"]["tags"] == [
            "method-tag",
            "class-tag",
            "database",
        ]

    def test_a_method_without_its_own_tags_still_takes_the_class_ones(
        self, lab: Lab
    ) -> None:
        assert lab.jobs()["pg.stop"]["tags"] == ["class-tag", "database"]

    def test_a_base_that_is_not_a_job_class_still_contributes_its_job_tags(
        self, lab: Lab
    ) -> None:
        """`Database` carries no `@job`, so it is not a job class — but its
        `JOB_TAGS` reaches the concrete class's jobs. The opt-in is not inherited;
        the metadata is."""
        assert lab.jobs()["pg.stop"]["tags"] == ["class-tag", "database"]
        assert lab.jobs()["pg.backup"]["tags"][-1] == "database"


class TestANameTwoDefinitionsClaim:
    def test_the_collided_name_exits_two_and_names_both_definitions(
        self, lab: Lab
    ) -> None:
        """A class-derived claimant makes the collision strict: neither runs."""
        proc = lab.run("pg", "start")

        assert proc.returncode == 2
        assert proc.stdout == ""
        assert "Job name 'pg.start' is declared twice" in proc.stderr
        assert "'start'" in proc.stderr
        assert "'Postgres.start'" in proc.stderr
        assert "jobs/legacy.py" in proc.stderr
        assert "jobs/pg.py" in proc.stderr
        assert "Neither is registered." in proc.stderr

    def test_the_collision_is_a_row_in_the_job_catalog(self, lab: Lab) -> None:
        proc = lab.ok("builtin", "info", "jobs", "--json")
        rows = {row["name"]: row for row in json.loads(proc.stdout)}

        assert set(rows) == {
            "data.reports.generate",
            "pg.start",
            "pg.stop",
            "pg.backup",
        }
        collided = rows["pg.start"]
        assert (
            collided["summary"] == "Name collision: neither definition is registered."
        )
        (detail,) = collided["collisions"]
        assert detail["canonical_name"] == "pg.start"
        assert [claimant["name"] for claimant in detail["claimants"]] == [
            "start",
            "Postgres.start",
        ]
        assert detail["claimants"][0]["source_file"].endswith("jobs/legacy.py")
        assert detail["claimants"][1]["source_file"].endswith("jobs/pg.py")

    def test_the_collision_is_reported_as_a_discovery_failure(self, lab: Lab) -> None:
        """The project still boots: three jobs registered, one failure reported."""
        proc = lab.ok("builtin", "info")

        assert "ClassJobNameCollision" in proc.stdout
        assert "jobs (3):" in proc.stdout
        assert "pg.start" not in proc.stdout.split("jobs (3):", 1)[1]

    def test_a_collided_name_is_not_a_command(self, lab: Lab) -> None:
        """A group listing shows what can run, so the refused name is absent."""
        proc = lab.ok("pg")

        command_lines = proc.stdout.split("Commands:", 1)[1]
        listed = {
            line.split()[0]
            for line in command_lines.splitlines()
            if line.startswith("  ") and line.strip()
        }

        assert listed == {"backup", "stop"}

    def test_the_surviving_jobs_of_the_colliding_class_still_run(
        self, lab: Lab
    ) -> None:
        """Only the contested name is withdrawn — the class is not disqualified."""
        assert lab.ok("pg", "stop").stdout.startswith("stopped")
        assert lab.ok("pg", "backup").stdout.startswith("backed up")


class TestTheDocumentedRefusal:
    def test_a_dotted_name_crosses_a_group_and_is_refused(self, lab: Lab) -> None:
        """Two levels are spelled with two words; the dotted identity is not a path.

        The README walks the reader through the earlier steps first, so the scan
        already knows `data.reports` is a group when this line runs — that is what
        turns the answer into the "crosses a group" refusal instead of a plain
        `Unknown command`. Do the same warm-up here rather than assert on a state
        a reader never sees.
        """
        lab.ok("data")

        proc = lab.run("data.reports", "generate")

        assert proc.returncode == 2
        assert "crosses a group" in proc.stderr
        assert "func data reports" in proc.stderr
