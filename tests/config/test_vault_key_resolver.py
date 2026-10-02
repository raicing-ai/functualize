"""The resolver: env first, one bounded wait, one memo, honest messages.

The field report this feature exists for was one false sentence — "no vault
key is available on this machine" — covering a locked keyring, a missing one
and an empty one, in a run whose stdout happened to be a pipe. These tests
pin the replacement contract: reads happen regardless of terminal, a blocking
backend costs one deadline (not one per lookup), the outcome is remembered,
and the refusal says which of the four states happened with next steps that
never destroy a secret that is fine.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

from functualize._config.vault import (
    KEY_BYTES,
    KeyringLockedError,
    KeyringUnavailableError,
    VaultError,
)
from functualize._config.vault_key_resolver import (
    KeyAccess,
    KeyLookup,
    KeyStatus,
    VaultKeyResolver,
    describe_key_failure,
    resolve_vault_key,
)
from functualize._types.enums import KeyAvailability

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._types.protocols import VaultKeyProvider

_KEY = bytes.fromhex("ab" * KEY_BYTES)
_HEX_KEY = "ab" * KEY_BYTES


class _Provider:
    """A scriptable stand-in for any key provider. No ``probe()`` — that
    capability is opt-in via :class:`_ProbedProvider`, mirroring the protocol
    split the feature ships."""

    def __init__(
        self,
        ident: str,
        *,
        interactive: bool = False,
        available: bool = True,
        key: bytes | None = None,
        delay: float = 0.0,
        raises: Exception | None = None,
        bad_hex: bool = False,
    ) -> None:
        self._id = ident
        self._interactive = interactive
        self._available = available
        self._key = key
        self._delay = delay
        self._raises = raises
        self._bad_hex = bad_hex
        self.get_key_calls = 0

    def identifier(self) -> str:
        return self._id

    def interactive(self) -> bool:
        return self._interactive

    def is_available(self) -> bool:
        return self._available

    def get_key(self, project_id: str) -> bytes | None:
        self.get_key_calls += 1
        if self._delay:
            time.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        if self._bad_hex:
            msg = "The vault key from the OS keyring is not valid hex."
            raise VaultError(msg)
        return self._key


class _ProbedProvider(_Provider):
    def __init__(self, ident: str, probe: KeyAvailability, **kwargs: object) -> None:
        super().__init__(ident, **kwargs)  # type: ignore[arg-type]
        self._probe = probe
        self.probe_calls = 0

    def probe(self) -> KeyAvailability:
        self.probe_calls += 1
        return self._probe


class _EnvProvider(_Provider):
    """The env provider's shape: available iff set, loud on a bad value."""

    def __init__(self, value: str | None) -> None:
        super().__init__("env")
        self._value = value

    def is_available(self) -> bool:
        return bool(self._value)

    def get_key(self, project_id: str) -> bytes | None:
        self.get_key_calls += 1
        if not self._value:
            return None
        try:
            key = bytes.fromhex(self._value)
        except ValueError as exc:
            msg = "The vault key from $FUNCTUALIZE_VAULT_KEY is not valid hex."
            raise VaultError(msg) from exc
        if len(key) != KEY_BYTES:
            msg = (
                f"The vault key from $FUNCTUALIZE_VAULT_KEY is {len(key)} bytes, "
                f"expected {KEY_BYTES}."
            )
            raise VaultError(msg)
        return key


def _resolver(
    providers: Sequence[VaultKeyProvider], timeout: float = 30.0
) -> VaultKeyResolver:
    return VaultKeyResolver("proj", list(providers), timeout=timeout)


class TestEnvShortCircuits:
    """A3 — with $FUNCTUALIZE_VAULT_KEY set, the keyring is never touched."""

    def test_no_other_provider_is_consulted(self) -> None:
        env = _EnvProvider(_HEX_KEY)
        keychain = _Provider("keychain", raises=AssertionError("never reached"))

        lookup = _resolver([env, keychain]).lookup()

        assert lookup.status is KeyStatus.FOUND
        assert lookup.provider_id == "env"
        assert keychain.get_key_calls == 0

    def test_a_broken_env_key_is_a_loud_error(self) -> None:
        env = _EnvProvider("nothex")

        with pytest.raises(VaultError, match="not valid hex"):
            _resolver([env]).lookup()

    def test_any_other_vault_error_propagates_unchanged(self) -> None:
        bad = _Provider("bad", bad_hex=True)

        with pytest.raises(VaultError, match="not valid hex"):
            _resolver([bad]).lookup()


