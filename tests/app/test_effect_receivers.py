"""Effect receivers: registration, the capability it declares, the boot drain.

Row 2.3 of the gate-interactions-outbox feature. The production call path the
delivery tests prove is

    plugin __call__ → app.extensions.register_effect_receiver
    → boot step 6.5 (durable_outbox requirement + OutboxStore agreement)
    → boot end → _app.effects.drain → OutboxDispatcher.drain
    → receiver.receive → queue.published

on **both** boot paths, because a drain that holds on one path and not the
other is the drift ``tests/app/test_store_selection.py`` exists to prevent.
The committed intent each delivery test consumes is appended directly through
the SQLite store — the walker that appends one in a transaction with its
acceptance is task 2.1's proof, and the process-kill recovery is task 4.1's.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from functualize_substrate_sqlite import SQLiteSubstratePlugin
from functualize_substrate_sqlite._factory import SqliteRuntimeStoreFactory

from functualize import FunctualizeApp
from functualize._config.chain import ResolutionChain
from functualize._config.sources import DefaultSource
from functualize._primitives.document_store import (
    DOCUMENT_PROFILE,
    DocumentRuntimeStore,
)
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import (
    RuntimeStoreCapabilityError,
    RuntimeStoreSelectionError,
    SubstrateInstallError,
)
from functualize._types.persistence import (
    PreparedStore,
    RuntimeStoreConfig,
    StoreProfile,
)
from functualize.app.config import ConfigSources, JobSources, PluginSources

if TYPE_CHECKING:
    from functualize._types.persistence import EffectView

TOPIC = "gate.accepted"


def alpha() -> None:
    """A job, so the app has something to register."""


class Recorder:
    """An `EffectReceiver` that records what reached it, key and payload."""

    topic = TOPIC

    def __init__(self) -> None:
        self.received: list[EffectView] = []

    def receive(self, effect: EffectView) -> None:
        self.received.append(effect)


class ReceiverPlugin:
    """Registers its receiver the way a consumer package does, at registration."""

    version = "0.1.0"
    description = "Registers an effect receiver."

    def __init__(self, name: str, receiver: Any) -> None:
        self.name = name
        self._receiver = receiver

    def __call__(self, app: Any) -> None:
        app.extensions.register_effect_receiver(self._receiver)


def _sqlite_url(db: Path) -> str:
    return f"sqlite://{db}"


def _commit_one_intent(db: Path, key: str) -> None:
    """Append one committed gate-acceptance intent, as a dead process would leave."""
    store = cast(
        "Any",
        SqliteRuntimeStoreFactory()
        .prepare(
            RuntimeStoreConfig(
                url=_sqlite_url(db), scheme="sqlite", project_root=db.parent
            )
        )
        .store,
    )
    try:
        with store.transaction() as tx:
            tx.effects.append("gate", TOPIC, {"key": key}, f"{TOPIC}:{key}")
    finally:
        store.close()


def _boot(
    path: str,
    tmp_path: Path,
    *plugins: object,
    url: str | None = None,
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
    return FunctualizeApp(
        "receivers", job_sources=jobs, config_sources=config, plugin_sources=sources
    )


@pytest.fixture(params=["static", "standard"])
def boot_path(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: Any) -> str:
    monkeypatch.chdir(tmp_path)
    return str(request.param)


def test_boot_delivers_a_committed_intent_to_the_registered_receiver(
    boot_path: str, tmp_path: Path
) -> None:
    """The whole row in one line: an intent committed before boot is delivered
    to the receiver registered through the plugin door, by the drain at the
    end of boot, on both boot paths."""
    db = tmp_path / "state.db"
    _commit_one_intent(db, "answer-1")
    receiver = Recorder()

    app = _boot(
        boot_path,
        tmp_path,
        SQLiteSubstratePlugin(),
        ReceiverPlugin("receiver-plugin", receiver),
        url=_sqlite_url(db),
    )

    [effect] = receiver.received
    assert effect.topic == TOPIC
    assert effect.payload == {"key": "answer-1"}
    assert effect.idempotency_key == f"{TOPIC}:answer-1"
    published = app.workflow_runtime_store().effects.effect(effect.effect_id)
    assert published is not None
    assert published.status == "published"

    # A second process on the same file receives nothing: the first boot's
    # drain acknowledged the intent, and a published row is never due again.
    second = Recorder()
    _boot(
        boot_path,
        tmp_path,
        SQLiteSubstratePlugin(),
        ReceiverPlugin("receiver-plugin", second),
        url=_sqlite_url(db),
    )
    assert second.received == []


def test_documents_with_no_receiver_builds_no_dispatcher(
    boot_path: str, tmp_path: Path
) -> None:
    """A store declaring durable_outbox=False is never asked for a queue."""
    from functualize._app.effects import drain

    app = _boot(boot_path, tmp_path, url="documents:")

    assert isinstance(app.workflow_runtime_store(), DocumentRuntimeStore)
    # Touching `.effects` on the document store would raise AttributeError;
    # returning None without touching it is what "builds no dispatcher" means.
    assert drain(app, app.workflow_runtime_store()) is None


def test_documents_with_a_registered_receiver_refuses_boot(
    boot_path: str, tmp_path: Path
) -> None:
    """Registering a receiver declares durable_outbox=True; the document
    store lacks it and boot refuses, naming everything the operator needs."""
    with pytest.raises(RuntimeStoreCapabilityError) as refused:
        _boot(
            boot_path,
            tmp_path,
            ReceiverPlugin("receiver-plugin", Recorder()),
            url="documents:",
        )

    message = str(refused.value)
    assert "documents" in message
    assert "durable_outbox" in message
    assert "runtime_store.url" in message
    assert TOPIC in message


def test_registration_after_boot_selected_the_store_is_refused(
    boot_path: str, tmp_path: Path
) -> None:
    """A receiver that misses the boot drain would miss every intent after it
    too; it is refused, as a runtime store factory registered late is."""
    app = _boot(boot_path, tmp_path)
    with pytest.raises(SubstrateInstallError, match="already selected"):
        app.extensions.register_effect_receiver(Recorder())


class _UnbootedApp:
    """An app-shaped stand-in with no engine: the store is not yet selected,
    which is the only state the registration door's own refusals need."""


