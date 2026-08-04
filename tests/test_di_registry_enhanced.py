"""Property-based tests for DI Registry enhancements (Properties 25–28).

Tests the enhanced DI registry capabilities:
- Property 25: DI type validation — isinstance fails raises TypeError
- Property 26: DI duplicate warning — second provide without qualifier emits warning
- Property 27: DI qualified resolution — resolving with qualifier returns correct instance
- Property 28: DI ambiguous resolution error — unqualified lookup with multiple qualifiers raises AmbiguousProviderError

**Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.6**
"""

from __future__ import annotations

import warnings

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._primitives.di import (
    AmbiguousProviderError,
    DIRegistry,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def _make_type(name: str) -> type:
    """Dynamically create a unique type with the given name."""
    return type(name, (), {})


@st.composite
def _type_name(draw: st.DrawFn) -> str:
    """Generate a valid Python identifier for use as a type name."""
    first = draw(st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    rest = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
            min_size=0,
            max_size=8,
        )
    )
    return first + rest


@st.composite
def _qualifier(draw: st.DrawFn) -> str:
    """Generate a non-empty qualifier string."""
    return draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz_",
            min_size=1,
            max_size=12,
        )
    )


# ---------------------------------------------------------------------------
# Helpers for type mismatch generation
# ---------------------------------------------------------------------------


class _Animal:
    """Base type for type-mismatch tests."""

    pass


class _Dog(_Animal):
    """Subclass of Animal."""

    pass


class _Cat(_Animal):
    """Another subclass of Animal."""

    pass


class _Car:
    """Completely unrelated type to Animal."""

    pass


class _Truck:
    """Completely unrelated type to Animal."""

    pass


# Strategy that generates (type_, instance) pairs where isinstance(instance, type_) is False
@st.composite
def _mismatched_type_instance(draw: st.DrawFn) -> tuple[type, object]:
    """Generate a (type_, instance) pair where isinstance(instance, type_) is False.

    Uses a fixed set of types to ensure clean type hierarchy mismatches.
    """
    # Pick from predefined incompatible pairs
    incompatible_pairs = [
        (_Animal, _Car()),  # Car is not an Animal
        (_Animal, _Truck()),  # Truck is not an Animal
        (_Dog, _Cat()),  # Cat is not a Dog
        (_Dog, _Car()),  # Car is not a Dog
        (_Cat, _Dog()),  # Dog is not a Cat
        (_Cat, _Car()),  # Car is not a Cat
        (_Car, _Animal()),  # Animal is not a Car
        (_Car, _Dog()),  # Dog is not a Car
        (_Truck, _Animal()),  # Animal is not a Truck
        (_Truck, _Dog()),  # Dog is not a Truck
        (int, "not_an_int"),  # str is not int
        (str, 42),  # int is not str
        (list, {}),  # dict is not list
        (dict, []),  # list is not dict
        (float, "3.14"),  # str is not float
    ]
    pair = draw(st.sampled_from(incompatible_pairs))
    return pair


# Strategy that generates (type_, instance) pairs where isinstance(instance, type_) is True
@st.composite
def _matching_type_instance(draw: st.DrawFn) -> tuple[type, object]:
    """Generate a (type_, instance) pair where isinstance(instance, type_) is True."""
    compatible_pairs = [
        (_Animal, _Animal()),
        (_Animal, _Dog()),  # Dog IS an Animal
        (_Animal, _Cat()),  # Cat IS an Animal
        (_Dog, _Dog()),
        (_Cat, _Cat()),
        (_Car, _Car()),
        (_Truck, _Truck()),
    ]
    pair = draw(st.sampled_from(compatible_pairs))
    return pair


# =============================================================================
# Property 25: DI type validation
# =============================================================================


