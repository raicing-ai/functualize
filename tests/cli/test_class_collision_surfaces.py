"""The strict collision as the CLI and the programmatic caller see it.

`contracts.md` § C5: when at least one claimant of a name is a method of a job
class, *neither* claimant is registered and the other jobs still are. So the
name is declared, is not a job, and is not a typo — three facts that sit badly
together on a command line, which is why the surfaces below each have to say
which one they are answering.

Nothing here asserts against `collisions.py`: every fact is read back from
`func`, from `builtin info`, or from the app. A defect in the projection, in the
refusal, or in the error conversion shows up as a wrong sentence or a wrong
exit code rather than as a disagreement with the resolver's internals.

The plain-function half is a *mixed* project on purpose — one strict collision
and one `JobNameCollision` in the same tree. Two shapes now travel through
`collision_projection` to one catalog, and the point is that neither changed the
other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import surfaces

#: The class half of the collision. `start` is the name both sides claim;
#: `stop` is the control — it must keep running while `start` does not.
JOBS = '''\
from pydantic import BaseModel

from functualize.job import Shell, job


@job(group="pg")
class Postgres(BaseModel):
    """A job class whose ``start`` collides with a plain function."""

    def start(self, sh: Shell) -> None:
        """Start the cluster."""
        print("class start ran")

    def stop(self, sh: Shell) -> None:
        """Stop the cluster."""
        print("class stop ran")
'''

#: The plain-function half: a module-level job in the same group, named
#: `start`, so its canonical name is `pg.start` — the class method's name.
LEGACY = '''\
"""A module function claiming the name a class method also claims."""

JOB_GROUP = "pg"


def start() -> None:
    """The second claimant of ``pg.start``."""
    print("legacy start ran")
'''

#: Two plain functions colliding on `build-wheel`. C5's last line keeps this
#: record, its keys and its rendering exactly as they were.
TWO_SPELLINGS = '''\
"""Two functions, one job name."""


def build_wheel() -> None:
    """Build the wheel (snake_case spelling)."""


def buildWheel() -> None:  # noqa: N802
    """Build the wheel (camelCase spelling)."""
'''

PLAIN_KEYS = {
    "canonical_name",
    "dropped_python_name",
    "dropped_source_file",
    "registered_python_name",
    "registered_source_file",
}

CATALOG_KEYS = {"name", "group", "summary", "parameters", "requires_tty"}


@pytest.fixture()
def project(project_tree) -> Path:
    """The C5 project: one job class, one plain function, one shared name."""
    return project_tree(
        pyproject='[project]\nname = "classcollision"\nversion = "0.1.0"\n'
        "dependencies = []\n",
        jobs={"pg.py": JOBS, "legacy.py": LEGACY},
    )


def _failures(cli_run, cwd: Path) -> list[dict]:
    result = cli_run(["builtin", "info", "--json"], cwd=cwd)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)["discovery_failures"]


def _strict_message(cli_run, cwd: Path) -> str:
    """The finding's own text — the one every refusing surface must print."""
    (failure,) = [
        item
        for item in _failures(cli_run, cwd)
        if item["error_type"] == "ClassJobNameCollision"
    ]
    return failure["message"]


def _catalog(cli_run, cwd: Path) -> list[dict]:
    result = cli_run(["builtin", "info", "jobs", "--json"], cwd=cwd)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


