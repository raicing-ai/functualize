"""The plugin registers the `sqlite` store; configuration selects it (task 15, E-1).

Three boot paths, as E-1 names them: ``boot_static`` (every source
explicit), and ``boot_standard`` with lazy discovery booted twice on one
project — `func` cold (no discovery cache yet), then `func` warm (the cache
the first boot wrote).

The reachability proof for tasks 5, 6, 7 and 15 is sabotage (ii): drop the
plugin's ``register_runtime_store_factory`` call and the ``sqlite:`` boot
test fails with an unknown-scheme refusal.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from functualize_substrate_sqlite import (
    SqliteRuntimeStore,
    SQLiteSubstrate,
    SQLiteSubstratePlugin,
)
from functualize_substrate_sqlite._factory import default_database_path
from functualize_substrate_sqlite._migrations import MigrationRefused

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.plugin import RuntimeStoreSelectionError


def alpha() -> None:
    """A job, so the app has something to register."""


def _config(url: str | None) -> ConfigSources:
    defaults: dict[str, Any] = {} if url is None else {"runtime_store": {"url": url}}
    return ConfigSources(
        config_resolution_chain=ResolutionChain([DefaultSource(defaults)])
    )


def _boot_static(project: Path, url: str | None) -> FunctualizeApp:
    app = FunctualizeApp(
        "static",
        job_sources=JobSources(functions=[alpha]),
        config_sources=_config(url),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )
    assert app._static_wiring
    return app


def _boot_lazy(project: Path, url: str | None) -> FunctualizeApp:
    jobs = project / "jobs"
    jobs.mkdir(exist_ok=True)
    (jobs / "alpha.py").write_text('def alpha() -> None:\n    """A job."""\n')
    app = FunctualizeApp(
        "lazy",
        job_sources=JobSources(directories=[str(jobs)], lazy=True),
        config_sources=_config(url),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=[SQLiteSubstratePlugin()]
        ),
    )
    assert not app._static_wiring
    return app


def _boot_cold(project: Path, url: str | None) -> FunctualizeApp:
    return _boot_lazy(project, url)


def _boot_warm(project: Path, url: str | None) -> FunctualizeApp:
    # The first boot writes the discovery cache — under the documents store,
    # with an explicit selection, so legacy data cannot stop the warm-up.
    _boot_lazy(project, "documents:")
    return _boot_lazy(project, url)


BOOTS: dict[str, Callable[[Path, str | None], FunctualizeApp]] = {
    "boot_static": _boot_static,
    "func-cold": _boot_cold,
    "func-warm": _boot_warm,
}


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(params=sorted(BOOTS))
def boot(
    request: pytest.FixtureRequest,
) -> Callable[[Path, str | None], FunctualizeApp]:
    return BOOTS[str(request.param)]


def test_installed_and_unconfigured_stays_on_documents_and_the_filesystem(
    project: Path, boot: Callable[[Path, str | None], FunctualizeApp]
) -> None:
    app = boot(project, None)

    assert isinstance(app.execution_engine._runtime_store, DocumentRuntimeStore)
    assert isinstance(app.substrate, JsonFileSubstrate)
    assert not default_database_path(app.fresh_root).exists()


def test_sqlite_configured_selects_the_sqlite_store_migrated(
    project: Path, boot: Callable[[Path, str | None], FunctualizeApp]
) -> None:
    app = boot(project, "sqlite:")

    store = app.execution_engine._runtime_store
    assert isinstance(store, SqliteRuntimeStore)
    assert store.driver.query("SELECT max(version) FROM schema_migrations") == [(1,)]
    assert isinstance(app.substrate, SQLiteSubstrate)
    assert app.substrate.path == default_database_path(app.fresh_root)


def test_an_unwritable_path_aborts_boot_never_falling_back(
    project: Path, boot: Callable[[Path, str | None], FunctualizeApp]
) -> None:
    blocker = project / "a-file"
    blocker.write_text("not a directory")

    with pytest.raises(OSError):
        boot(project, f"sqlite://{blocker}/state.db")


def test_a_doctored_checksum_aborts_boot_never_falling_back(
    project: Path, boot: Callable[[Path, str | None], FunctualizeApp]
) -> None:
    app = _boot_static(project, "sqlite:")
    store = cast("SqliteRuntimeStore", app.execution_engine._runtime_store)
    store.driver.batch([("UPDATE schema_migrations SET checksum = 'doctored'", ())])
    store.close()

    with pytest.raises(MigrationRefused):
        boot(project, "sqlite:")


def test_unconfigured_with_runtime_data_in_state_db_refuses_boot(
    project: Path, boot: Callable[[Path, str | None], FunctualizeApp]
) -> None:
    # D-3: a project that ran on the plugin before selection was configuration.
    probe = _boot_static(project, None)
    SQLiteSubstrate(default_database_path(probe.fresh_root)).write(
        "scopes", {"scopes": {}}
    )

    with pytest.raises(RuntimeStoreSelectionError) as refused:
        boot(project, None)

    message = str(refused.value)
    assert "holds runtime data for this project" in message
    assert "functualize-sqlite-import" in message
    assert 'runtime_store.url = "sqlite:"' in message


def test_explicit_documents_can_start_fresh_beside_legacy_sqlite_data(
    project: Path, boot: Callable[[Path, str | None], FunctualizeApp]
) -> None:
    probe = _boot_static(project, None)
    SQLiteSubstrate(default_database_path(probe.fresh_root)).write(
        "scopes", {"scopes": {}}
    )

    app = boot(project, "documents:")

    assert isinstance(app.execution_engine._runtime_store, DocumentRuntimeStore)
    assert isinstance(app.substrate, JsonFileSubstrate)


def test_the_plugin_no_longer_offers_a_substrate(project: Path) -> None:
    app = _boot_static(project, None)

    assert app._substrate_claims == []
    [(claimant, _factory)] = [
        (name, f) for name, f in app._runtime_store_factories if f.scheme == "sqlite"
    ]
    assert claimant == "substrate-sqlite"
