"""Property-based tests for DIRegistry (Properties 5, 6, 7, 8).

Tests the DI registry from functualize.primitives.di:
- Property 5: DIRegistry provide/resolve round-trip
- Property 6: DIRegistry scope semantics (singleton vs invocation)
- Property 7: DIRegistry resolution error diagnostics
- Property 8: DIRegistry freeze immutability

# Feature: unified-architecture-redesign, Task 3.3
"""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from functualize._primitives.di import (
    AmbiguousProviderError,
    DIRegistry,
    MissingProviderError,
    RegistryFrozenError,
)

# =============================================================================
# Strategies
# =============================================================================


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


@st.composite
def _provide_operations(draw: st.DrawFn) -> list[tuple[str, str | None]]:
    """Generate a sequence of provide operations: (type_name, qualifier).

    Multiple operations may target the same (type_name, qualifier) pair to
    test last-write-wins semantics. Instances are minted by `_realize_ops`
    rather than here, because `DIRegistry.provide` type-checks the instance
    against the type and a bare `object()` cannot satisfy that contract.
    """
    num_types = draw(st.integers(min_value=1, max_value=5))
    type_names = [draw(_type_name()) for _ in range(num_types)]
    # Ensure unique type names
    type_names = list(dict.fromkeys(type_names))
    assume(len(type_names) >= 1)

    num_ops = draw(st.integers(min_value=1, max_value=15))
    ops: list[tuple[str, str | None]] = []
    for _ in range(num_ops):
        tn = draw(st.sampled_from(type_names))
        qual = draw(st.one_of(st.none(), _qualifier()))
        ops.append((tn, qual))
    return ops


def _realize_ops(
    ops: list[tuple[str, str | None]],
) -> tuple[dict[str, type], list[tuple[str, str | None, object]]]:
    """Turn generated (type_name, qualifier) ops into concrete registrations.

    Returns the name→type map plus the ops with a freshly-minted instance of
    the correct type appended. Each instance has a distinct identity, which is
    what the last-write-wins and independence properties assert on.
    """
    type_map: dict[str, type] = {}
    for type_name, _ in ops:
        if type_name not in type_map:
            type_map[type_name] = _make_type(type_name)
    realized = [(tn, qual, type_map[tn]()) for tn, qual in ops]
    return type_map, realized


# =============================================================================
# Property 5: DIRegistry provide/resolve round-trip
# =============================================================================


class TestDIRegistryProvideResolveRoundTrip:
    """Property 5: DIRegistry provide/resolve round-trip.

    For any sequence of provide(type, instance, qualifier) calls on a DIRegistry,
    resolve(type, qualifier) SHALL return the instance from the most recent
    provide call with the matching (type, qualifier) pair.

    **Validates: Requirements 3.1, 3.4, 3.7**
    """

    @given(ops=_provide_operations())
    @settings(max_examples=200)
    def test_resolve_returns_most_recent_instance(
        self, ops: list[tuple[str, str | None]]
    ):
        """resolve(type, qualifier) returns the most recently provided instance.

        **Validates: Requirements 3.1, 3.4, 3.7**
        """
        reg = DIRegistry()

        type_map, realized = _realize_ops(ops)

        # Execute all provide operations
        for type_name, qualifier, instance in realized:
            reg.provide(type_map[type_name], instance, qualifier=qualifier)

        # For each unique (type_name, qualifier) pair, the last-written instance wins
        last_written: dict[tuple[str, str | None], object] = {}
        for type_name, qualifier, instance in realized:
            last_written[(type_name, qualifier)] = instance

        # Verify round-trip
        for (type_name, qualifier), expected_instance in last_written.items():
            resolved = reg.resolve(type_map[type_name], qualifier=qualifier)
            assert resolved is expected_instance, (
                f"Expected resolve({type_name}, qualifier={qualifier!r}) "
                f"to return last-provided instance"
            )

    @given(
        type_name=_type_name(),
        qualifiers=st.lists(_qualifier(), min_size=2, max_size=5, unique=True),
    )
    @settings(max_examples=200)
    def test_qualified_instances_are_independent(
        self, type_name: str, qualifiers: list[str]
    ):
        """Different qualifiers for the same type store independent instances.

        **Validates: Requirements 3.1, 3.4, 3.7**
        """
        reg = DIRegistry()
        t = _make_type(type_name)

        instances = {}
        for q in qualifiers:
            inst = t()
            instances[q] = inst
            reg.provide(t, inst, qualifier=q)

        # Each qualifier resolves its own instance
        for q in qualifiers:
            assert reg.resolve(t, qualifier=q) is instances[q]


# =============================================================================
# Property 6: DIRegistry scope semantics (singleton vs invocation)
# =============================================================================


