"""A group boolean can be turned off mid-path, on both surfaces.

`func deploy --strict run` reaches a **pre-boot** parser that click never sees;
an app's own entry point reaches click directly. Two parsers, one declaration —
so every cell here runs on both, which is the shape
`test_adapter_entry_point_parity.py` exists to enforce.

The `--strict=false` cells are the parity defect this closes. `func` used to
accept an inline value on a boolean because its parser never asked whether the
flag was one, while click refused the identical command. One spelling worked on
exactly one of the two surfaces, and no test covered it.
"""

from __future__ import annotations

from tests.conftest import surfaces

_JOBS = """
from pydantic import BaseModel, Field

from functualize.job import GroupOptions, Log, job

JOB_GROUP = "deploy"


class DeployOptions(GroupOptions, group="deploy"):
    strict: bool = Field(default=False, description="Fail on warnings")


@job(group="deploy")
def run(log: Log, options: DeployOptions) -> None:
    print(f"STRICT={options.strict}")
"""

_CONFIG = """
[deploy]
strict = true
"""


def _project(project_tree):
    return project_tree(jobs={"d.py": _JOBS}, extra_files={"config.base.toml": _CONFIG})


class TestAGroupBooleanCanBeTurnedOff:
    """A2 — the capability, on whichever surface you reach it from."""

    def test_the_negative_flag_overrides_a_config_true(
        self, cli_run, project_tree
    ) -> None:
        root = _project(project_tree)

        result = cli_run(["deploy", "--no-strict", "run"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "STRICT=False" in result.stdout

    def test_the_positive_flag_still_works(self, cli_run, project_tree) -> None:
        root = _project(project_tree)

        result = cli_run(["deploy", "--strict", "run"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "STRICT=True" in result.stdout

    def test_neither_resolves_from_the_config_file(self, cli_run, project_tree) -> None:
        """The control: the mid-path flag boundary is unchanged."""
        root = _project(project_tree)

        result = cli_run(["deploy", "run"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "STRICT=True" in result.stdout


class TestAnInlineValueIsRefused:
    """A6 — the one invocation that stops working, and why that is right."""

    def test_inline_false_is_refused(self, cli_run, project_tree) -> None:
        root = _project(project_tree)

        result = cli_run(["deploy", "--strict=false", "run"], cwd=root)

        assert result.exit_code != 0, f"--strict=false was accepted: {result.stdout}"

    @surfaces("func")
    def test_the_refusal_names_the_replacement(self, cli_run, project_tree) -> None:
        """A user whose command just broke must be told the new spelling.

        Scoped to `func`, because that is the parser this project owns. On an
        app's own entry point click refuses it first, with its own wording
        ("Option '--strict' does not take a value"), and rewording click would
        mean custom parameter handling for no gain — the command is refused
        either way, which is the parity A6 asks for.

        "unknown option" would be actively misleading on either surface:
        `--strict` is a real flag, used wrongly.
        """
        root = _project(project_tree)

        result = cli_run(["deploy", "--strict=false", "run"], cwd=root)
        combined = result.stdout + result.stderr

        assert "--no-strict" in combined, combined
