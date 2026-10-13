"""An installed substrate plugin is reachable, and configuration selects it. AC-3.

`plugin-taxonomy`/T5. This is the acceptance test for the defect the feature
exists to close, and it is deliberately written to fail on the *wiring* rather
than on the plugin.

What was wrong. `functualize-substrate-sqlite` declared itself under
``functualize.state_providers``, and **nothing in core read that group**. A
``functualize.<x>_providers`` group is scanned by
``_plugins/domain_registry.scan_domain_providers`` out of the
``entry_point_group`` field of a live ``DomainMetadata`` published under
``functualize.domains`` — and ADR-022 removed the ``state`` domain. So
``pip install functualize-substrate-sqlite`` installed a package that could never
load: ``SQLiteSubstratePlugin.__call__`` was never invoked, no substrate was
installed, and the project silently used the filesystem default. No error, no
warning, no log line.

Why this test is not simply "the plugin works". Everything *inside* the plugin
already worked, and its own suite proved it — `SQLiteSubstrate` satisfies the
port, round-trips documents, and locks. What no test asserted was that the
plugin is **reachable**: the gap was between an entry-point group and a reader,
which is invisible from either side.

Since the SQLite runtime provider, installing no longer *selects*: the plugin
registers its store under the scheme ``sqlite`` and a project chooses it with
``runtime_store.url = "sqlite:"`` (S-1). What this file defends is unchanged —
the plugin must be *reachable* through its entry point — so every boot here
writes that one line of project configuration, and one test pins the other
half: installed and unconfigured, nothing moves.

So this boots a real `FunctualizeApp` with:

* no ``explicit_plugins``,
* no ``entry_point_group`` override,
* no monkeypatched ``entry_points``,

and asks what storage the app ended up with. The only way `SQLiteSubstrate`
arrives is: entry-point discovery finds the distribution in a group core reads
→ the loader calls ``SQLiteSubstratePlugin(app)`` → it registers its factory →
step 6.5 selects ``sqlite`` from the project's config and prepares it. Four
links; breaking any one of them is a boot refusal or `JsonFileSubstrate`.

It therefore requires the workspace plugins to be installed
(``uv sync --all-packages --all-extras``), and skips rather than lying when they
are not.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from functualize.app import FunctualizeApp, JobSources

if TYPE_CHECKING:
    from collections.abc import Iterator

sqlite_substrate = pytest.importorskip(
    "functualize_substrate_sqlite.substrate",
    reason="workspace plugins not installed; run `uv sync --all-packages --all-extras`",
)
SQLiteSubstrate = sqlite_substrate.SQLiteSubstrate

#: Opts this file back in to real discovery. The root suite hides the substrate
#: plugin so the ambient environment cannot decide its storage backend
#: (`tests/conftest.py::_hide_default_changing_plugins`); this is the one file
#: whose subject *is* that discovery, so it must see the truth.
pytestmark = pytest.mark.installed_plugins


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An empty project directory, entered — the substrate resolves from cwd.

    Entered through ``monkeypatch`` rather than a bare ``os.chdir`` with a
    ``finally``: the restore then rides pytest's fixture stack, so the
    suite's own cwd comes back whatever the test does to it, and nothing
    here can leak a directory change into whichever file runs after this
    one under a different ordering.
    """
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def _boot(name: str = "ac3", *, select_sqlite: bool = True) -> FunctualizeApp:
    """A plain app. Nothing here mentions plugins, which is the point.

    The project selects the SQLite store the way a user does: one line of its
    own config file, read by the ordinary config discovery.
    """
    if select_sqlite:
        Path("config.base.toml").write_text('[runtime_store]\nurl = "sqlite:"\n')
    return FunctualizeApp(name=name, job_sources=JobSources(directories=[]))


def test_the_installed_substrate_plugin_decides_where_documents_live(
    project: Path,
) -> None:
    """The headline: an ordinary boot that selects ``sqlite``, and storage is the plugin's."""
    app = _boot()
    assert isinstance(app.substrate, SQLiteSubstrate), (
        "the selected substrate plugin did not take effect; the app fell back "
        "to the filesystem default, which is exactly the silent failure AC-3 "
        "exists to detect"
    )


def test_installed_but_unselected_changes_nothing(project: Path) -> None:
    """S-1: installing registers a store; it no longer moves anyone's data."""
    app = _boot(select_sqlite=False)

    assert not isinstance(app.substrate, SQLiteSubstrate)
    assert any(f.scheme == "sqlite" for _, f in app._runtime_store_factories)


def test_the_plugin_reached_the_app_through_its_entry_point(project: Path) -> None:
    """No explicit wiring was supplied, so discovery is the only path in.

    Asserted separately from the test above because the two fail for different
    reasons: that one fails if selection broke, this one fails if the plugin
    was never *called*.
    """
    app = _boot()
    claimants = [
        name for name, f in app._runtime_store_factories if f.scheme == "sqlite"
    ]
    assert claimants == ["substrate-sqlite"], (
        "nothing registered the sqlite store; the plugin's __call__ never ran"
    )


def test_every_store_resolves_to_the_same_object(project: Path) -> None:
    """One decision, not five — `.spec/ARCHITECTURE.md` → *One decision, not five*.

    The split brain this guards against is a scope record in one backend and
    the job state inside it in another. It is unreachable by construction only
    if every store is handed the *same* substrate instance, so identity is what
    is asserted, not type.
    """
    app = _boot()
    engine = app.execution_engine
    selected = engine.substrate

    assert isinstance(selected, SQLiteSubstrate)
    assert app.substrate is selected
    # The two stores an engine builds lazily on first access.
    assert engine._state_store()._substrate is selected
    assert engine._scope_store()._substrate is selected


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


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.surfaces("func")
def test_func_refuses_a_doctored_sqlite_schema_on_cold_and_warm_boot(
    project: Path, cli_run: Any, warm: bool
) -> None:
    """The real CLI entry must not continue on documents after migration fails."""
    from functualize_substrate_sqlite._driver import LocalSqliteDriver
    from functualize_substrate_sqlite._factory import default_database_path
    from functualize_substrate_sqlite._migrations import migrate

    (project / ".functualize").mkdir()
    (project / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\nroot = true\n'
    )
    jobs = project / "jobs"
    jobs.mkdir()
    (jobs / "alpha.py").write_text('def alpha() -> None:\n    """A job."""\n')
    if warm:
        priming = cli_run(["alpha"], cwd=project)
        assert priming.exit_code == 0, priming.stderr

    (project / "config.base.toml").write_text('[runtime_store]\nurl = "sqlite:"\n')
    driver = LocalSqliteDriver(default_database_path(project))
    migrate(driver)
    driver.batch([("UPDATE schema_migrations SET checksum = 'doctored'", ())])
    driver.close()

    refused = cli_run(["alpha"], cwd=project)
    assert refused.exit_code != 0
    assert "MigrationRefused" in refused.stderr
