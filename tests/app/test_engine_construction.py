"""One builder constructs the engine, on both boot paths (F3 · T2).

``boot_static`` and ``boot_standard`` used to carry the same twenty-line
construction block, twice — the same arguments, the same comment, and the only
difference the local alias of two imports. An engine argument added to one and
missed in the other survived every gate there is, which is how ``Shell`` and
``Stdout`` came to be missing from one of two lists.

The spy below is the test: it fails if either path goes back to constructing the
engine itself. The job lookup afterwards is what proves the builder was handed
a *working* host rather than merely called — a block that collapsed into one
call but passed the wrong app would still be one call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from functualize import FunctualizeApp
from functualize._app import boot
from functualize._config.chain import ResolutionChain
from functualize.app.config import ConfigSources, JobSources, PluginSources

PLAIN_JOB = '''
def alpha() -> None:
    """A job."""
'''


def _jobs(tmp_path: Path) -> Path:
    directory = tmp_path / "jobs"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "alpha.py").write_text(PLAIN_JOB)
    return directory


def _spy_on_the_builder(monkeypatch: Any) -> list[Any]:
    """Record every host passed to the one builder, in order."""
    hosts: list[Any] = []
    real = boot.build_engine

    def spy(host: Any) -> Any:
        hosts.append(host)
        return real(host)

    monkeypatch.setattr(boot, "build_engine", spy)
    return hosts


def alpha() -> None:
    """A job registered from a function rather than from a file."""


def test_the_static_path_builds_its_engine_through_the_one_builder(
    monkeypatch: Any,
) -> None:
    """`boot_static`: every source explicit, so no filesystem discovery runs."""
    hosts = _spy_on_the_builder(monkeypatch)

    app = FunctualizeApp(
        "static",
        job_sources=JobSources(functions=[alpha]),
        config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )

    assert hosts == [app]
    assert app.execution_engine.get_job("alpha").name == "alpha"


def test_the_standard_path_builds_its_engine_through_the_one_builder(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """`boot_standard`: discovery, so the engine is built from a host whose job
    registry is filled in *after* construction — the ordering that made the
    post-hoc wiring necessary in the first place."""
    hosts = _spy_on_the_builder(monkeypatch)

    app = FunctualizeApp(
        "standard", job_sources=JobSources(directories=[str(_jobs(tmp_path))])
    )

    assert hosts == [app]
    assert app.execution_engine.get_job("alpha").name == "alpha"
