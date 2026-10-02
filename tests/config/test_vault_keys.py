"""Key resolution: the terminal rule is for prompting, not for reading.

The rule these tests exist for splits in two. A provider that can only obtain
the key by asking a person at a terminal is never consulted without one — an
unattended run must not hang on a prompt. A provider that merely *may block*
on a backend (the keyring showing its own unlock dialog) is read regardless of
terminal and bounded by the resolver's deadline instead, and its failures are
typed so the refusal can say what actually happened.
"""

from __future__ import annotations

import sys

import pytest

from functualize._config.vault import (
    KEY_BYTES,
    KeyringLockedError,
    KeyringUnavailableError,
    KeyringUnverifiedError,
    VaultError,
)
from functualize._config.vault_key_resolver import (
    KeyAccess,
    KeyStatus,
    VaultKeyResolver,
)
from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow
from functualize._config.vault_keys import (
    ENV_VAR,
    EnvKeyProvider,
    KeychainKeyProvider,
    generate_key,
)
from functualize._types.enums import KeyAvailability
from functualize.plugin import VaultKeyProbe, VaultKeyProvider

_HEX_A = "a" * (KEY_BYTES * 2)
_HEX_B = "b" * (KEY_BYTES * 2)


class _FakeProvider:
    """A stand-in for any third-party key provider."""

    def __init__(
        self,
        ident: str,
        *,
        interactive: bool,
        available: bool = True,
        key: bytes | None = None,
    ) -> None:
        self._id = ident
        self._interactive = interactive
        self._available = available
        self._key = key
        self.get_key_calls = 0

    def identifier(self) -> str:
        return self._id

    def interactive(self) -> bool:
        return self._interactive

    def is_available(self) -> bool:
        return self._available

    def get_key(self, project_id: str) -> bytes | None:
        self.get_key_calls += 1
        return self._key


class _Terminal:
    """A stand-in for the `sys` module the resolver reads: a real terminal."""

    class _Tty:
        @staticmethod
        def isatty() -> bool:
            return True

    stdin = _Tty()
    stdout = _Tty()


@pytest.fixture
def on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("functualize._config.vault_key_resolver.sys", _Terminal())


def _lookup(*providers: _FakeProvider) -> object:
    return VaultKeyResolver("proj", list(providers)).lookup(KeyAccess.FOREGROUND)


class TestResolutionOrder:
    """Ported from the deleted terminal-flag resolver in `vault_keys`: the
    same rules, now asked of the resolver. The terminal decides only whether a
    provider that *needs* one is consulted."""

    @pytest.mark.usefixtures("on_a_terminal")
    def test_non_interactive_wins_over_interactive(self) -> None:
        env = _FakeProvider("env", interactive=False, key=b"\x01" * KEY_BYTES)
        chain = _FakeProvider("prompt", interactive=True, key=b"\x02" * KEY_BYTES)
        # Interactive listed FIRST, to prove order is not registration order.
        got = _lookup(chain, env)
        assert got.provider_id == "env"  # type: ignore[attr-defined]
        assert chain.get_key_calls == 0

    def test_an_interactive_provider_is_never_reached_without_a_tty(self) -> None:
        """The Lambda-hangs-on-a-prompt case."""
        chain = _FakeProvider("prompt", interactive=True, key=b"\x02" * KEY_BYTES)
        got = _lookup(chain)
        assert got.status is not KeyStatus.FOUND  # type: ignore[attr-defined]
        assert chain.get_key_calls == 0

    @pytest.mark.usefixtures("on_a_terminal")
    def test_an_interactive_provider_is_reached_with_a_tty(self) -> None:
        chain = _FakeProvider("prompt", interactive=True, key=b"\x02" * KEY_BYTES)
        got = _lookup(chain)
        assert got.provider_id == "prompt"  # type: ignore[attr-defined]

    def test_a_provider_that_needs_no_terminal_is_read_without_one(self) -> None:
        """The rule this feature exists for: a pipe is not a reason to skip a
        keyring that can answer."""
        keyring = _FakeProvider("keychain", interactive=False, key=b"\x05" * KEY_BYTES)
        got = _lookup(keyring)
        assert got.provider_id == "keychain"  # type: ignore[attr-defined]

    def test_an_unavailable_provider_is_skipped(self) -> None:
        absent = _FakeProvider("absent", interactive=False, available=False)
        present = _FakeProvider("present", interactive=False, key=b"\x03" * KEY_BYTES)
        got = _lookup(absent, present)
        assert got.provider_id == "present"  # type: ignore[attr-defined]
        assert absent.get_key_calls == 0

    def test_a_provider_returning_none_defers_to_the_next(self) -> None:
        """Returning None is normal, not an error."""
        empty = _FakeProvider("empty", interactive=False, key=None)
        full = _FakeProvider("full", interactive=False, key=b"\x04" * KEY_BYTES)
        got = _lookup(empty, full)
        assert got.provider_id == "full"  # type: ignore[attr-defined]

    def test_no_provider_at_all_is_no_keyring(self) -> None:
        """The caller decides whether that is fatal."""
        assert _lookup().status is KeyStatus.NO_KEYRING  # type: ignore[attr-defined]