class TestDITypeValidation:
    """Property 25: DI type validation.

    For any type T and instance obj where isinstance(obj, T) is False,
    calling app.provide(T, obj) SHALL raise a TypeError.

    **Validates: Requirements 10.1**
    """

    @given(pair=_mismatched_type_instance())
    @settings(max_examples=100)
    def test_isinstance_failure_raises_type_error(
        self, pair: tuple[type, object]
    ) -> None:
        """isinstance fails raises TypeError on provide().

        **Validates: Requirements 10.1**
        """
        type_, instance = pair
        reg = DIRegistry()

        with pytest.raises(TypeError) as exc_info:
            reg.provide(type_, instance)

        # Error message should mention both the expected type and actual type
        error_msg = str(exc_info.value)
        assert type_.__name__ in error_msg
        assert type(instance).__name__ in error_msg

    @given(pair=_mismatched_type_instance(), qualifier=_qualifier())
    @settings(max_examples=100)
    def test_isinstance_failure_raises_type_error_with_qualifier(
        self, pair: tuple[type, object], qualifier: str
    ) -> None:
        """isinstance fails raises TypeError even with qualifier specified.

        **Validates: Requirements 10.1**
        """
        type_, instance = pair
        reg = DIRegistry()

        with pytest.raises(TypeError) as exc_info:
            reg.provide(type_, instance, qualifier=qualifier)

        error_msg = str(exc_info.value)
        assert "isinstance check failed" in error_msg

    @given(pair=_matching_type_instance())
    @settings(max_examples=100)
    def test_isinstance_success_does_not_raise(self, pair: tuple[type, object]) -> None:
        """When isinstance passes, provide() succeeds without error.

        **Validates: Requirements 10.1**
        """
        type_, instance = pair
        reg = DIRegistry()

        # Should not raise
        reg.provide(type_, instance)

        # Verify it was registered
        resolved = reg.resolve(type_)
        assert resolved is instance


# =============================================================================
# Property 26: DI duplicate warning
# =============================================================================


