"""Property-based tests for RunContext plugin config copy semantics.

Property 7: with_plugin_config Copy Semantics
**Validates: Requirements 4.1, 4.3**
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import BaseModel

from functualize._config.job_config import JobConfigView
from functualize.job.context import RunContext

# --- Test Config Models ---


class FlexibleConfig(BaseModel):
    """A plugin config model with multiple field types for property testing."""

    name: str = "default"
    count: int = 0
    ratio: float = 1.0
    enabled: bool = True


class AltConfig(BaseModel):
    """Another plugin config model for multi-section testing."""

    api_key: str = "key-default"
    max_retries: int = 3
    verbose: bool = False


# --- Strategies ---

# Strategy for valid section names (dotted identifiers)
section_names = st.from_regex(r"plugin\.[a-z][a-z0-9_]{0,20}", fullmatch=True)

# Strategy for valid string field values
config_strings = st.text(min_size=1, max_size=50)

# Strategy for valid int field values
config_ints = st.integers(min_value=0, max_value=10000)

# Strategy for valid float field values
config_floats = st.floats(
    min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
)

# Strategy for FlexibleConfig instances
flexible_configs = st.builds(
    FlexibleConfig,
    name=config_strings,
    count=config_ints,
    ratio=config_floats,
    enabled=st.booleans(),
)

# Strategy for AltConfig instances
alt_configs = st.builds(
    AltConfig,
    api_key=config_strings,
    max_retries=st.integers(min_value=0, max_value=100),
    verbose=st.booleans(),
)

# Strategy for override values for FlexibleConfig fields (at least one override)
flexible_overrides: st.SearchStrategy[dict[str, Any]] = st.fixed_dictionaries(
    {},
    optional={
        "name": config_strings,
        "count": config_ints,
        "ratio": config_floats,
        "enabled": st.booleans(),
    },
).filter(lambda d: len(d) > 0)


# --- Helpers ---


def make_run_context(
    plugin_configs: dict[str, BaseModel] | None = None,
) -> RunContext:
    """Create a RunContext with mocked dependencies and optional plugin configs."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock(spec=logging.Logger)
    return RunContext(
        name="test-job",
        config=mock_config,
        logger=mock_logger,
        plugin_configs=plugin_configs,
    )


# Feature: enriched-runcontext, Property 7: with_plugin_config Copy Semantics
# with_plugin_config returns a new RunContext instance (not the same object).
# The original RunContext's plugin_configs remain unmodified after calling
# with_plugin_config. Other plugin config sections are preserved in the new
# RunContext. The new RunContext has the overridden values correctly applied.
# **Validates: Requirements 4.1, 4.3**
class TestWithPluginConfigCopySemantics:
    """Property 7: with_plugin_config Copy Semantics."""

    @given(config=flexible_configs, overrides=flexible_overrides)
    def test_returns_new_instance(
        self,
        config: FlexibleConfig,
        overrides: dict[str, Any],
    ) -> None:
        """with_plugin_config returns a new RunContext instance (not the same object).

        **Validates: Requirements 4.1**
        """
        rc = make_run_context(plugin_configs={"plugin.test": config})
        new_rc = rc.with_plugin_config("plugin.test", **overrides)
        assert new_rc is not rc

    @given(config=flexible_configs, overrides=flexible_overrides)
    def test_original_plugin_configs_unmodified(
        self,
        config: FlexibleConfig,
        overrides: dict[str, Any],
    ) -> None:
        """The original RunContext's plugin_configs remain unmodified after calling
        with_plugin_config.

        **Validates: Requirements 4.3**
        """
        rc = make_run_context(plugin_configs={"plugin.test": config})

        # Snapshot original values before override
        original_name = config.name
        original_count = config.count
        original_ratio = config.ratio
        original_enabled = config.enabled

        # Perform override
        rc.with_plugin_config("plugin.test", **overrides)

        # Verify original config object unchanged
        original_config = rc.get_plugin_config("plugin.test")
        assert isinstance(original_config, FlexibleConfig)
        assert original_config.name == original_name
        assert original_config.count == original_count
        assert original_config.ratio == original_ratio
        assert original_config.enabled == original_enabled

    @given(
        main_config=flexible_configs,
        alt_config=alt_configs,
        overrides=flexible_overrides,
        alt_section=section_names,
    )
    def test_other_sections_preserved(
        self,
        main_config: FlexibleConfig,
        alt_config: AltConfig,
        overrides: dict[str, Any],
        alt_section: str,
    ) -> None:
        """Other plugin config sections are preserved in the new RunContext.

        **Validates: Requirements 4.3**
        """
        assume(alt_section != "plugin.test")

        configs: dict[str, BaseModel] = {
            "plugin.test": main_config,
            alt_section: alt_config,
        }
        rc = make_run_context(plugin_configs=configs)

        new_rc = rc.with_plugin_config("plugin.test", **overrides)

        # The other section should be preserved identically
        preserved = new_rc.get_plugin_config(alt_section)
        assert preserved is alt_config  # Same object reference
        assert isinstance(preserved, AltConfig)
        assert preserved.api_key == alt_config.api_key
        assert preserved.max_retries == alt_config.max_retries
        assert preserved.verbose == alt_config.verbose

    @given(config=flexible_configs, overrides=flexible_overrides)
    def test_overridden_values_correctly_applied(
        self,
        config: FlexibleConfig,
        overrides: dict[str, Any],
    ) -> None:
        """The new RunContext has the overridden values correctly applied.

        **Validates: Requirements 4.1**
        """
        rc = make_run_context(plugin_configs={"plugin.test": config})
        new_rc = rc.with_plugin_config("plugin.test", **overrides)

        new_config = new_rc.get_plugin_config("plugin.test")
        assert isinstance(new_config, FlexibleConfig)

        # All override values must be applied
        for field_name, override_value in overrides.items():
            assert getattr(new_config, field_name) == override_value

    @given(config=flexible_configs, overrides=flexible_overrides)
    def test_non_overridden_fields_preserved_in_new(
        self,
        config: FlexibleConfig,
        overrides: dict[str, Any],
    ) -> None:
        """Fields not included in overrides retain their original values in the new
        RunContext.

        **Validates: Requirements 4.1**
        """
        rc = make_run_context(plugin_configs={"plugin.test": config})
        new_rc = rc.with_plugin_config("plugin.test", **overrides)

        new_config = new_rc.get_plugin_config("plugin.test")
        assert isinstance(new_config, FlexibleConfig)
        all_fields = {"name", "count", "ratio", "enabled"}
        non_overridden = all_fields - set(overrides.keys())

        for field_name in non_overridden:
            assert getattr(new_config, field_name) == getattr(config, field_name)

    @given(
        config=flexible_configs,
        alt_config=alt_configs,
        overrides=flexible_overrides,
    )
    def test_original_mapping_size_unchanged(
        self,
        config: FlexibleConfig,
        alt_config: AltConfig,
        overrides: dict[str, Any],
    ) -> None:
        """The original RunContext's plugin_configs mapping has unchanged size after
        with_plugin_config.

        **Validates: Requirements 4.3**
        """
        configs: dict[str, BaseModel] = {
            "plugin.test": config,
            "plugin.other": alt_config,
        }
        rc = make_run_context(plugin_configs=configs)

        original_size = len(rc.plugin_configs)
        rc.with_plugin_config("plugin.test", **overrides)

        assert len(rc.plugin_configs) == original_size
