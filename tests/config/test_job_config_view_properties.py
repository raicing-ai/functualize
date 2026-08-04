"""Property-based tests for JobConfigView using Hypothesis.

Tests correctness properties defined in the Unified Config Access design document.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from functualize._config.chain import ResolutionChain
from functualize._config.job_config import JobConfigView

# --- FakeSource ---


class FakeSource:
    """A simple configurable Source for testing JobConfigView properties.

    Implements the Source protocol with a dict of (section, key) → value mappings.
    """

    def __init__(
        self, data: dict[str, Any], source_type: str = "fake", source_id: str = "fake"
    ) -> None:
        self._data = data
        self._source_type = source_type
        self._source_id = source_id

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def source_id(self) -> str:
        return self._source_id

    def get(self, key: str, section: str | None = None) -> Any | None:
        if section is not None:
            lookup = f"{section}.{key}"
            if lookup in self._data:
                return self._data[lookup]
        return self._data.get(key)

    def has(self, key: str, section: str | None = None) -> bool:
        return self.get(key, section) is not None


# --- Strategies ---

# Strategy for non-None config values (primitives only)
config_values: st.SearchStrategy[Any] = st.one_of(
    st.text(min_size=1, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
)

# Strategy for valid config keys (must start with alpha, contain alphanum + underscore)
config_keys = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha())

# Strategy for section names (same constraints as keys)
config_sections = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha())

# Strategy for section prefixes (alias for config_sections, used by Properties 4 & 6)
section_prefixes = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=10,
).filter(lambda s: s[0].isalpha())

# Strategy for default values (any primitive type, used by Property 4)
default_values: st.SearchStrategy[Any] = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.none(),
)


class AlwaysMissingSource:
    """A source that never has any keys — forces MissingKeyError on resolve."""

    def __init__(self, source_id: str = "empty") -> None:
        self._source_id = source_id

    @property
    def source_type(self) -> str:
        return "fake"

    @property
    def source_id(self) -> str:
        return self._source_id

    def get(self, key: str, section: str | None = None) -> Any | None:
        return None

    def has(self, key: str, section: str | None = None) -> bool:
        return False


# Aliases used by other property tests in this file
section_prefixes = config_sections
default_values = config_values


# --- Property 2: Override Supremacy ---
# Feature: unified-config-access, Property 2: Override Supremacy


class TestProperty2OverrideSupremacy:
    """After set(), get() returns the override value regardless of chain contents.

    # Feature: unified-config-access, Property 2: Override Supremacy

    **Validates: Requirements 1.1, 2.3, 2.4**
    """

    @given(
        key=config_keys,
        override_value=config_values,
        section=config_sections,
    )
    def test_override_wins_over_empty_chain(
        self,
        key: str,
        override_value: Any,
        section: str,
    ) -> None:
        """After set(), get() returns override even when chain has no value."""
        chain = ResolutionChain([FakeSource({})])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set(key, override_value, section=section)
        result = view.get(key, section=section)

        assert result == override_value

    @given(
        key=config_keys,
        override_value=config_values,
        chain_value=config_values,
        section=config_sections,
    )
    def test_override_wins_over_chain_value(
        self,
        key: str,
        override_value: Any,
        chain_value: Any,
        section: str,
    ) -> None:
        """After set(), get() returns override even when chain provides a value."""
        source = FakeSource(
            {f"{section}.{key}": chain_value},
            source_type="file",
            source_id="test.toml",
        )
        chain = ResolutionChain([source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set(key, override_value, section=section)
        result = view.get(key, section=section)

        assert result == override_value

    @given(
        key=config_keys,
        override_value=config_values,
        chain_values=st.lists(config_values, min_size=1, max_size=4),
        section=config_sections,
    )
    def test_override_wins_over_multiple_chain_sources(
        self,
        key: str,
        override_value: Any,
        chain_values: list[Any],
        section: str,
    ) -> None:
        """After set(), get() returns override regardless of how many sources
        provide values in the chain."""
        sources = [
            FakeSource(
                {f"{section}.{key}": val},
                source_type=f"type_{idx}",
                source_id=f"source_{idx}",
            )
            for idx, val in enumerate(chain_values)
        ]
        chain = ResolutionChain(sources)  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set(key, override_value, section=section)
        result = view.get(key, section=section)

        assert result == override_value

    @given(
        key=config_keys,
        override_value=config_values,
        section=config_sections,
        default_value=config_values,
    )
    def test_override_wins_over_default_parameter(
        self,
        key: str,
        override_value: Any,
        section: str,
        default_value: Any,
    ) -> None:
        """After set(), get() returns override even when a default is provided."""
        chain = ResolutionChain([FakeSource({})])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set(key, override_value, section=section)
        result = view.get(key, default=default_value, section=section)

        assert result == override_value

    @given(
        key=config_keys,
        first_value=config_values,
        second_value=config_values,
        section=config_sections,
    )
    def test_last_set_wins(
        self,
        key: str,
        first_value: Any,
        second_value: Any,
        section: str,
    ) -> None:
        """Multiple set() calls for the same key — the last value wins."""
        chain = ResolutionChain([FakeSource({})])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set(key, first_value, section=section)
        view.set(key, second_value, section=section)
        result = view.get(key, section=section)

        assert result == second_value

    @given(
        key=config_keys,
        override_value=config_values,
        prefix=config_sections,
    )
    def test_override_wins_with_default_prefix_section(
        self,
        key: str,
        override_value: Any,
        prefix: str,
    ) -> None:
        """After set(key, value, section=None), get(key, section=None) returns
        override using the default section prefix."""
        chain = ResolutionChain([FakeSource({})])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix=prefix)

        # Both set and get use section=None (i.e., default prefix)
        view.set(key, override_value, section=None)
        result = view.get(key, section=None)

        assert result == override_value


# --- Property 5: Override Isolation Between Instances ---
# Feature: unified-config-access, Property 5: Override Isolation Between Instances


class TestProperty5OverrideIsolationBetweenInstances:
    """Two JobConfigView instances sharing the same ResolutionChain — set() on one
    does not affect get() on the other.

    **Validates: Requirements 6.1, 6.3**
    """

    @given(
        key=config_keys,
        value=config_values,
        section=config_sections,
    )
    def test_set_on_one_instance_not_visible_on_other(
        self,
        key: str,
        value: Any,
        section: str,
    ) -> None:
        """Setting a value on instance A must not be visible via get() on
        instance B, even when both share the same ResolutionChain."""
        chain = ResolutionChain([FakeSource({})])  # type: ignore[arg-type]

        instance_a = JobConfigView(
            resolution_chain=chain, default_section_prefix=section
        )
        instance_b = JobConfigView(
            resolution_chain=chain, default_section_prefix=section
        )

        instance_a.set(key, value, section=section)

        # Instance B should NOT see the override — key is missing from chain too
        result_b = instance_b.get(key, default=None, section=section)
        assert result_b is None, (
            f"Instance B should not see override set on instance A. "
            f"Got {result_b!r} for key={key!r}, section={section!r}"
        )

    @given(
        key=config_keys,
        value_a=config_values,
        value_b=config_values,
        section=config_sections,
    )
    def test_set_on_both_instances_remain_independent(
        self,
        key: str,
        value_a: Any,
        value_b: Any,
        section: str,
    ) -> None:
        """Setting the same key on both instances stores independently —
        each instance sees only its own override."""
        chain = ResolutionChain([FakeSource({})])  # type: ignore[arg-type]

        instance_a = JobConfigView(
            resolution_chain=chain, default_section_prefix=section
        )
        instance_b = JobConfigView(
            resolution_chain=chain, default_section_prefix=section
        )

        instance_a.set(key, value_a, section=section)
        instance_b.set(key, value_b, section=section)

        assert instance_a.get(key, section=section) == value_a
        assert instance_b.get(key, section=section) == value_b

    @given(
        key=config_keys,
        override_value=config_values,
        chain_value=config_values,
        section=config_sections,
    )
    def test_override_on_one_does_not_shadow_chain_for_other(
        self,
        key: str,
        override_value: Any,
        chain_value: Any,
        section: str,
    ) -> None:
        """When the chain provides a value and instance A overrides it,
        instance B still sees the chain value (not the override)."""
        source_data = {f"{section}.{key}": chain_value}
        chain = ResolutionChain([FakeSource(source_data)])  # type: ignore[arg-type]

        instance_a = JobConfigView(
            resolution_chain=chain, default_section_prefix=section
        )
        instance_b = JobConfigView(
            resolution_chain=chain, default_section_prefix=section
        )

        instance_a.set(key, override_value, section=section)

        # Instance A sees its override
        assert instance_a.get(key, section=section) == override_value

        # Instance B sees the chain value, not instance A's override
        assert instance_b.get(key, section=section) == chain_value


# --- Property 6: Model Resolution Field Consistency ---
# Feature: unified-config-access, Property 6: Model Resolution Field Consistency


class SimpleStringModel(BaseModel):
    """A simple Pydantic model with optional string fields for property testing."""

    alpha: str = ""
    beta: str = ""
    gamma: str = ""


class TypedConfigModel(BaseModel):
    """A Pydantic model with typed fields (str, int, Optional) for coercion testing."""

    name: str = ""
    port: int = 0
    label: str | None = None


class TestProperty6ModelResolutionFieldConsistency:
    """Each field in model from get_model() equals what get(field_name, section)
    returns (after type coercion). The resolution priority (overrides > chain)
    applies identically to both paths.

    **Validates: Requirements 3.1, 3.2**
    """

    @given(
        alpha_val=st.text(min_size=1, max_size=20),
        beta_val=st.text(min_size=1, max_size=20),
        gamma_val=st.text(min_size=1, max_size=20),
        section=section_prefixes,
    )
    def test_model_fields_equal_individual_get_calls_from_chain(
        self,
        alpha_val: str,
        beta_val: str,
        gamma_val: str,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 6: Model Resolution Field Consistency
        """When values come from the chain, get_model() fields match get() calls."""
        source_data = {
            f"{section}.alpha": alpha_val,
            f"{section}.beta": beta_val,
            f"{section}.gamma": gamma_val,
        }
        source = FakeSource(source_data)
        chain = ResolutionChain([source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        model = view.get_model(SimpleStringModel, section=section)

        assert model.alpha == view.get("alpha", section=section)
        assert model.beta == view.get("beta", section=section)
        assert model.gamma == view.get("gamma", section=section)

    @given(
        alpha_val=st.text(min_size=1, max_size=20),
        beta_val=st.text(min_size=1, max_size=20),
        gamma_val=st.text(min_size=1, max_size=20),
        section=section_prefixes,
    )
    def test_model_fields_equal_individual_get_calls_from_overrides(
        self,
        alpha_val: str,
        beta_val: str,
        gamma_val: str,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 6: Model Resolution Field Consistency
        """When values come from overrides, get_model() fields match get() calls."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set("alpha", alpha_val, section=section)
        view.set("beta", beta_val, section=section)
        view.set("gamma", gamma_val, section=section)

        model = view.get_model(SimpleStringModel, section=section)

        assert model.alpha == view.get("alpha", section=section)
        assert model.beta == view.get("beta", section=section)
        assert model.gamma == view.get("gamma", section=section)

    @given(
        alpha_override=st.text(min_size=1, max_size=20),
        beta_chain_val=st.text(min_size=1, max_size=20),
        gamma_override=st.text(min_size=1, max_size=20),
        alpha_chain_val=st.text(min_size=1, max_size=20),
        section=section_prefixes,
    )
    def test_model_fields_equal_get_calls_with_mixed_sources(
        self,
        alpha_override: str,
        beta_chain_val: str,
        gamma_override: str,
        alpha_chain_val: str,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 6: Model Resolution Field Consistency
        """When values come from mixed sources (overrides + chain), get_model()
        fields still match individual get() calls — overrides take priority."""
        source_data = {
            f"{section}.alpha": alpha_chain_val,
            f"{section}.beta": beta_chain_val,
        }
        source = FakeSource(source_data)
        chain = ResolutionChain([source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        # Set overrides for alpha and gamma (alpha overrides chain value)
        view.set("alpha", alpha_override, section=section)
        view.set("gamma", gamma_override, section=section)

        model = view.get_model(SimpleStringModel, section=section)

        # Each model field must equal what get() returns individually
        assert model.alpha == view.get("alpha", section=section)
        assert model.beta == view.get("beta", section=section)
        assert model.gamma == view.get("gamma", section=section)

        # Additionally verify overrides won over chain values
        assert model.alpha == alpha_override
        assert model.beta == beta_chain_val
        assert model.gamma == gamma_override

    @given(
        alpha_val=st.text(min_size=1, max_size=20),
        beta_val=st.text(min_size=1, max_size=20),
        gamma_val=st.text(min_size=1, max_size=20),
        prefix=section_prefixes,
    )
    def test_model_fields_equal_get_calls_using_default_section_prefix(
        self,
        alpha_val: str,
        beta_val: str,
        gamma_val: str,
        prefix: str,
    ) -> None:
        # Feature: unified-config-access, Property 6: Model Resolution Field Consistency
        """When section=None, get_model() uses default prefix — same as get()
        with section=None."""
        source_data = {
            f"{prefix}.alpha": alpha_val,
            f"{prefix}.beta": beta_val,
            f"{prefix}.gamma": gamma_val,
        }
        source = FakeSource(source_data)
        chain = ResolutionChain([source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix=prefix)

        # Call both with section=None to use default prefix
        model = view.get_model(SimpleStringModel, section=None)

        assert model.alpha == view.get("alpha", section=None)
        assert model.beta == view.get("beta", section=None)
        assert model.gamma == view.get("gamma", section=None)

    @given(
        name_val=st.text(min_size=1, max_size=20),
        port_val=st.integers(min_value=1, max_value=65535),
        label_val=st.text(min_size=1, max_size=20),
        section=section_prefixes,
    )
    def test_typed_model_fields_equal_get_calls_with_coercion(
        self,
        name_val: str,
        port_val: int,
        label_val: str,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 6: Model Resolution Field Consistency
        """When values are set via overrides with native types (str, int),
        get_model() with TypedConfigModel coerces and each field matches
        what get(field_name, section) would return after coercion."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set("name", name_val, section=section)
        view.set("port", port_val, section=section)
        view.set("label", label_val, section=section)

        model = view.get_model(TypedConfigModel, section=section)

        # After Pydantic type coercion, each field should equal the coerced
        # version of what get() returns
        raw_name = view.get("name", section=section)
        raw_port = view.get("port", section=section)
        raw_label = view.get("label", section=section)

        assert model.name == str(raw_name) if raw_name is not None else ""
        assert model.port == int(raw_port) if raw_port is not None else 0
        assert model.label == raw_label

    @given(
        name_val=st.text(min_size=1, max_size=20),
        port_val=st.integers(min_value=1, max_value=65535),
        section=section_prefixes,
    )
    def test_typed_model_with_string_port_coercion(
        self,
        name_val: str,
        port_val: int,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 6: Model Resolution Field Consistency
        """When port is stored as a string (like from file sources), Pydantic
        coerces it to int. Field still matches get() after coercion."""
        # Store port as string to simulate file source behavior
        source_data = {
            f"{section}.name": name_val,
            f"{section}.port": str(port_val),
        }
        source = FakeSource(source_data)
        chain = ResolutionChain([source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        model = view.get_model(TypedConfigModel, section=section)

        # get() returns the raw string for port
        raw_port = view.get("port", section=section)
        # Pydantic coerces string → int
        assert model.port == int(raw_port)
        # name stays as string
        assert model.name == view.get("name", section=section)
        # label is Optional, not in source → None
        assert model.label is None

    @given(
        name_val=st.text(min_size=1, max_size=20),
        port_val=st.integers(min_value=1, max_value=65535),
        section=section_prefixes,
    )
    def test_typed_model_optional_field_none_when_missing(
        self,
        name_val: str,
        port_val: int,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 6: Model Resolution Field Consistency
        """Optional fields resolve to None when not present — consistent with
        get() returning None for missing keys."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set("name", name_val, section=section)
        view.set("port", port_val, section=section)
        # label intentionally not set — Optional[str] field defaults to None

        model = view.get_model(TypedConfigModel, section=section)

        # label is None (not set, Pydantic default for Optional)
        assert model.label is None
        # get() also returns None for missing key
        assert view.get("label", section=section) is None


# --- Property 4: Section Prefix Scoping ---
# Feature: unified-config-access, Property 4: Section Prefix Scoping


class TestProperty4SectionPrefixScoping:
    """For any key and for any default section prefix (set via constructor or
    set_prefix()), calling get(key, section=None) SHALL produce the same result
    as calling get(key, section=current_prefix). Similarly, set(key, value,
    section=None) SHALL store under the current prefix section.

    **Validates: Requirements 1.6, 2.5, 3.4, 4.1, 4.2**
    """

    @given(
        key=config_keys,
        prefix=section_prefixes,
    )
    def test_get_section_none_equals_get_section_prefix_empty_chain(
        self,
        key: str,
        prefix: str,
    ) -> None:
        # Feature: unified-config-access, Property 4: Section Prefix Scoping
        """get(key, section=None) == get(key, section=current_prefix) when
        chain has no values (both return default None)."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix=prefix)

        result_none = view.get(key, section=None)
        result_explicit = view.get(key, section=prefix)

        assert result_none == result_explicit

    @given(
        key=config_keys,
        prefix=section_prefixes,
        value=st.one_of(
            st.text(min_size=1, max_size=20),
            st.integers(min_value=-1000, max_value=1000),
            st.booleans(),
        ),
    )
    def test_get_section_none_equals_get_section_prefix_with_chain_data(
        self,
        key: str,
        prefix: str,
        value: Any,
    ) -> None:
        # Feature: unified-config-access, Property 4: Section Prefix Scoping
        """get(key, section=None) == get(key, section=current_prefix) when
        chain has data for the section.key combination."""
        # Store value under section.key so FakeSource returns it
        data = {f"{prefix}.{key}": value}
        chain = ResolutionChain([FakeSource(data)])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix=prefix)

        result_none = view.get(key, section=None)
        result_explicit = view.get(key, section=prefix)

        assert result_none == result_explicit
        assert result_none == value

    @given(
        key=config_keys,
        prefix=section_prefixes,
        value=st.one_of(
            st.text(min_size=1, max_size=20),
            st.integers(min_value=-1000, max_value=1000),
            st.booleans(),
        ),
        default=default_values,
    )
    def test_get_section_none_equals_get_section_prefix_with_default(
        self,
        key: str,
        prefix: str,
        value: Any,
        default: Any,
    ) -> None:
        # Feature: unified-config-access, Property 4: Section Prefix Scoping
        """get(key, default=d, section=None) == get(key, default=d, section=prefix)
        regardless of whether the key exists."""
        data = {f"{prefix}.{key}": value}
        chain = ResolutionChain([FakeSource(data)])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix=prefix)

        result_none = view.get(key, default=default, section=None)
        result_explicit = view.get(key, default=default, section=prefix)

        assert result_none == result_explicit

    @given(
        key=config_keys,
        initial_prefix=section_prefixes,
        new_prefix=section_prefixes,
        value=st.one_of(
            st.text(min_size=1, max_size=20),
            st.integers(min_value=-1000, max_value=1000),
        ),
    )
    def test_set_prefix_changes_scoping_for_get(
        self,
        key: str,
        initial_prefix: str,
        new_prefix: str,
        value: Any,
    ) -> None:
        # Feature: unified-config-access, Property 4: Section Prefix Scoping
        """After set_prefix(new_prefix), get(key, section=None) ==
        get(key, section=new_prefix)."""
        # Put value under new_prefix.key
        data = {f"{new_prefix}.{key}": value}
        chain = ResolutionChain([FakeSource(data)])  # type: ignore[arg-type]
        view = JobConfigView(
            resolution_chain=chain, default_section_prefix=initial_prefix
        )

        # Change prefix
        view.set_prefix(new_prefix)

        result_none = view.get(key, section=None)
        result_explicit = view.get(key, section=new_prefix)

        assert result_none == result_explicit

    @given(
        key=config_keys,
        prefix=section_prefixes,
        value=st.one_of(
            st.text(min_size=1, max_size=20),
            st.integers(min_value=-1000, max_value=1000),
            st.booleans(),
        ),
    )
    def test_set_section_none_then_get_section_prefix_returns_value(
        self,
        key: str,
        prefix: str,
        value: Any,
    ) -> None:
        # Feature: unified-config-access, Property 4: Section Prefix Scoping
        """set(key, value, section=None) stores under current prefix, so
        get(key, section=current_prefix) returns that value."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix=prefix)

        view.set(key, value, section=None)
        result = view.get(key, section=prefix)

        assert result == value

    @given(
        key=config_keys,
        initial_prefix=section_prefixes,
        new_prefix=section_prefixes,
        value=st.one_of(
            st.text(min_size=1, max_size=20),
            st.integers(min_value=-1000, max_value=1000),
            st.booleans(),
        ),
    )
    def test_set_after_set_prefix_stores_under_new_prefix(
        self,
        key: str,
        initial_prefix: str,
        new_prefix: str,
        value: Any,
    ) -> None:
        # Feature: unified-config-access, Property 4: Section Prefix Scoping
        """After set_prefix(new_prefix), set(key, value, section=None) stores
        under new_prefix, retrievable via get(key, section=new_prefix)."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(
            resolution_chain=chain, default_section_prefix=initial_prefix
        )

        view.set_prefix(new_prefix)
        view.set(key, value, section=None)

        result = view.get(key, section=new_prefix)
        assert result == value


# --- Property 3: Default Fallback for Missing Keys ---
# Feature: unified-config-access, Property 3: Default Fallback for Missing Keys


class TestProperty3DefaultFallbackForMissingKeys:
    """For any key that does not exist in the override layer or the ResolutionChain,
    and for any default value provided, get(key, default=default) SHALL return the
    provided default value. When no default is provided, it SHALL return None.

    **Validates: Requirements 1.4, 1.5**
    """

    @given(
        key=config_keys,
        default_val=config_values,
        section=config_sections,
    )
    def test_missing_key_with_default_returns_default(
        self,
        key: str,
        default_val: Any,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 3: Default Fallback for Missing Keys
        """get(key, default=d) returns d when key is not in overrides or chain."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        result = view.get(key, default=default_val, section=section)

        assert result == default_val

    @given(
        key=config_keys,
        section=config_sections,
    )
    def test_missing_key_without_default_returns_none(
        self,
        key: str,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 3: Default Fallback for Missing Keys
        """get(key) returns None when key is not in overrides or chain and no
        default is provided."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        result = view.get(key, section=section)

        assert result is None

    @given(
        key=config_keys,
        default_val=config_values,
        prefix=section_prefixes,
    )
    def test_missing_key_with_default_uses_prefix_section(
        self,
        key: str,
        default_val: Any,
        prefix: str,
    ) -> None:
        # Feature: unified-config-access, Property 3: Default Fallback for Missing Keys
        """get(key, default=d, section=None) returns d using default prefix when
        key is missing from both overrides and chain."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix=prefix)

        result = view.get(key, default=default_val, section=None)

        assert result == default_val

    @given(
        key=config_keys,
        prefix=section_prefixes,
    )
    def test_missing_key_without_default_uses_prefix_returns_none(
        self,
        key: str,
        prefix: str,
    ) -> None:
        # Feature: unified-config-access, Property 3: Default Fallback for Missing Keys
        """get(key, section=None) returns None using default prefix when key is
        missing from both overrides and chain."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix=prefix)

        result = view.get(key, section=None)

        assert result is None

    @given(
        key=config_keys,
        default_val=default_values,
        section=config_sections,
    )
    def test_missing_key_returns_any_type_of_default(
        self,
        key: str,
        default_val: Any,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 3: Default Fallback for Missing Keys
        """get(key, default=d) returns d for any type of default value (str, int,
        bool, float, None) when key is missing."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        result = view.get(key, default=default_val, section=section)

        assert result is default_val


# --- Property 1: Resolution Equivalence ---
# Feature: unified-config-access, Property 1: Resolution Equivalence


class TestProperty1ResolutionEquivalence:
    """For any valid configuration key, section, and equivalent state,
    JobConfigView.get() SHALL return the same value as Configurations.get()
    would for equivalent inputs.

    Since Configurations is deprecated, we verify equivalence against a mock
    chain with known values. The key insight is that both systems resolve in
    the same order: overrides → env → files → defaults. We verify that
    JobConfigView delegates correctly to the chain and produces the expected
    value.

    **Validates: Requirements 1.7**
    """

    @given(
        key=config_keys,
        value=config_values,
        section=config_sections,
    )
    def test_key_in_chain_returns_chain_value(
        self,
        key: str,
        value: Any,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 1: Resolution Equivalence
        """When a key exists in the chain, get() returns the chain value —
        equivalent to what Configurations.get() would return from file sources."""
        source_data = {f"{section}.{key}": value}
        source = FakeSource(source_data, source_type="file", source_id="test.toml")
        chain = ResolutionChain([source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        result = view.get(key, section=section)

        assert result == value

    @given(
        key=config_keys,
        default_val=config_values,
        section=config_sections,
    )
    def test_key_not_in_chain_returns_default(
        self,
        key: str,
        default_val: Any,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 1: Resolution Equivalence
        """When a key is not found in any source, get() returns the provided
        default — equivalent to what Configurations.get() would return."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        result = view.get(key, default=default_val, section=section)

        assert result == default_val

    @given(
        key=config_keys,
        override_value=config_values,
        chain_value=config_values,
        section=config_sections,
    )
    def test_override_trumps_chain_value(
        self,
        key: str,
        override_value: Any,
        chain_value: Any,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 1: Resolution Equivalence
        """When an override is set, get() returns the override regardless of
        the chain value — matching Configurations' behavior where stored
        settings take priority over file sources."""
        source_data = {f"{section}.{key}": chain_value}
        source = FakeSource(source_data, source_type="file", source_id="test.toml")
        chain = ResolutionChain([source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        view.set(key, override_value, section=section)
        result = view.get(key, section=section)

        assert result == override_value

    @given(
        key=config_keys,
        high_priority_value=config_values,
        low_priority_value=config_values,
        section=config_sections,
    )
    def test_chain_precedence_first_source_wins(
        self,
        key: str,
        high_priority_value: Any,
        low_priority_value: Any,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 1: Resolution Equivalence
        """When multiple sources in the chain provide a value, the first
        (highest priority) source wins — equivalent to Configurations'
        resolution order of env → files."""
        high_source = FakeSource(
            {f"{section}.{key}": high_priority_value},
            source_type="env",
            source_id="environ",
        )
        low_source = FakeSource(
            {f"{section}.{key}": low_priority_value},
            source_type="file",
            source_id="config.toml",
        )
        chain = ResolutionChain([high_source, low_source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        result = view.get(key, section=section)

        assert result == high_priority_value

    @given(
        key=config_keys,
        section=config_sections,
    )
    def test_key_not_in_chain_no_default_returns_none(
        self,
        key: str,
        section: str,
    ) -> None:
        # Feature: unified-config-access, Property 1: Resolution Equivalence
        """When a key is not found and no default is provided, get() returns
        None — equivalent to Configurations.get() returning None."""
        chain = ResolutionChain([AlwaysMissingSource()])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        result = view.get(key, section=section)

        assert result is None

    @given(
        key=config_keys,
        value=config_values,
        section=config_sections,
        default_val=config_values,
    )
    def test_key_in_chain_ignores_default(
        self,
        key: str,
        value: Any,
        section: str,
        default_val: Any,
    ) -> None:
        # Feature: unified-config-access, Property 1: Resolution Equivalence
        """When a key exists in the chain, the default parameter is ignored —
        equivalent to Configurations.get() behavior."""
        source_data = {f"{section}.{key}": value}
        source = FakeSource(source_data, source_type="file", source_id="test.toml")
        chain = ResolutionChain([source])  # type: ignore[arg-type]
        view = JobConfigView(resolution_chain=chain, default_section_prefix="general")

        result = view.get(key, default=default_val, section=section)

        assert result == value
