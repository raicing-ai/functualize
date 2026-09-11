"""Run state is written where the host says the project is (F3 · T5).

The kernel used to answer *"where does this project's run state live?"* three
times, each time by asking the process's working directory: once in the
executor's state store, once as the pre-flight's fingerprint root, and once as
``RunContext.cwd``'s fallback. They matter together rather than apart — a run
whose request carried a ``cwd`` could still land its state file somewhere else,
because the state store never consulted the request — and three answers are why
the durable run layer could not simply be added on top.

Both tests move the **process** away from the project between construction and
the run. A kernel that still asked the operating system would follow it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.app.core import request_for
from functualize.job import RunContext  # noqa: TC001 - resolved at runtime for DI

CAPTURED: dict[str, Any] = {}


def _capture_cwd(rc: RunContext) -> None:
    """A job that reports the working directory its run was given."""
    CAPTURED["cwd"] = rc.cwd


def _app() -> FunctualizeApp:
    """A static app: explicit sources, no discovery, no file I/O at boot."""
    return FunctualizeApp(
        "state-root",
        job_sources=JobSources(functions=[_capture_cwd]),
        config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )


def test_a_run_writes_its_state_under_the_projects_root(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The app is built in the project; the run happens somewhere else."""
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.chdir(project)
    app = _app()
    assert app.fresh_root == project

    monkeypatch.chdir(elsewhere)
    app.execute(request_for("capture-cwd"))

    # The **run log**, not `state.json`. `durable-run-layer`/T3b removed the
    # history ring, which was the only thing a plain job wrote to `state.json`
    # — it now holds freshness verdicts, so a job that declares no sources
    # leaves no file there at all. The question this test asks is unchanged:
    # did the run's state land under the *project*, or did the kernel follow
    # the process's working directory? `runs.json` answers it, and every run
    # writes one.
    assert (project / ".functualize" / "runs.json").exists()
    assert not (elsewhere / ".functualize").exists(), (
        "the run wrote under the process's cwd rather than the project"
    )
    assert not (elsewhere / ".functualize").exists()


def test_a_run_that_named_no_directory_reports_the_projects_root(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """`RunContext.cwd` falls back to the host's answer, not the process's.

    A request without a `cwd` used to hand the job whatever directory the
    process happened to be in — a different directory from the one the run
    belonged to, and one the job would then write into.
    """
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.chdir(project)
    app = _app()
    assert app.fresh_root == project

    monkeypatch.chdir(elsewhere)
    app.execute(request_for("capture-cwd"))

    assert CAPTURED["cwd"] == project