class TestTheBoundedWait:
    """A4/A5 — a blocking backend refuses after the deadline; a dead one is
    immediate."""

    def test_a_blocking_backend_locks_after_the_deadline(self) -> None:
        blocking = _Provider("keychain", delay=10.0)
        resolver = _resolver([blocking], timeout=0.3)

        started = time.monotonic()
        lookup = resolver.lookup()

        assert lookup.status is KeyStatus.LOCKED
        assert lookup.timed_out is True
        assert lookup.key is None
        assert time.monotonic() - started < 5.0

    def test_where_no_keyring_can_answer_there_is_no_wait(self) -> None:
        absent = _Provider("keychain", available=False)
        resolver = _resolver([absent], timeout=30.0)

        started = time.monotonic()
        lookup = resolver.lookup()

        assert lookup.status is KeyStatus.NO_KEYRING
        assert lookup.timed_out is False
        assert time.monotonic() - started < 2.0
        assert absent.get_key_calls == 0

    def test_a_locked_keyring_is_locked_without_waiting(self) -> None:
        locked = _Provider("keychain", raises=KeyringLockedError("locked"))
        lookup = _resolver([locked], timeout=30.0).lookup()
        assert lookup.status is KeyStatus.LOCKED
        assert lookup.timed_out is False

    def test_an_unavailable_backend_is_no_keyring(self) -> None:
        dead = _Provider("keychain", raises=KeyringUnavailableError("no bus"))
        lookup = _resolver([dead], timeout=30.0).lookup()
        assert lookup.status is KeyStatus.NO_KEYRING

    def test_a_live_backend_with_no_entry_is_not_stored(self) -> None:
        empty = _Provider("keychain", key=None)
        lookup = _resolver([empty], timeout=30.0).lookup()
        assert lookup.status is KeyStatus.NOT_STORED

    def test_a_found_key_carries_its_provider(self) -> None:
        keychain = _Provider("keychain", key=_KEY)
        lookup = _resolver([keychain], timeout=30.0).lookup()
        assert lookup.status is KeyStatus.FOUND
        assert lookup.key == _KEY
        assert lookup.provider_id == "keychain"


