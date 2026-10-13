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

FUN-17/T12 moved the window to step 6.5, and the SQLite runtime provider then
moved the *decision* out of the plugin altogether: the shipped plugin registers a
store factory from `__call__` (`app.register_runtime_store_factory`), and
configuration (`runtime_store.url = "sqlite:"`) selects it at step 6.5, which
prepares the store and the `SQLiteSubstrate` beside it. So every boot here
configures `sqlite:`, and the claim under test is unchanged: with storage
chosen, hook order cannot change the answer.
`test_the_shipped_plugin_is_honoured_in_its_own_window` pins the window from
the plugin's side.

These use ``explicit_plugins`` rather than entry-point discovery: the subject is
the *order* the loader puts hooks in, and handing the plugins over directly is
the only way to control it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources
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
SqliteRuntimeStore = sqlite_module.SqliteRuntimeStore
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
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain(
                [DefaultSource({"runtime_store": {"url": "sqlite:"}})]
            )
        ),
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

    Step 6.5 selects the store and its substrate together and hands both to
    the engine; the tasks plugin's `APP_READY` hook — which used to be able to
    resolve a substrate out from under the installer by reading
    `app.substrate` first — runs after the decision either way. Nothing claimed
    the install slot, and what the app reports is what the engine was built
    with: the decision moved, and the read did not.
    """
    app = _boot(SQLiteSubstratePlugin(), LocalTasksPlugin())

    assert app.substrate_override is None
    assert app.substrate is app.execution_engine.substrate
    assert isinstance(app.substrate, SQLiteSubstrate)


def test_the_shipped_plugin_is_honoured_in_its_own_window(
    project: Path,
) -> None:
    """The window from the plugin's side, on the plugin exactly as it ships.

    `SQLiteSubstratePlugin` registers its factory from `__call__`; step 6.5
    prepares it because configuration names `sqlite`, and the store and
    substrate it prepared are the ones the engine holds. The plugin claims no
    substrate of its own — an offer or install made at any time would be a
    second, unconfigured way to choose storage.
    """
    app = _boot(SQLiteSubstratePlugin())

    assert app._substrate_claims == []
    assert isinstance(app.execution_engine._runtime_store, SqliteRuntimeStore)
    assert isinstance(app.substrate, SQLiteSubstrate)


def test_a_late_install_is_refused_loudly_rather_than_swallowed(
    project: Path,
) -> None:
    """AC-4, and the reason AC-8 cannot regress silently.

    The refusal existed before; it was caught and logged. A future caller that
    reintroduces an early read now gets an exception instead of a project
    quietly writing to the wrong place.
    """
    app = _boot(SQLiteSubstratePlugin())
    _ = app.substrate  # resolve it, the way a run would

    with pytest.raises(SubstrateInstallError, match="already in use"):
        app.install_substrate(SQLiteSubstrate(project / "late.db"))
