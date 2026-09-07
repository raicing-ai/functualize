"""Key resolution puts non-interactive sources first, always.

The rule these tests exist for: an unattended run — CI, Lambda, `builtin
parallel` — must never reach a provider that can prompt. Getting the order
backwards does not fail loudly; it hangs.
"""

from __future__ import annotations

import pytest

from functualize._config.vault import KEY_BYTES, VaultError
from functualize._config.vault_keys import (
    ENV_VAR,
    EnvKeyProvider,
    KeychainKeyProvider,
    generate_key,
    resolve_vault_key,
)
from functualize.plugin import VaultKeyProvider

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


class TestResolutionOrder:
    def test_non_interactive_wins_over_interactive(self) -> None:
        env = _FakeProvider("env", interactive=False, key=b"\x01" * KEY_BYTES)
        chain = _FakeProvider("keychain", interactive=True, key=b"\x02" * KEY_BYTES)
        # Interactive listed FIRST, to prove order is not registration order.
        got = resolve_vault_key("proj", [chain, env], allow_interactive=True)
        assert got is not None
        assert got.provider_id == "env"
        assert chain.get_key_calls == 0

    def test_an_interactive_provider_is_never_reached_without_a_tty(self) -> None:
        """The Lambda-hangs-on-a-prompt case."""
        chain = _FakeProvider("keychain", interactive=True, key=b"\x02" * KEY_BYTES)
        got = resolve_vault_key("proj", [chain], allow_interactive=False)
        assert got is None
        assert chain.get_key_calls == 0

    def test_an_interactive_provider_is_reached_with_a_tty(self) -> None:
        chain = _FakeProvider("keychain", interactive=True, key=b"\x02" * KEY_BYTES)
        got = resolve_vault_key("proj", [chain], allow_interactive=True)
        assert got is not None
        assert got.provider_id == "keychain"

    def test_an_unavailable_provider_is_skipped(self) -> None:
        absent = _FakeProvider("absent", interactive=False, available=False)
        present = _FakeProvider("present", interactive=False, key=b"\x03" * KEY_BYTES)
        got = resolve_vault_key("proj", [absent, present], allow_interactive=False)
        assert got is not None
        assert got.provider_id == "present"
        assert absent.get_key_calls == 0

    def test_a_provider_returning_none_defers_to_the_next(self) -> None:
        """Returning None is normal, not an error."""
        empty = _FakeProvider("empty", interactive=False, key=None)
        full = _FakeProvider("full", interactive=False, key=b"\x04" * KEY_BYTES)
        got = resolve_vault_key("proj", [empty, full], allow_interactive=False)
        assert got is not None
        assert got.provider_id == "full"

    def test_no_key_anywhere_returns_none(self) -> None:
        """The caller decides whether that is fatal."""
        assert resolve_vault_key("proj", [], allow_interactive=True) is None


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
    def test_it_is_interactive(self) -> None:
        assert KeychainKeyProvider().interactive() is True

    def test_a_missing_keyring_reports_unavailable_rather_than_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STATUS #1's lesson: a missing optional dep degrades, never crashes.

        `keyring` is not a declared dependency of functualize -- it is present
        in some environments transitively, and relying on that accident is the
        bug this test prevents.
        """
        monkeypatch.setitem(__import__("sys").modules, "keyring", None)
        provider = KeychainKeyProvider()
        assert provider.is_available() is False
        assert provider.get_key("proj") is None


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


class TestKeyResolutionIsSafeToLog:
    def test_its_repr_does_not_contain_the_key(self) -> None:
        got = resolve_vault_key(
            "proj",
            [_FakeProvider("env", interactive=False, key=bytes.fromhex(_HEX_B))],
            allow_interactive=False,
        )
        assert got is not None
        assert _HEX_B not in repr(got)
        assert "bytes" in repr(got)
