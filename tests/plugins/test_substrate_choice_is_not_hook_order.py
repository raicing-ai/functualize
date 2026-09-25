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

1. Storage is settled **once, at step 6.5 of boot**, before any `APP_READY` hook
   runs: `_app` reads the install slot, hands the answer to the engine, and
   refuses every later install. Order among `APP_READY` hooks therefore cannot
   reach the decision — a plugin that installs *after* step 6.5 is refused
   loudly rather than silently losing.
2. The sqlite plugin no longer swallows a failed install, so if a future caller
   reintroduces an early read the result is an error rather than silence.

FUN-17/T12 moved the window, and the shipped plugin moved with it: it *offers*
its substrate from `__call__` (`app.offer_substrate`) and boot asks for it inside
step 6.5, after configuration and before selection. So the shipped plugin stands
for itself here; the stand-in that used to install on its behalf one window
earlier is gone. `test_the_shipped_plugin_is_honoured_in_its_own_window` pins
the window from the plugin's side.

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
from functualize.plugin import SubstrateInstallError

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

    The install fills the slot at registration; step 6.5 then reads it and hands
    the answer to the engine, and the tasks plugin's `APP_READY` hook — which
    used to be able to resolve a substrate out from under the installer by
    reading `app.substrate` first — now runs after the decision either way. The
    slot being *present and still honoured* is what says the decision moved and
    the read did not.
    """
    app = _boot(SQLiteSubstratePlugin(), LocalTasksPlugin())

    assert app.substrate_override is not None
    assert app.substrate is app.substrate_override


def test_the_shipped_plugin_is_honoured_in_its_own_window(
    project: Path,
) -> None:
    """The window from the plugin's side, on the plugin exactly as it ships.

    `SQLiteSubstratePlugin` offers from `__call__` and boot asks for the offer
    inside step 6.5, so the substrate the plugin built is the one the engine
    holds. This used to pin the opposite — the plugin installed from its
    `APP_READY` hook, after step 6.5, and was refused — and its docstring said
    to update it, not delete it, the day the plugin moved: without it, a plugin
    quietly claiming storage after the decision is how the AC-3 fallback comes
    back.
    """
    plugin = SQLiteSubstratePlugin()
    app = _boot(plugin)

    assert isinstance(app.substrate_override, SQLiteSubstrate)
    assert app.substrate is plugin.substrate


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

    with pytest.raises(SubstrateInstallError, match="already in use"):
        app.install_substrate(SQLiteSubstrate(project / "late.db"))