class TestOneWaitPerProcess:
    """A6 — the outcome is remembered; N lookups wait once."""

    def test_ten_lookups_make_one_provider_call(self) -> None:
        blocking = _Provider("keychain", delay=10.0)
        resolver = _resolver([blocking], timeout=0.3)

        lookups = [resolver.lookup() for _ in range(10)]

        assert all(look.status is KeyStatus.LOCKED for look in lookups)
        assert blocking.get_key_calls == 1

    def test_a_found_outcome_is_reused(self) -> None:
        keychain = _Provider("keychain", key=_KEY)
        resolver = _resolver([keychain], timeout=30.0)

        first = resolver.lookup()
        second = resolver.lookup()

        assert first.key == second.key == _KEY
        assert keychain.get_key_calls == 1

    def test_two_threads_make_one_provider_call(self) -> None:
        blocking = _Provider("keychain", delay=10.0)
        resolver = _resolver([blocking], timeout=0.3)
        results: list[KeyLookup] = []
        barrier = threading.Barrier(2)

        def ask() -> None:
            barrier.wait()
            results.append(resolver.lookup())

        threads = [threading.Thread(target=ask) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        assert all(result.status is KeyStatus.LOCKED for result in results)
        assert blocking.get_key_calls == 1


class TestTheTerminalRuleSurvivesForPrompting:
    def test_a_terminal_needing_provider_is_skipped_without_a_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prompter = _Provider("prompter", interactive=True, key=_KEY)

        class _NotATty:
            def isatty(self) -> bool:
                return False

        monkeypatch.setattr(sys, "stdin", _NotATty())
        monkeypatch.setattr(sys, "stdout", _NotATty())

        lookup = _resolver([prompter]).lookup()

        assert lookup.status is KeyStatus.NO_KEYRING
        assert prompter.get_key_calls == 0

    def test_a_terminal_needing_provider_is_consulted_on_a_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prompter = _Provider("prompter", interactive=True, key=_KEY)

        class _Tty:
            def isatty(self) -> bool:
                return True

        monkeypatch.setattr(sys, "stdin", _Tty())
        monkeypatch.setattr(sys, "stdout", _Tty())

        lookup = _resolver([prompter]).lookup()

        assert lookup.status is KeyStatus.FOUND
        assert prompter.get_key_calls == 1

    def test_a_blocking_provider_is_read_without_a_tty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The point of the feature: no terminal, still read, still bounded."""

        class _NotATty:
            def isatty(self) -> bool:
                return False

        monkeypatch.setattr(sys, "stdin", _NotATty())
        monkeypatch.setattr(sys, "stdout", _NotATty())

        blocking = _Provider("keychain", key=_KEY, delay=0.05)
        lookup = _resolver([blocking], timeout=5.0).lookup()

        assert lookup.status is KeyStatus.FOUND
        assert lookup.key == _KEY


class TestForegroundAccess:
    """`vault unlock` waits without a limit, and failures are not memoised."""

    def test_no_deadline_is_applied(self) -> None:
        slow = _Provider("keychain", key=_KEY, delay=0.6)
        resolver = _resolver([slow], timeout=0.1)

        lookup = resolver.lookup(KeyAccess.FOREGROUND)

        assert lookup.status is KeyStatus.FOUND
        assert lookup.key == _KEY

    def test_a_failure_is_not_memoised(self) -> None:
        locked = _Provider("keychain", raises=KeyringLockedError("locked"))
        resolver = _resolver([locked], timeout=30.0)

        first = resolver.lookup(KeyAccess.FOREGROUND)
        assert first.status is KeyStatus.LOCKED

        # A person may have unlocked it between the two calls: ask again.
        second = resolver.lookup(KeyAccess.FOREGROUND)
        assert second.status is KeyStatus.LOCKED
        assert locked.get_key_calls == 2

    def test_a_found_outcome_is_memoised_for_later_bounded_calls(self) -> None:
        keychain = _Provider("keychain", key=_KEY)
        resolver = _resolver([keychain])

        resolver.lookup(KeyAccess.FOREGROUND)
        resolver.lookup(KeyAccess.BOUNDED)

        assert keychain.get_key_calls == 1


class TestSilentAccess:
    """A8 — status/inspect never prompt; they probe, then read only if safe."""

    def test_a_locked_probe_never_reads(self) -> None:
        keychain = _ProbedProvider("keychain", KeyAvailability.LOCKED, key=_KEY)
        resolver = _resolver([keychain])

        lookup = resolver.lookup(KeyAccess.SILENT)

        assert lookup.status is KeyStatus.LOCKED
        assert keychain.get_key_calls == 0
        assert keychain.probe_calls == 1

    def test_an_unlocked_probe_reads(self) -> None:
        keychain = _ProbedProvider("keychain", KeyAvailability.UNLOCKED, key=_KEY)
        lookup = _resolver([keychain]).lookup(KeyAccess.SILENT)
        assert lookup.status is KeyStatus.FOUND
        assert lookup.key == _KEY
        assert lookup.provider_id == "keychain"

    def test_no_probe_capability_answers_unknown(self) -> None:
        """A live backend with no probe may raise its own dialog, so silent
        access never asks it — even though it is available and holds a key."""
        plain = _Provider("kms", key=_KEY)  # no probe, would answer if asked

        lookup = _resolver([plain]).lookup(KeyAccess.SILENT)

        assert lookup.status is KeyStatus.UNKNOWN
        assert plain.get_key_calls == 0

    def test_the_env_provider_is_read_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reading a variable cannot prompt, so env with a key set reports
        available."""
        from functualize._config.vault_keys import ENV_VAR, EnvKeyProvider

        monkeypatch.setenv(ENV_VAR, _HEX_KEY)
        lookup = _resolver([EnvKeyProvider()]).lookup(KeyAccess.SILENT)
        assert lookup.status is KeyStatus.FOUND
        assert lookup.provider_id == "env"

    def test_a_silent_failure_is_not_memoised(self) -> None:
        keychain = _ProbedProvider("keychain", KeyAvailability.LOCKED, key=_KEY)
        resolver = _resolver([keychain])

        resolver.lookup(KeyAccess.SILENT)
        resolver.lookup(KeyAccess.BOUNDED)  # the run path still reads

        assert keychain.get_key_calls == 1


class TestTheOneShotHelper:
    def test_it_resolves_without_sharing_a_memo(self) -> None:
        env = _EnvProvider(_HEX_KEY)
        first = resolve_vault_key("proj", [env, _Provider("keychain", key=_KEY)])
        second = resolve_vault_key("proj", [env, _Provider("keychain", key=_KEY)])
        assert first.status is second.status is KeyStatus.FOUND
        assert first.provider_id == second.provider_id == "env"

    def test_fixed_never_consults_providers(self) -> None:
        loud = _Provider("loud", raises=AssertionError("never reached"))
        resolver = VaultKeyResolver.fixed(_KEY, provider_id="test")
        # The fixed resolver's provider list is empty; the loud one is a canary.
        lookup = resolver.lookup()
        assert lookup.status is KeyStatus.FOUND
        assert lookup.key == _KEY
        assert lookup.provider_id == "test"
        assert loud.get_key_calls == 0


class TestTheLookupIsSafeToLog:
    def test_the_repr_does_not_contain_the_key(self) -> None:
        lookup = KeyLookup(KeyStatus.FOUND, key=_KEY, provider_id="keychain")
        assert _HEX_KEY not in repr(lookup)
        assert str(_KEY) not in repr(lookup)
        assert "32 bytes" in repr(lookup)


class TestTheRefusalMessages:
    """B3 — four outcomes, four messages, none of them destructive."""

    @pytest.fixture
    def locked(self) -> KeyLookup:
        return KeyLookup(KeyStatus.LOCKED, provider_id="keychain", timed_out=True)

    @pytest.fixture
    def no_keyring(self) -> KeyLookup:
        return KeyLookup(KeyStatus.NO_KEYRING, provider_id="keychain")

    @pytest.fixture
    def not_stored(self) -> KeyLookup:
        return KeyLookup(KeyStatus.NOT_STORED, provider_id="keychain")

    def test_locked_says_locked_or_did_not_answer_and_names_the_exits(
        self, locked: KeyLookup
    ) -> None:
        text = describe_key_failure(locked, timeout=30.0)
        assert "locked or did not answer" in text
        assert "func builtin vault unlock" in text
        assert "FUNCTUALIZE_VAULT_KEY" in text

    @pytest.mark.parametrize("direct", [True, False])
    def test_locked_never_offers_destructive_fixes(
        self, locked: KeyLookup, direct: bool
    ) -> None:
        text = describe_key_failure(locked, direct=direct, timeout=30.0)
        assert "vault remove" not in text
        assert "vault clear" not in text
        assert "vault sync" not in text

    def test_no_keyring_names_the_env_var_and_the_extra(
        self, no_keyring: KeyLookup
    ) -> None:
        text = describe_key_failure(no_keyring)
        assert "no OS keyring is reachable" in text
        assert "FUNCTUALIZE_VAULT_KEY" in text
        assert "functualize[keychain]" in text

    @pytest.mark.parametrize("direct", [True, False])
    def test_no_keyring_never_offers_destructive_fixes(
        self, no_keyring: KeyLookup, direct: bool
    ) -> None:
        text = describe_key_failure(no_keyring, direct=direct)
        assert "vault remove" not in text
        assert "vault clear" not in text
        assert "vault sync" not in text

    def test_not_stored_names_init_and_the_env_var(self, not_stored: KeyLookup) -> None:
        text = describe_key_failure(not_stored)
        assert "func builtin vault init" in text
        assert "FUNCTUALIZE_VAULT_KEY" in text

    def test_not_stored_may_offer_remove_last_with_the_warning(
        self, not_stored: KeyLookup
    ) -> None:
        text = describe_key_failure(not_stored, qualified="db.password")
        assert "vault remove" in text
        assert text.index("func builtin vault init") < text.index("vault remove")
        assert "destroys" in text

    def test_not_stored_warns_a_direct_entry_is_the_only_copy(
        self, not_stored: KeyLookup
    ) -> None:
        text = describe_key_failure(not_stored, direct=True)
        assert "only copy" in text

    def test_a_qualified_entry_is_named(self, locked: KeyLookup) -> None:
        text = describe_key_failure(locked, qualified="database.password", timeout=30.0)
        assert "database.password" in text

    def test_unknown_says_it_could_not_tell(self) -> None:
        unknown = KeyLookup(KeyStatus.UNKNOWN, provider_id="keychain")
        text = describe_key_failure(unknown)
        assert "could not be determined" in text

    def test_found_is_a_programming_error(self) -> None:
        found = KeyLookup(KeyStatus.FOUND, key=_KEY)
        with pytest.raises(ValueError, match="FOUND"):
            describe_key_failure(found)


class TestNoImportTax:
    def test_importing_the_resolver_module_imports_no_keyring(self) -> None:
        """A10 — a run that resolves no key pays no import cost."""
        code = (
            "import sys;"
            "import functualize._config.vault_key_resolver;"
            "offenders = [m for m in ('keyring', 'secretstorage') if m in sys.modules];"
            "assert not offenders, offenders"
        )
        subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603