class TestTheEnvProvider:
    def test_it_is_not_interactive(self) -> None:
        assert EnvKeyProvider().interactive() is False

    def test_it_reads_a_hex_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ENV_VAR, _HEX_A)
        key = EnvKeyProvider().get_key("proj")
        assert key == bytes.fromhex(_HEX_A)
        assert len(key or b"") == KEY_BYTES

    def test_it_tolerates_surrounding_whitespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A key pasted into a shell profile often carries a newline."""
        monkeypatch.setenv(ENV_VAR, f"  {_HEX_A}\n")
        assert EnvKeyProvider().get_key("proj") == bytes.fromhex(_HEX_A)

    def test_it_is_unavailable_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ENV_VAR, raising=False)
        provider = EnvKeyProvider()
        assert provider.is_available() is False
        assert provider.get_key("proj") is None

    def test_an_empty_variable_is_unavailable_not_a_zero_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "   ")
        assert EnvKeyProvider().is_available() is False
        assert EnvKeyProvider().get_key("proj") is None

    @pytest.mark.parametrize("bad", ["nothex!!", "zz" * KEY_BYTES])
    def test_a_non_hex_key_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch, bad: str
    ) -> None:
        monkeypatch.setenv(ENV_VAR, bad)
        with pytest.raises(VaultError, match="not valid hex"):
            EnvKeyProvider().get_key("proj")

    @pytest.mark.parametrize("length", [2, 30, 31, 33, 64])
    def test_a_wrong_length_key_fails_rather_than_being_padded(
        self, monkeypatch: pytest.MonkeyPatch, length: int
    ) -> None:
        """A truncated key must not silently become a different valid key."""
        monkeypatch.setenv(ENV_VAR, "ab" * length)
        with pytest.raises(VaultError, match="bytes, expected 32"):
            EnvKeyProvider().get_key("proj")

    def test_the_error_names_the_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(ENV_VAR, "ab")
        with pytest.raises(VaultError, match=ENV_VAR):
            EnvKeyProvider().get_key("proj")


class TestTheKeychainProvider:
    def test_it_does_not_need_a_terminal(self) -> None:
        """Reading needs no person at *this* process's terminal, and never
        prompts, so a pipe is not a reason to skip the read.

        Rewritten from `test_it_is_interactive` (interactive() was True): the
        TTY gate this feature removes was exactly that flag.
        """
        assert KeychainKeyProvider().interactive() is False

    def test_a_missing_keyring_is_unavailable_and_refuses_with_its_own_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing optional dep degrades, never crashes — and the refusal is
        typed, so the resolver can say *no keyring* instead of a false
        "no key is available".
        """
        monkeypatch.setitem(sys.modules, "keyring", None)
        provider = KeychainKeyProvider()
        assert provider.is_available() is False
        with pytest.raises(KeyringUnavailableError, match="functualize\\[keychain\\]"):
            provider.get_key("proj")


class _ScriptedAdapter:
    """A keyring adapter that answers what a test says, and counts the calls."""

    def __init__(
        self,
        read: AdapterRead,
        *,
        state: KeyAvailability = KeyAvailability.UNKNOWN,
        unlocked: AdapterRead | None = None,
    ) -> None:
        self._read = read
        self._state = state
        self._unlocked = unlocked or read
        self.reads = 0
        self.unlocks = 0

    @property
    def name(self) -> str:
        return "scripted"

    def read_silent(self) -> AdapterRead:
        self.reads += 1
        return self._read

    def state(self) -> KeyAvailability:
        return self._state

    def unlock(self) -> AdapterRead:
        self.unlocks += 1
        return self._unlocked


def _provider(read: AdapterRead, **kwargs: object) -> KeychainKeyProvider:
    return KeychainKeyProvider(adapter=_ScriptedAdapter(read, **kwargs))  # type: ignore[arg-type]


