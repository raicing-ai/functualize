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


class TestAConfigDeclaredCwdSurvives:
    """The other half of the rule, and the half the first fix broke.

    T14 stops single-file mode scanning the working directory, because
    `func weather.py trip_planner` run beside an unrelated app was answered by
    *that* app and the requested file never ran. The rule the change-site
    comment states is **declared or implicit**, not "is it the cwd":

        Config-declared directories stay ... The working directory is the one
        that is implicit — `auto_discover` adds it and no setting can remove it
        — so it is the one this drops.

    The first implementation compared paths, and `auto_discover` resolves a
    declared `jobs_directories = ["."]` to exactly the cwd. So a project that
    named its own root lost it: `func caller.py caller` died with
    `KeyError: "Job 'project_peer' not found in engine registry"` and a
    traceback, while `func project_peer` in the same directory ran fine. A
    working project stopped working, found by adversarial review rather than by
    this suite.
    """

    @surfaces("func")
    def test_a_peer_declared_by_config_is_still_reachable(
        self, tmp_path: Path, cli_run
    ) -> None:
        """`func`-only, and deliberately so.

        `func <file>.py` is `Mode.SINGLE_FILE` — it reads a path as the thing to
        run. An app **is** the program and has no such mode, which
        `contributor/architecture/surface-boundary.md` §4 lists as one of the
        features that may be `func`-only. Restricting with a reason rather than
        letting the parameterisation fail is what `tests/conftest.py` asks for.
        """
        (tmp_path / ".functualize.toml").write_text('jobs_directories = ["."]\n')
        (tmp_path / "project_peer.py").write_text(
            "from functualize.job import job\n"
            "\n"
            "\n"
            "@job()\n"
            "def project_peer() -> str:\n"
            '    """A peer the project declares."""\n'
            '    print("PEER RAN")\n'
            '    return "ok"\n'
        )
        (tmp_path / "caller.py").write_text(
            "from functualize.job import Invoke, job\n"
            "\n"
            "\n"
            "@job()\n"
            "def caller(invoke: Invoke) -> str:\n"
            '    """Invoke the config-declared peer."""\n'
            "    return f\"peer said {invoke('project_peer').status}\"\n"
        )

        result = cli_run(["caller.py", "caller"], cwd=tmp_path)

        assert "not found in engine registry" not in (result.stdout + result.stderr)
        assert result.exit_code == 0, result.stderr


class TestTheOtherDoorIntoTheWorkingDirectory:
    """The job scan is not the only thing that reads the cwd (review S5).

    T14's filter reaches `job_sources.directories`. The **plugin loader** falls
    back to `./.functualize/plugins/` by its own convention and execs every
    module there during app construction — before the named file has run, and
    outside the filter's reach entirely. So the reported symptom survived, at a
    doorway the fix never came near:

        $ func weather.py trip        # beside ./.functualize/plugins/killer.py
        CWD PLUGIN-DIR MODULE TOP LEVEL RAN
        exit 13                       # the target never ran

    The implementer missed it because the fix was written against the
    *mechanism* they had just read (discovery's directory list), and the AC was
    written against the *outcome* ("not hijacked by an unrelated module in the
    working directory"). The reviewer went at the outcome and looked for other
    ways to reach it. Both were right about their own half.

    `PluginSources.ambient_directory` is the switch, and it keeps T14's line:
    a **declared** `plugins_directories` still loads — see the second test.
    """

    _KILLER = textwrap.dedent(
        """\
        import sys

        print("PLUGIN DIR MODULE RAN", file=sys.stderr)
        """
    )

    @surfaces("func")
    def test_a_cwd_plugin_directory_is_not_executed(
        self, cli_run, tmp_path: Path
    ) -> None:
        """`func` only, and that is the point rather than a limitation.

        An app's own entry point **is** the project, so its
        `./.functualize/plugins/` is its own and loads exactly as before —
        `ambient_directory` defaults to `True`. Only `func <file>.py <job>`
        declines it, because there the cwd is wherever the shell happened to
        be.
        """
        (tmp_path / "weather.py").write_text(_WEATHER)
        plugins = tmp_path / ".functualize" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "killer.py").write_text(self._KILLER)

        result = cli_run(["weather.py", "trip_planner"], cwd=tmp_path)

        combined = result.stdout + result.stderr
        assert result.exit_code == 0, combined
        assert "PLANNED" in result.stdout
        assert "PLUGIN DIR MODULE RAN" not in combined

    def test_a_declared_plugins_directory_still_loads(self, tmp_path: Path) -> None:
        """The falsifier, and the line T14 drew: *declared* survives.

        Asserted against the resolver rather than an end-to-end run, because
        what is being distinguished is which of two directory sources answered
        — and only one of them is reachable from a config file.
        """
        from functualize._plugins.loader import PluginLoader
        from functualize.app.config import PluginSources

        declared = tmp_path / "myplugins"
        declared.mkdir()
        convention = tmp_path / ".functualize" / "plugins"
        convention.mkdir(parents=True)

        class _Resolved:
            value = [str(declared)]

        class _Chain:
            def resolve(self, key: str, section: str) -> object:
                return _Resolved()

        class _App:
            _resolution_chain = _Chain()
            _plugin_sources = PluginSources(ambient_directory=False)

        loader = PluginLoader()
        assert loader._resolve_plugin_directories(_App()) == [str(declared)]