class TestTheRestOfTheProjectStillWorks:
    """`contracts.md` § C5, bullet one — the other jobs register."""

    @surfaces("func")
    def test_a_sibling_method_runs(self, cli_run, project: Path) -> None:
        result = cli_run(["pg", "stop"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "class stop ran" in result.stdout

    @surfaces("func")
    def test_the_catalog_holds_the_surviving_method(
        self, cli_run, project: Path
    ) -> None:
        names = [row["name"] for row in _catalog(cli_run, project)]

        assert "pg.stop" in names


class TestTheRefusal:
    """Both spellings of the name exit 2 with the finding's own text."""

    @surfaces("func")
    @pytest.mark.parametrize("argv", (["pg", "start"], ["pg.start"]))
    def test_it_exits_usage_and_names_both_definitions(
        self, cli_run, project: Path, argv: list[str]
    ) -> None:
        message = _strict_message(cli_run, project)

        result = cli_run(argv, cwd=project)

        # 2 is ExitCode.USAGE: the name is real, the invocation is well formed,
        # and nothing is registered under it: the same category as a bad flag,
        # not the runtime failure code a broken job exits with.
        assert result.exit_code == 2, result.stderr
        assert message in result.stderr
        # Named by definition *and* by file, because `python_name` is `start`
        # for both claimants and the class name is the only thing that tells
        # them apart.
        assert "'start'" in result.stderr
        assert "'Postgres.start'" in result.stderr
        assert "legacy.py" in result.stderr
        assert "pg.py" in result.stderr
        # Not a typo, so the guess is worse than useless: a fuzzy suggestion
        # would name a job the user did not type.
        assert "Did you mean" not in result.stderr

    @surfaces("func")
    def test_a_name_nobody_claimed_still_reads_as_unknown(
        self, cli_run, project: Path
    ) -> None:
        result = cli_run(["pg", "missing"], cwd=project)

        assert result.exit_code == 1
        assert "Unknown command 'missing'" in result.stderr


class TestTheListing:
    """`contracts.md` § C5, bullet two — `builtin info` names both sides."""

    @surfaces("func")
    def test_the_human_catalog_prints_the_finding(self, cli_run, project: Path) -> None:
        message = _strict_message(cli_run, project)

        result = cli_run(["builtin", "info", "jobs"], cwd=project)

        assert result.exit_code == 0, result.stderr
        assert "pg.start" in result.stdout
        assert message in result.stdout
        assert "pg.stop" in result.stdout

    @surfaces("func")
    def test_the_default_info_lists_the_failure(self, cli_run, project: Path) -> None:
        result = cli_run(["builtin", "info"], cwd=project)

        assert result.exit_code == 0, result.stderr
        # The rich table folds the message to the terminal width, so the
        # sentence is asserted by its parts rather than as one line. The exact
        # text is pinned on the plain and JSON surfaces above.
        rendered = result.stdout + result.stderr
        assert "pg.start" in rendered
        assert "declared twice" in rendered
        assert "legacy.py" in rendered
        assert "pg.py" in rendered

    @surfaces("func")
    def test_the_plain_report_says_the_same_thing(self, cli_run, project: Path) -> None:
        """Piped output is the third renderer, and it must not be the one that
        forgets to say why the name is missing.
        """
        message = _strict_message(cli_run, project)

        result = cli_run(
            ["builtin", "info"], cwd=project, env={"FUNCTUALIZE_CLI_OUTPUT": "plain"}
        )

        assert result.exit_code == 0, result.stderr
        assert "discovery failures (1):" in result.stdout
        assert message in result.stdout
        assert "pg.start" in result.stdout

    @surfaces("func")
    def test_the_json_payload_keeps_its_four_keys(self, cli_run, project: Path) -> None:
        """C5's four-key payload is the report contract; nothing was added."""
        (failure,) = [
            item
            for item in _failures(cli_run, project)
            if item["error_type"] == "ClassJobNameCollision"
        ]

        assert set(failure) == {"module", "path", "error_type", "message"}
        assert failure["path"].endswith("legacy.py")
        assert "Postgres.start" in failure["message"]
        assert "pg.py" in failure["message"]

    @surfaces("func")
    def test_the_catalog_row_carries_the_third_shape(
        self, cli_run, project: Path
    ) -> None:
        """No descriptor exists, so the row that names the collision is the
        catalog's — the detail view has nothing honest to say about a name
        nobody registered.
        """
        rows = {row["name"]: row for row in _catalog(cli_run, project)}

        assert set(rows) >= {"pg.start", "pg.stop"}
        row = rows["pg.start"]
        assert set(row) == CATALOG_KEYS | {"collisions"}
        assert row["group"] == "pg"
        (collision,) = row["collisions"]
        assert set(collision) == {"canonical_name", "claimants", "message"}
        assert collision["canonical_name"] == "pg.start"
        assert {claimant["name"] for claimant in collision["claimants"]} == {
            "start",
            "Postgres.start",
        }
        assert {
            Path(claimant["source_file"]).name for claimant in collision["claimants"]
        } == {"legacy.py", "pg.py"}
        assert collision["message"] == _strict_message(cli_run, project)


class TestTheProgrammaticCaller:
    """`contracts.md` § C5's last clause: same text, existing failure mode."""

    @pytest.fixture()
    def app(self, project: Path):
        from functualize.app import FunctualizeApp, JobSources

        jobs = project / ".functualize" / "jobs"
        return FunctualizeApp(
            "classcollision",
            job_sources=JobSources(directories=[str(jobs)], lazy=False),
        )

    def test_invoke_raises_job_not_found_with_the_finding_text(self, app) -> None:
        from functualize._cli.info import discovery_failures
        from functualize._engine.capabilities.invoke import WiredInvoke
        from functualize._types.errors import JobNotFoundError

        (failure,) = [
            item
            for item in discovery_failures(app)
            if item["error_type"] == "ClassJobNameCollision"
        ]
        invoke = WiredInvoke(
            execution_engine=app.execution_engine, invoke_depth=0, max_invoke_depth=10
        )

        with pytest.raises(JobNotFoundError) as raised:
            invoke("pg.start")

        assert str(raised.value) == failure["message"]

    def test_an_unclaimed_name_keeps_the_failure_it_raised(self, app) -> None:
        """The conversion is scoped to the strict name: every other unknown
        name fails exactly as it did, so no caller's `except` changes meaning.
        """
        from functualize._engine.capabilities.invoke import WiredInvoke

        invoke = WiredInvoke(
            execution_engine=app.execution_engine, invoke_depth=0, max_invoke_depth=10
        )

        with pytest.raises(KeyError):
            invoke("pg.missing")

    def test_execute_fails_the_way_it_does_for_any_unknown_name(self, app) -> None:
        from functualize.app.core import request_for

        with pytest.raises(KeyError):
            app.execute(request_for("pg.missing"))
        with pytest.raises(KeyError):
            app.execute(request_for("pg.start"))


class TestAPlainCollisionIsUnchanged:
    """C5's last line, on a tree that holds both shapes at once."""

    @pytest.fixture()
    def mixed(self, project_tree) -> Path:
        return project_tree(
            pyproject='[project]\nname = "mixed"\nversion = "0.1.0"\n'
            "dependencies = []\n",
            jobs={
                "pg.py": JOBS,
                "legacy.py": LEGACY,
                "wheels.py": TWO_SPELLINGS,
            },
        )

    @surfaces("func")
    def test_the_plain_notice_renders_as_before(self, cli_run, mixed: Path) -> None:
        result = cli_run(["builtin", "info", "jobs"], cwd=mixed)

        assert result.exit_code == 0, result.stderr
        assert "JobNameCollision: build-wheel:" in result.stdout
        assert "was dropped. Rename one job." in result.stdout
        assert "wheels.py" in result.stdout
        # And the strict row is still there, in the same listing.
        assert "pg.start" in result.stdout

    @surfaces("func")
    def test_the_plain_record_keeps_its_five_keys(self, cli_run, mixed: Path) -> None:
        rows = {row["name"]: row for row in _catalog(cli_run, mixed)}

        (collision,) = rows["build-wheel"]["collisions"]
        assert set(collision) == PLAIN_KEYS
        assert collision["canonical_name"] == "build-wheel"
        assert rows["build-wheel"]["name"] == collision["canonical_name"]
        assert not rows["build-wheel"].get("claimants")

        (strict,) = rows["pg.start"]["collisions"]
        assert set(strict) == {"canonical_name", "claimants", "message"}

    @surfaces("func")
    def test_the_catalog_stays_sorted(self, cli_run, mixed: Path) -> None:
        names = [row["name"] for row in _catalog(cli_run, mixed)]

        assert names == sorted(names)
