"""T14 — single-file mode runs the file it was given, not the directory's other scripts.

`_handle_single_file` boots an app for execution context, and that app's job
sources came straight from `auto_discover(cwd)` — which adds the working
directory itself whenever it holds a qualifying `.py` file. Importing those
modules executes their top level, so a neighbour ending in `app.cli_command()`
consumed the invocation:

    $ func weather.py trip_planner        # beside stray.py
    Error: No such command 'weather.py'.

The requested file never ran. Single-file mode was asked for one file; the CWD
scan is the part of discovery that reads files nobody named.

The app still scans what discovery was *told* to scan — declared directories,
and anything a configured `scan_depth` reaches. Only the implicit working
directory goes, and the last test here pins that the two are distinguishable.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from tests.conftest import surfaces

_WEATHER = """\
from functualize.job import job


@job
def forecast(city: str = "oslo") -> str:
    print(f"FORECAST {city}")
    return city


@job
def trip_planner() -> str:
    print("PLANNED")
    return "planned"
"""

#: A neighbour that builds an app and hands it the process's own argv. Before
#: the fix this ran during the target's boot and answered for it.
_HIJACKER = """\
import sys

from functualize.app import FunctualizeApp

print("STRAY RAN", file=sys.stderr)

app = FunctualizeApp("stray")


def hello() -> None:
    print("stray hello")


app.cli_command()
"""

#: A neighbour that only prints. It is not a hijack, and it must not run either
#: — "stops executing CWD module code" is the claim, not "stopped the one
#: spelling that happened to win the race".
_QUIET_NEIGHBOUR = """\
import sys

print("NEIGHBOUR RAN", file=sys.stderr)


def hello() -> None:
    print("neighbour hello")
"""


@surfaces("func")
class TestASingleFileDoesNotRunItsNeighbours:
    def test_a_stray_cli_does_not_hijack_the_invocation(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The reported case: exit 0, the target's output, no stray."""
        (tmp_path / "weather.py").write_text(_WEATHER)
        (tmp_path / "stray.py").write_text(_HIJACKER)

        result = cli_run(["weather.py", "trip_planner"], cwd=tmp_path)

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "PLANNED" in result.stdout

    def test_an_unrelated_neighbour_is_not_executed(
        self, cli_run, tmp_path: Path
    ) -> None:
        """Its top level is the thing that runs; a marker is the evidence."""
        (tmp_path / "weather.py").write_text(_WEATHER)
        (tmp_path / "neighbour.py").write_text(_QUIET_NEIGHBOUR)

        result = cli_run(["weather.py", "forecast"], cwd=tmp_path)

        combined = result.stdout + result.stderr
        assert result.exit_code == 0, combined
        assert "FORECAST" in result.stdout
        assert "NEIGHBOUR RAN" not in combined


@surfaces("func")
def test_the_discovery_the_app_was_given_still_runs(cli_run, project_tree) -> None:
    """The other reading of "stop importing from CWD" is "give it none".

    That would drop `rc.invoke` into the surrounding project without saying so,
    so which of the two this is needs pinning: a script in the project root
    still reaches a job declared in `.functualize/jobs/`.
    """
    script = textwrap.dedent(
        """
        from functualize.job import Invoke, job


        @job
        def call_peer(invoke: Invoke) -> None:
            invoke("project_peer")
        """
    ).lstrip()
    root = project_tree(
        jobs={
            "peer.py": (
                "from functualize.job import job\n"
                "\n"
                "\n"
                "@job\n"
                "def project_peer() -> None:\n"
                '    print("PEER RAN")\n'
            ),
        },
        extra_files={"caller.py": script},
    )

    result = cli_run(["caller.py", "call_peer"], cwd=root)

    combined = result.stdout + result.stderr
    assert result.exit_code == 0, combined
    assert "PEER RAN" in combined
