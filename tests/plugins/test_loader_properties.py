"""Property-based tests for Plugin Metadata Protocol Validation.

Tests Property 28 (Plugin Metadata Protocol Validation) using Hypothesis.
"""

import logging
from unittest.mock import MagicMock, patch

from hypothesis import assume, given
from hypothesis import strategies as st

from functualize._plugins.loader import (
    PluginLoader,
    _validate_metadata,
    _validate_pep440,
)

# --- Strategies ---

# Strategy for valid PEP 440 versions
_pep440_release = st.tuples(
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}")

_pep440_pre = st.one_of(
    st.just(""),
    st.tuples(
        st.sampled_from(["a", "b", "rc"]),
        st.integers(min_value=0, max_value=9),
    ).map(lambda t: f"{t[0]}{t[1]}"),
)

_pep440_post = st.one_of(
    st.just(""),
    st.integers(min_value=0, max_value=9).map(lambda n: f".post{n}"),
)

_pep440_dev = st.one_of(
    st.just(""),
    st.integers(min_value=0, max_value=9).map(lambda n: f".dev{n}"),
)

valid_pep440_versions = st.builds(
    lambda release, pre, post, dev: f"{release}{pre}{post}{dev}",
    release=_pep440_release,
    pre=_pep440_pre,
    post=_pep440_post,
    dev=_pep440_dev,
)

# Strategy for valid plugin names (≤64 chars)
valid_plugin_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=1,
    max_size=64,
)

# Strategy for valid plugin descriptions (≤256 chars)
valid_plugin_descriptions = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        whitelist_characters=" .,!?-_:;",
    ),
    min_size=0,
    max_size=256,
)

# Strategy for invalid names (too long)
invalid_long_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=65,
    max_size=128,
)

# Strategy for invalid descriptions (too long)
invalid_long_descriptions = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=257,
    max_size=512,
)

# Strategy for invalid PEP 440 versions
invalid_versions = st.one_of(
    st.just(""),
    st.just("v1.0.0"),
    st.just("01.0.0"),
    st.just("abc"),
    st.just("1.0.0.0.0.invalid"),
    st.text(
        alphabet=st.characters(whitelist_categories=("L",)),
        min_size=1,
        max_size=10,
    ).filter(lambda s: not _validate_pep440(s)),
)


# --- Property 28: Plugin Metadata Protocol Validation ---
# Feature: functualize, Property 28: Plugin Metadata Protocol Validation


