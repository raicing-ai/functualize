"""Property-based tests for same-precedence ordering in the Resolution_Chain.

Tests Property 7 from the design document: Same-precedence ordering.

When multiple sources at the same precedence level provide a value for
the same key, the source declared first (lowest index in the sources list)
always wins. The ordering is strictly deterministic.

**Validates: Requirements 5.6**
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.chain import ResolutionChain

# --- Test helpers ---


class SamePrecedenceSource:
    """A Source implementation representing sources at the same precedence level.

    All instances use the same source_type to simulate same-precedence sources
    (e.g., multiple remote providers or multiple file sources).
    """

    def __init__(
        self,
        *,
        source_type: str = "remote",
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

# Strategy for configuration values that sources might provide
config_values: st.SearchStrategy[Any] = st.one_of(
    st.text(min_size=1, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    st.booleans(),
)

# Strategy for valid config keys
config_keys = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha())

# Strategy for valid section names
section_names = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=10,
).filter(lambda s: s[0].isalpha())

# Strategy for source identifiers (unique names for same-precedence sources)
source_ids = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Nd"), whitelist_characters="_-"
    ),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha())


# --- Property 7: Same-precedence ordering ---


class TestProperty7SamePrecedenceOrdering:
    """When sources at the same precedence level provide the same key,
    the first source in the list always wins deterministically.

    **Validates: Requirements 5.6**
    """

    @given(
        key=config_keys,
        values=st.lists(config_values, min_size=2, max_size=8, unique_by=repr),
    )
    def test_first_source_in_list_always_wins(
        self,
        key: str,
        values: list[Any],
    ) -> None:
        """When sources at the same precedence level are ordered in a list,
        the first one always wins regardless of how many sources provide
        the same key."""
        # Create N sources all at same precedence (same source_type)
        # but with different values for the same key
        sources = [
            SamePrecedenceSource(
                source_type="remote",
                source_id=f"provider_{i}",
                data={(None, key): value},
            )
            for i, value in enumerate(values)
        ]

        chain = ResolutionChain(sources)
        result = chain.resolve(key)

        # The first source (index 0) must always win
        assert result.value == values[0]
        assert result.source_id == "provider_0"
        assert result.source_type == "remote"

    @given(
        key=config_keys,
        values=st.lists(config_values, min_size=2, max_size=6, unique_by=repr),
        seed=st.integers(min_value=0, max_value=100),
    )
    def test_permutation_index_zero_always_wins(
        self,
        key: str,
        values: list[Any],
        seed: int,
    ) -> None:
        """For any permutation of sources with the same values, the one at
        index 0 in the list always wins. Reordering sources changes the
        winner to whatever is now at position 0."""
        # Create sources
        sources = [
            SamePrecedenceSource(
                source_type="remote",
                source_id=f"provider_{i}",
                data={(None, key): value},
            )
            for i, value in enumerate(values)
        ]

        # Try the original order
        chain = ResolutionChain(sources)
        result = chain.resolve(key)
        assert result.value == values[0]
        assert result.source_id == "provider_0"

        # Reverse the sources — now the last original source is first
        reversed_sources = list(reversed(sources))
        chain_reversed = ResolutionChain(reversed_sources)
        result_reversed = chain_reversed.resolve(key)
        assert result_reversed.value == values[-1]
        assert result_reversed.source_id == f"provider_{len(values) - 1}"

    @given(
        key=config_keys,
        values=st.lists(config_values, min_size=2, max_size=8, unique_by=repr),
    )
    def test_ordering_is_deterministic(
        self,
        key: str,
        values: list[Any],
    ) -> None:
        """The ordering is strictly deterministic — resolving the same chain
        multiple times always produces the same result with no randomness."""
        sources = [
            SamePrecedenceSource(
                source_type="remote",
                source_id=f"provider_{i}",
                data={(None, key): value},
            )
            for i, value in enumerate(values)
        ]

        chain = ResolutionChain(sources)

        # Resolve multiple times — must always return the same result
        results = [chain.resolve(key) for _ in range(10)]

        for result in results:
            assert result.value == values[0]
            assert result.source_id == "provider_0"
            assert result.source_type == "remote"

    @given(
        key=config_keys,
        section=section_names,
        values=st.lists(config_values, min_size=2, max_size=6, unique_by=repr),
    )
    def test_same_precedence_ordering_with_sections(
        self,
        key: str,
        section: str,
        values: list[Any],
    ) -> None:
        """Same-precedence ordering holds when using sectioned keys.
        The first source in the list providing a sectioned key wins."""
        sources = [
            SamePrecedenceSource(
                source_type="file",
                source_id=f"config_{i}.toml",
                data={(section, key): value},
            )
            for i, value in enumerate(values)
        ]

        chain = ResolutionChain(sources)
        result = chain.resolve(key, section=section)

        # First source still wins for sectioned keys
        assert result.value == values[0]
        assert result.source_id == "config_0.toml"

    @given(
        key=config_keys,
        values=st.lists(config_values, min_size=2, max_size=6, unique_by=repr),
    )
    def test_alternatives_preserve_ordering(
        self,
        key: str,
        values: list[Any],
    ) -> None:
        """The alternatives in the ResolvedValue maintain the same ordering
        as the sources list (minus the winner at index 0)."""
        sources = [
            SamePrecedenceSource(
                source_type="remote",
                source_id=f"provider_{i}",
                data={(None, key): value},
            )
            for i, value in enumerate(values)
        ]

        chain = ResolutionChain(sources)
        result = chain.resolve(key)

        # Winner is index 0
        assert result.value == values[0]

        # Alternatives should follow the same order as the remaining sources
        assert len(result.alternatives) == len(values) - 1
        for i, (src_type, src_id, alt_value) in enumerate(result.alternatives):
            expected_idx = i + 1
            assert alt_value == values[expected_idx]
            assert src_id == f"provider_{expected_idx}"
            assert src_type == "remote"
