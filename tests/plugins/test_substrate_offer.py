"""A substrate plugin offers at registration; boot asks at step 6.5. FUN-17/T12.

Decided in TD-1. Three rules, each pinned here on the boot path(s) it concerns:

- **The offer reads resolved configuration.** On the standard path, plugin
  registration runs before configuration resolves, so a plugin that installed
  from ``__call__`` read nothing, and one that installed at ``APP_READY`` was
  after the store had been chosen and was refused. ``offer_substrate`` is the
  window that is both: boot invokes the offer inside ``_select_runtime_store``.
  Red at ``8b2e9dc`` (the configured path was ignored), green at ``36d6d0d``
  (the pre-T11 ``APP_READY`` install honoured it) — the offer *restores* that
  behaviour, and nothing pinned it before this file.
- **Two claimants refuse; neither wins.** An install and an offer are both
  claims, and more than one is refused by name — "first wins" would be plugin
  load order deciding storage.
- **A registration-time ``SubstrateInstallError`` aborts boot**, through the
  entry-point loader and through ``boot_static``'s explicit loop alike, rather
  than being logged while boot carries on over the filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from functualize._config import ResolutionChain
from functualize._primitives.substrate import JsonFileSubstrate
from functualize.app import ConfigSources, FunctualizeApp, JobSources, PluginSources
from functualize.plugin import SubstrateInstallError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from functualize._types.protocols import StoreSubstrate


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """A project directory, entered — the standard path reads config from it."""
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(previous)


def _static_app(*plugins: Any) -> FunctualizeApp:
    """``boot_static``: everything explicit, plugins through its own loop."""

    def alpha() -> None:
        """A job."""

    return FunctualizeApp(
        "offers-static",
        job_sources=JobSources(functions=[alpha]),
        config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
        plugin_sources=PluginSources(
            entry_point_group="", explicit_plugins=list(plugins)
        ),
    )


def _standard_app(*plugins: Any) -> FunctualizeApp:
    """``boot_standard``: explicit plugins go through ``PluginLoader.load_all``."""
    return FunctualizeApp(
        "offers-standard",
        job_sources=JobSources(directories=[]),
        plugin_sources=PluginSources(explicit_plugins=list(plugins)),
    )


_BOOTS = {"static": _static_app, "standard": _standard_app}


class _Plugin:
    """The metadata `PluginLoader` requires before it will call a plugin."""

    version = "0.0.0"
    description = "a storage claimant, for FUN-17/T12's window"


class _Offers(_Plugin):
    """A plugin that offers a filesystem substrate rooted where it is told."""

    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self._root = root
        self.asked = 0

    def __call__(self, app: Any) -> None:
        app.offer_substrate(self._choose)

    def _choose(self, app: Any) -> StoreSubstrate:
        self.asked += 1
        return JsonFileSubstrate(self._root)


class _Installs(_Plugin):
    """A plugin that installs eagerly, at registration — the config-free door."""

    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self._root = root

    def __call__(self, app: Any) -> None:
        app.install_substrate(JsonFileSubstrate(self._root))


class _RefusesAtRegistration(_Plugin):
    """A storage plugin whose claim fails during its registration call."""

    name = "refuses-at-registration"

    def __call__(self, app: Any) -> None:
        raise SubstrateInstallError("this backend cannot be reached")


class TestTheOfferReadsResolvedConfig:
    """The regression this whole dispatch exists to close."""

    @pytest.mark.installed_plugins
    def test_a_configured_db_path_is_where_the_database_goes(
        self, project: Path
    ) -> None:
        """Entry-point discovery, a project config file, and nothing else."""
        sqlite = pytest.importorskip(
            "functualize_substrate_sqlite",
            reason="workspace plugins not installed; run `uv sync --all-packages`",
        )
        configured = project / "elsewhere" / "configured.db"
        configured.parent.mkdir()
        (project / "config.base.toml").write_text(
            f'[plugin.substrate-sqlite]\ndb_path = "{configured}"\n'
        )

        app = FunctualizeApp(
            name="offer-config", job_sources=JobSources(directories=[])
        )

        assert isinstance(app.substrate, sqlite.SQLiteSubstrate)
        assert Path(app.substrate.path) == configured, (
            "the plugin's offer did not see plugin.substrate-sqlite.db_path; "
            "it ran before configuration resolved"
        )


class TestTheOfferIsWhatTheEngineHolds:
    @pytest.mark.parametrize("path", sorted(_BOOTS))
    def test_one_offer_is_asked_once_and_is_the_storage(
        self, tmp_path: Path, path: str
    ) -> None:
        plugin = _Offers("offers-one", tmp_path / "offered")

        app = _BOOTS[path](plugin)

        assert plugin.asked == 1
        assert isinstance(app.substrate, JsonFileSubstrate)
        assert app.substrate.root == tmp_path / "offered"
        assert app.substrate is app.substrate_override

    def test_an_offer_after_boot_is_refused(self, tmp_path: Path) -> None:
        app = _static_app()

        with pytest.raises(SubstrateInstallError, match="already selected"):
            app.offer_substrate(lambda host: JsonFileSubstrate(tmp_path / "late"))


class TestTwoClaimantsRefuse:
    @pytest.mark.parametrize("path", sorted(_BOOTS))
    def test_two_offers_refuse_naming_both(self, tmp_path: Path, path: str) -> None:
        first = _Offers("offers-first", tmp_path / "a")
        second = _Offers("offers-second", tmp_path / "b")

        with pytest.raises(SubstrateInstallError) as refused:
            _BOOTS[path](first, second)

        message = str(refused.value)
        assert "offers-first" in message
        assert "offers-second" in message
        assert first.asked == second.asked == 0, "a claimant was asked anyway"

    @pytest.mark.parametrize("path", sorted(_BOOTS))
    def test_an_install_and_an_offer_refuse_by_the_same_rule(
        self, tmp_path: Path, path: str
    ) -> None:
        with pytest.raises(SubstrateInstallError) as refused:
            _BOOTS[path](
                _Installs("installs-eagerly", tmp_path / "a"),
                _Offers("offers-later", tmp_path / "b"),
            )

        assert "installs-eagerly" in str(refused.value)
        assert "offers-later" in str(refused.value)

    def test_the_outcome_does_not_depend_on_which_sorts_first(
        self, tmp_path: Path
    ) -> None:
        """Handed over in both orders: the same refusal, not a different winner."""
        messages = []
        for order in ((0, 1), (1, 0)):
            plugins = [
                _Offers("offers-a", tmp_path / "a"),
                _Offers("offers-z", tmp_path / "z"),
            ]
            with pytest.raises(SubstrateInstallError) as refused:
                _static_app(*(plugins[i] for i in order))
            messages.append(str(refused.value))

        assert messages[0] == messages[1]


class TestARegistrationTimeRefusalAbortsBoot:
    """Both registration loops re-raise it by name — no log-and-continue."""

    @pytest.mark.parametrize("path", sorted(_BOOTS))
    def test_it_propagates(self, path: str) -> None:
        with pytest.raises(SubstrateInstallError, match="cannot be reached"):
            _BOOTS[path](_RefusesAtRegistration())