class TestDIRegistryScopeSemantics:
    """Property 6: DIRegistry scope semantics (singleton vs invocation).

    For any factory registered with scope="singleton", all calls to resolve
    SHALL return the same object (by identity). For any factory registered with
    scope="invocation", each call to resolve within a new invocation context
    SHALL return a distinct object (by identity).

    **Validates: Requirements 3.2, 3.9, 3.10**
    """

    @given(num_resolves=st.integers(min_value=2, max_value=20))
    @settings(max_examples=200)
    def test_singleton_factory_returns_same_object(self, num_resolves: int):
        """Singleton factory always returns the same object by identity.

        **Validates: Requirements 3.2, 3.9, 3.10**
        """
        reg = DIRegistry()
        t = _make_type("SingletonService")

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return object()

        reg.provide_factory(t, factory, "singleton")

        results = [reg.resolve(t) for _ in range(num_resolves)]

        # All results are the same object
        first = results[0]
        for r in results[1:]:
            assert r is first, (
                "Singleton factory must return same object on every resolve"
            )

        # Factory was invoked exactly once
        assert call_count == 1

    @given(num_resolves=st.integers(min_value=2, max_value=20))
    @settings(max_examples=200)
    def test_invocation_factory_returns_distinct_objects(self, num_resolves: int):
        """Invocation factory returns a distinct object on each resolve.

        **Validates: Requirements 3.2, 3.9, 3.10**
        """
        reg = DIRegistry()
        t = _make_type("InvocationService")

        def factory(caps: dict):
            return object()

        reg.provide_factory(t, factory, "invocation")

        results = [reg.resolve(t, caps={}) for _ in range(num_resolves)]

        # All results are distinct objects
        ids = [id(r) for r in results]
        assert len(set(ids)) == num_resolves, (
            "Invocation factory must return a distinct object on each resolve"
        )

    @given(
        qualifiers=st.lists(_qualifier(), min_size=2, max_size=4, unique=True),
        num_resolves=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=200)
    def test_singleton_factories_are_independent_per_qualifier(
        self, qualifiers: list[str], num_resolves: int
    ):
        """Each (type, qualifier) pair has its own singleton cache.

        **Validates: Requirements 3.2, 3.9, 3.10**
        """
        reg = DIRegistry()
        t = _make_type("QualifiedSingleton")

        for q in qualifiers:
            reg.provide_factory(t, lambda: object(), "singleton", qualifier=q)

        # Resolve each qualifier multiple times
        results_per_qualifier: dict[str, list[object]] = {q: [] for q in qualifiers}
        for q in qualifiers:
            for _ in range(num_resolves):
                results_per_qualifier[q].append(reg.resolve(t, qualifier=q))

        # Within each qualifier, all resolves return the same object (singleton)
        for q in qualifiers:
            first = results_per_qualifier[q][0]
            for r in results_per_qualifier[q][1:]:
                assert r is first

        # Across qualifiers, singletons are distinct
        singleton_objects = [results_per_qualifier[q][0] for q in qualifiers]
        assert len(set(id(o) for o in singleton_objects)) == len(qualifiers)


# =============================================================================
# Property 7: DIRegistry resolution error diagnostics
# =============================================================================


class TestDIRegistryResolutionErrorDiagnostics:
    """Property 7: DIRegistry resolution error diagnostics.

    For any type not registered in the DIRegistry (and not Optional[T]),
    resolve(type) SHALL raise MissingProviderError containing the requested
    type name and the list of all available types. For any type with N > 1
    qualifiers where no qualifier is specified, resolve(type) SHALL raise
    AmbiguousProviderError listing all available qualifiers.

    **Validates: Requirements 3.5, 3.6, 18.1, 18.2**
    """

    @given(
        registered_names=st.lists(_type_name(), min_size=1, max_size=5, unique=True),
        missing_name=_type_name(),
    )
    @settings(max_examples=200)
    def test_missing_provider_error_contains_type_and_available(
        self, registered_names: list[str], missing_name: str
    ):
        """MissingProviderError includes requested type name and available types.

        **Validates: Requirements 3.5, 3.6, 18.1, 18.2**
        """
        assume(missing_name not in registered_names)

        reg = DIRegistry()
        type_map: dict[str, type] = {}

        for name in registered_names:
            t = _make_type(name)
            type_map[name] = t
            reg.provide(t, t())

        missing_type = _make_type(missing_name)

        try:
            reg.resolve(missing_type)
            raise AssertionError("Should have raised MissingProviderError")
        except MissingProviderError as e:
            # Error must reference the requested type
            assert e.type_ is missing_type
            # Error must list all available types
            for name in registered_names:
                assert type_map[name] in e.available, (
                    f"Available types should include {name}"
                )

    @given(
        qualifiers=st.lists(_qualifier(), min_size=2, max_size=6, unique=True),
    )
    @settings(max_examples=200)
    def test_ambiguous_provider_error_lists_all_qualifiers(self, qualifiers: list[str]):
        """AmbiguousProviderError lists all available qualifiers.

        When a type has N > 1 qualifiers and resolve is called without
        a qualifier, AmbiguousProviderError must list all qualifiers.

        **Validates: Requirements 3.5, 3.6, 18.1, 18.2**
        """
        reg = DIRegistry()
        t = _make_type("AmbiguousService")

        for q in qualifiers:
            reg.provide(t, t(), qualifier=q)

        try:
            reg.resolve(t)
            raise AssertionError("Should have raised AmbiguousProviderError")
        except AmbiguousProviderError as e:
            assert e.type_ is t
            # All qualifiers must be listed
            for q in qualifiers:
                assert q in e.qualifiers, (
                    f"Qualifier {q!r} should be in error qualifiers"
                )

    @given(
        registered_names=st.lists(_type_name(), min_size=0, max_size=5, unique=True),
        missing_name=_type_name(),
    )
    @settings(max_examples=200)
    def test_missing_provider_error_message_contains_type_name(
        self, registered_names: list[str], missing_name: str
    ):
        """MissingProviderError string representation includes the type name.

        **Validates: Requirements 3.5, 3.6, 18.1, 18.2**
        """
        assume(missing_name not in registered_names)

        reg = DIRegistry()
        for name in registered_names:
            _t = _make_type(name)
            reg.provide(_t, _t())

        missing_type = _make_type(missing_name)

        try:
            reg.resolve(missing_type)
            raise AssertionError("Should have raised MissingProviderError")
        except MissingProviderError as e:
            assert missing_name in str(e), (
                f"Error message should contain type name {missing_name!r}"
            )


