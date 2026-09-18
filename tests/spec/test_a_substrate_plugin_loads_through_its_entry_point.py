"""Installing a substrate plugin makes the project use it. AC-3.

`plugin-taxonomy`/T5. This is the acceptance test for the defect the feature
exists to close, and it is deliberately written to fail on the *wiring* rather
than on the plugin.

What was wrong. `functualize-state-sqlite` declared itself under
``functualize.state_providers``, and **nothing in core read that group**. A
``functualize.<x>_providers`` group is scanned by
``_plugins/domain_registry.scan_domain_providers`` out of the
``entry_point_group`` field of a live ``DomainMetadata`` published under
``functualize.domains`` — and ADR-022 removed the ``state`` domain. So
``pip install functualize-state-sqlite`` installed a package that could never
load: ``SQLiteStatePlugin.__call__`` was never invoked, no substrate was
installed, and the project silently used the filesystem default. No error, no
warning, no log line.

Why this test is not simply "the plugin works". Everything *inside* the plugin
already worked, and its own suite proved it — `SQLiteSubstrate` satisfies the
port, round-trips documents, and locks. What no test asserted was that the
plugin is **reachable**: the gap was between an entry-point group and a reader,
which is invisible from either side.

So this boots a real `FunctualizeApp` with:

* no ``explicit_plugins``,
* no ``entry_point_group`` override,
* no monkeypatched ``entry_points``,

and asks what storage the app ended up with. The only way `SQLiteSubstrate`
arrives is: entry-point discovery finds the distribution in a group core reads
→ the loader calls ``SQLiteStatePlugin(app)`` → it registers an ``APP_READY``
hook → the hook calls ``app.install_substrate``. Four links; breaking any one
of them turns the answer back into `JsonFileSubstrate`.

It therefore requires the workspace plugins to be installed
(``uv sync --all-packages --all-extras``), and skips rather than lying when they
are not.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from functualize.app import FunctualizeApp, JobSources

if TYPE_CHECKING:
    from collections.abc import Iterator

sqlite_substrate = pytest.importorskip(
    "functualize_state_sqlite.substrate",
    reason="workspace plugins not installed; run `uv sync --all-packages --all-extras`",
)
SQLiteSubstrate = sqlite_substrate.SQLiteSubstrate

#: Opts this file back in to real discovery. The root suite hides the substrate
#: plugin so the ambient environment cannot decide its storage backend
#: (`tests/conftest.py::_hide_default_changing_plugins`); this is the one file
#: whose subject *is* that discovery, so it must see the truth.
pytestmark = pytest.mark.installed_plugins


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """An empty project directory, entered — the substrate resolves from cwd."""
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(previous)


def _boot(name: str = "ac3") -> FunctualizeApp:
    """A plain app. Nothing here mentions plugins, which is the point."""
    return FunctualizeApp(name=name, job_sources=JobSources(directories=[]))


def test_the_installed_substrate_plugin_decides_where_documents_live(
    project: Path,
) -> None:
    """The headline: an ordinary boot, and storage is the plugin's."""
    app = _boot()
    assert isinstance(app.substrate, SQLiteSubstrate), (
        "the installed substrate plugin did not take effect; the app fell back "
        "to the filesystem default, which is exactly the silent failure AC-3 "
        "exists to detect"
    )


def test_the_plugin_reached_the_app_through_its_entry_point(project: Path) -> None:
    """No explicit wiring was supplied, so discovery is the only path in.

    Asserted separately from the test above because the two fail for different
    reasons: that one fails if `install_substrate` broke, this one fails if the
    plugin was never *called*.
    """
    app = _boot()
    assert app.substrate_override is not None, (
        "nothing installed a substrate; the plugin's __call__ never ran"
    )
    assert isinstance(app.substrate_override, SQLiteSubstrate)


def test_every_store_resolves_to_the_same_object(project: Path) -> None:
    """One decision, not five — `.spec/ARCHITECTURE.md` → *One decision, not five*.

    The split brain this guards against is a scope record in one backend and
    the job state inside it in another. It is unreachable by construction only
    if every store is handed the *same* substrate instance, so identity is what
    is asserted, not type.
    """
    app = _boot()
    engine = app.execution_engine
    installed = app.substrate_override

    assert app.substrate is installed
    assert engine.substrate is installed
    # The two stores an engine builds lazily on first access.
    assert engine._state_store()._substrate is installed
    assert engine._scope_store()._substrate is installed


def test_the_database_is_written_beside_the_projects_other_state(
    project: Path,
) -> None:
    """Where, not just whether — a plugin that installed into the wrong root
    would satisfy every assertion above and still put a user's data somewhere
    they did not expect."""
    app = _boot()
    substrate = app.substrate
    assert isinstance(substrate, SQLiteSubstrate)
    assert Path(substrate.path).parent.name == ".functualize"
    assert Path(substrate.path).is_relative_to(project.resolve())