class TestDIDuplicateWarning:
    """Property 26: DI duplicate warning.

    For any type T registered twice without a qualifier, the second
    app.provide(T, instance) call SHALL emit a Python warning via the
    warnings module.

    **Validates: Requirements 10.2**
    """

    @given(type_name=_type_name())
    @settings(max_examples=100)
    def test_second_provide_without_qualifier_emits_warning(
        self, type_name: str
    ) -> None:
        """Second provide without qualifier emits UserWarning.

        **Validates: Requirements 10.2**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        first_instance = t()
        second_instance = t()

        # First registration — no warning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reg.provide(t, first_instance)
            assert len(w) == 0

        # Second registration — should warn
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reg.provide(t, second_instance)
            assert len(w) == 1
            assert issubclass(w[0].category, UserWarning)
            assert "Duplicate registration" in str(w[0].message)
            assert type_name in str(w[0].message)

    @given(type_name=_type_name())
    @settings(max_examples=100)
    def test_duplicate_replaces_previous_instance(self, type_name: str) -> None:
        """Duplicate registration replaces the previous instance (last-write-wins).

        **Validates: Requirements 10.2**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        first_instance = t()
        second_instance = t()

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            reg.provide(t, first_instance)
            reg.provide(t, second_instance)

        # The second instance wins
        resolved = reg.resolve(t)
        assert resolved is second_instance
        assert resolved is not first_instance

    @given(
        type_name=_type_name(),
        qualifier=_qualifier(),
    )
    @settings(max_examples=100)
    def test_duplicate_with_qualifier_does_not_warn(
        self, type_name: str, qualifier: str
    ) -> None:
        """Duplicate registration WITH qualifier does not emit warning.

        The warning is only for unqualified duplicates.

        **Validates: Requirements 10.2**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        first_instance = t()
        second_instance = t()

        # First qualified registration — no warning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reg.provide(t, first_instance, qualifier=qualifier)
            assert len(w) == 0

        # Second qualified registration (same qualifier) — no warning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reg.provide(t, second_instance, qualifier=qualifier)
            assert len(w) == 0


# =============================================================================
# Property 27: DI qualified resolution
# =============================================================================


class TestDIQualifiedResolution:
    """Property 27: DI qualified resolution.

    For any type T with multiple qualified registrations, resolving with
    a specific qualifier SHALL return the instance registered under that qualifier.

    **Validates: Requirements 10.3, 10.4**
    """

    @given(
        type_name=_type_name(),
        qualifiers=st.lists(_qualifier(), min_size=2, max_size=6, unique=True),
    )
    @settings(max_examples=100)
    def test_resolving_with_qualifier_returns_correct_instance(
        self, type_name: str, qualifiers: list[str]
    ) -> None:
        """Resolving with qualifier returns the correct instance.

        **Validates: Requirements 10.3, 10.4**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        # Register multiple instances with different qualifiers
        instances: dict[str, object] = {}
        for q in qualifiers:
            inst = t()
            instances[q] = inst
            reg.provide(t, inst, qualifier=q)

        # Each qualifier resolves to its own instance
        for q in qualifiers:
            resolved = reg.resolve(t, qualifier=q)
            assert resolved is instances[q], (
                f"Qualifier {q!r} should resolve to its registered instance"
            )

    @given(
        type_name=_type_name(),
        qualifiers=st.lists(_qualifier(), min_size=2, max_size=5, unique=True),
        data=st.data(),
    )
    @settings(max_examples=100)
    def test_qualified_resolution_independent_of_registration_order(
        self, type_name: str, qualifiers: list[str], data: st.DataObject
    ) -> None:
        """Qualified resolution works regardless of registration order.

        **Validates: Requirements 10.3, 10.4**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        instances: dict[str, object] = {}
        for q in qualifiers:
            inst = t()
            instances[q] = inst
            reg.provide(t, inst, qualifier=q)

        # Pick a random qualifier to resolve
        target_q = data.draw(st.sampled_from(qualifiers))
        resolved = reg.resolve(t, qualifier=target_q)
        assert resolved is instances[target_q]

    @given(
        type_name=_type_name(),
        qualifier=_qualifier(),
    )
    @settings(max_examples=100)
    def test_single_qualified_registration_resolves_correctly(
        self, type_name: str, qualifier: str
    ) -> None:
        """A single qualified registration can be resolved by its qualifier.

        **Validates: Requirements 10.3, 10.4**
        """
        reg = DIRegistry()
        t = _make_type(type_name)
        inst = t()

        reg.provide(t, inst, qualifier=qualifier)

        resolved = reg.resolve(t, qualifier=qualifier)
        assert resolved is inst


# =============================================================================
# Property 28: DI ambiguous resolution error
# =============================================================================


class TestDIAmbiguousResolutionError:
    """Property 28: DI ambiguous resolution error.

    For any type T with multiple qualified registrations and no unqualified
    registration, resolving T without a qualifier SHALL raise AmbiguousProviderError.

    **Validates: Requirements 10.6**
    """

    @given(
        type_name=_type_name(),
        qualifiers=st.lists(_qualifier(), min_size=2, max_size=6, unique=True),
    )
    @settings(max_examples=100)
    def test_unqualified_lookup_with_multiple_qualifiers_raises_error(
        self, type_name: str, qualifiers: list[str]
    ) -> None:
        """Unqualified lookup with multiple qualifiers raises AmbiguousProviderError.

        **Validates: Requirements 10.6**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        # Register multiple qualified instances (no unqualified)
        for q in qualifiers:
            reg.provide(t, t(), qualifier=q)

        with pytest.raises(AmbiguousProviderError) as exc_info:
            reg.resolve(t)

        error = exc_info.value
        assert error.type_ is t
        # All qualifiers should be listed in the error
        for q in qualifiers:
            assert q in error.qualifiers

    @given(
        type_name=_type_name(),
        qualifiers=st.lists(_qualifier(), min_size=2, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_ambiguous_error_message_suggests_disambiguation(
        self, type_name: str, qualifiers: list[str]
    ) -> None:
        """AmbiguousProviderError message suggests using Provide('qualifier').

        **Validates: Requirements 10.6**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        for q in qualifiers:
            reg.provide(t, t(), qualifier=q)

        with pytest.raises(AmbiguousProviderError) as exc_info:
            reg.resolve(t)

        error_msg = str(exc_info.value)
        assert "Provide(" in error_msg or "qualifier" in error_msg.lower()

    @given(
        type_name=_type_name(),
        qualifiers=st.lists(_qualifier(), min_size=2, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_no_ambiguity_when_unqualified_registration_exists(
        self, type_name: str, qualifiers: list[str]
    ) -> None:
        """When an unqualified registration exists alongside qualified ones,
        unqualified resolve succeeds (no ambiguity).

        **Validates: Requirements 10.6**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        # Register an unqualified instance
        unqualified_inst = t()
        reg.provide(t, unqualified_inst)

        # Also register qualified instances
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            for q in qualifiers:
                reg.provide(t, t(), qualifier=q)

        # Unqualified resolve should succeed (returns the unqualified instance)
        resolved = reg.resolve(t)
        assert resolved is unqualified_inst