# =============================================================================
# Property 8: DIRegistry freeze immutability
# =============================================================================


class TestDIRegistryFreezeImmutability:
    """Property 8: DIRegistry freeze immutability.

    For any DIRegistry that has been frozen, all mutation methods (provide,
    provide_factory, provide_named) SHALL raise RegistryFrozenError, while
    all read methods (resolve, named lookups) SHALL continue to function
    normally for previously-registered entries.

    **Validates: Requirements 4.1, 4.2, 4.3**
    """

    @given(ops=_provide_operations())
    @settings(max_examples=200)
    def test_frozen_registry_rejects_all_mutations(
        self, ops: list[tuple[str, str | None]]
    ):
        """All mutation methods raise RegistryFrozenError after freeze.

        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        reg = DIRegistry()
        type_map, realized = _realize_ops(ops)

        # Set up some registrations
        for type_name, qualifier, instance in realized:
            reg.provide(type_map[type_name], instance, qualifier=qualifier)

        # Freeze
        reg.freeze()

        # All mutation methods must raise RegistryFrozenError
        new_type = _make_type("NewType")

        try:
            reg.provide(new_type, new_type())
            raise AssertionError("provide() should raise RegistryFrozenError")
        except RegistryFrozenError as e:
            assert e.method_name == "provide"

        try:
            reg.provide_factory(new_type, lambda: object(), "singleton")
            raise AssertionError("provide_factory() should raise RegistryFrozenError")
        except RegistryFrozenError as e:
            assert e.method_name == "provide_factory"

        try:
            reg.provide_named("frozen_key", "value")
            raise AssertionError("provide_named() should raise RegistryFrozenError")
        except RegistryFrozenError as e:
            assert e.method_name == "provide_named"

    @given(ops=_provide_operations())
    @settings(max_examples=200)
    def test_frozen_registry_reads_still_work(self, ops: list[tuple[str, str | None]]):
        """Read methods continue to work normally after freeze.

        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        reg = DIRegistry()
        type_map, realized = _realize_ops(ops)

        # Set up registrations and track last-written per key
        last_written: dict[tuple[str, str | None], object] = {}
        for type_name, qualifier, instance in realized:
            reg.provide(type_map[type_name], instance, qualifier=qualifier)
            last_written[(type_name, qualifier)] = instance

        # Also register some named values
        reg.provide_named("test_key", "test_value")

        # Freeze
        reg.freeze()

        # Resolve still works for all previously-registered entries
        for (type_name, qualifier), expected in last_written.items():
            resolved = reg.resolve(type_map[type_name], qualifier=qualifier)
            assert resolved is expected

        # Named lookups still work
        assert reg.resolve_named("test_key") == "test_value"

    @given(
        named_entries=st.dictionaries(
            keys=st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz_",
                min_size=1,
                max_size=10,
            ),
            values=st.integers(),
            min_size=1,
            max_size=8,
        )
    )
    @settings(max_examples=200)
    def test_frozen_registry_named_reads_work(self, named_entries: dict[str, int]):
        """Named value lookups continue normally after freeze.

        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        reg = DIRegistry()

        for name, value in named_entries.items():
            reg.provide_named(name, value)

        reg.freeze()

        # All named reads still work
        for name, expected_value in named_entries.items():
            assert reg.resolve_named(name) == expected_value

        # Mutation is rejected
        try:
            reg.provide_named("new_after_freeze", 999)
            raise AssertionError("Should have raised RegistryFrozenError")
        except RegistryFrozenError:
            pass

    @given(num_resolves=st.integers(min_value=2, max_value=10))
    @settings(max_examples=200)
    def test_frozen_registry_singleton_factory_still_works(self, num_resolves: int):
        """Singleton factories continue to resolve after freeze.

        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        reg = DIRegistry()
        t = _make_type("FrozenSingleton")

        reg.provide_factory(t, lambda: object(), "singleton")

        # Resolve once before freeze to cache the singleton
        first = reg.resolve(t)

        reg.freeze()

        # Subsequent resolves after freeze still return same singleton
        for _ in range(num_resolves):
            assert reg.resolve(t) is first
