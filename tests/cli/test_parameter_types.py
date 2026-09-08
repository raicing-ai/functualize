"""A job can take a Path, a UUID, a date, a Decimal or an Enum.

Found while landing the Subjects guide, whose example carried the note "a bare
`Path` parameter fails at boot — take `str` and convert". Measured on 0.2.3
that undersold it:

    def backup(to: Path) -> None: ...

    $ func backup --to /tmp/x
    Error: Job 'backup' could not be loaded: DI validation failed with 1 error(s):
      1. No provider for Path (job: '<unknown>', available: [])

Everything that was not a builtin was assumed to be a dependency to inject, so
`pathlib.Path` — close to the most ordinary parameter a task runner takes — was
"everything else". `UUID`, `date`, `Decimal` and any `Enum` failed the same
way, and `Annotated[Path, Option(...)]`, the marker that says *this is a
command-line option*, did not help.

**And it took the whole CLI down on a cold boot**, because the gate raised for
the app rather than for the job. Measured, one bad job present:

    func fine (an unrelated healthy job)  -> DIValidationError traceback
    func builtin info                     -> DIValidationError traceback
    func --help                            -> ok

Warm boots masked it — cached jobs register as lazy proxies and validation
skips proxies — so it presented as intermittent: after a cache clear, on a
fresh clone, in CI.

Four separate layers classified a job signature and each kept its own answer.
This suite drives the outcome through the real CLI so a fifth cannot appear
without failing here.
"""

from __future__ import annotations

import json

import pytest

VALUE_TYPE_JOBS = '''
"""Jobs taking standard-library value types."""

import enum
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


def backup(to: Path) -> None:
    """Takes a Path."""
    print(f"{type(to).__name__}:{to}")


def tag(u: UUID) -> None:
    """Takes a UUID."""
    print(f"{type(u).__name__}:{u}")


def when(d: date) -> None:
    """Takes a date."""
    print(f"{type(d).__name__}:{d}")


def at(ts: datetime) -> None:
    """Takes a datetime."""
    print(f"{type(ts).__name__}:{ts}")


def price(p: Decimal) -> None:
    """Takes a Decimal."""
    print(f"{type(p).__name__}:{p}")


def paint(c: Color) -> None:
    """Takes an Enum."""
    print(f"chose:{c}")
'''

UNSATISFIABLE = '''
"""One job with a real unregistered dependency, and one healthy neighbour."""


class Database:
    """Nothing registers a provider for this."""


def deploy(db: Database) -> None:
    """Cannot run: its dependency is unsatisfiable."""


def fine() -> None:
    """An unrelated job that must keep working."""
    print("fine ran")
'''

MARKED_UNLISTED_TYPE = '''
"""An author overruling the type list with an explicit marker."""

from typing import Annotated

from functualize.job import Option


class Widget:
    def __init__(self, raw: str) -> None:
        self.raw = raw


def marked(w: Annotated[Widget, Option(help="a widget")]) -> None:
    """Takes a type no list mentions, because the author said so."""
    print(f"{type(w).__name__}:{w.raw}")
'''


