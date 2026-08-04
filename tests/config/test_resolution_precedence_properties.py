"""Property-based tests for ResolutionChain precedence behavior using Hypothesis.

Tests Property 4 from the design document: Resolution precedence.

**Validates: Requirements 5.1**
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._config.chain import ResolutionChain
from functualize._config.errors import MissingKeyError

# --- FakeSource ---


class FakeSource:
    """A simple configurable Source for testing resolution precedence.

    Implements the Source protocol with a dict of key → value mappings.
    Supports optional section-scoped keys via (section, key) tuples.
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

# Strategy for valid config keys
config_keys = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha())

# Strategy for source type identifiers
source_types = st.sampled_from(["cli", "env", "remote", "file", "default"])

# Strategy for source id identifiers
source_ids = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Nd"), whitelist_characters="_-/"
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s[0].isalpha())


# --- Property 4: Resolution precedence ---


class TestProperty4ResolutionPrecedence:
    """Sources at earlier indices always take precedence over later indices.

    **Validates: Requirements 5.1**
    """

    @given(
        key=config_keys,
        value_i=config_values,
        value_j=config_values,
        i=st.integers(min_value=0, max_value=4),
        j_offset=st.integers(min_value=1, max_value=4),
        total_sources=st.integers(min_value=2, max_value=6),
    )
    def test_earlier_source_wins_over_later_source(
        self,
        key: str,
        value_i: Any,
        value_j: Any,
        i: int,
        j_offset: int,
        total_sources: int,
    ) -> None:
        """If source at index i provides a value and source at index j (j > i)
        also provides a value, the value from source i always wins."""
        j = i + j_offset
        # Ensure we have enough sources
        num_sources = max(total_sources, j + 1)

        sources: list[FakeSource] = []
        for idx in range(num_sources):
            if idx == i:
                sources.append(
                    FakeSource(
                        {key: value_i},
                        source_type=f"type_{idx}",
                        source_id=f"source_{idx}",
                    )
                )
            elif idx == j:
                sources.append(
                    FakeSource(
                        {key: value_j},
                        source_type=f"type_{idx}",
                        source_id=f"source_{idx}",
                    )
                )
            else:
                sources.append(
                    FakeSource(
                        {},
                        source_type=f"type_{idx}",
                        source_id=f"source_{idx}",
                    )
                )

        chain = ResolutionChain(sources)  # type: ignore[arg-type]
        result = chain.resolve(key)

        assert result.value == value_i
        assert result.source_type == f"type_{i}"
        assert result.source_id == f"source_{i}"

    @given(
        key=config_keys,
        values=st.lists(config_values, min_size=2, max_size=6),
    )
    def test_first_source_always_wins(
        self,
        key: str,
        values: list[Any],
    ) -> None:
        """When multiple sources all provide a value for the same key,
        the source at index 0 always wins regardless of how many sources
        provide values."""
        sources = [
            FakeSource(
                {key: val},
                source_type=f"type_{idx}",
                source_id=f"source_{idx}",
            )
            for idx, val in enumerate(values)
        ]

        chain = ResolutionChain(sources)  # type: ignore[arg-type]
        result = chain.resolve(key)

        assert result.value == values[0]
        assert result.source_type == "type_0"
        assert result.source_id == "source_0"

    @given(
        key=config_keys,
        value=config_values,
        position=st.integers(min_value=0, max_value=5),
        total_sources=st.integers(min_value=1, max_value=6),
    )
    def test_single_source_wins_regardless_of_position(
        self,
        key: str,
        value: Any,
        position: int,
        total_sources: int,
    ) -> None:
        """If only one source provides a value, that source always wins
        regardless of its position in the chain."""
        num_sources = max(total_sources, position + 1)

        sources: list[FakeSource] = []
        for idx in range(num_sources):
            if idx == position:
                sources.append(
                    FakeSource(
                        {key: value},
                        source_type=f"type_{idx}",
                        source_id=f"source_{idx}",
                    )
                )
            else:
                sources.append(
                    FakeSource(
                        {},
                        source_type=f"type_{idx}",
                        source_id=f"source_{idx}",
                    )
                )

        chain = ResolutionChain(sources)  # type: ignore[arg-type]
        result = chain.resolve(key)

        assert result.value == value
        assert result.source_type == f"type_{position}"
        assert result.source_id == f"source_{position}"

    @given(
        key=config_keys,
        num_sources=st.integers(min_value=1, max_value=6),
    )
    def test_missing_key_raises_when_no_source_provides_value(
        self,
        key: str,
        num_sources: int,
    ) -> None:
        """If no source provides a value, MissingKeyError is always raised."""
        sources = [
            FakeSource(
                {},
                source_type=f"type_{idx}",
                source_id=f"source_{idx}",
            )
            for idx in range(num_sources)
        ]

        chain = ResolutionChain(sources)  # type: ignore[arg-type]

        with pytest.raises(MissingKeyError) as exc_info:
            chain.resolve(key)

        assert exc_info.value.key == key
        assert len(exc_info.value.consulted_sources) == num_sources
        for idx in range(num_sources):
            assert f"source_{idx}" in exc_info.value.consulted_sources

    @given(
        key=config_keys,
        values=st.lists(config_values, min_size=2, max_size=6),
    )
    def test_later_sources_appear_as_alternatives(
        self,
        key: str,
        values: list[Any],
    ) -> None:
        """Sources that lose the precedence battle appear in the alternatives
        list of the resolved value, preserving their order."""
        sources = [
            FakeSource(
                {key: val},
                source_type=f"type_{idx}",
                source_id=f"source_{idx}",
            )
            for idx, val in enumerate(values)
        ]

        chain = ResolutionChain(sources)  # type: ignore[arg-type]
        result = chain.resolve(key)

        # The winner is always the first source
        assert result.value == values[0]

        # Remaining sources are in alternatives in order
        assert len(result.alternatives) == len(values) - 1
        for alt_idx, (src_type, src_id, alt_value) in enumerate(result.alternatives):
            original_idx = alt_idx + 1
            assert src_type == f"type_{original_idx}"
            assert src_id == f"source_{original_idx}"
            assert alt_value == values[original_idx]
