"""Property-based tests for idempotent same-class provider registration.

# Feature: unified-config-access, Property 7: Idempotent Same-Class Provider Registration

Tests that re-registering the same provider class for the same extension/identifier
is a no-op: registry state remains unchanged and no warning is logged.

**Validates: Requirements 10.1, 10.3**
"""

from __future__ import annotations

import logging
import logging.handlers
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

# Strategy for number of re-registrations
num_reregistrations = st.integers(min_value=1, max_value=10)


# --- Test helpers ---


class SameClassFormatProvider:
    """A format provider class used to test same-class re-registration."""

    def __init__(self, exts: list[str]) -> None:
        self._extensions = exts

    def extensions(self) -> list[str]:
        return self._extensions

    def parse(self, path: str) -> dict[str, Any]:
        return {}

    def serialize(self, data: dict[str, Any]) -> str:
        return ""


class SameClassRemoteProvider:
    """A remote provider class used to test same-class re-registration."""

    def __init__(self, ident: str) -> None:
        self._identifier = ident

    def identifier(self) -> str:
        return self._identifier

    def is_ready(self) -> bool:
        return True

    def fetch(self, reference: str) -> str:
        return ""


# --- Property 7: Idempotent Same-Class Provider Registration ---


class TestProperty7IdempotentSameClassProviderRegistration:
    """For any format provider instance of class C already registered for extension E,
    calling register_format_provider() again with another instance of class C for the
    same extension E SHALL be a no-op (the registry state remains unchanged and no
    warning is logged). The same holds for register_remote_provider() with remote
    provider identifiers.

    **Validates: Requirements 10.1, 10.3**
    """

    @given(
        ext=extensions,
        num_rereg=num_reregistrations,
    )
    def test_format_provider_same_class_reregistration_is_noop(
        self, ext: str, num_rereg: int
    ) -> None:
        """Re-registering the same format provider class for the same extension
        does not change registry state."""
        registry = ProviderRegistry()

        # Register the initial instance
        initial_instance = SameClassFormatProvider([ext])
        registry.register_format_provider(initial_instance)

        # Snapshot state after initial registration
        state_before = registry.list_format_providers()

        # Re-register with new instances of the same class
        for _ in range(num_rereg):
            new_instance = SameClassFormatProvider([ext])
            registry.register_format_provider(new_instance)

        # State should be unchanged — original instance still registered
        state_after = registry.list_format_providers()
        assert state_after.keys() == state_before.keys()
        assert state_after[ext] is initial_instance

    @given(
        ident=identifiers,
        num_rereg=num_reregistrations,
    )
    def test_remote_provider_same_class_reregistration_is_noop(
        self, ident: str, num_rereg: int
    ) -> None:
        """Re-registering the same remote provider class for the same identifier
        does not change registry state."""
        registry = ProviderRegistry()

        # Register the initial instance
        initial_instance = SameClassRemoteProvider(ident)
        registry.register_remote_provider(initial_instance)

        # Snapshot state after initial registration
        state_before = registry.list_remote_providers()

        # Re-register with new instances of the same class
        for _ in range(num_rereg):
            new_instance = SameClassRemoteProvider(ident)
            registry.register_remote_provider(new_instance)

        # State should be unchanged — original instance still registered
        state_after = registry.list_remote_providers()
        assert state_after.keys() == state_before.keys()
        assert state_after[ident] is initial_instance

    @given(
        ext=extensions,
        num_rereg=num_reregistrations,
    )
    def test_format_provider_same_class_reregistration_no_warning(
        self, ext: str, num_rereg: int
    ) -> None:
        """Re-registering the same format provider class for the same extension
        does not emit any warning log."""
        registry = ProviderRegistry()

        # Register the initial instance
        initial_instance = SameClassFormatProvider([ext])
        registry.register_format_provider(initial_instance)

        # Capture warnings during re-registration
        log_handler = logging.handlers.MemoryHandler(capacity=100)
        log_handler.setLevel(logging.WARNING)
        registry_logger = logging.getLogger("functualize._config.registry")
        registry_logger.addHandler(log_handler)
        try:
            for _ in range(num_rereg):
                new_instance = SameClassFormatProvider([ext])
                registry.register_format_provider(new_instance)

            log_handler.flush()
            assert len(log_handler.buffer) == 0, (
                f"Expected no warnings, got {len(log_handler.buffer)}: "
                f"{[r.getMessage() for r in log_handler.buffer]}"
            )
        finally:
            registry_logger.removeHandler(log_handler)

    @given(
        ident=identifiers,
        num_rereg=num_reregistrations,
    )
    def test_remote_provider_same_class_reregistration_no_warning(
        self, ident: str, num_rereg: int
    ) -> None:
        """Re-registering the same remote provider class for the same identifier
        does not emit any warning log."""
        registry = ProviderRegistry()

        # Register the initial instance
        initial_instance = SameClassRemoteProvider(ident)
        registry.register_remote_provider(initial_instance)

        # Capture warnings during re-registration
        log_handler = logging.handlers.MemoryHandler(capacity=100)
        log_handler.setLevel(logging.WARNING)
        registry_logger = logging.getLogger("functualize._config.registry")
        registry_logger.addHandler(log_handler)
        try:
            for _ in range(num_rereg):
                new_instance = SameClassRemoteProvider(ident)
                registry.register_remote_provider(new_instance)

            log_handler.flush()
            assert len(log_handler.buffer) == 0, (
                f"Expected no warnings, got {len(log_handler.buffer)}: "
                f"{[r.getMessage() for r in log_handler.buffer]}"
            )
        finally:
            registry_logger.removeHandler(log_handler)

    @given(
        data=st.data(),
        ext_list=st.lists(extensions, min_size=2, max_size=5, unique=True),
    )
    def test_format_provider_same_class_reregistration_does_not_affect_other_extensions(
        self, data: st.DataObject, ext_list: list[str]
    ) -> None:
        """Re-registering same-class providers for one extension does not affect
        providers registered for other extensions."""
        registry = ProviderRegistry()

        # Register a unique instance per extension
        initial_providers: dict[str, SameClassFormatProvider] = {}
        for ext in ext_list:
            provider = SameClassFormatProvider([ext])
            registry.register_format_provider(provider)
            initial_providers[ext] = provider

        # Pick one extension to re-register
        target_ext = data.draw(st.sampled_from(ext_list), label="target_ext")

        # Re-register the target extension with a new instance of same class
        new_instance = SameClassFormatProvider([target_ext])
        registry.register_format_provider(new_instance)

        # Target should still have original instance (no-op)
        assert registry.get_format_provider(target_ext) is initial_providers[target_ext]

        # Other extensions should be unaffected
        for ext in ext_list:
            if ext != target_ext:
                assert registry.get_format_provider(ext) is initial_providers[ext]
