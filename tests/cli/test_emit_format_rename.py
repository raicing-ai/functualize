"""`--output` became `--emit-format`, and the old name says so.

The flag governs `out.emit()` **and nothing else**. A job's return value is
never rendered at any format, and `print()` ignores it entirely — two facts the
docs had to warn about twice, because `--output` promises to control "the
command's output" and does not:

    @job
    def returns_only() -> dict:
        return {"from": "return"}          # never calls emit

    $ func --emit-format json j.py returns_only   -> (nothing, exit 0)

The rename came out of two informed guesses at what the old name meant —
`--line-format` and `--return-value-format` — neither of which described what
the flag does. `--line-format` is true of exactly one of the five values
(`emit([a, b, c])` is *one array* under `json`), and the return value is the one
thing the flag provably ignores. A name that reliably produces the wrong model
is worth changing while the project is pre-release.

`func builtin parallel --output {interleaved,grouped,prefixed}` is deliberately
**untouched**: it is a different flag with a disjoint vocabulary, and the
collision it had with the global is gone now that the global has a different
name.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tests.conftest import surfaces

_JOB = textwrap.dedent(
    '''
    from functualize.job import Stdout, job


    @job
    def emits(out: Stdout) -> dict:
        """Emits one thing and returns another."""
        out.emit({"from": "emit"})
        return {"from": "return"}


    @job
    def returns_only() -> dict:
        """Returns without emitting."""
        return {"from": "return"}
    '''
)


def _tree(project_tree) -> Path:
    return project_tree(jobs={"j.py": _JOB}, convention_dirs=True)


class TestTheFlagRendersWhatEmitWasGiven:
    @surfaces("func")
    def test_the_emitted_value_is_rendered(self, cli_run, project_tree) -> None:
        result = cli_run(["--emit-format", "json", "emits"], cwd=_tree(project_tree))

        assert result.exit_code == 0, result.stdout + result.stderr
        assert '"from":"emit"' in result.stdout.replace(" ", "")

    @surfaces("func")
    def test_the_returned_value_is_not(self, cli_run, project_tree) -> None:
        """The evidence that killed `--return-value-format`.

        The same job returns something different from what it emits, and the
        returned value never appears at any format.
        """
        result = cli_run(["--emit-format", "json", "emits"], cwd=_tree(project_tree))

        assert '"from":"return"' not in result.stdout.replace(" ", "")

    @surfaces("func")
    def test_a_job_that_only_returns_prints_nothing(
        self, cli_run, project_tree
    ) -> None:
        result = cli_run(
            ["--emit-format", "json", "returns_only"], cwd=_tree(project_tree)
        )

        assert result.exit_code == 0, result.stderr
        assert result.stdout.strip() == ""

    @surfaces("func")
    def test_a_bare_flag_still_falls_back_to_the_default(
        self, cli_run, project_tree
    ) -> None:
        """The optional-value lookahead the grammar table encodes: a bare
        `--emit-format` means `auto`, and must not swallow the job name."""
        result = cli_run(["--emit-format", "emits"], cwd=_tree(project_tree))

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "emit" in result.stdout


class TestTheOldNameIsSimplyGone:
    """No migration aid. The project is pre-alpha and the constitution says
    delete rather than shim, so `--output` is not recognised and gets whatever
    an unknown token gets.

    Kept as a test because "there is no second spelling" is the property worth
    guarding — a helpful alias is exactly how two names for one thing come
    back.
    """

    @surfaces("func")
    def test_the_old_name_is_not_accepted(self, cli_run, project_tree) -> None:
        result = cli_run(["--output", "json", "emits"], cwd=_tree(project_tree))

        assert result.exit_code != 0
        assert '"from":"emit"' not in result.stdout.replace(" ", "")


def test_the_flag_has_exactly_one_spelling() -> None:
    """`--output` is in no grammar table — not as a flag, not as an alias."""
    from functualize._types.flag_grammar import (
        GLOBAL_BOOL_FLAGS,
        GLOBAL_OPTIONS_WITH_VALUE,
        OPTIONAL_VALUE_VALID_SET,
    )

    every_flag = GLOBAL_OPTIONS_WITH_VALUE | GLOBAL_BOOL_FLAGS
    assert "--emit-format" in every_flag
    assert "--output" not in every_flag
    assert "--output" not in OPTIONAL_VALUE_VALID_SET
