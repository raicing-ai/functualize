"""Boot step 6.5 selects the runtime store from ``runtime_store.url``.

Every store arrives through ``register_runtime_store_factory`` — boot's own
``documents`` factory first, then any plugin's — and the configured scheme
picks exactly one. Each case runs on **both** boot paths: ``boot_static``
(every source explicit) and ``boot_standard`` (discovery), because a selection
that holds on one path and not the other is the drift this step exists to
prevent.

Two breaks prove the call path (``tasks.md`` task 3): replacing
``_select_runtime_store``'s delegate with the old hard-wired body fails the
``stub:`` cases, and dropping boot's documents-factory registration fails the
unset and ``documents:`` cases.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.document_store import (
    DOCUMENT_PROFILE,
    DocumentRuntimeStore,
)
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import RuntimeStoreSelectionError, SubstrateInstallError
from functualize._types.persistence import (
    PreparedStore,
    RuntimeStoreConfig,
    StoreProfile,
)
from functualize.app.config import ConfigSources, JobSources, PluginSources


def alpha() -> None:
    """A job, so the app has something to register."""


class StubFactory:
    """A backend selected by ``stub:``; records what boot handed it."""

    scheme = "stub"
    profile: StoreProfile = DOCUMENT_PROFILE

    def __init__(self, root: Path, *, fail: bool = False, holds: str | None = None):
        self.substrate = JsonFileSubstrate(root / "stub-store")
        self.store = DocumentRuntimeStore(self.substrate)
        self.fail = fail
        self.holds = holds
        self.configs: list[RuntimeStoreConfig] = []

    def prepare(self, config: RuntimeStoreConfig) -> PreparedStore:
        self.configs.append(config)
        if self.fail:
            raise RuntimeError("stub store cannot open")
        return PreparedStore(store=self.store, substrate=self.substrate)

    def unselected_data(self, project_root: Path) -> str | None:
        return self.holds


class StubPlugin:
    """Registers its factory the way a storage plugin does, at registration."""

    version = "0.1.0"
    description = "Registers a stub runtime store."

    def __init__(self, name: str, factory: Any) -> None:
        self.name = name
        self._factory = factory

    def __call__(self, app: Any) -> None:
        app.register_runtime_store_factory(self._factory)


def _boot(
    path: str, tmp_path: Path, *plugins: object, url: str | None = None
) -> FunctualizeApp:
    defaults: dict[str, Any] = {} if url is None else {"runtime_store": {"url": url}}
    config = ConfigSources(
        config_resolution_chain=ResolutionChain([DefaultSource(defaults)])
    )
    sources = PluginSources(entry_point_group="", explicit_plugins=list(plugins))
    if path == "static":
        jobs = JobSources(functions=[alpha])
    else:
        directory = tmp_path / "jobs"
        directory.mkdir(exist_ok=True)
        (directory / "alpha.py").write_text('def alpha() -> None:\n    """A job."""\n')
        jobs = JobSources(directories=[str(directory)])
    app = FunctualizeApp(
        "selection", job_sources=jobs, config_sources=config, plugin_sources=sources
    )
    assert app._static_wiring is (path == "static")
    return app


@pytest.fixture(params=["static", "standard"])
def boot_path(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: Any) -> str:
    monkeypatch.chdir(tmp_path)
    return str(request.param)


@pytest.mark.parametrize("url", [None, "documents:"], ids=["unset", "documents"])
def test_the_documents_store_is_selected_through_its_registered_factory(
    boot_path: str, tmp_path: Path, url: str | None
) -> None:
    app = _boot(boot_path, tmp_path, url=url)

    store = app.execution_engine._runtime_store
    assert isinstance(store, DocumentRuntimeStore)
    assert store.profile is DOCUMENT_PROFILE
    registered = [f.scheme for _, f in app._runtime_store_factories]  # type: ignore[attr-defined]
    assert registered == ["documents"]


def test_a_configured_scheme_selects_the_plugins_store_and_substrate(
    boot_path: str, tmp_path: Path
) -> None:
    factory = StubFactory(tmp_path)
    app = _boot(boot_path, tmp_path, StubPlugin("stub-plugin", factory), url="stub:x")

    assert app.execution_engine._runtime_store is factory.store
    assert app.execution_engine.substrate is factory.substrate
    [config] = factory.configs
    assert (config.url, config.scheme, config.config_key) == (
        "stub:x",
        "stub",
        "runtime_store.url",
    )
    assert config.project_root == app.fresh_root


def test_installing_a_backend_does_not_select_it(
    boot_path: str, tmp_path: Path
) -> None:
    factory = StubFactory(tmp_path)
    app = _boot(boot_path, tmp_path, StubPlugin("stub-plugin", factory))

    assert factory.configs == []
    assert app.execution_engine._runtime_store is not factory.store


def test_an_unknown_scheme_is_refused_naming_the_key_and_the_registered_schemes(
    boot_path: str, tmp_path: Path
) -> None:
    plugin = StubPlugin("stub-plugin", StubFactory(tmp_path))
    with pytest.raises(RuntimeStoreSelectionError) as refused:
        _boot(boot_path, tmp_path, plugin, url="postgres://db")

    message = str(refused.value)
    assert "runtime_store.url" in message
    assert "'postgres'" in message
    assert "documents, stub" in message


def test_a_failing_prepare_aborts_boot(boot_path: str, tmp_path: Path) -> None:
    plugin = StubPlugin("stub-plugin", StubFactory(tmp_path, fail=True))
    with pytest.raises(RuntimeError, match="stub store cannot open"):
        _boot(boot_path, tmp_path, plugin, url="stub:")


def test_two_factories_for_one_scheme_are_refused_naming_both(
    boot_path: str, tmp_path: Path
) -> None:
    first = StubPlugin("stub-one", StubFactory(tmp_path))
    second = StubPlugin("stub-two", StubFactory(tmp_path))
    with pytest.raises(RuntimeStoreSelectionError) as refused:
        _boot(boot_path, tmp_path, first, second, url="stub:")

    assert "stub-one, stub-two" in str(refused.value)


def test_a_plugin_claiming_documents_is_refused_never_preferred(
    boot_path: str, tmp_path: Path
) -> None:
    impostor = StubFactory(tmp_path)
    impostor.scheme = "documents"
    with pytest.raises(
        RuntimeStoreSelectionError, match="claim the scheme 'documents'"
    ):
        _boot(boot_path, tmp_path, StubPlugin("impostor", impostor))


def test_unconfigured_data_held_by_a_backend_refuses_boot(
    boot_path: str, tmp_path: Path
) -> None:
    held = "state.db holds runtime data for this project."
    plugin = StubPlugin("stub-plugin", StubFactory(tmp_path, holds=held))
    with pytest.raises(RuntimeStoreSelectionError) as refused:
        _boot(boot_path, tmp_path, plugin)

    message = str(refused.value)
    assert message.startswith(held)
    assert 'runtime_store.url = "stub:"' in message
    assert '"documents:"' in message


def test_configured_selection_does_not_ask_about_unselected_data(
    boot_path: str, tmp_path: Path
) -> None:
    plugin = StubPlugin("stub-plugin", StubFactory(tmp_path, holds="held."))
    app = _boot(boot_path, tmp_path, plugin, url="documents:")

    assert isinstance(app.execution_engine._runtime_store, DocumentRuntimeStore)


def test_registration_after_selection_is_refused(
    boot_path: str, tmp_path: Path
) -> None:
    app = _boot(boot_path, tmp_path)
    with pytest.raises(SubstrateInstallError, match="already selected"):
        app.register_runtime_store_factory(StubFactory(tmp_path))
