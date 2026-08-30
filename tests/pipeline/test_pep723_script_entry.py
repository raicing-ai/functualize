"""A `func` script that runs like a program (T41).

`func file.py …` has always read the first argument as a **function name**.
That is right when you are poking at a file from the shell, and wrong the
moment the file has a shebang: a program takes its own flags. Without a
declared entry point, `./deploy.py --env prod` fails with "Function '--env' not
found" and a bare `./deploy.py` prints a listing rather than doing anything —
so `#!/usr/bin/env -S func` was reachable but not usable.

`[tool.functualize] job` closes that. PEP 723 reserves `[tool.<name>]` for
exactly this, so the fix costs no new file, flag, or convention — the metadata
block a script already carries gains one field, and the file stops being "a
module `func` can pick a function out of" and becomes "this job".

Both halves of that sentence are tested here, plus the case that must **not**
change: a file with no `[tool.functualize]` keeps the old positional behaviour,
because that is what every existing script and every existing test relies on.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from tests.conftest import surfaces

from functualize._cli.pep723 import (
    declared_job,
    parse_pep723_deps,
    parse_script_metadata,
)

# ─── Surface ──────────────────────────────────────────────────────────────
#
# `func file.py …` is `Mode.SINGLE_FILE`, a dispatch mode of the bare `func`
# CLI: it reads a path as the thing to run. An app entry point *is* the
# program — it has no file to be handed and no such mode — so there is no
# second surface for these to run on. Restricted, not deleted, so the reason
# is in the file rather than in someone's memory.
pytestmark = surfaces("func")

if TYPE_CHECKING:
    import pytest

_WITH_ENTRY = textwrap.dedent("""\
    # /// script
    # dependencies = []
    #
    # [tool.functualize]
    # job = "greet"
    # ///


    def greet(name: str = "world") -> None:
        print(f"hello {name}")


    def other() -> None:
        print("other")
""")

_WITHOUT_ENTRY = textwrap.dedent("""\
    def greet(name: str = "world") -> None:
        print(f"hello {name}")


    def other() -> None:
        print("other")
""")


def _script(tmp_path: Path, source: str, name: str = "s.py") -> Path:
    path = tmp_path / name
    path.write_text(source)
    return path


class TestParsingTheToolTable:
    def test_the_declared_job_is_read(self, tmp_path: Path) -> None:
        assert declared_job(_script(tmp_path, _WITH_ENTRY)) == "greet"

    def test_a_file_without_the_table_declares_nothing(self, tmp_path: Path) -> None:
        assert declared_job(_script(tmp_path, _WITHOUT_ENTRY)) is None

    def test_dependencies_still_parse_alongside_it(self, tmp_path: Path) -> None:
        """The table must not disturb the half that already worked."""
        source = _WITH_ENTRY.replace(
            "# dependencies = []", '# dependencies = ["httpx"]'
        )

        assert parse_pep723_deps(_script(tmp_path, source)) == ["httpx"]

    def test_a_block_with_only_dependencies_declares_no_job(
        self, tmp_path: Path
    ) -> None:
        source = '# /// script\n# dependencies = ["httpx"]\n# ///\n\ndef greet(): ...\n'

        metadata = parse_script_metadata(_script(tmp_path, source))

        assert metadata is not None
        assert metadata.dependencies == ["httpx"]
        assert metadata.job is None

    def test_malformed_toml_is_absent_not_fatal(self, tmp_path: Path) -> None:
        """The block is a comment. A script whose dependencies happen to be
        installed must still run rather than die on a typo in metadata that
        was not needed."""
        source = "# /// script\n# dependencies = [oops\n# ///\n\ndef greet(): ...\n"

        assert parse_script_metadata(_script(tmp_path, source)) is None

    def test_a_non_string_job_is_ignored(self, tmp_path: Path) -> None:
        source = "# /// script\n# [tool.functualize]\n# job = 42\n# ///\n"

        assert declared_job(_script(tmp_path, source)) is None

    def test_an_unknown_key_warns_but_still_runs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Not an error: a newer functualize may add keys, and refusing to run
        a script over a field this version has not heard of is worse than the
        typo it guards. Not silence either — that is how a misspelled setting
        looks exactly like a setting with no effect."""
        source = (
            "# /// script\n# [tool.functualize]\n"
            '# job = "greet"\n# jobs = "typo"\n# ///\n'
        )

        result = declared_job(_script(tmp_path, source))

        assert result == "greet"
        assert "jobs" in capsys.readouterr().err

    def test_a_multi_line_value_parses(self, tmp_path: Path) -> None:
        """`dependencies` is commonly written one-per-line, so the block has to
        survive being unindented line by line.

        Note this does *not* pin the exact unindent rule. PEP 723 strips
        precisely `"# "`; a greedy `lstrip("# ")` would also eat the leading
        spaces here and still parse, because TOML ignores them inside an array.
        The strict rule matters only for a whitespace-sensitive value (a
        multi-line string), and no key this module reads is one — so there is
        nothing honest to assert about it yet. See the note in `pep723.py`.
        """
        source = '# /// script\n# dependencies = [\n#     "httpx",\n# ]\n# ///\n'

        assert parse_pep723_deps(_script(tmp_path, source)) == ["httpx"]


