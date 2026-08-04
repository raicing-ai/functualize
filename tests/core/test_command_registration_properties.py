"""Property-based tests for Plugin CLI Command Registration.

Tests Property 6 (command name validation) and Property 7 (duplicate command
registration) using Hypothesis.

**Validates: Requirements 3.4, 3.5**
"""

from __future__ import annotations

import re
from collections.abc import Generator

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp

# --- Constants ---

COMMAND_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


# --- Strategies ---

# Strategy for valid command names: starts with lowercase letter, followed by
# 0-63 lowercase alphanumeric or hyphen characters
valid_command_names = st.from_regex(r"^[a-z][a-z0-9\-]{0,63}$", fullmatch=True)

# Strategy for valid group names (same pattern as command names)
valid_group_names = st.one_of(
    st.none(),
    st.from_regex(r"^[a-z][a-z0-9\-]{0,63}$", fullmatch=True),
)

# Strategy for arbitrary strings that may or may not match the valid pattern
arbitrary_strings = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
    ),
    min_size=0,
    max_size=100,
)


# --- Fixtures ---


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


# --- Property 6: Plugin command name validation rejects invalid patterns ---


class TestCommandNameValidation:
    """Property 6: For any string that does not match the pattern
    `^[a-z][a-z0-9-]{0,63}$`, `register_plugin_command()` SHALL raise a ValueError.

    **Validates: Requirements 3.5**
    """

    @settings(max_examples=200)
    @given(name=arbitrary_strings)
    def test_invalid_names_raise_value_error(self, name: str) -> None:
        """Any string NOT matching the valid command name pattern raises ValueError."""
        assume(not COMMAND_NAME_PATTERN.match(name))

        app = FunctualizeApp(name="testapp")

        def dummy_callback() -> None:
            pass

        with pytest.raises(ValueError, match="Invalid command name"):
            app.register_plugin_command(name, dummy_callback)

    @settings(max_examples=200)
    @given(name=valid_command_names)
    def test_valid_names_accepted(self, name: str) -> None:
        """Any string matching the valid command name pattern is accepted."""
        app = FunctualizeApp(name="testapp")

        def dummy_callback() -> None:
            pass

        # Should not raise
        app.register_plugin_command(name, dummy_callback)
        assert name in app._plugin_commands[None]


# --- Property 7: Duplicate command registration raises ValueError ---


class TestDuplicateCommandRegistration:
    """Property 7: For any command name already registered within a given
    namespace (or at top level), attempting to register the same name in the
    same namespace SHALL raise a ValueError.

    **Validates: Requirements 3.4**
    """

    @settings(max_examples=100)
    @given(name=valid_command_names, namespace=valid_group_names)
    def test_duplicate_registration_raises_value_error(
        self, name: str, namespace: str | None
    ) -> None:
        """Registering the same command name in the same namespace a second
        time raises ValueError."""
        app = FunctualizeApp(name="testapp")

        def callback_a() -> None:
            pass

        def callback_b() -> None:
            pass

        # First registration succeeds
        app.register_plugin_command(name, callback_a, namespace=namespace)

        # Second registration with same name and namespace raises
        with pytest.raises(ValueError, match="Duplicate command name"):
            app.register_plugin_command(name, callback_b, namespace=namespace)

    @settings(max_examples=100, suppress_health_check=[HealthCheck.filter_too_much])
    @given(
        name=valid_command_names,
        namespace_a=valid_group_names.filter(lambda g: g is not None),
        namespace_b=valid_group_names.filter(lambda g: g is not None),
    )
    def test_same_name_different_namespaces_allowed(
        self, name: str, namespace_a: str, namespace_b: str
    ) -> None:
        """The same command name can be registered in different namespaces
        without error."""
        assume(namespace_a != namespace_b)

        app = FunctualizeApp(name="testapp")

        def callback_a() -> None:
            pass

        def callback_b() -> None:
            pass

        # Both registrations should succeed in different namespaces
        app.register_plugin_command(name, callback_a, namespace=namespace_a)
        app.register_plugin_command(name, callback_b, namespace=namespace_b)

        assert name in app._plugin_commands[namespace_a]
        assert name in app._plugin_commands[namespace_b]
