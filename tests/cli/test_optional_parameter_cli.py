"""Optional job parameters reach both public CLI entry points."""

from __future__ import annotations

import pytest

_JOBS = '''\
from typing import Annotated, Optional

from functualize.job import Option, RunContext, TTY


def greet(name: str, greeting: str | None = None) -> None:
    """Greet someone."""
    print(f"GREET {greeting or 'hello'} {name}")


def typed(name: str, greeting: Optional[str] = None) -> None:
    """Use the typing.Optional spelling."""
    print(f"TYPED {greeting or 'hello'} {name}")


def volume(loud: bool | None = None) -> None:
    """Show the optional boolean value."""
    print(f"LOUD {loud!r}")


def collision(loud: bool | None = None, no_loud: bool = False) -> None:
    """Show ownership of the negative spelling."""
    print(f"VALUES {loud!r} {no_loud!r}")


def marked(name: str, greeting: Annotated[Optional[str], Option("--greeting")] = None) -> None:
    """Keep the explicit option spelling."""
    print(f"MARKED {greeting or 'hello'} {name}")


def injected(name: str, rc: RunContext | None = None, tty: TTY | None = None) -> None:
    """Optional capabilities remain injected."""
    print(f"INJECTED {name}")
'''


@pytest.fixture
def optional_project(project_tree):
    return project_tree(jobs={"optional.py": _JOBS})


@pytest.mark.parametrize(
    "job, option",
    [("greet", "--greeting"), ("typed", "--greeting"), ("volume", "--loud")],
)
def test_optional_options_appear_in_help(
    cli_run, optional_project, job, option
) -> None:
    result = cli_run([job, "--help"], cwd=optional_project)
    assert result.exit_code == 0, result.stderr
    assert option in result.stdout


@pytest.mark.parametrize(
    "job, argv, expected",
    [
        ("greet", ["ada"], "GREET hello ada"),
        ("greet", ["--greeting", "hi", "ada"], "GREET hi ada"),
        ("typed", ["ada"], "TYPED hello ada"),
        ("typed", ["--greeting", "hi", "ada"], "TYPED hi ada"),
        ("volume", [], "LOUD None"),
        ("volume", ["--loud"], "LOUD True"),
        ("volume", ["--no-loud"], "LOUD False"),
        ("collision", [], "VALUES None False"),
        ("collision", ["--loud"], "VALUES True False"),
        ("collision", ["--no-loud"], "VALUES None True"),
        ("marked", ["--greeting", "hi", "ada"], "MARKED hi ada"),
    ],
)
def test_optional_values_reach_jobs(
    cli_run, optional_project, job, argv, expected
) -> None:
    result = cli_run([job, *argv], cwd=optional_project)
    assert result.exit_code == 0, result.stderr
    assert expected in result.stdout


def test_documented_optional_capabilities_have_no_flags(
    cli_run, optional_project
) -> None:
    result = cli_run(["injected", "--help"], cwd=optional_project)
    assert result.exit_code == 0, result.stderr
    assert "--rc" not in result.stdout
    assert "--tty" not in result.stdout


def test_optional_value_survives_cached_discovery(cli_run, optional_project) -> None:
    first = cli_run(["greet", "--greeting", "hi", "ada"], cwd=optional_project)
    second = cli_run(["greet", "--greeting", "again", "ada"], cwd=optional_project)
    assert first.exit_code == second.exit_code == 0
    assert "GREET hi ada" in first.stdout
    assert "GREET again ada" in second.stdout
