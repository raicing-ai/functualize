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
    """`interactive()` is what keeps an unattended run from blocking."""

    def test_providers_declare_whether_they_may_prompt(self) -> None:
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
