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
import types

import pytest

from functualize._config.vault import (
    KEY_BYTES,
    KeyringLockedError,
    KeyringUnavailableError,
    VaultError,
)
from functualize._config.vault_key_resolver import (
    KeyAccess,
    KeyStatus,
    VaultKeyResolver,
)
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
        """Reading may block on the backend; it needs no person at *this*
        process's terminal. The resolver's deadline is the bound, so a pipe is
        not a reason to skip the read.

        Rewritten from `test_it_is_interactive` (interactive() was True): the
        TTY gate this feature removes was exactly that flag.
        """
        assert KeychainKeyProvider().interactive() is False

    def test_a_missing_keyring_is_unavailable_and_refuses_with_its_own_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing optional dep degrades, never crashes — and the refusal is
        now typed, so the resolver can say *no keyring* instead of a false
        "no key is available".

        `keyring` is a declared extra (`functualize[keychain]`) rather than
        something present transitively by accident, but declaring it does not
        make it installed: a base `pip install functualize` has no keyring,
        and that must stay a reported state.
        """
        monkeypatch.setitem(sys.modules, "keyring", None)
        provider = KeychainKeyProvider()
        assert provider.is_available() is False
        with pytest.raises(KeyringUnavailableError, match="functualize\\[keychain\\]"):
            provider.get_key("proj")


class _FakeKeyring:
    """A keyring backend in a dict, so scope can be asserted on the real API.

    Mocking `get_key` would assert nothing: the whole change is *which
    (service, account) pair* the provider reads and writes, so the fake has to
    be at the `keyring` module boundary where that pair is visible. Raises the
    *real* `keyring.errors` exceptions so the provider's typed mapping is
    exercised against the classes the installed library actually raises.
    """

    def __init__(self) -> None:
        import keyring.errors as real_errors

        self.store: dict[tuple[str, str], str] = {}
        self.locked = False
        self.error: Exception | None = None
        self.errors = real_errors

    def get_password(self, service: str, account: str) -> str | None:
        if self.error is not None:
            raise self.error
        if self.locked:
            raise self.errors.KeyringLocked("collection is locked")
        return self.store.get((service, account))

    def set_password(self, service: str, account: str, password: str) -> None:
        if self.locked:
            raise self.errors.KeyringLocked("collection is locked")
        self.store[(service, account)] = password


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> _FakeKeyring:
    fake = _FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake.errors)
    return fake


class TestKeychainFailureStatesAreTyped:
    """Locked / no-backend / nothing-stored are three different answers, and
    the refusal text must be able to say which one happened (the field report
    this feature exists for was one false sentence covering all three).
    """

    def test_a_locked_keyring_raises_locked(self, fake_keyring: _FakeKeyring) -> None:
        fake_keyring.locked = True
        with pytest.raises(KeyringLockedError, match="locked"):
            KeychainKeyProvider().get_key("proj")

    def test_a_backendless_environment_raises_unavailable(
        self, fake_keyring: _FakeKeyring
    ) -> None:
        fake_keyring.error = fake_keyring.errors.NoKeyringError("no backend")
        with pytest.raises(KeyringUnavailableError):
            KeychainKeyProvider().get_key("proj")

    def test_a_failed_backend_init_raises_unavailable(
        self, fake_keyring: _FakeKeyring
    ) -> None:
        fake_keyring.error = fake_keyring.errors.InitError("chainer failed")
        with pytest.raises(KeyringUnavailableError):
            KeychainKeyProvider().get_key("proj")

    def test_a_raw_runtime_error_from_backend_init_raises_unavailable(
        self, fake_keyring: _FakeKeyring
    ) -> None:
        """keyring raises bare RuntimeError when no backend could be chosen."""
        fake_keyring.error = RuntimeError("No recommended backend was available")
        with pytest.raises(KeyringUnavailableError):
            KeychainKeyProvider().get_key("proj")

    def test_a_live_backend_with_no_entry_returns_none(
        self, fake_keyring: _FakeKeyring
    ) -> None:
        """None means 'a keyring answered; nothing is stored' — not locked,
        not missing. The resolver turns it into NOT_STORED."""
        assert KeychainKeyProvider().get_key("proj") is None


class _FakeCollection:
    def __init__(self, locked: bool) -> None:
        self._locked = locked

    def is_locked(self) -> bool:
        return self._locked


class _FakeSecretStorage(types.ModuleType):
    """Stands in for `secretstorage` at the module boundary the probe imports.

    The probe asks the default collection's Locked property — the same read
    keyring's SecretService backend makes before calling unlock() — so the
    fake has to sit where dbus_init/get_default_collection are visible.
    """

    def __init__(
        self, collection: _FakeCollection | None, error: Exception | None = None
    ):
        super().__init__("secretstorage")
        self._collection = collection
        self._error = error

    def dbus_init(self) -> object:
        if self._error is not None:
            raise self._error
        return object()

    def get_default_collection(self, bus: object) -> _FakeCollection | None:
        return self._collection


def _install_secretstorage(
    monkeypatch: pytest.MonkeyPatch, fake: _FakeSecretStorage
) -> None:
    monkeypatch.setitem(sys.modules, "secretstorage", fake)


class TestTheProbe:
    """status/inspect ask 'would a read prompt?' and must never prompt."""

    def test_an_unlocked_collection_probes_unlocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_secretstorage(
            monkeypatch, _FakeSecretStorage(_FakeCollection(locked=False))
        )
        assert KeychainKeyProvider().probe() is KeyAvailability.UNLOCKED

    def test_a_locked_collection_probes_locked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_secretstorage(
            monkeypatch, _FakeSecretStorage(_FakeCollection(locked=True))
        )
        assert KeychainKeyProvider().probe() is KeyAvailability.LOCKED

    def test_a_missing_secretstorage_answers_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "secretstorage", None)
        assert KeychainKeyProvider().probe() is KeyAvailability.UNKNOWN

    def test_a_dead_dbus_answers_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_secretstorage(
            monkeypatch,
            _FakeSecretStorage(None, error=RuntimeError("no session bus")),
        )
        assert KeychainKeyProvider().probe() is KeyAvailability.UNKNOWN

    def test_no_default_collection_answers_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_secretstorage(monkeypatch, _FakeSecretStorage(None))
        assert KeychainKeyProvider().probe() is KeyAvailability.UNKNOWN

    def test_the_shipped_provider_satisfies_the_probe_protocol(self) -> None:
        assert isinstance(KeychainKeyProvider(), VaultKeyProbe)

    def test_the_probe_does_not_read_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A probe is a question about prompting, not a read: it must leave
        the keyring untouched — no get_password, no entry access."""

        class _RecordingKeyring(_FakeKeyring):
            def __init__(self) -> None:
                super().__init__()
                self.reads = 0

            def get_password(self, service: str, account: str) -> str | None:
                self.reads += 1
                return super().get_password(service, account)

        recording = _RecordingKeyring()
        monkeypatch.setitem(sys.modules, "keyring", recording)
        monkeypatch.setitem(sys.modules, "keyring.errors", recording.errors)
        _install_secretstorage(
            monkeypatch, _FakeSecretStorage(_FakeCollection(locked=True))
        )

        KeychainKeyProvider().probe()

        assert recording.reads == 0


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

    def test_two_projects_read_the_same_key(self, fake_keyring: _FakeKeyring) -> None:
        """The change itself. The provider used to key on project_id."""
        from functualize._config.vault_keys import (
            KEYCHAIN_ACCOUNT,
            KEYCHAIN_SERVICE,
            KeychainKeyProvider,
        )

        fake_keyring.store[(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)] = generate_key()
        provider = KeychainKeyProvider()

        assert provider.get_key("project-aaa") == provider.get_key("project-bbb")
        assert provider.get_key("project-aaa") is not None

    def test_it_never_reads_a_project_scoped_entry(
        self, fake_keyring: _FakeKeyring
    ) -> None:
        """A key left at the old per-project address is not picked up.

        Stated as a test because it is the one visible consequence for anyone
        who had manually run `keyring set functualize-vault <project_id>`:
        nothing in functualize has ever written such an entry, so this is
        expected to affect nobody, but it should fail loudly if it does rather
        than resolve a key the current code would not have written.
        """
        from functualize._config.vault_keys import (
            KEYCHAIN_SERVICE,
            KeychainKeyProvider,
        )

        fake_keyring.store[(KEYCHAIN_SERVICE, "some-project-id")] = generate_key()

        assert KeychainKeyProvider().get_key("some-project-id") is None

    def test_it_agrees_with_the_environment_provider(
        self, fake_keyring: _FakeKeyring, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both shipped providers ignore project_id. The hazard this closes is
        that *which* scope applied depended on whether the env var was set."""
        from functualize._config.vault_keys import (
            ENV_VAR,
            EnvKeyProvider,
            KeychainKeyProvider,
        )

        key = generate_key()
        monkeypatch.setenv(ENV_VAR, key)
        env = EnvKeyProvider()

        assert env.get_key("a") == env.get_key("b")
        assert KeychainKeyProvider().get_key("a") == KeychainKeyProvider().get_key("b")


class TestKeychainInitialize:
    def test_it_creates_and_persists_a_key(self, fake_keyring: _FakeKeyring) -> None:
        from functualize._config.vault_keys import (
            KEYCHAIN_ACCOUNT,
            KEYCHAIN_SERVICE,
            KeychainKeyProvider,
        )

        created = KeychainKeyProvider().initialize_key("proj")

        assert len(created) == KEY_BYTES
        assert (KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) in fake_keyring.store

    def test_it_is_idempotent(self, fake_keyring: _FakeKeyring) -> None:
        """A second call must return what the first persisted.

        Generating a fresh key here would strand every value already written
        under the old one — silently, because nothing in the store records
        which key wrote a row.
        """
        provider = KeychainKeyProvider()

        first = provider.initialize_key("proj")
        second = provider.initialize_key("proj")

        assert first == second
        assert len(fake_keyring.store) == 1

    def test_it_returns_the_same_key_for_any_project(
        self, fake_keyring: _FakeKeyring
    ) -> None:
        provider = KeychainKeyProvider()

        assert provider.initialize_key("one") == provider.initialize_key("two")

    def test_a_locked_keyring_refuses_rather_than_returning_a_stray_key(
        self, fake_keyring: _FakeKeyring
    ) -> None:
        from functualize._config.vault import VaultError

        fake_keyring.locked = True

        with pytest.raises(VaultError, match="keyring"):
            KeychainKeyProvider().initialize_key("proj")

    def test_it_satisfies_the_initializer_protocol(
        self, fake_keyring: _FakeKeyring
    ) -> None:
        """T1.2 shipped the port unwired; this is the shipped implementor."""
        from functualize.plugin import VaultKeyInitializer

        assert isinstance(KeychainKeyProvider(), VaultKeyInitializer)

    def test_the_environment_provider_is_not_an_initializer(self) -> None:
        """It cannot be: only the operator can set an environment variable."""
        from functualize.plugin import VaultKeyInitializer, VaultKeyProvider

        provider = EnvKeyProvider()
        assert isinstance(provider, VaultKeyProvider)
        assert not isinstance(provider, VaultKeyInitializer)