def test_the_door_refuses_a_second_receiver_for_one_topic() -> None:
    from functualize._app.impl import register_effect_receiver

    app = _UnbootedApp()
    register_effect_receiver(app, Recorder())
    with pytest.raises(ValueError, match="already registered"):
        register_effect_receiver(app, Recorder())
    assert list(app._effect_receivers) == [TOPIC]


def test_the_door_refuses_a_non_receiver_and_an_empty_topic() -> None:
    from functualize._app.impl import register_effect_receiver

    app = _UnbootedApp()
    with pytest.raises(TypeError, match="must provide a 'topic'"):
        register_effect_receiver(app, object())

    class NoTopic:
        topic = ""

        def receive(self, effect: EffectView) -> None: ...

    with pytest.raises(ValueError, match="non-empty string"):
        register_effect_receiver(app, NoTopic())
    assert not hasattr(app, "_effect_receivers") or not app._effect_receivers


class _ProfileLyingStore:
    """Declares durable_outbox=True; provides no effects queue."""

    profile: StoreProfile = replace(
        DOCUMENT_PROFILE, durable_outbox=True, name="profile-lying"
    )


class _QueueLyingStore(DocumentRuntimeStore):
    """Carries an effects attribute while declaring durable_outbox=False."""

    effects = None


class _LyingFactory:
    """Serves the ``lying:`` scheme with the store it was built around."""

    scheme = "lying"

    def __init__(self, store: Any, root: Path) -> None:
        self._store = store
        self.substrate = JsonFileSubstrate(root / "lying-store")

    def prepare(self, config: RuntimeStoreConfig) -> PreparedStore:
        return PreparedStore(store=self._store, substrate=self.substrate)

    def unselected_data(self, project_root: Path) -> str | None:
        return None


class _LyingPlugin:
    version = "0.1.0"
    description = "Registers a lying store."

    def __init__(self, factory: Any) -> None:
        self.name = "lying-plugin"
        self._factory = factory

    def __call__(self, app: Any) -> None:
        app.register_runtime_store_factory(self._factory)


@pytest.mark.parametrize(
    ("store", "complaint"),
    [
        (
            _ProfileLyingStore(),
            "declares durable_outbox=True but provides no effects queue",
        ),
        (
            _QueueLyingStore(JsonFileSubstrate(Path("."))),
            "provides an effects queue (OutboxStore) but declares durable_outbox=False",
        ),
    ],
    ids=["profile-claims-queue-missing", "queue-present-profile-denies"],
)
def test_a_store_whose_profile_and_type_disagree_is_refused(
    boot_path: str, tmp_path: Path, store: Any, complaint: str
) -> None:
    """The profile is the capability's one meaning; a store that misdescribes
    itself is refused at selection, not at the first drain that believed it."""
    plugin = _LyingPlugin(_LyingFactory(store, tmp_path))
    with pytest.raises(RuntimeStoreSelectionError) as refused:
        _boot(boot_path, tmp_path, plugin, url="lying:")

    message = str(refused.value)
    assert complaint in message
    assert "profile and type disagree" in message


def test_a_queue_that_cannot_be_read_does_not_stop_boot(
    boot_path: str, tmp_path: Path, monkeypatch: Any, caplog: Any
) -> None:
    """The boot drain's one caught failure: the queue itself. Intents stay
    committed for the next drain, so the app still starts, and says why
    nothing was delivered."""
    import sqlite3

    import functualize._app.effects as effects

    def locked(app: Any, store: Any) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(effects, "drain", locked)
    db = tmp_path / "state.db"
    _commit_one_intent(db, "answer-1")
    receiver = Recorder()

    with caplog.at_level("WARNING", logger="functualize._app.boot"):
        app = _boot(
            boot_path,
            tmp_path,
            SQLiteSubstratePlugin(),
            ReceiverPlugin("receiver-plugin", receiver),
            url=_sqlite_url(db),
        )

    assert receiver.received == []
    assert "database is locked" in caplog.text
    assert app.workflow_runtime_store().profile.durable_outbox is True