class TestKeychainFailureStatesAreTyped:
    """Locked / no keyring / unverified / nothing stored are different answers,
    and the refusal text must be able to say which one happened (the field
    report this feature exists for was one false sentence covering them all).
    """

    def test_a_locked_keyring_raises_locked(self) -> None:
        with pytest.raises(KeyringLockedError, match="locked"):
            _provider(AdapterRead(AdapterOutcome.LOCKED)).get_key("proj")

    def test_no_keyring_raises_unavailable(self) -> None:
        with pytest.raises(KeyringUnavailableError, match="keychain"):
            _provider(AdapterRead(AdapterOutcome.NO_KEYRING)).get_key("proj")

    def test_an_unverified_backend_raises_unverified(self) -> None:
        with pytest.raises(KeyringUnverifiedError, match="vault unlock"):
            _provider(AdapterRead(AdapterOutcome.UNVERIFIED)).get_key("proj")

    def test_nothing_stored_returns_none(self) -> None:
        """None means 'an unlocked keyring answered; nothing is stored'. The
        resolver turns it into NOT_STORED."""
        assert _provider(AdapterRead(AdapterOutcome.NOT_STORED)).get_key("proj") is None

    def test_a_found_secret_is_decoded(self) -> None:
        key = _provider(AdapterRead(AdapterOutcome.FOUND, secret=_HEX_A)).get_key(
            "proj"
        )
        assert key == bytes.fromhex(_HEX_A)

    def test_a_malformed_secret_is_a_loud_error(self) -> None:
        with pytest.raises(VaultError, match="not valid hex"):
            _provider(AdapterRead(AdapterOutcome.FOUND, secret="nothex")).get_key(
                "proj"
            )

    def test_get_key_never_unlocks(self) -> None:
        """The provider contract: a read never asks the keyring to unlock."""
        adapter = _ScriptedAdapter(AdapterRead(AdapterOutcome.LOCKED))
        with pytest.raises(KeyringLockedError):
            KeychainKeyProvider(adapter=adapter).get_key("proj")  # type: ignore[arg-type]
        assert (adapter.reads, adapter.unlocks) == (1, 0)


class TestTheProbe:
    """status/inspect ask 'would a read succeed?' and must never prompt."""

    @pytest.mark.parametrize("state", list(KeyAvailability))
    def test_it_is_the_adapter_state(self, state: KeyAvailability) -> None:
        provider = _provider(AdapterRead(AdapterOutcome.NOT_STORED), state=state)
        assert provider.probe() is state

    def test_the_probe_does_not_read_the_key(self) -> None:
        adapter = _ScriptedAdapter(
            AdapterRead(AdapterOutcome.FOUND, secret=_HEX_A),
            state=KeyAvailability.UNLOCKED,
        )
        KeychainKeyProvider(adapter=adapter).probe()  # type: ignore[arg-type]
        assert (adapter.reads, adapter.unlocks) == (0, 0)

    def test_the_shipped_provider_satisfies_the_probe_protocol(self) -> None:
        assert isinstance(KeychainKeyProvider(), VaultKeyProbe)


class TestUnlock:
    def test_it_satisfies_the_unlocker_protocol(self) -> None:
        from functualize.plugin import VaultKeyUnlocker

        assert isinstance(KeychainKeyProvider(), VaultKeyUnlocker)

    def test_unlocking_returns_the_key_with_how_it_went(self) -> None:
        provider = _provider(
            AdapterRead(AdapterOutcome.LOCKED),
            unlocked=AdapterRead(
                AdapterOutcome.FOUND, secret=_HEX_B, how=UnlockHow.UNLOCKED_NOW
            ),
        )
        unlocked = provider.unlock_key()
        assert unlocked.key == bytes.fromhex(_HEX_B)
        assert unlocked.how is UnlockHow.UNLOCKED_NOW
        assert _HEX_B not in repr(unlocked)

    def test_a_cancelled_unlock_is_false(self) -> None:
        provider = _provider(
            AdapterRead(AdapterOutcome.LOCKED),
            unlocked=AdapterRead(AdapterOutcome.LOCKED, how=UnlockHow.CANCELLED),
        )
        assert provider.unlock() is False


