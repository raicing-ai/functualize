"""Property-based tests for plugin registration (Properties 13, 15).

Tests:
- Property 13: InteractivityPlugin registration rejects non-conforming objects
- Property 15: Plugin instance registry — get_plugin returns correct instance or raises KeyError

Validates: Requirements 6.3, 8.1, 8.2
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


# --- Strategies ---

# The two independent surface capabilities (the method that defines each).
SURFACE_METHOD = "handle_event"
COLLECTOR_METHOD = "collect"
ALL_PROTOCOL_MEMBERS = [SURFACE_METHOD, COLLECTOR_METHOD]

# Strategy for plugin names (non-empty strings)
plugin_names = st.text(
    min_size=1,
    max_size=30,
    alphabet=st.characters(categories=("L", "N", "Pd")),
)

# To be non-conforming an object must implement NEITHER method; the only
# such subset to remove is both of them.
missing_members_subsets = st.just(list(ALL_PROTOCOL_MEMBERS))


def _make_conforming_plugin(name: str) -> Any:
    """Create an object that satisfies the PromptCollector protocol."""

    class _Plugin:
        pass

    p = _Plugin()
    p.name = name  # type: ignore[attr-defined]

    def _collect(*args: Any, **kwargs: Any) -> Any:
        from functualize._types.interactivity import PromptResponse

        return PromptResponse(value="test", source="user")

    p.collect = _collect  # type: ignore[attr-defined]

    return p


def _make_nonconforming_plugin(missing: list[str]) -> Any:
    """Create an object that satisfies NEITHER Surface nor PromptCollector."""

    class _Plugin:
        pass

    p = _Plugin()
    p.name = "test-plugin"  # type: ignore[attr-defined]

    def _noop(*args: Any, **kwargs: Any) -> None:
        pass

    # Add any protocol methods NOT in the missing list (missing is both, so
    # this adds nothing — the object conforms to neither).
    for method_name in ALL_PROTOCOL_MEMBERS:
        if method_name not in missing:
            setattr(p, method_name, _noop)

    return p


# Strategy for sets of unique plugin names (for Property 15)
unique_plugin_names = st.lists(
    plugin_names,
    min_size=1,
    max_size=10,
    unique=True,
)


# Feature: plugin-ecosystem-enablement, Property 13: InteractivityPlugin registration rejects non-conforming objects
# For any object that does not satisfy the InteractivityPlugin protocol
# (missing `name` attribute or any required lifecycle method),
# `register_interactivity_plugin()` SHALL raise a TypeError indicating
# which members are missing.
# **Validates: Requirements 6.3**
class TestInteractivityPluginRegistrationRejectsNonConforming:
    """Property 13: InteractivityPlugin registration rejects non-conforming objects."""

    @given(missing=missing_members_subsets)
    @settings(max_examples=100)
    def test_missing_members_raises_type_error(self, missing: list[str]) -> None:
        """For any combination of missing required protocol members, TypeError is raised.

        **Validates: Requirements 6.3**
        """
        app = FunctualizeApp(name="testapp")
        plugin = _make_nonconforming_plugin(missing)

        with pytest.raises(TypeError, match="Surface protocol"):
            app.register_surface(plugin)

    @given(missing=missing_members_subsets)
    @settings(max_examples=100)
    def test_error_message_indicates_required_protocols(
        self, missing: list[str]
    ) -> None:
        """TypeError message indicates which protocols are required.

        **Validates: Requirements 6.3**
        """
        app = FunctualizeApp(name="testapp")
        plugin = _make_nonconforming_plugin(missing)

        with pytest.raises(
            TypeError, match="handle_event.*collect|collect.*handle_event"
        ):
            app.register_surface(plugin)

    @given(name=plugin_names)
    @settings(max_examples=50)
    def test_conforming_plugin_does_not_raise(self, name: str) -> None:
        """A fully conforming plugin with any valid name does NOT raise TypeError.

        **Validates: Requirements 6.3**
        """
        app = FunctualizeApp(name="testapp")
        plugin = _make_conforming_plugin(name)

        # Should not raise
        app.register_surface(plugin)
        assert plugin in app._surfaces


# Feature: plugin-ecosystem-enablement, Property 15: Plugin instance registry — get_plugin returns correct instance or raises KeyError
# For any set of registered plugins with unique names, `get_plugin(name)`
# SHALL return the matching instance. For any name not matching a registered
# plugin, it SHALL raise a KeyError whose message includes the list of
# registered plugin names.
# **Validates: Requirements 8.1, 8.2**
class TestPluginInstanceRegistry:
    """Property 15: Plugin instance registry — get_plugin returns correct instance or raises KeyError."""

    @given(names=unique_plugin_names)
    @settings(max_examples=100)
    def test_get_plugin_returns_correct_instance(self, names: list[str]) -> None:
        """For any set of registered plugins, get_plugin(name) returns the matching instance.

        **Validates: Requirements 8.1**
        """
        app = FunctualizeApp(name="testapp")

        # Register plugins by name
        plugins: dict[str, Any] = {}
        for name in names:
            plugin = _make_conforming_plugin(name)
            plugins[name] = plugin
            app._plugin_name_index[name] = plugin

        # Each plugin is retrievable by its name
        for name, expected_plugin in plugins.items():
            result = app.get_plugin(name)
            assert result is expected_plugin

    @given(
        registered_names=unique_plugin_names,
        unregistered_name=plugin_names,
    )
    @settings(max_examples=100)
    def test_get_plugin_raises_key_error_for_unregistered(
        self,
        registered_names: list[str],
        unregistered_name: str,
    ) -> None:
        """For any unregistered name, get_plugin raises KeyError including registered names.

        **Validates: Requirements 8.2**
        """
        assume(unregistered_name not in registered_names)

        app = FunctualizeApp(name="testapp")

        # Register plugins
        for name in registered_names:
            plugin = _make_conforming_plugin(name)
            app._plugin_name_index[name] = plugin

        # Lookup of unregistered name raises KeyError
        with pytest.raises(KeyError) as exc_info:
            app.get_plugin(unregistered_name)

        # Error message includes the registered names
        error_message = str(exc_info.value)
        for registered_name in registered_names:
            assert registered_name in error_message

    @given(names=unique_plugin_names)
    @settings(max_examples=50)
    def test_get_plugin_case_sensitive(self, names: list[str]) -> None:
        """Plugin lookup uses case-sensitive comparison.

        **Validates: Requirements 8.1**
        """
        app = FunctualizeApp(name="testapp")

        for name in names:
            plugin = _make_conforming_plugin(name)
            app._plugin_name_index[name] = plugin

        # If we try to look up a name with altered case, it should fail
        # (unless the altered version happens to also be registered)
        for name in names:
            altered = name.swapcase()
            if altered not in names and altered != name:
                with pytest.raises(KeyError):
                    app.get_plugin(altered)
