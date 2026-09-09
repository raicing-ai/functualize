"""``--output`` works on an app's own entry point, not only on ``func`` (D-2).

The point of these tests is that they run **twice** — the `cli_run` fixture is
parameterised over the `func` and `app` surfaces, so one body asserts parity.
Before run-request/T13 the `app` half could not pass: `adapters/cli.py`
declared `--force` under a comment claiming "parity with the bare `func` CLI,
which has both as pre-command globals", and `--output` was simply absent. An
app entry point could not ask for a machine-readable run at all.

The vocabulary is not restated here. `--output`'s legal values come from
`OPTIONAL_VALUE_VALID_SET`, the one flag grammar both surfaces read, so a value
added there is offered by both without either test or adapter changing.
"""

from __future__ import annotations

import json

import pytest

from functualize.types import OPTIONAL_VALUE_VALID_SET

_VALUES, _DEFAULT = OPTIONAL_VALUE_VALID_SET["--output"]

_EMIT_JOB = """\
from functualize.job import Stdout, job


@job()
def emit(out: Stdout) -> None:
    "Emit a mapping so --output decides the rendering."
    out.emit({"answer": 42})
"""


@pytest.fixture
def emit_tree(project_tree):
    return project_tree(jobs={"emit_job.py": _EMIT_JOB})


class TestTheFlagIsAcceptedOnBothSurfaces:
    def test_json_renders_json(self, cli_run, emit_tree) -> None:
        result = cli_run(["--output", "json", "emit"], cwd=emit_tree)

        assert result.exit_code == 0, result.stderr
        assert json.loads(result.stdout.strip()) == {"answer": 42}

    def test_none_suppresses_the_emission(self, cli_run, emit_tree) -> None:
        result = cli_run(["--output", "none", "emit"], cwd=emit_tree)

        assert result.exit_code == 0, result.stderr
        assert "42" not in result.stdout

    @pytest.mark.parametrize("value", sorted(_VALUES))
    def test_every_value_the_grammar_declares_is_accepted(
        self, cli_run, emit_tree, value: str
    ) -> None:
        # Not "these five strings" — whatever the grammar says today. A value
        # added to the table without being wired through would fail here on
        # whichever surface forgot it.
        result = cli_run(["--output", value, "emit"], cwd=emit_tree)

        assert result.exit_code == 0, f"--output {value}: {result.stderr}"

    def test_an_unknown_value_is_a_usage_error_not_a_traceback(
        self, cli_run, emit_tree
    ) -> None:
        result = cli_run(["--output", "yaml", "emit"], cwd=emit_tree)

        assert result.exit_code != 0
        assert "Traceback" not in result.stderr
