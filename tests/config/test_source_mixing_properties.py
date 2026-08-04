"""Property-based tests for independent source mixing using Hypothesis.

Tests Property 16 from the design document: Independent source mixing.

**Validates: Requirements 7.5**

For any configuration section where different keys are provided by different
sources (e.g., one key from env, another from file), all keys SHALL resolve
correctly from their respective sources without requiring all keys in the
section to come from the same source.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.chain import ResolutionChain

# --- Test helpers ---


class FakeSource:
    """A simple fake Source for testing the ResolutionChain."""

    def __init__(
        self,
        *,
        source_type: str,
        source_id: str,
        data: dict[tuple[str | None, str], Any] | None = None,
    ) -> None:
        self._source_type = source_type
        self._source_id = source_id
        self._data: dict[tuple[str | None, str], Any] = data or {}

    @property
    def source_type(self) -> str:
        return self._source_type

    @property
    def source_id(self) -> str:
        return self._source_id

    def get(self, key: str, section: str | None = None) -> Any | None:
        return self._data.get((section, key))

    def has(self, key: str, section: str | None = None) -> bool:
        return (section, key) in self._data


# --- Strategies ---

# Strategy for valid key names
key_names = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=12,
).filter(lambda s: s[0].isalpha())

# Strategy for valid section names
section_names = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=10,
).filter(lambda s: s[0].isalpha())

# Strategy for config values (primitives)
config_values: st.SearchStrategy[Any] = st.one_of(
    st.text(min_size=1, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
)


# --- Property 16: Independent source mixing ---


class TestProperty16IndependentSourceMixing:
    """Different keys in the same section can be provided by different sources
    independently. No source is required to provide all keys in a section.

    **Validates: Requirements 7.5**
    """

    @given(
        section=section_names,
        key_a=key_names,
        key_b=key_names,
        value_a=config_values,
        value_b=config_values,
    )
    def test_different_keys_from_different_sources(
        self,
        section: str,
        key_a: str,
        key_b: str,
        value_a: Any,
        value_b: Any,
    ) -> None:
        """Different keys in the same section can be provided by different
        sources independently."""
        # Ensure keys are distinct
        if key_a == key_b:
            return

        # Source 1 (e.g., env) provides key_a only
        env_source = FakeSource(
            source_type="env",
            source_id="environ",
            data={(section, key_a): value_a},
        )
        # Source 2 (e.g., file) provides key_b only
        file_source = FakeSource(
            source_type="file",
            source_id="config.toml",
            data={(section, key_b): value_b},
        )

        chain = ResolutionChain([env_source, file_source])

        # Both keys resolve correctly from their respective sources
        result_a = chain.resolve(key_a, section=section)
        result_b = chain.resolve(key_b, section=section)

        assert result_a.value == value_a
        assert result_a.source_type == "env"

        assert result_b.value == value_b
        assert result_b.source_type == "file"

    @given(
        section=section_names,
        keys_with_values=st.lists(
            st.tuples(key_names, config_values),
            min_size=2,
            max_size=6,
            unique_by=lambda x: x[0],
        ),
    )
    def test_no_source_required_to_provide_all_keys(
        self,
        section: str,
        keys_with_values: list[tuple[str, Any]],
    ) -> None:
        """No source is required to provide all keys in a section. Keys can
        be distributed across multiple sources, each providing only a subset."""
        # Split keys across multiple sources (alternating assignment)
        source_a_data: dict[tuple[str | None, str], Any] = {}
        source_b_data: dict[tuple[str | None, str], Any] = {}

        for i, (key, value) in enumerate(keys_with_values):
            if i % 2 == 0:
                source_a_data[(section, key)] = value
            else:
                source_b_data[(section, key)] = value

        source_a = FakeSource(
            source_type="cli",
            source_id="cli",
            data=source_a_data,
        )
        source_b = FakeSource(
            source_type="default",
            source_id="defaults",
            data=source_b_data,
        )

        chain = ResolutionChain([source_a, source_b])

        # Every key resolves correctly regardless of which source provides it
        for key, value in keys_with_values:
            result = chain.resolve(key, section=section)
            assert result.value == value

    @given(
        section=section_names,
        shared_key=key_names,
        independent_key=key_names,
        shared_value_high=config_values,
        shared_value_low=config_values,
        independent_value=config_values,
    )
    def test_resolution_of_one_key_does_not_affect_another(
        self,
        section: str,
        shared_key: str,
        independent_key: str,
        shared_value_high: Any,
        shared_value_low: Any,
        independent_value: Any,
    ) -> None:
        """The resolution of one key does not affect the resolution of
        another key. Each key is resolved independently through the chain."""
        if shared_key == independent_key:
            return

        # High-priority source has both shared_key and independent_key NOT present
        # (shared_key is provided, independent_key is not)
        high_source = FakeSource(
            source_type="env",
            source_id="environ",
            data={(section, shared_key): shared_value_high},
        )
        # Low-priority source provides both keys
        low_source = FakeSource(
            source_type="file",
            source_id="config.toml",
            data={
                (section, shared_key): shared_value_low,
                (section, independent_key): independent_value,
            },
        )

        chain = ResolutionChain([high_source, low_source])

        # shared_key resolves from high priority source
        result_shared = chain.resolve(shared_key, section=section)
        assert result_shared.value == shared_value_high
        assert result_shared.source_type == "env"

        # independent_key resolves from low priority source (the only source that has it)
        # The fact that shared_key was resolved from env doesn't affect independent_key
        result_independent = chain.resolve(independent_key, section=section)
        assert result_independent.value == independent_value
        assert result_independent.source_type == "file"

    @given(
        section=section_names,
        env_keys=st.lists(key_names, min_size=1, max_size=3, unique=True),
        file_keys=st.lists(key_names, min_size=1, max_size=3, unique=True),
        default_keys=st.lists(key_names, min_size=1, max_size=3, unique=True),
    )
    def test_mixed_source_resolution(
        self,
        section: str,
        env_keys: list[str],
        file_keys: list[str],
        default_keys: list[str],
    ) -> None:
        """Mixed-source resolution (some keys from env, some from file, some
        from defaults) works correctly. Each key resolves from the highest-
        priority source that provides it."""
        # Make unique key pools: env_only, file_only, default_only
        all_keys = set(env_keys + file_keys + default_keys)
        # Assign values per source
        env_data: dict[tuple[str | None, str], Any] = {}
        file_data: dict[tuple[str | None, str], Any] = {}
        default_data: dict[tuple[str | None, str], Any] = {}

        for key in env_keys:
            env_data[(section, key)] = f"env_{key}"
        for key in file_keys:
            file_data[(section, key)] = f"file_{key}"
        for key in default_keys:
            default_data[(section, key)] = f"default_{key}"

        env_source = FakeSource(source_type="env", source_id="environ", data=env_data)
        file_source = FakeSource(
            source_type="file", source_id="config.toml", data=file_data
        )
        default_source = FakeSource(
            source_type="default", source_id="defaults", data=default_data
        )

        # Precedence: env > file > default
        chain = ResolutionChain([env_source, file_source, default_source])

        # Each key resolves from the highest-priority source that provides it
        for key in all_keys:
            result = chain.resolve(key, section=section)

            if key in env_keys:
                # If env provides it, env wins (highest priority)
                assert result.value == f"env_{key}"
                assert result.source_type == "env"
            elif key in file_keys:
                # If only file and/or default provide it, file wins
                assert result.value == f"file_{key}"
                assert result.source_type == "file"
            else:
                # Only default provides it
                assert result.value == f"default_{key}"
                assert result.source_type == "default"
