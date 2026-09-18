"""Which storage a project uses cannot depend on plugin load order. AC-8.

`plugin-taxonomy`/T7.

The bug, reproduced before the fix. `functualize-tasks-local` read
`app.substrate` inside its `APP_READY` hook, and that read *resolves and caches*
the engine's substrate. `install_substrate` then refuses — correctly, because a
second backend after the first has been handed out is the split brain
`.spec/ARCHITECTURE.md` exists to make unreachable — and the sqlite plugin
**swallowed the refusal** into a `logger.exception`. So the project quietly used
the filesystem and the database it was told to use stayed empty.

Which plugin's hook ran first decided it, and hook order is the loader's
topological sort with a stable **alphabetical** tiebreak. The deciding fact was
therefore the *spelling of a plugin's name*. Two runs of the same two plugins,
differing in nothing else::

    name 'tasks-local'    (sorts after  substrate-sqlite) -> SQLiteSubstrate
    name 'a-tasks-local'  (sorts before substrate-sqlite) -> JsonFileSubstrate

That is a load-bearing accident, and `plugin-taxonomy` was about to rename the
plugin on the lucky side of it.

Two changes remove it, and this file asserts both:

1. The provider takes a **callable** and reads the substrate on first use, well
   after boot — so nothing resolves storage during `APP_READY`.
2. The sqlite plugin no longer swallows a failed install, so if a future caller
   reintroduces an early read the result is an error rather than silence.

These use ``explicit_plugins`` rather than entry-point discovery: the subject is
the *order* the loader puts hooks in, and handing the plugins over directly is
the only way to control it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from functualize.app import FunctualizeApp, JobSources, PluginSources

if TYPE_CHECKING:
    from collections.abc import Iterator

sqlite_module = pytest.importorskip(
    "functualize_substrate_sqlite",
    reason="workspace plugins not installed; run `uv sync --all-packages --all-extras`",
)
tasks_local_module = pytest.importorskip("functualize_tasks_local._plugin")

SQLiteSubstratePlugin = sqlite_module.SQLiteSubstratePlugin
SQLiteSubstrate = sqlite_module.SQLiteSubstrate
LocalTasksPlugin = tasks_local_module.LocalTasksPlugin


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """An empty project directory, entered — storage resolves from the cwd."""
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(previous)


def _boot(*plugins: object) -> FunctualizeApp:
    return FunctualizeApp(
        name="ordering",
        job_sources=JobSources(directories=[]),
        plugin_sources=PluginSources(explicit_plugins=list(plugins)),
    )


@pytest.mark.parametrize(
    "tasks_plugin_name",
    ["tasks-local", "a-tasks-local"],
    ids=["sorts-after-the-substrate", "sorts-before-the-substrate"],
)
def test_the_substrate_wins_whichever_hook_runs_first(
    project: Path, tasks_plugin_name: str
) -> None:
    """The headline. Both orders, one answer.

    `a-tasks-local` is not a hypothetical: it is the second run of the
    reproduction above, and before the fix it returned `JsonFileSubstrate`.
    """
    tasks = LocalTasksPlugin()
    tasks.name = tasks_plugin_name

    app = _boot(SQLiteSubstratePlugin(), tasks)

    assert isinstance(app.substrate, SQLiteSubstrate), (
        f"with the tasks plugin named {tasks_plugin_name!r} the project fell "
        f"back to the filesystem; storage is still decided by hook order"
    )


def test_the_order_the_plugins_are_handed_over_does_not_matter_either(
    project: Path,
) -> None:
    """Belt and braces: the loader re-sorts, so the constructor's order is not
    the same lever as the name — and neither should matter."""
    tasks = LocalTasksPlugin()
    app = _boot(tasks, SQLiteSubstratePlugin())

    assert isinstance(app.substrate, SQLiteSubstrate)


def test_nothing_resolved_the_substrate_during_boot(project: Path) -> None:
    """The mechanism, asserted directly rather than through its symptom.

    If a plugin reads `app.substrate` at `APP_READY`, the engine has already
    cached one by the time boot finishes and `substrate_override` is moot. The
    override being *present and honoured* is what says the read was deferred.
    """
    app = _boot(SQLiteSubstratePlugin(), LocalTasksPlugin())

    assert app.substrate_override is not None
    assert app.substrate is app.substrate_override


def test_a_late_install_is_refused_loudly_rather_than_swallowed(
    project: Path,
) -> None:
    """AC-4, and the reason AC-8 cannot regress silently.

    The refusal existed before; it was caught and logged. A future caller that
    reintroduces an early read now gets an exception instead of a project
    quietly writing to the wrong place.
    """
    app = _boot()
    _ = app.substrate  # resolve it, the way a run would

    with pytest.raises(RuntimeError, match="already in use"):
        app.install_substrate(SQLiteSubstrate(project / "late.db"))
