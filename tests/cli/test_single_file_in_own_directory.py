"""`func file.py job` works from the file's own directory.

The common case was the broken one. Running a single file from *inside* its own
directory crashed with an unhandled `ValueError` and a traceback:

    $ cd /tmp/sf && func weather.py trip_planner --help
    ValueError: Cannot register dynamic job 'forecast': a job with this name
    already exists

while the identical command from one directory up worked. Directory discovery
registers the file's peers, and `_register_single_file_peers` then registered
them a second time.

It is **one job registered twice**, not two jobs contending for a name — which
is why the fix is in the peer loop and `register_dynamic_job` stays strict.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import surfaces

_TWO_JOBS = """\
from functualize.job import job
from functualize.workflow import END, Edge, Step, workflow


@job
def forecast(city: str = "oslo") -> str:
    return f"sun in {city}"


@workflow(steps=[Step("forecast")], edges=[Edge(source="forecast", target=END)])
def trip_planner() -> str:
    return "planned"
"""


@surfaces("func")
class TestSingleFileFromItsOwnDirectory:
    """AC-24."""

    def test_running_a_file_from_its_own_directory_does_not_crash(
        self, cli_run, tmp_path: Path
    ) -> None:
        script = tmp_path / "weather.py"
        script.write_text(_TWO_JOBS)

        result = cli_run(["weather.py", "trip_planner", "--help"], cwd=tmp_path)

        assert result.exit_code == 0
        assert "Traceback" not in result.stderr
        assert "already exists" not in result.stderr

    def test_the_same_file_from_outside_still_works(
        self, cli_run, tmp_path: Path
    ) -> None:
        """The contrast that proved the mechanism. Both must work now."""
        inner = tmp_path / "sf"
        inner.mkdir()
        (inner / "weather.py").write_text(_TWO_JOBS)
        outside = tmp_path / "outside"
        outside.mkdir()

        result = cli_run(
            [str(inner / "weather.py"), "trip_planner", "--help"], cwd=outside
        )

        assert result.exit_code == 0

    def test_the_peer_job_is_still_reachable(self, cli_run, tmp_path: Path) -> None:
        """Skipping the duplicate registration must not lose the job — the
        entry directory discovery made is the one that answers."""
        script = tmp_path / "weather.py"
        script.write_text(_TWO_JOBS)

        result = cli_run(["weather.py", "forecast", "--city", "bergen"], cwd=tmp_path)

        assert result.exit_code == 0


@surfaces("func")
class TestGenuineCollisionsStillRaise:
    """The tolerance is scoped to peer re-registration. `register_dynamic_job`
    itself must stay strict, or it stops catching what it exists for."""

    def test_registering_two_different_jobs_under_one_name_still_raises(self) -> None:
        from functualize.app.core import FunctualizeApp

        app = FunctualizeApp(name="testapp")
        app.register_dynamic_job("build", lambda: "a")
        with pytest.raises(ValueError, match="already exists"):
            app.register_dynamic_job("build", lambda: "b")
