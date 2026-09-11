"""`state show` makes the scope file's growth visible.

`scope-record-lifecycle`/T4, AC-4. The defect's real cost was invisibility: the
file reached 2,188 records and 58 ms per state write on a real project, and
nobody noticed until an external review measured it. The count alone was
already printed and is not enough — a number with no ceiling beside it does not
read as "getting full".
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from functualize._primitives.scope_format import SCOPES_LIMIT


def _show() -> str:
    """Run `builtin state show` against the current working directory."""
    from functualize.app.core import FunctualizeApp

    app = FunctualizeApp(name="show-test")
    runner = CliRunner()
    result = runner.invoke(
        app.cli_command, ["builtin", "state", "show"], catch_exceptions=False
    )
    return result.output


class TestScopesAreReportedWithTheirCeiling:
    def test_the_line_carries_count_cap_and_size(self, tmp_path: Path) -> None:
        """All three, because each answers a different question.

        Count says how many, the cap says how close to full, the size says
        whether it is slow. Only the first was ever printed.
        """
        import os

        project = tmp_path / "proj"
        (project / ".functualize").mkdir(parents=True)
        scopes = project / ".functualize" / "scopes.json"
        scopes.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "scopes": {f"s-{i}": {"status": "completed"} for i in range(7)},
                }
            )
        )

        cwd = Path.cwd()
        os.chdir(project)
        try:
            output = _show()
        finally:
            os.chdir(cwd)

        line = next((ln for ln in output.splitlines() if ln.startswith("Scopes:")), "")
        assert line, f"no Scopes line in:\n{output}"
        assert "7" in line, f"record count missing: {line!r}"
        assert str(SCOPES_LIMIT) in line, (
            f"the cap is missing, so the count has no ceiling to read against: {line!r}"
        )
        assert "B" in line or "KB" in line or "MB" in line, (
            f"the file size is missing: {line!r}"
        )

    def test_an_absent_file_says_so_rather_than_erroring(self, tmp_path: Path) -> None:
        """`show` is what someone runs to find out what is wrong.

        A project that has never run anything has no scope file, and that is
        a normal state, not a fault.
        """
        import os

        project = tmp_path / "empty"
        (project / ".functualize").mkdir(parents=True)

        cwd = Path.cwd()
        os.chdir(project)
        try:
            output = _show()
        finally:
            os.chdir(cwd)

        line = next((ln for ln in output.splitlines() if ln.startswith("Scopes:")), "")
        assert "0" in line and "absent" in line, line
