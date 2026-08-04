"""Property-based tests for Protocol Compliance and Entry-point Resilience.

Tests Property 12 (Protocol compliance) and Property 33 (Entry-point load failure)
using Hypothesis.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._plugins.loader import PluginLoader
from functualize._types.interactivity import (
    PromptCollector,
    PromptResponse,
    Surface,
)

# --- Strategies for Property 12 ---

# Strategy for whether to include the name attribute
include_name = st.booleans()

# Strategy for name values
name_values = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=30,
)


def _make_surface_class(
    has_handle_event: bool, has_name: bool, name_value: str
) -> type:
    """Dynamically create a class with/without the Surface method."""
    attrs: dict[str, Any] = {}
    if has_name:
        attrs["name"] = name_value
    if has_handle_event:
        attrs["handle_event"] = lambda self, event: None
    return type("DynamicSurface", (), attrs)


def _make_collector_class(has_collect: bool, has_name: bool, name_value: str) -> type:
    """Dynamically create a class with/without the PromptCollector method."""
    attrs: dict[str, Any] = {}
    if has_name:
        attrs["name"] = name_value
    if has_collect:
        attrs["collect"] = lambda self, request: PromptResponse(
            value="test", source="user"
        )
    return type("DynamicCollector", (), attrs)


# --- Strategies for Property 33 ---

# Strategy for entry-point names
entry_point_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=30,
)

# Strategy for exception types that represent load failures
load_failure_exceptions = st.sampled_from([ImportError, ModuleNotFoundError])

# Strategy for error messages
error_messages = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=100,
)

# Strategy for number of working plugins alongside the failing one
num_working_plugins = st.integers(min_value=0, max_value=5)


# --- Property 12: Protocol compliance ---


class TestProtocolCompliance:
    """Property 12: an object with ``handle_event`` satisfies Surface; one with
    ``collect`` satisfies PromptCollector; missing the method fails. Neither
    protocol requires a ``name`` attribute.

    **Validates: Requirements 5.1, 5.2**
    """

    @settings(max_examples=100)
    @given(name_value=name_values, has_name=include_name)
    def test_handle_event_satisfies_surface(self, name_value: str, has_name: bool):
        cls = _make_surface_class(
            has_handle_event=True, has_name=has_name, name_value=name_value
        )
        assert isinstance(cls(), Surface)

    @settings(max_examples=100)
    @given(name_value=name_values, has_name=include_name)
    def test_missing_handle_event_fails_surface(self, name_value: str, has_name: bool):
        cls = _make_surface_class(
            has_handle_event=False, has_name=has_name, name_value=name_value
        )
        assert not isinstance(cls(), Surface)

    @settings(max_examples=100)
    @given(name_value=name_values, has_name=include_name)
    def test_collect_satisfies_prompt_collector(self, name_value: str, has_name: bool):
        cls = _make_collector_class(
            has_collect=True, has_name=has_name, name_value=name_value
        )
        assert isinstance(cls(), PromptCollector)

    @settings(max_examples=100)
    @given(name_value=name_values, has_name=include_name)
    def test_missing_collect_fails_prompt_collector(
        self, name_value: str, has_name: bool
    ):
        cls = _make_collector_class(
            has_collect=False, has_name=has_name, name_value=name_value
        )
        assert not isinstance(cls(), PromptCollector)


# --- Property 33: Entry-point load failure logged and skipped ---


class TestEntryPointLoadFailureResilience:
    """Property 33: For any plugin entry-point that fails to load (ImportError,
    missing dependency), the core logs a warning and continues loading remaining
    plugins without raising.

    **Validates: Requirements 27.8**
    """

    @settings(max_examples=50)
    @given(
        ep_name=entry_point_names,
        exc_type=load_failure_exceptions,
        err_msg=error_messages,
    )
    def test_import_error_logged_and_skipped(
        self, ep_name: str, exc_type: type, err_msg: str
    ):
        """**Validates: Requirements 27.8**

        For any entry-point that raises ImportError or ModuleNotFoundError
        on load, the loader logs a warning and does not raise.
        """
        mock_ep = MagicMock()
        mock_ep.name = ep_name
        exc = exc_type(err_msg)
        exc.name = err_msg  # ImportError has a .name attribute
        mock_ep.load.side_effect = exc

        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        plugin_logger = logging.getLogger("functualize._plugins.loader")
        plugin_logger.addHandler(handler)
        original_level = plugin_logger.level
        plugin_logger.setLevel(logging.DEBUG)

        try:
            with patch(
                "functualize._plugins.loader.entry_points", return_value=[mock_ep]
            ):
                loader = PluginLoader()
                app = MagicMock()
                # Ensure load_all does not raise
                loader.load_all(app)

            # Plugin should NOT be loaded
            assert loader.loaded_plugins == {}
            # A warning should be logged
            warning_records = [r for r in log_records if r.levelno >= logging.WARNING]
            assert len(warning_records) > 0, (
                f"Expected a warning to be logged for failed entry-point '{ep_name}'"
            )
            # Warning should mention the plugin name
            log_text = " ".join(r.getMessage() for r in warning_records)
            assert ep_name in log_text, (
                f"Warning should mention entry-point name '{ep_name}'. Got: {log_text}"
            )
        finally:
            plugin_logger.removeHandler(handler)
            plugin_logger.setLevel(original_level)

    @settings(max_examples=50)
    @given(
        failing_ep_name=entry_point_names,
        exc_type=load_failure_exceptions,
        err_msg=error_messages,
        n_working=num_working_plugins,
    )
    def test_remaining_plugins_loaded_after_failure(
        self,
        failing_ep_name: str,
        exc_type: type,
        err_msg: str,
        n_working: int,
    ):
        """**Validates: Requirements 27.8**

        For any entry-point that fails to load, the remaining plugins in
        the discovery list are still loaded successfully.
        """
        # Create the failing entry point
        failing_ep = MagicMock()
        failing_ep.name = failing_ep_name
        exc = exc_type(err_msg)
        exc.name = err_msg
        failing_ep.load.side_effect = exc

        # Create working entry points with unique names
        working_eps = []
        working_plugins = []
        for i in range(n_working):
            plugin = MagicMock()
            plugin.name = f"working-plugin-{i}"
            plugin.version = "1.0.0"
            plugin.description = f"Working plugin {i}"
            # Ensure no config declaration attributes
            del plugin.config_model
            del plugin.config_section
            del plugin.depends_on

            ep = MagicMock()
            ep.name = f"working-ep-{i}"
            ep.load.return_value = plugin
            working_eps.append(ep)
            working_plugins.append(plugin)

        # Put the failing one first so subsequent ones must still load
        all_eps = [failing_ep] + working_eps

        with patch("functualize._plugins.loader.entry_points", return_value=all_eps):
            loader = PluginLoader()
            app = MagicMock()
            loader.load_all(app)

        # The failing plugin should not be loaded
        assert failing_ep_name not in loader.loaded_plugins

        # All working plugins should be loaded
        for i in range(n_working):
            expected_name = f"working-plugin-{i}"
            assert expected_name in loader.loaded_plugins, (
                f"Working plugin '{expected_name}' should still be loaded "
                f"after '{failing_ep_name}' failed"
            )

    @settings(max_examples=50)
    @given(
        ep_name=entry_point_names,
        err_msg=error_messages,
    )
    def test_general_exception_on_load_also_skipped(self, ep_name: str, err_msg: str):
        """**Validates: Requirements 27.8**

        Entry-points that raise any exception during load are skipped
        with a warning, not just ImportError.
        """
        mock_ep = MagicMock()
        mock_ep.name = ep_name
        mock_ep.load.side_effect = Exception(err_msg)

        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        plugin_logger = logging.getLogger("functualize._plugins.loader")
        plugin_logger.addHandler(handler)
        original_level = plugin_logger.level
        plugin_logger.setLevel(logging.DEBUG)

        try:
            with patch(
                "functualize._plugins.loader.entry_points", return_value=[mock_ep]
            ):
                loader = PluginLoader()
                app = MagicMock()
                # Should not raise
                loader.load_all(app)

            # Plugin should NOT be loaded
            assert loader.loaded_plugins == {}
            # A warning should be logged
            warning_records = [r for r in log_records if r.levelno >= logging.WARNING]
            assert len(warning_records) > 0
            log_text = " ".join(r.getMessage() for r in warning_records)
            assert ep_name in log_text
        finally:
            plugin_logger.removeHandler(handler)
            plugin_logger.setLevel(original_level)

    @settings(max_examples=30)
    @given(
        n_failing=st.integers(min_value=1, max_value=4),
        n_working=num_working_plugins,
    )
    def test_multiple_failures_all_logged_remaining_loaded(
        self, n_failing: int, n_working: int
    ):
        """**Validates: Requirements 27.8**

        When multiple entry-points fail to load, each failure is logged
        independently and remaining valid plugins still load.
        """
        # Create multiple failing entry points
        failing_eps = []
        for i in range(n_failing):
            ep = MagicMock()
            ep.name = f"failing-ep-{i}"
            exc = ImportError(f"missing-dep-{i}")
            exc.name = f"missing-dep-{i}"
            ep.load.side_effect = exc
            failing_eps.append(ep)

        # Create working entry points
        working_eps = []
        for i in range(n_working):
            plugin = MagicMock()
            plugin.name = f"ok-plugin-{i}"
            plugin.version = "1.0.0"
            plugin.description = f"OK plugin {i}"
            del plugin.config_model
            del plugin.config_section
            del plugin.depends_on

            ep = MagicMock()
            ep.name = f"ok-ep-{i}"
            ep.load.return_value = plugin
            working_eps.append(ep)

        all_eps = failing_eps + working_eps

        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        plugin_logger = logging.getLogger("functualize._plugins.loader")
        plugin_logger.addHandler(handler)
        original_level = plugin_logger.level
        plugin_logger.setLevel(logging.DEBUG)

        try:
            with patch(
                "functualize._plugins.loader.entry_points", return_value=all_eps
            ):
                loader = PluginLoader()
                app = MagicMock()
                loader.load_all(app)

            # All working plugins should load
            for i in range(n_working):
                assert f"ok-plugin-{i}" in loader.loaded_plugins

            # Each failing EP should generate a warning
            warning_records = [r for r in log_records if r.levelno >= logging.WARNING]
            warning_text = " ".join(r.getMessage() for r in warning_records)
            for i in range(n_failing):
                assert f"failing-ep-{i}" in warning_text, (
                    f"Expected warning for 'failing-ep-{i}' in: {warning_text}"
                )
        finally:
            plugin_logger.removeHandler(handler)
            plugin_logger.setLevel(original_level)
