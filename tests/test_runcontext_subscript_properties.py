"""Property-based tests for RunContext subscript access (Property 11).

Tests the RunContext DI facade: rc[Type], rc[Type, "qualifier"], rc["name"],
and the `in` operator for containment checks.

# Feature: unified-architecture-redesign, Task 5.6
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import assume, given
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize._primitives.di import DIRegistry, MissingProviderError
from functualize.job.context import RunContext

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
def _named_key(draw: st.DrawFn) -> str:
    """Generate a non-empty named string key."""
    return draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz_",
            min_size=1,
            max_size=15,
        )
    )


# =============================================================================
# Helpers
# =============================================================================


def _make_runcontext_with_registry(
    registry: DIRegistry, name: str = "test-job"
) -> RunContext:
    """Create a RunContext backed by the given DIRegistry."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock()
    return RunContext(
        name=name,
        config=mock_config,
        logger=mock_logger,
        _di_registry=registry,
    )


# =============================================================================
# Property 11: RunContext subscript access round-trip
# =============================================================================


class TestRunContextSubscriptAccessRoundTrip:
    """Property 11: RunContext subscript access round-trip.

    For any type T registered in the backing DIRegistry, rc[T] SHALL return the
    registered instance. For any qualified registration (T, qualifier), rc[T, qualifier]
    SHALL return the qualified instance. For any named registration name, rc[name]
    SHALL return the named value. The in operator SHALL return True iff the type/name
    is registered.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.7, 6.8, 6.9**
    """

    @given(
        type_names=st.lists(_type_name(), min_size=1, max_size=5, unique=True),
    )
    def test_unqualified_type_roundtrip(self, type_names: list[str]):
        """rc[Type] returns the registered instance for any type T.

        **Validates: Requirements 6.1**
        """
        reg = DIRegistry()
        types_and_instances: list[tuple[type, object]] = []

        for name in type_names:
            t = _make_type(name)
            inst = t()
            reg.provide(t, inst)
            types_and_instances.append((t, inst))

        rc = _make_runcontext_with_registry(reg)

        for t, expected in types_and_instances:
            assert rc[t] is expected, (
                f"rc[{t.__name__}] should return the registered instance"
            )

    @given(
        type_name=_type_name(),
        qualifiers=st.lists(_qualifier(), min_size=1, max_size=5, unique=True),
    )
    def test_qualified_type_roundtrip(self, type_name: str, qualifiers: list[str]):
        """rc[Type, "qualifier"] returns the qualified instance.

        **Validates: Requirements 6.2**
        """
        reg = DIRegistry()
        t = _make_type(type_name)
        instances: dict[str, object] = {}

        for q in qualifiers:
            inst = t()
            instances[q] = inst
            reg.provide(t, inst, qualifier=q)

        rc = _make_runcontext_with_registry(reg)

        for q, expected in instances.items():
            assert rc[t, q] is expected, (
                f"rc[{type_name}, {q!r}] should return the qualified instance"
            )

    @given(
        named_entries=st.dictionaries(
            keys=_named_key(),
            values=st.integers(),
            min_size=1,
            max_size=8,
        ),
    )
    def test_named_value_roundtrip(self, named_entries: dict[str, int]):
        """rc["name"] returns the named value.

        **Validates: Requirements 6.3**
        """
        reg = DIRegistry()

        for name, value in named_entries.items():
            reg.provide_named(name, value)

        rc = _make_runcontext_with_registry(reg)

        for name, expected in named_entries.items():
            assert rc[name] == expected, (
                f"rc[{name!r}] should return the registered named value"
            )

    @given(
        registered_names=st.lists(_type_name(), min_size=1, max_size=5, unique=True),
        unregistered_name=_type_name(),
    )
    def test_type_containment_true_when_registered(
        self, registered_names: list[str], unregistered_name: str
    ):
        """Type in rc returns True iff type is registered.

        **Validates: Requirements 6.4**
        """
        assume(unregistered_name not in registered_names)

        reg = DIRegistry()
        type_map: dict[str, type] = {}

        for name in registered_names:
            t = _make_type(name)
            type_map[name] = t
            reg.provide(t, t())

        unregistered_type = _make_type(unregistered_name)

        rc = _make_runcontext_with_registry(reg)

        # Registered types return True
        for name in registered_names:
            assert type_map[name] in rc, f"{name} should be in rc (registered)"

        # Unregistered type returns False
        assert unregistered_type not in rc, (
            f"{unregistered_name} should not be in rc (not registered)"
        )

    @given(
        registered_keys=st.lists(_named_key(), min_size=1, max_size=5, unique=True),
        unregistered_key=_named_key(),
    )
    def test_named_containment_true_when_registered(
        self, registered_keys: list[str], unregistered_key: str
    ):
        """`"name" in rc` returns True iff name is registered.

        **Validates: Requirements 6.5**
        """
        assume(unregistered_key not in registered_keys)

        reg = DIRegistry()

        for key in registered_keys:
            reg.provide_named(key, object())

        rc = _make_runcontext_with_registry(reg)

        # Registered names return True
        for key in registered_keys:
            assert key in rc, f"{key!r} should be in rc (registered named value)"

        # Unregistered name returns False
        assert unregistered_key not in rc, (
            f"{unregistered_key!r} should not be in rc (not registered)"
        )

    @given(
        type_name=_type_name(),
    )
    def test_unqualified_missing_type_raises(self, type_name: str):
        """rc[Type] raises MissingProviderError for unregistered types.

        **Validates: Requirements 6.7**
        """
        reg = DIRegistry()
        rc = _make_runcontext_with_registry(reg)
        missing_type = _make_type(type_name)

        try:
            rc[missing_type]
            raise AssertionError("Should have raised MissingProviderError")
        except MissingProviderError as e:
            assert e.type_ is missing_type

    @given(
        type_name=_type_name(),
        qualifier=_qualifier(),
    )
    def test_qualified_missing_type_raises(self, type_name: str, qualifier: str):
        """rc[Type, "qualifier"] raises MissingProviderError for missing qualified type.

        **Validates: Requirements 6.8**
        """
        reg = DIRegistry()
        rc = _make_runcontext_with_registry(reg)
        missing_type = _make_type(type_name)

        try:
            rc[missing_type, qualifier]
            raise AssertionError("Should have raised MissingProviderError")
        except MissingProviderError as e:
            assert e.type_ is missing_type

    @given(
        name=_named_key(),
    )
    def test_named_missing_raises(self, name: str):
        """rc["name"] raises MissingProviderError for unregistered names.

        **Validates: Requirements 6.9**
        """
        reg = DIRegistry()
        rc = _make_runcontext_with_registry(reg)

        try:
            rc[name]
            raise AssertionError("Should have raised MissingProviderError")
        except MissingProviderError:
            pass

    @given(
        type_names=st.lists(_type_name(), min_size=1, max_size=4, unique=True),
        named_keys=st.lists(_named_key(), min_size=1, max_size=4, unique=True),
        qualifiers=st.lists(_qualifier(), min_size=1, max_size=3, unique=True),
    )
    def test_mixed_registrations_all_accessible(
        self,
        type_names: list[str],
        named_keys: list[str],
        qualifiers: list[str],
    ):
        """All registration kinds (type, qualified, named) are accessible together.

        **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
        """
        reg = DIRegistry()

        # Register unqualified types
        unqualified: list[tuple[type, object]] = []
        for name in type_names:
            t = _make_type(name)
            inst = t()
            reg.provide(t, inst)
            unqualified.append((t, inst))

        # Register qualified type (use first type name with each qualifier)
        qualified_type = _make_type(type_names[0] + "Qualified")
        qualified_instances: dict[str, object] = {}
        for q in qualifiers:
            inst = qualified_type()
            reg.provide(qualified_type, inst, qualifier=q)
            qualified_instances[q] = inst

        # Register named values
        named_values: dict[str, object] = {}
        for key in named_keys:
            val = object()
            reg.provide_named(key, val)
            named_values[key] = val

        rc = _make_runcontext_with_registry(reg)

        # All unqualified types accessible
        for t, expected in unqualified:
            assert rc[t] is expected

        # All qualified types accessible
        for q, expected in qualified_instances.items():
            assert rc[qualified_type, q] is expected

        # All named values accessible
        for key, expected in named_values.items():
            assert rc[key] is expected

        # Containment works for all
        for t, _ in unqualified:
            assert t in rc
        for key in named_keys:
            assert key in rc
