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


class TestTheOldNameSaysWhereItWent:
    """A renamed global flag produces an actively misleading error otherwise.

    `detect_mode` skips *known* flags when hunting for the first positional, so
    one that no longer exists is read as the command name — a failure mode
    `_cli/dispatch.py` already documents for `--force`. Without the hint,
    `func --output json build` answers `Unknown command 'output'`: it names no
    flag, suggests nothing, and is wrong about what the user typed.
    """

    @surfaces("func")
    def test_the_old_name_names_the_new_one(self, cli_run, project_tree) -> None:
        result = cli_run(["--output", "json", "emits"], cwd=_tree(project_tree))

        combined = result.stdout + result.stderr
        assert "--emit-format" in combined, combined
        assert "Unknown command 'output'" not in combined

    @surfaces("func")
    def test_an_ordinary_typo_is_still_a_typo(self, cli_run, project_tree) -> None:
        """The falsifier: the hint must not swallow every unknown command."""
        result = cli_run(["emitz"], cwd=_tree(project_tree))

        combined = result.stdout + result.stderr
        assert "was renamed" not in combined
        assert "Unknown command" in combined


def test_the_table_only_holds_flags_that_are_really_gone() -> None:
    """An entry for a flag that still exists would be a lie in a help message."""
    from functualize._types.flag_grammar import (
        GLOBAL_BOOL_FLAGS,
        GLOBAL_OPTIONS_WITH_VALUE,
        RENAMED_FLAGS,
    )

    live = GLOBAL_OPTIONS_WITH_VALUE | GLOBAL_BOOL_FLAGS
    for old, new in RENAMED_FLAGS.items():
        assert old not in live, f"{old} is still a real flag; it was not renamed"
        assert new in live, f"{old} points at {new}, which is not a flag"
