"""Property-based tests for plugin config immutable access via RunContext.

Property 6: Plugin Config Immutable Access via RunContext
**Validates: Requirements 3.1, 3.2, 3.3, 3.5**
"""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from functualize._config.job_config import JobConfigView
from functualize.job.context import RunContext

# --- Strategies ---

# Strategy for valid config section names (dot-separated identifiers)
section_names = st.from_regex(
    r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){0,2}", fullmatch=True
)

# Strategy for valid job names
job_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd")),
    min_size=1,
    max_size=30,
)


# --- Dynamic model generation ---


class DynamicConfigA(BaseModel):
    """A sample config model with string and int fields."""

    name: str = "default"
    value: int = 0
    enabled: bool = True


class DynamicConfigB(BaseModel):
    """Another config model with different fields."""

    endpoint: str = "http://localhost"
    retries: int = 3
    verbose: bool = False


class DynamicConfigC(BaseModel):
    """Third config model for diversity."""

    api_key: str = "key-123"
    timeout: float = 30.0


# Strategy that picks a model class and generates valid values for it
config_model_strategy = st.sampled_from(
    [DynamicConfigA, DynamicConfigB, DynamicConfigC]
)


@st.composite
def plugin_config_entries(draw: st.DrawFn) -> dict[str, BaseModel]:
    """Generate a mapping of section names to config model instances."""
    num_entries = draw(st.integers(min_value=1, max_value=5))
    sections = draw(
        st.lists(section_names, min_size=num_entries, max_size=num_entries, unique=True)
    )
    entries: dict[str, BaseModel] = {}
    for section in sections:
        model_cls = draw(config_model_strategy)
        instance: BaseModel
        if model_cls is DynamicConfigA:
            instance = DynamicConfigA(
                name=draw(st.text(min_size=1, max_size=20)),
                value=draw(st.integers(min_value=-1000, max_value=1000)),
                enabled=draw(st.booleans()),
            )
        elif model_cls is DynamicConfigB:
            instance = DynamicConfigB(
                endpoint=draw(st.text(min_size=1, max_size=50)),
                retries=draw(st.integers(min_value=0, max_value=10)),
                verbose=draw(st.booleans()),
            )
        else:
            instance = DynamicConfigC(
                api_key=draw(st.text(min_size=1, max_size=30)),
                timeout=draw(
                    st.floats(min_value=0.1, max_value=300.0, allow_nan=False)
                ),
            )
        entries[section] = instance
    return entries


# --- Helpers ---


