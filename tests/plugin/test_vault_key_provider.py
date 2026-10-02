"""VaultKeyProvider is a structural contract a third party can satisfy.

The point of the protocol is that the key source is a *seam*: an OS keychain,
a cloud KMS, a password manager and a hosted control plane are all the same
shape, and none of them requires a change to core. These tests pin that
shape — an object satisfying it structurally, with no inheritance and no
import from functualize, is accepted.
"""

from __future__ import annotations

from functualize.plugin import VaultKeyProvider


class _KeychainLike:
    """A third-party provider. Note it inherits nothing."""

    def identifier(self) -> str:
        return "keychain"

    def interactive(self) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    def get_key(self, project_id: str) -> bytes | None:
        return b"\x01" * 32


class _EnvLike:
    def identifier(self) -> str:
        return "env"

    def interactive(self) -> bool:
        return False

    def is_available(self) -> bool:
        return True

    def get_key(self, project_id: str) -> bytes | None:
        return None


class _MissingGetKey:
    def identifier(self) -> str:
        return "broken"

    def interactive(self) -> bool:
        return False

    def is_available(self) -> bool:
        return True


class TestStructuralSatisfaction:
    def test_a_duck_typed_provider_satisfies_the_protocol(self) -> None:
        assert isinstance(_KeychainLike(), VaultKeyProvider)

    def test_a_non_interactive_provider_satisfies_it_too(self) -> None:
        assert isinstance(_EnvLike(), VaultKeyProvider)

    def test_a_provider_missing_a_method_does_not(self) -> None:
        """The protocol is runtime_checkable, so the gap is caught."""
        assert not isinstance(_MissingGetKey(), VaultKeyProvider)


class TestTheInteractivityAxis:
    """`interactive()` now means "needs a person at a terminal", nothing else.

    A provider that may block on a backend (an OS keyring showing its own
    unlock dialog) returns False: it is bounded by the resolver's deadline,
    not gated on a TTY. True is reserved for a prompt a pipe cannot answer.
    """

    def test_providers_declare_whether_they_need_a_terminal(self) -> None:
        assert _EnvLike().interactive() is False
        assert _KeychainLike().interactive() is True

    def test_returning_none_is_normal_not_an_error(self) -> None:
        """A provider with no key defers; it does not raise."""
        assert _EnvLike().get_key("proj") is None


class TestPublicSurface:
    def test_it_is_exported_from_the_public_plugin_package(self) -> None:
        """Plugin authors import from functualize.plugin, never from _types."""
        import functualize.plugin as plugin_pkg

        assert "VaultKeyProvider" in plugin_pkg.__all__


class TestVaultKeyInitializer:
    """The optional write half of the key seam.

    Split from `VaultKeyProvider` rather than added to it, so the test that
    matters most is the negative one: a read-only provider must still be a
    valid provider after this exists.
    """

    def test_a_read_only_provider_is_not_an_initializer(self) -> None:
        """The whole reason this is a second protocol.

        Widening `VaultKeyProvider` with `initialize_key` would have made every
        structural implementation that ships today — and every third-party one
        — silently stop satisfying it.
        """
        from functualize.plugin import VaultKeyInitializer, VaultKeyProvider

        class ReadOnly:
            def identifier(self) -> str:
                return "read-only"

            def interactive(self) -> bool:
                return False

            def is_available(self) -> bool:
                return True

            def get_key(self, project_id: str) -> bytes | None:
                return b"\x00" * 32

        provider = ReadOnly()
        assert isinstance(provider, VaultKeyProvider)
        assert not isinstance(provider, VaultKeyInitializer)

    def test_adding_the_method_opts_in_structurally(self) -> None:
        """No registration, no inheritance — the method is the opt-in."""
        from functualize.plugin import VaultKeyInitializer, VaultKeyProvider

        class Writable:
            def identifier(self) -> str:
                return "writable"

            def interactive(self) -> bool:
                return False

            def is_available(self) -> bool:
                return True

            def get_key(self, project_id: str) -> bytes | None:
                return b"\x01" * 32

            def initialize_key(self, project_id: str) -> bytes:
                return b"\x01" * 32

        provider = Writable()
        assert isinstance(provider, VaultKeyProvider)
        assert isinstance(provider, VaultKeyInitializer)

    def test_it_is_runtime_checkable_like_its_base(self) -> None:
        """`isinstance` is how selection works; a non-runtime-checkable
        protocol would raise at the point of use, not at import."""
        from functualize.plugin import VaultKeyInitializer

        assert getattr(VaultKeyInitializer, "_is_runtime_protocol", False)

    def test_it_is_reachable_from_the_public_plugin_surface(self) -> None:
        import functualize.plugin as plugin_api

        assert "VaultKeyInitializer" in plugin_api.__all__


