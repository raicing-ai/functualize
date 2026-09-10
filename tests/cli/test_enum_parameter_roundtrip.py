"""#38 — an enum parameter arrives in the job body as the enum member.

`_click_type_for` renders an `Enum` parameter as a `click.Choice` of its member
values, and until `_EnumChoice` existed nothing converted the chosen value back:
the CLI handed the job the **string** it parsed while the programmatic path
passed the member through unchanged. The two surfaces therefore disagreed about
the type of the same parameter — a job that switched on `color` worked standing
and failed from the command line.

Both halves of that claim are asserted here against the real entry points, not
against `_click_type_for`: a test of the renderer would have passed before the
fix.
"""

from __future__ import annotations

import contextlib
import io
import sys
import textwrap
from pathlib import Path
from typing import Any

from functualize.app import FunctualizeApp
from functualize.app.core import request_for
from functualize.app.utils import import_job
from tests.conftest import surfaces

SCRIPT = textwrap.dedent(
    '''
    import enum


    class Color(enum.Enum):
        RED = "red"
        GREEN = "green"


    def paint(color: Color):
        """Paint."""
        print(f"body={type(color).__name__}:{color!r}")
    '''
)

#: What the body must print on every surface. The type *name* and the member's
#: repr, because the single-file path imports the script twice — two `Color`
#: classes, one identity check that is `False` for reasons of its own.
MEMBER = "body=Color:<Color.RED: 'red'>"


def _script(tmp_path: Path) -> Path:
    path = tmp_path / "paint.py"
    path.write_text(SCRIPT)
    return path


def _run_programmatically(script: Path) -> str:
    """Run the script's job the way an embedder does: `app.execute(request)`."""
    paint = import_job(script, "paint")
    assert callable(paint)
    color = sys.modules[script.stem].Color

    app = FunctualizeApp("app")
    app.register_dynamic_job(name="paint", function=paint, config_class=None)

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        app.execute(request_for("paint", color=color.RED))
    return out.getvalue()


@surfaces("func")
def test_the_cli_delivers_the_member(cli_run: Any, tmp_path: Path) -> None:
    """The door the defect was reported against: `func paint.py paint red`."""
    script = _script(tmp_path)

    result = cli_run([str(script), "paint", "red"], cwd=tmp_path)

    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == MEMBER


@surfaces("func")
def test_the_cli_and_the_programmatic_path_agree(cli_run: Any, tmp_path: Path) -> None:
    """One assertion, two surfaces (AC-11).

    The programmatic path was never broken — it passes the member through — so
    this is only a real test if the CLI half is compared against *it* rather
    than against a value written down here.
    """
    script = _script(tmp_path)

    cli = cli_run([str(script), "paint", "red"], cwd=tmp_path)
    programmatic = _run_programmatically(script)

    assert cli.exit_code == 0, cli.stderr
    assert cli.stdout.strip() == programmatic.strip() == MEMBER