class TestRunningTheScript:
    """The behaviour a shebang needs, driven through the real CLI."""

    def test_a_declared_entry_point_runs_with_no_arguments(
        self, cli_run, tmp_path: Path
    ) -> None:
        """A bare `./script.py` must *do* the thing, not list what it could
        do."""
        script = _script(tmp_path, _WITH_ENTRY)

        result = cli_run([str(script)])

        assert result.exit_code == 0
        assert "hello world" in result.stdout

    def test_its_flags_reach_the_job(self, cli_run, tmp_path: Path) -> None:
        """The regression this task exists for: `--name` used to be read as a
        function name and the script died before running."""
        script = _script(tmp_path, _WITH_ENTRY)

        result = cli_run([str(script), "--name", "ada"])

        assert result.exit_code == 0
        assert "hello ada" in result.stdout

    def test_help_describes_the_job_not_the_file(self, cli_run, tmp_path: Path) -> None:
        script = _script(tmp_path, _WITH_ENTRY)

        result = cli_run([str(script), "--help"])

        assert "--name" in result.stdout

    def test_a_positional_is_not_taken_as_a_function_name(
        self, cli_run, tmp_path: Path
    ) -> None:
        """Declaring an entry point means the file *is* that job, so `other`
        is an argument to `greet` — not a request to run `other`. Otherwise a
        script could never take a positional argument that happened to share a
        name with one of its own functions."""
        script = _script(tmp_path, _WITH_ENTRY)

        result = cli_run([str(script), "--name", "other"])

        assert "hello other" in result.stdout
        assert result.stdout.count("other") == 1


class TestTheOldBehaviourIsUnchanged:
    """No `[tool.functualize]` — every existing script depends on this."""

    def test_the_first_argument_is_still_a_function_name(
        self, cli_run, tmp_path: Path
    ) -> None:
        script = _script(tmp_path, _WITHOUT_ENTRY)

        result = cli_run([str(script), "greet"])

        assert result.exit_code == 0
        assert "hello world" in result.stdout

    def test_a_bare_file_still_lists_its_functions(
        self, cli_run, tmp_path: Path
    ) -> None:
        script = _script(tmp_path, _WITHOUT_ENTRY)

        result = cli_run([str(script)])

        assert "greet" in result.stdout
        assert "other" in result.stdout

    def test_a_named_function_still_takes_its_flags(
        self, cli_run, tmp_path: Path
    ) -> None:
        script = _script(tmp_path, _WITHOUT_ENTRY)

        result = cli_run([str(script), "greet", "--name", "ada"])

        assert "hello ada" in result.stdout
