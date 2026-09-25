"""`SubstrateInstallError` — a storage backend that cannot open fails boot.

A symbol in a public package's `__all__` must have a caller under `examples/`
(`contributor/reference/public-api-example-coverage.md` → *The gate for new
public API*), because `examples/` is pytest-collected: the example **is** the
end-to-end test for that API, entered through the user's own door. This is that
door for `SubstrateInstallError`.

The shape is one a storage-plugin author writes and an operator reads. A plugin
*offers* its backend from `__call__` (`app.offer_substrate`) and boot asks for
it while selecting the store — after configuration has resolved, before the
engine is built. Installing from `APP_READY` is too late: the engine already
holds its storage, and the install is refused rather than half-applied
(FUN-17/T12). When the backend cannot be opened, the plugin raises `SubstrateInstallError` instead of the app continuing
on the filesystem substrate nobody asked for; boot then refuses, and the
caller's `except` below is where a diagnostic comes from.

Why the raise has to be the plugin's own decision: the alternative is the
failure that motivated this error type — a raise that was logged one frame up
and swallowed, so the run continued against the wrong storage and the only
symptom was a database that stayed empty. `SubstrateInstallError` is exempt
from that swallow on both boot paths, which is what makes the `except` here
reachable at all.

Run it as a suite from the repository root:

    uv run pytest examples/standalone/substrate_failure/
"""

from __future__ import annotations

from pathlib import Path

import pytest
from functualize_substrate_sqlite import SQLiteSubstrate

from functualize.app import FunctualizeApp, JobSources, PluginSources
from functualize.plugin import PluginHost, SubstrateInstallError


class SharedStorePlugin:
    """A storage plugin whose database path the operator supplies.

    A real plugin would read the path from its own settings; a constructor
    argument keeps the example to the part under test — what the plugin does
    when the backend will not open.
    """

    name = "example-shared-store"
    version = "1.0.0"
    description = "Offers a SQLite substrate at an operator-supplied path."

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def __call__(self, app: PluginHost) -> None:
        """Registration only: offer the backend; boot asks for it later."""
        app.offer_substrate(self._open)

    def _open(self, app: PluginHost) -> SQLiteSubstrate:
        """Open the backend and hand it over — or refuse the boot.

        The same three lines the shipped SQLite plugin runs when boot asks for
        its offer: construction failure becomes `SubstrateInstallError`, and
        the `from exc` keeps the driver's own message, which is the part an
        operator needs to fix the path.
        """
        try:
            return SQLiteSubstrate(self._db_path)
        except Exception as exc:
            raise SubstrateInstallError(
                f"could not open the store at {self._db_path}: {exc}"
            ) from exc


def boot(root: Path, db_path: Path) -> str:
    """Boot an app against ``db_path``, reporting rather than raising.

    The user-shaped call. `SubstrateInstallError` leaves `FunctualizeApp(...)`,
    so a caller that wants to say *which* store was refused and why catches it
    here — a CLI that prints the reason and exits non-zero, rather than one that
    starts on the filesystem and lets the user find out later.
    """
    try:
        app = FunctualizeApp(
            name="shared-store",
            job_sources=JobSources(directories=[]),
            plugin_sources=PluginSources(
                entry_point_group="",
                explicit_plugins=[SharedStorePlugin(db_path)],
            ),
        )
    except SubstrateInstallError as exc:
        return f"refused to boot: {exc}"
    return f"booted on {type(app.substrate).__name__}"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project directory to boot in, so nothing is written beside the repo."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".functualize").mkdir()
    return tmp_path


class TestABackendThatCannotOpen:
    def test_it_refuses_the_boot_and_names_the_path(self, project: Path) -> None:
        """A directory where the database file should be: unusable, and named."""
        unusable = project / "not-a-database"
        unusable.mkdir()

        reported = boot(project, unusable)

        assert reported.startswith("refused to boot: could not open the store at")
        assert str(unusable) in reported, "the diagnostic must name the path"
        assert not (project / "not-a-database.db").exists(), (
            "the app booted on something after all"
        )


class TestABackendThatOpens:
    def test_it_boots_on_the_installed_substrate(self, project: Path) -> None:
        """The control: the same plugin, a usable path, so the refusal above is
        about the backend rather than about a plugin that always raises."""
        db_path = project / "store.db"

        reported = boot(project, db_path)

        assert reported == "booted on SQLiteSubstrate"
        assert db_path.exists(), "the substrate was not installed where it was told"
