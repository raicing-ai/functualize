"""Property-based tests for the ProviderRegistry override behavior using Hypothesis.

Tests Property 12 from the design document: when a DIFFERENT class registers for
the same extension/identifier, the last one wins (overrides). Same-class
re-registration is a no-op (tested in test_provider_registry_idempotent_properties.py).
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.registry import ProviderRegistry

# --- Strategies ---

# Strategy for valid file extensions (leading dot + lowercase alpha)
extensions = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=1,
    max_size=6,
).map(lambda s: f".{s}")

# Strategy for valid provider identifiers (lowercase alpha + hyphens)
identifiers = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="-"),
    min_size=1,
    max_size=10,
).filter(lambda s: s[0].isalpha() and not s.endswith("-"))


# --- Test helpers ---


def _make_format_provider_class(class_id: int) -> type:
    """Create a unique format provider class with a distinct type identity.

    Each call with a different class_id produces a different class, which is
    essential for testing that different-class overrides work correctly.
    """

    class _FormatProvider:
        """A dynamically-created format provider class."""

        def __init__(self, exts: list[str], label: str = "") -> None:
            self._extensions = exts
            self.label = label

        def extensions(self) -> list[str]:
            return self._extensions

        def parse(self, path: str) -> dict[str, Any]:
            return {"provider": self.label}

        def serialize(self, data: dict[str, Any]) -> str:
            return f"# {self.label}"

    # Give it a unique name for clearer error messages
    _FormatProvider.__name__ = f"FormatProvider_{class_id}"
    _FormatProvider.__qualname__ = f"FormatProvider_{class_id}"
    return _FormatProvider


def _make_remote_provider_class(class_id: int) -> type:
    """Create a unique remote provider class with a distinct type identity."""

    class _RemoteProvider:
        """A dynamically-created remote provider class."""

        def __init__(self, ident: str, label: str = "") -> None:
            self._identifier = ident
            self.label = label

        def identifier(self) -> str:
            return self._identifier

        def is_ready(self) -> bool:
            return True

        def fetch(self, reference: str) -> str:
            return f"{self.label}:{reference}"

    _RemoteProvider.__name__ = f"RemoteProvider_{class_id}"
    _RemoteProvider.__qualname__ = f"RemoteProvider_{class_id}"
    return _RemoteProvider


# --- Property 12: Last-registered provider override (different classes) ---


class TestProperty12LastRegisteredProviderOverride:
    """When multiple providers of DIFFERENT classes register for the same
    extension/identifier, the last one registered is always the one returned.

    **Validates: Requirements 10.2, 10.4**
    """

    @given(
        ext=extensions,
        num_providers=st.integers(min_value=2, max_value=10),
    )
    def test_last_format_provider_wins(self, ext: str, num_providers: int) -> None:
        """When multiple format providers of different classes register for
        the same extension, the last one registered is returned."""
        registry = ProviderRegistry()
        providers = []
        for i in range(num_providers):
            cls = _make_format_provider_class(i)
            provider = cls([ext], label=f"provider_{i}")
            providers.append(provider)

        for provider in providers:
            registry.register_format_provider(provider)

        # The last registered provider should be the one returned
        result = registry.get_format_provider(ext)
        assert result is providers[-1]

    @given(
        ident=identifiers,
        num_providers=st.integers(min_value=2, max_value=10),
    )
    def test_last_remote_provider_wins(self, ident: str, num_providers: int) -> None:
        """When multiple remote providers of different classes register for
        the same identifier, the last one registered is returned."""
        registry = ProviderRegistry()
        providers = []
        for i in range(num_providers):
            cls = _make_remote_provider_class(i)
            provider = cls(ident, label=f"provider_{i}")
            providers.append(provider)

        for provider in providers:
            registry.register_remote_provider(provider)

        # The last registered provider should be the one returned
        result = registry.get_remote_provider(ident)
        assert result is providers[-1]

    @given(
        data=st.data(),
        ext_list=st.lists(extensions, min_size=1, max_size=5, unique=True),
    )
    def test_list_format_providers_reflects_last_wins(
        self, data: st.DataObject, ext_list: list[str]
    ) -> None:
        """After any sequence of registrations with different classes,
        list_format_providers() reflects the last override for each extension."""
        registry = ProviderRegistry()
        # Track expected state: extension -> last provider registered
        expected: dict[str, Any] = {}

        # Perform a random sequence of registrations using different classes
        num_registrations = data.draw(
            st.integers(min_value=1, max_value=15), label="num_registrations"
        )
        for i in range(num_registrations):
            # Pick a random subset of extensions for this provider
            provider_exts = data.draw(
                st.lists(st.sampled_from(ext_list), min_size=1, max_size=len(ext_list)),
                label=f"provider_{i}_exts",
            )
            cls = _make_format_provider_class(i)
            provider = cls(provider_exts, label=f"reg_{i}")
            registry.register_format_provider(provider)
            for ext in provider_exts:
                expected[ext] = provider

        # Verify list_format_providers matches expected state
        result = registry.list_format_providers()
        assert set(result.keys()) == set(expected.keys())
        for ext, provider in expected.items():
            assert result[ext] is provider

    @given(
        data=st.data(),
        ident_list=st.lists(identifiers, min_size=1, max_size=5, unique=True),
    )
    def test_list_remote_providers_reflects_last_wins(
        self, data: st.DataObject, ident_list: list[str]
    ) -> None:
        """After any sequence of registrations with different classes,
        list_remote_providers() reflects the last override for each identifier."""
        registry = ProviderRegistry()
        # Track expected state: identifier -> last provider registered
        expected: dict[str, Any] = {}

        # Perform a random sequence of registrations using different classes
        num_registrations = data.draw(
            st.integers(min_value=1, max_value=15), label="num_registrations"
        )
        for i in range(num_registrations):
            # Pick a random identifier for this provider
            ident = data.draw(st.sampled_from(ident_list), label=f"provider_{i}_ident")
            cls = _make_remote_provider_class(i)
            provider = cls(ident, label=f"reg_{i}")
            registry.register_remote_provider(provider)
            expected[ident] = provider

        # Verify list_remote_providers matches expected state
        result = registry.list_remote_providers()
        assert set(result.keys()) == set(expected.keys())
        for ident, provider in expected.items():
            assert result[ident] is provider

    @given(
        data=st.data(),
        all_exts=st.lists(extensions, min_size=2, max_size=6, unique=True),
    )
    def test_override_does_not_affect_other_extensions(
        self, data: st.DataObject, all_exts: list[str]
    ) -> None:
        """Overriding a provider for one extension with a different class
        does not affect other extensions."""
        registry = ProviderRegistry()

        # Register a unique class/provider for each extension
        initial_providers: dict[str, Any] = {}
        for idx, ext in enumerate(all_exts):
            cls = _make_format_provider_class(idx)
            provider = cls([ext], label=f"initial_{ext}")
            registry.register_format_provider(provider)
            initial_providers[ext] = provider

        # Pick one extension to override with a new different class
        target_ext = data.draw(st.sampled_from(all_exts), label="target_ext")
        override_cls = _make_format_provider_class(len(all_exts) + 100)
        override_provider = override_cls([target_ext], label=f"override_{target_ext}")
        registry.register_format_provider(override_provider)

        # Verify the target was overridden
        assert registry.get_format_provider(target_ext) is override_provider

        # Verify all other extensions are unaffected
        for ext in all_exts:
            if ext != target_ext:
                assert registry.get_format_provider(ext) is initial_providers[ext]