class TestTheAdapterIsChosenForThisPlatform:
    def test_it_is_built_once_with_the_fixed_service_and_account(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One key for every project (ADR-023 §4): the address never involves
        the project id."""
        from functualize._config import vault_keyring
        from functualize._config.vault_keys import KEYCHAIN_ACCOUNT, KEYCHAIN_SERVICE

        calls: list[tuple[str, str]] = []

        def recording(service: str, account: str, **kwargs: object) -> _ScriptedAdapter:
            calls.append((service, account))
            return _ScriptedAdapter(AdapterRead(AdapterOutcome.NOT_STORED))

        monkeypatch.setattr(vault_keyring, "select_adapter", recording)
        provider = KeychainKeyProvider()
        provider.get_key("project-aaa")
        provider.get_key("project-bbb")

        assert calls == [(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)]


class _StoreKeyring:
    """`keyring` at the module boundary, for the write path `init` still uses."""

    def __init__(self) -> None:
        import keyring.errors as real_errors

        self.store: dict[tuple[str, str], str] = {}
        self.locked = False
        self.errors = real_errors

    def set_password(self, service: str, account: str, password: str) -> None:
        if self.locked:
            raise self.errors.KeyringLocked("collection is locked")
        self.store[(service, account)] = password


class _StoreAdapter:
    """Reads the same store `_StoreKeyring` writes, as an unlocked keyring would."""

    def __init__(self, keyring_module: _StoreKeyring) -> None:
        self._keyring = keyring_module

    @property
    def name(self) -> str:
        return "store"

    def read_silent(self) -> AdapterRead:
        from functualize._config.vault_keys import KEYCHAIN_ACCOUNT, KEYCHAIN_SERVICE

        if self._keyring.locked:
            return AdapterRead(AdapterOutcome.LOCKED)
        secret = self._keyring.store.get((KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT))
        if secret is None:
            return AdapterRead(AdapterOutcome.NOT_STORED)
        return AdapterRead(AdapterOutcome.FOUND, secret=secret)

    def state(self) -> KeyAvailability:
        return (
            KeyAvailability.LOCKED if self._keyring.locked else KeyAvailability.UNLOCKED
        )

    def unlock(self) -> AdapterRead:
        read = self.read_silent()
        how = (
            UnlockHow.CANCELLED if self._keyring.locked else UnlockHow.ALREADY_UNLOCKED
        )
        return AdapterRead(read.outcome, secret=read.secret, how=how)


@pytest.fixture
def store_keyring(monkeypatch: pytest.MonkeyPatch) -> _StoreKeyring:
    fake = _StoreKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake.errors)
    return fake


def _store_provider(store: _StoreKeyring) -> KeychainKeyProvider:
    return KeychainKeyProvider(adapter=_StoreAdapter(store))  # type: ignore[arg-type]


class TestGenerateKey:
    def test_it_produces_a_decodable_key_of_the_right_size(self) -> None:
        key = generate_key()
        assert len(key) == KEY_BYTES * 2
        assert len(bytes.fromhex(key)) == KEY_BYTES

    def test_successive_keys_differ(self) -> None:
        assert len({generate_key() for _ in range(20)}) == 20

    def test_a_generated_key_round_trips_through_the_env_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """keygen's output must be exactly what the env provider accepts."""
        monkeypatch.setenv(ENV_VAR, generate_key())
        assert EnvKeyProvider().get_key("proj") is not None


class TestProtocolConformance:
    @pytest.mark.parametrize(
        "provider", [EnvKeyProvider(), KeychainKeyProvider()], ids=["env", "keychain"]
    )
    def test_shipped_providers_satisfy_the_public_protocol(
        self, provider: object
    ) -> None:
        assert isinstance(provider, VaultKeyProvider)


class TestKeychainKeyScope:
    """One key for every project (ADR-023 §4)."""

    def test_two_projects_read_the_same_key(self, store_keyring: _StoreKeyring) -> None:
        """The change itself. The provider used to key on project_id."""
        from functualize._config.vault_keys import KEYCHAIN_ACCOUNT, KEYCHAIN_SERVICE

        store_keyring.store[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] = generate_key()
        provider = _store_provider(store_keyring)

        assert provider.get_key("project-aaa") == provider.get_key("project-bbb")
        assert provider.get_key("project-aaa") is not None

    def test_it_agrees_with_the_environment_provider(
        self, store_keyring: _StoreKeyring, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both shipped providers ignore project_id. The hazard this closes is
        that *which* scope applied depended on whether the env var was set."""
        key = generate_key()
        monkeypatch.setenv(ENV_VAR, key)
        env = EnvKeyProvider()
        keychain = _store_provider(store_keyring)

        assert env.get_key("a") == env.get_key("b")
        assert keychain.get_key("a") == keychain.get_key("b")


class TestKeychainInitialize:
    def test_it_creates_and_persists_a_key(self, store_keyring: _StoreKeyring) -> None:
        from functualize._config.vault_keys import KEYCHAIN_ACCOUNT, KEYCHAIN_SERVICE

        created = _store_provider(store_keyring).initialize_key("proj")

        assert len(created) == KEY_BYTES
        assert (KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) in store_keyring.store

    def test_it_is_idempotent(self, store_keyring: _StoreKeyring) -> None:
        """A second call must return what the first persisted.

        Generating a fresh key here would strand every value already written
        under the old one — silently, because nothing in the store records
        which key wrote a row.
        """
        provider = _store_provider(store_keyring)

        first = provider.initialize_key("proj")
        second = provider.initialize_key("proj")

        assert first == second
        assert len(store_keyring.store) == 1

    def test_it_returns_the_same_key_for_any_project(
        self, store_keyring: _StoreKeyring
    ) -> None:
        provider = _store_provider(store_keyring)

        assert provider.initialize_key("one") == provider.initialize_key("two")

    def test_a_locked_keyring_refuses_rather_than_returning_a_stray_key(
        self, store_keyring: _StoreKeyring
    ) -> None:
        store_keyring.locked = True

        with pytest.raises(VaultError, match="keyring"):
            _store_provider(store_keyring).initialize_key("proj")
        assert store_keyring.store == {}

    def test_it_satisfies_the_initializer_protocol(self) -> None:
        """T1.2 shipped the port unwired; this is the shipped implementor."""
        from functualize.plugin import VaultKeyInitializer

        assert isinstance(KeychainKeyProvider(), VaultKeyInitializer)

    def test_the_environment_provider_is_not_an_initializer(self) -> None:
        """It cannot be: only the operator can set an environment variable."""
        from functualize.plugin import VaultKeyInitializer, VaultKeyProvider

        provider = EnvKeyProvider()
        assert isinstance(provider, VaultKeyProvider)
        assert not isinstance(provider, VaultKeyInitializer)


def _backend(module: str, name: str, **attributes: object) -> object:
    """An object whose class looks like a `keyring` backend, without importing one."""
    kind = type(name, (), dict(attributes))
    kind.__module__ = module
    kind.__qualname__ = name
    return kind()


_SECRET_SERVICE = ("keyring.backends.SecretService", "Keyring")
_MACOS = ("keyring.backends.macOS", "Keyring")
_WINDOWS = ("keyring.backends.Windows", "WinVaultKeyring")


class TestTheAllowlist:
    """Only backends proven silent get a platform adapter (spec B9, D14)."""

    @pytest.mark.parametrize(
        ("backend", "platform", "adapter"),
        [
            (_SECRET_SERVICE, "linux", "linux"),
            (("keyring.backends.libsecret", "Keyring"), "linux", "linux"),
            (_SECRET_SERVICE, "freebsd14", "linux"),
            (_MACOS, "darwin", "macos"),
            (_WINDOWS, "win32", "windows"),
            # A platform backend on the wrong platform is not proven silent.
            (_SECRET_SERVICE, "darwin", "keyring"),
            (_MACOS, "linux", "keyring"),
            (_WINDOWS, "linux", "keyring"),
            # A third-party backend nobody has proven silent.
            (("keyrings.alt.file", "PlaintextKeyring"), "linux", "keyring"),
        ],
    )
    def test_the_adapter_follows_backend_and_platform(
        self, backend: tuple[str, str], platform: str, adapter: str
    ) -> None:
        from functualize._config.vault_keyring import select_adapter

        chosen = select_adapter(
            "functualize-vault",
            "vault-key",
            platform=platform,
            backend=_backend(*backend),
        )
        assert chosen.name == adapter

    def test_an_unproven_backend_is_never_read_by_a_run(self) -> None:
        from functualize._config.vault_keyring import select_adapter

        chosen = select_adapter(
            "functualize-vault",
            "vault-key",
            platform="linux",
            backend=_backend("keyrings.alt.file", "PlaintextKeyring"),
        )
        assert chosen.read_silent().outcome is AdapterOutcome.UNVERIFIED

    @pytest.mark.parametrize(
        "backend",
        [None, _backend("keyring.backends.fail", "Keyring")],
        ids=["none", "fail"],
    )
    def test_no_backend_is_no_keyring(self, backend: object) -> None:
        from functualize._config.vault_keyring import select_adapter

        chosen = select_adapter(
            "functualize-vault", "vault-key", platform="linux", backend=backend
        )
        assert chosen.read_silent().outcome is AdapterOutcome.NO_KEYRING

    def test_a_chainer_is_decided_by_its_first_real_backend(self) -> None:
        from functualize._config.vault_keyring import select_adapter

        chainer = _backend(
            "keyring.backends.chainer",
            "ChainerBackend",
            backends=[
                _backend("keyring.backends.fail", "Keyring"),
                _backend(*_SECRET_SERVICE),
            ],
        )
        chosen = select_adapter(
            "functualize-vault", "vault-key", platform="linux", backend=chainer
        )
        assert chosen.name == "linux"