def make_run_context(
    name: str = "test-job",
    plugin_configs: dict[str, BaseModel] | None = None,
) -> RunContext:
    """Create a RunContext with mocked dependencies."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock()
    return RunContext(
        name=name,
        config=mock_config,
        logger=mock_logger,
        plugin_configs=plugin_configs,
    )


# Feature: functualize, Property 6: Plugin Config Immutable Access via RunContext
# For any set of registered plugin configs, RunContext.plugin_configs always returns
# a MappingProxyType (read-only), get_plugin_config(section) returns the correct model
# for registered sections, raises KeyError for unknown sections, the mapping is immutable,
# and empty mapping is returned when no plugins are registered.
# **Validates: Requirements 3.1, 3.2, 3.3, 3.5**


class TestPluginConfigsReturnsMappingProxy:
    """plugin_configs always returns a MappingProxyType (read-only).

    **Validates: Requirements 3.1, 3.5**
    """

    @given(configs=plugin_config_entries())
    def test_plugin_configs_is_mapping_proxy_type(
        self, configs: dict[str, BaseModel]
    ) -> None:
        """For any registered configs, plugin_configs returns MappingProxyType."""
        # **Validates: Requirements 3.1**
        rc = make_run_context(plugin_configs=configs)
        result = rc.plugin_configs
        assert isinstance(result, MappingProxyType)

    @given(name=job_names)
    def test_plugin_configs_is_mapping_proxy_when_empty(self, name: str) -> None:
        """When no plugins registered, plugin_configs still returns MappingProxyType."""
        # **Validates: Requirements 3.1, 3.5**
        rc = make_run_context(name=name, plugin_configs=None)
        result = rc.plugin_configs
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0


class TestGetPluginConfigReturnsCorrectModel:
    """get_plugin_config(section) returns the correct model instance.

    **Validates: Requirements 3.2**
    """

    @given(configs=plugin_config_entries())
    def test_get_plugin_config_returns_registered_instance(
        self, configs: dict[str, BaseModel]
    ) -> None:
        """For any registered section, get_plugin_config returns the exact instance."""
        # **Validates: Requirements 3.2**
        rc = make_run_context(plugin_configs=configs)
        for section, expected_model in configs.items():
            result = rc.get_plugin_config(section)
            assert result is expected_model

    @given(configs=plugin_config_entries())
    def test_get_plugin_config_correct_type(
        self, configs: dict[str, BaseModel]
    ) -> None:
        """For any registered section, the returned model is the correct type."""
        # **Validates: Requirements 3.2**
        rc = make_run_context(plugin_configs=configs)
        for section, expected_model in configs.items():
            result = rc.get_plugin_config(section)
            assert type(result) is type(expected_model)


class TestGetPluginConfigRaisesKeyError:
    """get_plugin_config(section) raises KeyError for unknown sections.

    **Validates: Requirements 3.3**
    """

    @given(
        configs=plugin_config_entries(),
        unknown_section=st.from_regex(r"unknown\.[a-z][a-z0-9_]*", fullmatch=True),
    )
    def test_raises_key_error_for_unknown_section(
        self, configs: dict[str, BaseModel], unknown_section: str
    ) -> None:
        """For any section not in configs, get_plugin_config raises KeyError."""
        # **Validates: Requirements 3.3**
        # Ensure the unknown section is truly not registered
        if unknown_section in configs:
            return  # Skip (extremely unlikely due to namespace prefix)
        rc = make_run_context(plugin_configs=configs)
        with pytest.raises(KeyError, match="No plugin config for section"):
            rc.get_plugin_config(unknown_section)

    @given(
        configs=plugin_config_entries(),
        unknown_section=st.from_regex(r"unknown\.[a-z][a-z0-9_]*", fullmatch=True),
    )
    def test_error_message_lists_available_sections(
        self, configs: dict[str, BaseModel], unknown_section: str
    ) -> None:
        """KeyError message includes 'Available' with registered sections."""
        # **Validates: Requirements 3.3**
        if unknown_section in configs:
            return
        rc = make_run_context(plugin_configs=configs)
        with pytest.raises(KeyError, match="Available:"):
            rc.get_plugin_config(unknown_section)

    @given(name=job_names, unknown_section=section_names)
    def test_raises_key_error_when_no_plugins_registered(
        self, name: str, unknown_section: str
    ) -> None:
        """When no plugins are registered, any section lookup raises KeyError."""
        # **Validates: Requirements 3.3**
        rc = make_run_context(name=name, plugin_configs=None)
        with pytest.raises(KeyError):
            rc.get_plugin_config(unknown_section)


class TestPluginConfigsImmutability:
    """The mapping is immutable — no assignment, no deletion from outside.

    **Validates: Requirements 3.5**
    """

    @given(configs=plugin_config_entries())
    def test_cannot_assign_to_mapping(self, configs: dict[str, BaseModel]) -> None:
        """Assignment to plugin_configs mapping raises TypeError."""
        # **Validates: Requirements 3.5**
        rc = make_run_context(plugin_configs=configs)
        mapping = rc.plugin_configs
        with pytest.raises(TypeError):
            mapping["new.section"] = DynamicConfigA()  # type: ignore[index]

    @given(configs=plugin_config_entries())
    def test_cannot_delete_from_mapping(self, configs: dict[str, BaseModel]) -> None:
        """Deletion from plugin_configs mapping raises TypeError."""
        # **Validates: Requirements 3.5**
        rc = make_run_context(plugin_configs=configs)
        mapping = rc.plugin_configs
        section = next(iter(configs))
        with pytest.raises(TypeError):
            del mapping[section]  # type: ignore[attr-defined]

    @given(configs=plugin_config_entries())
    def test_mapping_has_no_mutating_methods(
        self, configs: dict[str, BaseModel]
    ) -> None:
        """MappingProxyType does not expose pop, update, clear, setdefault."""
        # **Validates: Requirements 3.5**
        rc = make_run_context(plugin_configs=configs)
        mapping = rc.plugin_configs
        assert not hasattr(mapping, "pop")
        assert not hasattr(mapping, "update")
        assert not hasattr(mapping, "clear")
        assert not hasattr(mapping, "setdefault")


class TestEmptyMappingWhenNoPlugins:
    """Empty mapping returned when no plugins registered (no error).

    **Validates: Requirements 3.5**
    """

    @given(name=job_names)
    def test_empty_mapping_no_error(self, name: str) -> None:
        """Accessing plugin_configs with no plugins does not raise."""
        # **Validates: Requirements 3.5**
        rc = make_run_context(name=name, plugin_configs=None)
        result = rc.plugin_configs
        assert len(result) == 0
        assert isinstance(result, MappingProxyType)

    @given(name=job_names)
    def test_empty_mapping_is_iterable(self, name: str) -> None:
        """Empty plugin_configs mapping can be iterated without error."""
        # **Validates: Requirements 3.5**
        rc = make_run_context(name=name, plugin_configs=None)
        items = list(rc.plugin_configs.items())
        assert items == []