@pytest.mark.parametrize(
    ("job", "argv", "expected"),
    [
        ("backup", ["/tmp/x"], "PosixPath:/tmp/x"),
        (
            "tag",
            ["12345678-1234-5678-1234-567812345678"],
            "UUID:12345678-1234-5678-1234-567812345678",
        ),
        ("when", ["2026-09-07"], "date:2026-09-07"),
        ("at", ["2026-09-07T12:30:00"], "datetime:2026-09-07 12:30:00"),
        ("price", ["19.99"], "Decimal:19.99"),
    ],
)
class TestValueTypesRunAndConvert:
    """A1, A2. The value must arrive as its annotated type, not as a string:
    a job that has to call `str`-to-`Path` itself has gained nothing.
    """

    def test_cold(self, cli_run, project_tree, job, argv, expected) -> None:
        root = project_tree(jobs={"jobs.py": VALUE_TYPE_JOBS})

        result = cli_run([job, *argv], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert expected in result.stdout

    def test_warm(self, cli_run, project_tree, job, argv, expected) -> None:
        """The same invocation twice. Cold and warm resolve the parameter
        through different code (live signature vs cached field), and this file
        exists partly because those two disagreed."""
        root = project_tree(jobs={"jobs.py": VALUE_TYPE_JOBS})
        cli_run([job, *argv], cwd=root)

        result = cli_run([job, *argv], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert expected in result.stdout


class TestEnumParameters:
    def test_an_enum_member_is_offered_as_a_choice(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"jobs.py": VALUE_TYPE_JOBS})

        result = cli_run(["paint", "--help"], cwd=root)

        assert result.exit_code == 0
        assert "red" in result.stdout and "blue" in result.stdout

    def test_a_valid_choice_runs(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"jobs.py": VALUE_TYPE_JOBS})

        result = cli_run(["paint", "red"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "chose:" in result.stdout

    def test_an_invalid_choice_is_rejected(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"jobs.py": VALUE_TYPE_JOBS})

        result = cli_run(["paint", "green"], cwd=root)

        assert result.exit_code != 0


class TestAMalformedValueIsAUsageError:
    """A10. Click calls the annotation to convert, and `date("2026-09-07")`
    raises `TypeError: 'str' object cannot be interpreted as an integer` — an
    internal-looking traceback for a plain usage mistake."""

    def test_it_names_the_parameter_and_the_expected_form(
        self, cli_run, project_tree
    ) -> None:
        root = project_tree(jobs={"jobs.py": VALUE_TYPE_JOBS})

        result = cli_run(["when", "notadate"], cwd=root)

        assert result.exit_code != 0
        combined = result.stdout + result.stderr
        assert "notadate" in combined
        assert "ISO-8601" in combined
        assert "Traceback" not in combined


class TestAnExplicitMarkerOutranksTheTypeList:
    """A3. The list is a convenience, not a ceiling: an author who says
    `Option(...)` has stated the intent, and the framework used to overrule
    them and then report the value they passed as an unexpected argument."""

    def test_an_unlisted_type_becomes_an_option(self, cli_run, project_tree) -> None:
        root = project_tree(jobs={"jobs.py": MARKED_UNLISTED_TYPE})

        result = cli_run(["marked", "--help"], cwd=root)

        assert result.exit_code == 0
        assert "--w" in result.stdout

    def test_the_value_reaches_the_job_as_that_type(
        self, cli_run, project_tree
    ) -> None:
        root = project_tree(jobs={"jobs.py": MARKED_UNLISTED_TYPE})

        result = cli_run(["marked", "--w", "hello"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "Widget:hello" in result.stdout


class TestAGenuineDependencyStillFails:
    """A4, A5, A6. The loudness is kept; the blast radius is not."""

    def test_the_unrelated_job_still_runs(self, cli_run, project_tree) -> None:
        """A5. This is the criterion that matters most: it used to be a
        traceback."""
        root = project_tree(jobs={"jobs.py": UNSATISFIABLE})

        result = cli_run(["fine"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "fine ran" in result.stdout

    def test_builtin_info_still_works(self, cli_run, project_tree) -> None:
        """A6. Under the old behaviour the two commands an operator would
        reach for to find out what was wrong were the two the fault killed."""
        root = project_tree(jobs={"jobs.py": UNSATISFIABLE})

        result = cli_run(["builtin", "info"], cwd=root)

        assert result.exit_code == 0, result.stderr

    def test_the_reason_is_reported(self, cli_run, project_tree) -> None:
        """A7. Through the same key as a module that failed to import and a
        job-name collision — one list answers "why can't I run my job?"."""
        root = project_tree(jobs={"jobs.py": UNSATISFIABLE})

        result = cli_run(["builtin", "info", "--json"], cwd=root)

        report = json.loads(result.stdout)
        unsatisfiable = [
            f
            for f in report["discovery_failures"]
            if f["error_type"] == "UnsatisfiableParameter"
        ]
        assert len(unsatisfiable) == 1
        assert "deploy" in unsatisfiable[0]["message"]

    def test_invoking_it_names_the_job_and_the_parameter(
        self, cli_run, project_tree
    ) -> None:
        """A8, A9. The message used to say `job: '<unknown>'` even though the
        validator walking the signature knew exactly which parameter of which
        job had asked — it was built inside the registry, which is handed a
        type and nothing else."""
        root = project_tree(jobs={"jobs.py": UNSATISFIABLE})

        result = cli_run(["deploy"], cwd=root)

        combined = result.stdout + result.stderr
        assert result.exit_code != 0
        assert "'db'" in combined
        assert "'deploy'" in combined
        assert "Traceback" not in combined

    def test_help_still_works(self, cli_run, project_tree) -> None:
        """A12. It already did — the one command that survived."""
        root = project_tree(jobs={"jobs.py": UNSATISFIABLE})

        assert cli_run(["--help"], cwd=root).exit_code == 0
