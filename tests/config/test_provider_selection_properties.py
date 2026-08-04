"""Property-based tests for provider selection by extension in ProviderRegistry.

Tests Property 11 from the design document.

**Validates: Requirements 2.4, 2.6**
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._config.errors import UnsupportedFormatError
from functualize._config.registry import ProviderRegistry

# --- Strategies ---

# Strategy for valid file extensions (leading dot + lowercase alpha)
extensions = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=1,
    max_size=6,
).map(lambda s: f".{s}")


# --- Test helpers ---


class DynamicFormatProvider:
    """A configurable format provider for property testing."""

    def __init__(self, exts: list[str], label: str = "") -> None:
        self._extensions = exts
        self.label = label

    def extensions(self) -> list[str]:
        return self._extensions

    def parse(self, path: str) -> dict[str, Any]:
        return {"provider": self.label}

    def serialize(self, data: dict[str, Any]) -> str:
        return f"# {self.label}"


# --- Property 11: Provider selection by extension ---


class TestProperty11ProviderSelectionByExtension:
    """For any registered extension, get_format_provider(ext) returns the correct
    provider. For unregistered extensions, it raises UnsupportedFormatError.

    **Validates: Requirements 2.4, 2.6**
    """

    @given(
        ext=extensions,
    )
    def test_registered_extension_returns_provider_containing_that_extension(
        self, ext: str
    ) -> None:
        """For any registered extension, get_format_provider(ext) always returns
        a provider whose extensions() list contains that extension."""
        registry = ProviderRegistry()
        provider = DynamicFormatProvider([ext], label=f"provider_for_{ext}")
        registry.register_format_provider(provider)

        result = registry.get_format_provider(ext)
        assert ext in result.extensions()

    @given(
        registered_exts=st.lists(extensions, min_size=1, max_size=5, unique=True),
        unregistered_ext=extensions,
    )
    def test_unregistered_extension_raises_unsupported_format_error(
        self, registered_exts: list[str], unregistered_ext: str
    ) -> None:
        """For any unregistered extension, get_format_provider(ext) always raises
        UnsupportedFormatError."""
        # Ensure the unregistered extension is truly not in the registered set
        if unregistered_ext in registered_exts:
            return  # Skip this case — not a true unregistered extension

        registry = ProviderRegistry()
        for ext in registered_exts:
            provider = DynamicFormatProvider([ext], label=f"provider_{ext}")
            registry.register_format_provider(provider)

        with pytest.raises(UnsupportedFormatError) as exc_info:
            registry.get_format_provider(unregistered_ext)

        assert exc_info.value.extension == unregistered_ext

    @given(
        ext_lists=st.lists(
            st.lists(extensions, min_size=1, max_size=3, unique=True),
            min_size=1,
            max_size=8,
        ),
    )
    def test_n_providers_distinct_extensions_all_retrievable(
        self, ext_lists: list[list[str]]
    ) -> None:
        """After registering N providers for distinct extensions, all N are
        retrievable via their respective extensions."""
        registry = ProviderRegistry()

        # Deduplicate extensions across providers to get truly distinct mappings
        seen_exts: set[str] = set()
        providers: list[DynamicFormatProvider] = []
        ext_to_provider: dict[str, DynamicFormatProvider] = {}

        for i, exts in enumerate(ext_lists):
            # Only use extensions not yet seen
            unique_exts = [e for e in exts if e not in seen_exts]
            if not unique_exts:
                continue
            provider = DynamicFormatProvider(unique_exts, label=f"provider_{i}")
            registry.register_format_provider(provider)
            providers.append(provider)
            for ext in unique_exts:
                seen_exts.add(ext)
                ext_to_provider[ext] = provider

        # All registered extensions should be retrievable
        for ext, expected_provider in ext_to_provider.items():
            result = registry.get_format_provider(ext)
            assert result is expected_provider

    @given(
        ext=extensions,
        num_providers=st.integers(min_value=2, max_value=10),
    )
    def test_most_recently_registered_provider_wins_for_same_extension(
        self, ext: str, num_providers: int
    ) -> None:
        """The provider returned for an extension always matches the most recently
        registered provider of a DIFFERENT class for that extension.

        Note: Same-class re-registration is a no-op (see Requirement 10.1),
        so this test uses distinct classes to verify override behavior.
        """
        registry = ProviderRegistry()
        providers = []
        for i in range(num_providers):
            # Create a unique class per provider so overrides actually happen
            cls = type(
                f"FormatProvider_{i}",
                (),
                {
                    "__init__": lambda self, exts, label="": (
                        setattr(self, "_extensions", exts)
                        or setattr(self, "label", label)
                    ),
                    "extensions": lambda self: self._extensions,
                    "parse": lambda self, path: {"provider": self.label},
                    "serialize": lambda self, data: f"# {self.label}",
                },
            )
            provider = cls([ext], label=f"provider_{i}")
            providers.append(provider)

        for provider in providers:
            registry.register_format_provider(provider)

        result = registry.get_format_provider(ext)
        # The last registered provider should win
        assert result is providers[-1]
        # And it should contain the extension
        assert ext in result.extensions()
