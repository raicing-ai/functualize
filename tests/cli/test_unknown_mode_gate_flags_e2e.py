"""The UNKNOWN dispatch branch must forward the workflow gate flags.

`detect_mode` classifies a first positional it cannot find in the cheap
pre-boot enumeration as `Mode.UNKNOWN`, and `main()` then hands it to
`_handle_job` anyway — the enumeration only sees file *stems*, so a
function-level job whose name differs from its file's name (`trip_planner`
inside `weather.py`) always lands there until the discovery cache is warm.

That branch used to drop `--scope-id` and `--prompt-gates`, which
`_handle_job` defaults to `None`/`False`. The result was a workflow that
honoured the caller's scope id on every warm run and silently minted a
generated one on the first, cold-cache run — so the id the caller chose
addressed nothing, and `workflow resume <id>` could not reach the scope that
had just blocked.

These tests run in a subprocess against an isolated `XDG_CACHE_HOME`, because
a cold cache is the whole point: with a warm one the job resolves to
`Mode.JOB` and the bug is invisible.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

_WORKFLOW_SOURCE = '''\
"""A gated workflow whose job name differs from this file's stem."""

from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.workflow import END, Edge, Gate, Step, workflow


class Cfg(BaseModel):
    city: str = Field(default="Tokyo", description="City to check")


class Prefs(BaseModel):
    budget: str = Field(description="Budget level")


def forecast(config: Cfg, rc: RunContext) -> str:
    """Fetch a forecast."""
    return f"{config.city}: sunny"


@workflow(
    steps=[
        Step(forecast),
        Gate(name="preferences", awaits=Prefs),
    ],
    edges=[
        Edge(source="forecast", target="preferences"),
        Edge(source="preferences", target=END),
    ],
)
def trip_planner(config: Cfg, rc: RunContext) -> str:
    """Walks to the gate and blocks."""
    return f"done: {config.city}"
'''


def _write_project(tmp_path: Path) -> Path:
    """A project whose only job is `trip-planner`, declared in `plans.py`.

    The stem (`plans`) deliberately differs from the job name so the pre-boot
    enumeration cannot find it and the invocation is classified UNKNOWN.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".functualize.toml").write_text('jobs_directories = ["jobs"]\n')
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "plans.py").write_text(_WORKFLOW_SOURCE)
    return tmp_path


def _run_func(
    *args: str, cwd: Path, cache_home: Path, timeout: int = 90
) -> subprocess.CompletedProcess[str]:
    """Run `uv run func` against a cache directory the caller controls."""
    import os

    env = {**os.environ, "XDG_CACHE_HOME": str(cache_home)}
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout,
        env=env,
    )


class TestScopeIdSurvivesUnknownDispatch:
    """`--scope-id` must reach the executor on the cold, UNKNOWN-mode run."""

    def test_cold_run_blocks_under_the_caller_s_scope_id(self, tmp_path: Path) -> None:
        """The very first invocation records the id the caller passed.

        This is the regression: on a cold cache the scope was recorded under a
        generated id, so `workflow list` never showed `chosen-scope-id`.
        """
        project = _write_project(tmp_path / "proj")
        cache = tmp_path / "cache"

        run = _run_func(
            "--scope-id",
            "chosen-scope-id",
            "trip-planner",
            "--city",
            "Tokyo",
            cwd=project,
            cache_home=cache,
        )

        # Exit 5 is BLOCKED — the gate engaged, which is what makes the scope
        # id observable at all. If this is not 5 the test proves nothing.
        assert run.returncode == 5, f"stdout: {run.stdout}\nstderr: {run.stderr}"
        assert "chosen-scope-id" in run.stderr, (
            "the blocked scope should carry the caller's id, not a generated "
            f"one — stderr: {run.stderr}"
        )

        listing = _run_func(
            "builtin", "workflow", "list", cwd=project, cache_home=cache
        )
        assert listing.returncode == 0, f"stderr: {listing.stderr}"
        assert "chosen-scope-id" in listing.stdout, (
            "the scope must be addressable by the id the caller chose — "
            f"stdout: {listing.stdout}"
        )

    def test_the_answered_gate_lets_the_same_scope_id_complete(
        self, tmp_path: Path
    ) -> None:
        """Resuming by the caller's id walks past the gate.

        The end-to-end consequence of the fix: an id minted before the first
        run stays usable for `resume`, which is how a caller (or an agent over
        MCP) is expected to drive a gated workflow.
        """
        project = _write_project(tmp_path / "proj")
        cache = tmp_path / "cache"

        blocked = _run_func(
            "--scope-id", "resume-me", "trip-planner", cwd=project, cache_home=cache
        )
        assert blocked.returncode == 5, f"stderr: {blocked.stderr}"

        resumed = _run_func(
            "builtin",
            "workflow",
            "resume",
            "resume-me",
            "preferences",
            "--input",
            '{"budget": "mid-range"}',
            cwd=project,
            cache_home=cache,
        )
        assert resumed.returncode == 0, f"stderr: {resumed.stderr}"

        completed = _run_func(
            "--scope-id", "resume-me", "trip-planner", cwd=project, cache_home=cache
        )
        assert completed.returncode == 0, (
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
