"""`SqliteRuntimeStoreFactory.prepare` and the buffered transaction (task 7)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from functualize_substrate_sqlite import (
    SQLITE_PROFILE,
    LegacyImportRequired,
    SqliteRuntimeStore,
    SqliteRuntimeStoreFactory,
    SQLiteSubstrate,
)
from functualize_substrate_sqlite._driver import LocalSqliteDriver
from functualize_substrate_sqlite._factory import database_path
from functualize_substrate_sqlite._migrations import MigrationRefused

from functualize.plugin import (
    RuntimeStore,
    RuntimeStoreConfig,
    RuntimeStoreFactory,
    RuntimeStoreSelectionError,
)

if TYPE_CHECKING:
    from functualize_substrate_sqlite._transaction import BufferedTransaction


#: Rows a test staged, beside the namespace the store itself owns.
_STAGED_NAMESPACES = "SELECT count(*) FROM namespaces WHERE id != 'default'"


def _config(tmp_path: Path, db: Path) -> RuntimeStoreConfig:
    return RuntimeStoreConfig(
        url=f"sqlite://{db}", scheme="sqlite", project_root=tmp_path
    )


def test_the_factory_and_store_satisfy_their_ports(tmp_path: Path) -> None:
    factory = SqliteRuntimeStoreFactory()
    prepared = factory.prepare(_config(tmp_path, tmp_path / "state.db"))

    assert isinstance(factory, RuntimeStoreFactory)
    assert isinstance(prepared.store, RuntimeStore)
    assert prepared.store.profile is SQLITE_PROFILE is factory.profile


def test_prepare_on_an_empty_path_migrates_to_version_1(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "state.db"
    prepared = SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db))

    store = cast("SqliteRuntimeStore", prepared.store)
    assert store.driver.query("SELECT max(version) FROM schema_migrations") == [(1,)]


def test_the_substrate_is_the_same_file_never_none(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    prepared = SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db))

    assert isinstance(prepared.substrate, SQLiteSubstrate)
    assert prepared.substrate.path == db


def test_a_doctored_checksum_is_refused_out_of_prepare(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db)).store.close()
    LocalSqliteDriver(db).batch(
        [("UPDATE schema_migrations SET checksum = 'doctored'", ())]
    )

    with pytest.raises(MigrationRefused):
        SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db))


def test_unimported_legacy_runtime_documents_are_refused_naming_the_command(
    tmp_path: Path,
) -> None:
    db = tmp_path / "state.db"
    SQLiteSubstrate(db).write("scopes", {"scopes": {}})

    with pytest.raises(LegacyImportRequired) as refused:
        SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db))

    assert isinstance(refused.value, RuntimeStoreSelectionError)
    assert "functualize-sqlite-import" in str(refused.value)


def test_derived_documents_alone_are_not_legacy(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    SQLiteSubstrate(db).write("fresh", {"entries": {}})

    SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db))


def test_a_cutover_marker_lets_the_imported_file_open(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    SQLiteSubstrate(db).write("runs", {"runs": []})
    driver = LocalSqliteDriver(db)
    from functualize_substrate_sqlite._migrations import migrate

    migrate(driver)
    driver.batch(
        [
            (
                "INSERT INTO runtime_cutover VALUES ('documents', 'now', 'digest', NULL)",
                (),
            )
        ]
    )

    SqliteRuntimeStoreFactory().prepare(_config(tmp_path, db))


def test_a_raising_body_leaves_zero_rows(tmp_path: Path) -> None:
    store = (
        SqliteRuntimeStoreFactory()
        .prepare(_config(tmp_path, tmp_path / "state.db"))
        .store
    )

    with pytest.raises(RuntimeError, match="mid-transition"), store.transaction() as tx:
        buffered = cast("BufferedTransaction", tx)
        buffered.stage("INSERT INTO namespaces VALUES ('ns', 'project', 'now')")
        raise RuntimeError("mid-transition")

    sqlite_store = cast("SqliteRuntimeStore", store)
    assert sqlite_store.driver.query(_STAGED_NAMESPACES) == [(0,)]


def test_a_clean_exit_applies_everything_as_one_batch(tmp_path: Path) -> None:
    store = cast(
        "SqliteRuntimeStore",
        SqliteRuntimeStoreFactory()
        .prepare(_config(tmp_path, tmp_path / "state.db"))
        .store,
    )

    with store.transaction() as tx:
        buffered = cast("BufferedTransaction", tx)
        buffered.stage("INSERT INTO namespaces VALUES ('a', 'one', 'now')")
        buffered.stage("INSERT INTO namespaces VALUES ('b', 'two', 'now')")
        # Staged, not sent: nothing is visible until the block exits.
        assert store.driver.query(_STAGED_NAMESPACES) == [(0,)]

    assert store.driver.query(_STAGED_NAMESPACES) == [(2,)]


def test_a_failing_batch_applies_none_of_it(tmp_path: Path) -> None:
    store = cast(
        "SqliteRuntimeStore",
        SqliteRuntimeStoreFactory()
        .prepare(_config(tmp_path, tmp_path / "state.db"))
        .store,
    )

    with pytest.raises(Exception, match="UNIQUE"), store.transaction() as tx:
        buffered = cast("BufferedTransaction", tx)
        buffered.stage("INSERT INTO namespaces VALUES ('a', 'one', 'now')")
        buffered.stage("INSERT INTO namespaces VALUES ('a', 'two', 'now')")

    assert store.driver.query(_STAGED_NAMESPACES) == [(0,)]


def test_ports_not_yet_built_refuse_rather_than_answer(tmp_path: Path) -> None:
    store = (
        SqliteRuntimeStoreFactory()
        .prepare(_config(tmp_path, tmp_path / "state.db"))
        .store
    )

    with pytest.raises(NotImplementedError, match="task 10"):
        store.workflows.resumable()


def test_close_releases_the_driver(tmp_path: Path) -> None:
    store = cast(
        "SqliteRuntimeStore",
        SqliteRuntimeStoreFactory()
        .prepare(_config(tmp_path, tmp_path / "state.db"))
        .store,
    )
    driver = cast("LocalSqliteDriver", store.driver)

    store.close()

    assert driver.open_connections() == 0


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///abs/state.db", Path("/abs/state.db")),
        ("sqlite:data/state.db", Path("PROJECT/data/state.db")),
    ],
)
def test_url_forms(url: str, expected: Path) -> None:
    assert database_path(url, Path("PROJECT")) == expected


def test_a_url_naming_a_host_is_refused() -> None:
    with pytest.raises(RuntimeStoreSelectionError, match="local file"):
        database_path("sqlite://host/db", Path("PROJECT"))