class TestVaultKeyProbe:
    """The optional "can you answer without prompting?" half of the seam.

    Split from `VaultKeyProvider` exactly as `VaultKeyInitializer` is, so the
    test that matters most is again the negative one: a provider without
    `probe()` must remain a valid provider after this exists.
    """

    def test_a_probe_less_provider_is_not_a_probe(self) -> None:
        """The whole reason this is a second protocol, twice over."""
        from functualize.plugin import VaultKeyProbe

        assert not isinstance(_KeychainLike(), VaultKeyProbe)

    def test_adding_probe_opts_in_structurally(self) -> None:
        """No registration, no inheritance — the method is the opt-in."""
        from functualize.plugin import KeyAvailability, VaultKeyProbe

        class Probed:
            def identifier(self) -> str:
                return "probed"

            def interactive(self) -> bool:
                return False

            def is_available(self) -> bool:
                return True

            def get_key(self, project_id: str) -> bytes | None:
                return b"\x02" * 32

            def probe(self) -> KeyAvailability:
                return KeyAvailability.UNLOCKED

        provider = Probed()
        assert isinstance(provider, VaultKeyProbe)

    def test_probe_answers_use_the_shared_vocabulary(self) -> None:
        """UNLOCKED / LOCKED / UNKNOWN are the only three answers."""
        from functualize._types.enums import KeyAvailability

        assert {state.value for state in KeyAvailability} == {
            "unlocked",
            "locked",
            "unknown",
        }

    def test_it_is_runtime_checkable_like_its_base(self) -> None:
        from functualize.plugin import VaultKeyProbe

        assert getattr(VaultKeyProbe, "_is_runtime_protocol", False)

    def test_it_is_reachable_from_the_public_plugin_surface(self) -> None:
        import functualize.plugin as plugin_api

        assert "VaultKeyProbe" in plugin_api.__all__
        assert "KeyAvailability" in plugin_api.__all__


class TestVaultKeyUnlocker:
    """The one key-provider capability that may prompt (`vault unlock` only).

    Split like the other two, so the negative test matters most: a provider
    without `unlock()` stays a valid provider.
    """

    def test_an_unlock_less_provider_is_not_an_unlocker(self) -> None:
        from functualize.plugin import VaultKeyUnlocker

        assert not isinstance(_KeychainLike(), VaultKeyUnlocker)

    def test_adding_unlock_opts_in_structurally(self) -> None:
        from functualize.plugin import VaultKeyUnlocker

        class Unlockable:
            def identifier(self) -> str:
                return "unlockable"

            def interactive(self) -> bool:
                return False

            def is_available(self) -> bool:
                return True

            def get_key(self, project_id: str) -> bytes | None:
                return None

            def unlock(self) -> bool:
                return True

        assert isinstance(Unlockable(), VaultKeyUnlocker)

    def test_it_is_runtime_checkable_like_its_base(self) -> None:
        from functualize.plugin import VaultKeyUnlocker

        assert getattr(VaultKeyUnlocker, "_is_runtime_protocol", False)

    def test_the_provider_contract_says_get_key_never_prompts(self) -> None:
        """The contract a third-party provider is held to, stated where it reads."""
        from functualize.plugin import VaultKeyProvider

        doc = VaultKeyProvider.get_key.__doc__ or ""
        assert "Must not prompt" in doc

    def test_it_is_reachable_from_the_public_plugin_surface(self) -> None:
        import functualize.plugin as plugin_api

        assert "VaultKeyUnlocker" in plugin_api.__all__