class TestPluginMetadataProtocolValidation:
    """Property 28: For any discovered plugin, the framework SHALL verify it satisfies
    the PluginMetadata protocol (name ≤ 64 chars, version conforming to PEP 440,
    description ≤ 256 chars). Plugins failing validation SHALL be skipped with a
    logged warning.

    **Validates: Requirements 10.5, 10.6**
    """

    @given(
        name=valid_plugin_names,
        version=valid_pep440_versions,
        description=valid_plugin_descriptions,
    )
    def test_valid_metadata_passes_validation(
        self, name: str, version: str, description: str
    ):
        # Feature: functualize, Property 28: Plugin Metadata Protocol Validation
        """Plugins with valid metadata (name ≤64 chars, PEP 440 version,
        description ≤256 chars) pass validation with no errors."""
        plugin = MagicMock()
        plugin.name = name
        plugin.version = version
        plugin.description = description

        errors = _validate_metadata(plugin, "test-ep")
        assert errors == [], f"Expected no errors for valid metadata, got: {errors}"

    @given(
        name=invalid_long_names,
        version=valid_pep440_versions,
        description=valid_plugin_descriptions,
    )
    def test_name_exceeding_64_chars_fails_validation(
        self, name: str, version: str, description: str
    ):
        # Feature: functualize, Property 28: Plugin Metadata Protocol Validation
        """Plugins with name exceeding 64 characters fail validation."""
        plugin = MagicMock()
        plugin.name = name
        plugin.version = version
        plugin.description = description

        errors = _validate_metadata(plugin, "test-ep")
        assert len(errors) > 0
        assert any("exceeds 64 characters" in e for e in errors)

    @given(
        name=valid_plugin_names,
        version=invalid_versions,
        description=valid_plugin_descriptions,
    )
    def test_invalid_pep440_version_fails_validation(
        self, name: str, version: str, description: str
    ):
        # Feature: functualize, Property 28: Plugin Metadata Protocol Validation
        """Plugins with non-PEP 440 conformant version fail validation."""
        assume(not _validate_pep440(version))

        plugin = MagicMock()
        plugin.name = name
        plugin.version = version
        plugin.description = description

        errors = _validate_metadata(plugin, "test-ep")
        assert len(errors) > 0
        assert any("PEP 440" in e for e in errors)

    @given(
        name=valid_plugin_names,
        version=valid_pep440_versions,
        description=invalid_long_descriptions,
    )
    def test_description_exceeding_256_chars_fails_validation(
        self, name: str, version: str, description: str
    ):
        # Feature: functualize, Property 28: Plugin Metadata Protocol Validation
        """Plugins with description exceeding 256 characters fail validation."""
        plugin = MagicMock()
        plugin.name = name
        plugin.version = version
        plugin.description = description

        errors = _validate_metadata(plugin, "test-ep")
        assert len(errors) > 0
        assert any("exceeds 256 characters" in e for e in errors)

    @given(
        missing_attrs=st.lists(
            st.sampled_from(["name", "version", "description"]),
            min_size=1,
            max_size=3,
            unique=True,
        ),
    )
    def test_missing_attributes_fail_validation(self, missing_attrs: list[str]):
        # Feature: functualize, Property 28: Plugin Metadata Protocol Validation
        """Plugins missing any required metadata attribute fail validation."""
        # Create a plugin with only the attributes NOT in missing_attrs
        all_attrs = {
            "name": "valid-plugin",
            "version": "1.0.0",
            "description": "A plugin",
        }
        present_attrs = {k: v for k, v in all_attrs.items() if k not in missing_attrs}

        plugin = MagicMock(spec=list(present_attrs.keys()))
        for k, v in present_attrs.items():
            setattr(plugin, k, v)
        # Ensure missing attrs are truly absent
        for attr in missing_attrs:
            if hasattr(plugin, attr):
                delattr(plugin, attr)

        errors = _validate_metadata(plugin, "test-ep")
        assert len(errors) >= len(missing_attrs)
        for attr in missing_attrs:
            assert any(f"missing '{attr}'" in e for e in errors), (
                f"Expected error for missing '{attr}', got: {errors}"
            )

    @given(
        name=valid_plugin_names,
        version=valid_pep440_versions,
        description=valid_plugin_descriptions,
    )
    def test_valid_plugin_is_loaded_successfully(
        self, name: str, version: str, description: str
    ):
        # Feature: functualize, Property 28: Plugin Metadata Protocol Validation
        """Plugins satisfying the metadata protocol are loaded and their registration
        callable is invoked with the app instance."""
        mock_plugin = MagicMock()
        mock_plugin.name = name
        mock_plugin.version = version
        mock_plugin.description = description

        mock_ep = MagicMock()
        mock_ep.name = "test-ep"
        mock_ep.load.return_value = mock_plugin

        with patch("functualize._plugins.loader.entry_points", return_value=[mock_ep]):
            loader = PluginLoader()
            app = MagicMock()
            loader.load_all(app)

        # Plugin should be loaded and called
        mock_plugin.assert_called_once_with(app)
        assert name in loader.loaded_plugins

    @given(
        name=invalid_long_names,
        version=valid_pep440_versions,
        description=valid_plugin_descriptions,
    )
    def test_invalid_plugin_is_skipped_with_warning(
        self, name: str, version: str, description: str
    ):
        # Feature: functualize, Property 28: Plugin Metadata Protocol Validation
        """Plugins failing metadata validation are skipped and a warning is logged
        identifying the entry point and the invalid attributes."""
        mock_plugin = MagicMock()
        mock_plugin.name = name
        mock_plugin.version = version
        mock_plugin.description = description

        mock_ep = MagicMock()
        mock_ep.name = "invalid-ep"
        mock_ep.load.return_value = mock_plugin

        # Set up log capture
        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        plugin_logger = logging.getLogger("functualize._plugins.loader")
        plugin_logger.addHandler(handler)
        plugin_logger.setLevel(logging.WARNING)

        try:
            with patch(
                "functualize._plugins.loader.entry_points", return_value=[mock_ep]
            ):
                loader = PluginLoader()
                app = MagicMock()
                loader.load_all(app)

            # Plugin should NOT be loaded
            assert loader.loaded_plugins == {}
            # Plugin registration callable should NOT be invoked
            mock_plugin.assert_not_called()
            # Warning should identify the entry point
            log_text = " ".join(r.getMessage() for r in log_records)
            assert "invalid-ep" in log_text
            assert "does not satisfy metadata protocol" in log_text
        finally:
            plugin_logger.removeHandler(handler)
