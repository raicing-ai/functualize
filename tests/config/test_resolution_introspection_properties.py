"""Property-based tests for Resolution_Chain introspection accuracy.

Tests Property 6 from the design document: Resolution introspection accuracy.

For any resolved configuration value, the introspection record SHALL correctly
report the source_type, source_id, and key that provided the winning value,
and SHALL list all alternative values encountered in lower-priority sources
that were consulted.

**Validates: Requirements 5.3, 5.4**
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
        source_type: str = "test",
        source_id: str = "test-source",
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

# Strategy for non-None config values (primitives)
config_values: st.SearchStrategy[Any] = st.one_of(
    st.text(min_size=1, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
)

# Strategy for source type identifiers
source_types = st.sampled_from(["cli", "env", "remote", "file", "default"])

# Strategy for source identifiers
source_ids = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Nd"), whitelist_characters="_-./"
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s[0].isalpha())

# Strategy for config keys
config_keys = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha())

# Strategy for section names (optional)
section_names = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Nd"), whitelist_characters="_"
        ),
        min_size=1,
        max_size=10,
    ).filter(lambda s: s[0].isalpha()),
)


# Strategy for a FakeSource with a specific key populated
@st.composite
def fake_source_with_key(
    draw: st.DrawFn,
    key: str,
    section: str | None,
) -> FakeSource:
    """Generate a FakeSource that provides a value for the given key."""
    stype = draw(source_types)
    sid = draw(source_ids)
    value = draw(config_values)
    data = {(section, key): value}
    return FakeSource(source_type=stype, source_id=sid, data=data)


@st.composite
def fake_source_without_key(
    draw: st.DrawFn,
    key: str,
    section: str | None,
) -> FakeSource:
    """Generate a FakeSource that does NOT provide a value for the given key."""
    stype = draw(source_types)
    sid = draw(source_ids)
    # Create an empty source (no data for the target key)
    return FakeSource(source_type=stype, source_id=sid, data={})


@st.composite
def source_list_with_providers(
    draw: st.DrawFn,
) -> tuple[str, str | None, list[FakeSource], list[int]]:
    """Generate a key, section, list of FakeSource objects, and indices of sources
    that provide the key.

    Returns (key, section, sources, providing_indices) where providing_indices
    is a non-empty sorted list of indices into sources that have a value for key.
    """
    key = draw(config_keys)
    section = draw(section_names)
    num_sources = draw(st.integers(min_value=1, max_value=6))

    # Decide which sources will provide the key (at least one must)
    providing_indices = draw(
        st.lists(
            st.integers(min_value=0, max_value=num_sources - 1),
            min_size=1,
            max_size=num_sources,
            unique=True,
        )
    )
    providing_indices.sort()

    sources: list[FakeSource] = []
    for i in range(num_sources):
        if i in providing_indices:
            source = draw(fake_source_with_key(key, section))
        else:
            source = draw(fake_source_without_key(key, section))
        sources.append(source)

    return key, section, sources, providing_indices


# --- Property 6: Resolution introspection accuracy ---


class TestProperty6ResolutionIntrospectionAccuracy:
    """Property 6: Resolution introspection accuracy.

    For any resolved configuration value, the introspection record SHALL
    correctly report the source_type, source_id, and key that provided
    the winning value, and SHALL list all alternative values encountered
    in lower-priority sources that were consulted.

    **Validates: Requirements 5.3, 5.4**
    """

    @given(data=source_list_with_providers())
    def test_introspect_winning_value_matches_resolve(
        self,
        data: tuple[str, str | None, list[FakeSource], list[int]],
    ) -> None:
        """The introspect result always contains the same winning value
        as resolve()."""
        key, section, sources, _providing_indices = data
        chain = ResolutionChain(sources)  # type: ignore[arg-type]

        resolved = chain.resolve(key, section)
        introspected = chain.introspect(key, section)

        assert introspected.value == resolved.value
        assert introspected.source_type == resolved.source_type
        assert introspected.source_id == resolved.source_id
        assert introspected.key == resolved.key

    @given(data=source_list_with_providers())
    def test_alternatives_come_from_lower_priority_sources(
        self,
        data: tuple[str, str | None, list[FakeSource], list[int]],
    ) -> None:
        """Alternatives always come from sources with lower priority (higher
        index) than the winner."""
        key, section, sources, providing_indices = data
        chain = ResolutionChain(sources)  # type: ignore[arg-type]

        result = chain.introspect(key, section)

        # The winner is the first providing source (lowest index = highest priority)
        winner_index = providing_indices[0]
        winner_source = sources[winner_index]

        assert result.source_type == winner_source.source_type
        assert result.source_id == winner_source.source_id

        # All alternatives must come from sources after the winner in index order
        for alt_type, alt_id, _alt_value in result.alternatives:
            # Find which source produced this alternative
            found_after_winner = False
            for i in range(winner_index + 1, len(sources)):
                if (
                    sources[i].source_type == alt_type
                    and sources[i].source_id == alt_id
                ):
                    found_after_winner = True
                    break
            assert found_after_winner, (
                f"Alternative ({alt_type}, {alt_id}) not found "
                f"after winner at index {winner_index}"
            )

    @given(data=source_list_with_providers())
    def test_number_of_alternatives_equals_lower_priority_providers(
        self,
        data: tuple[str, str | None, list[FakeSource], list[int]],
    ) -> None:
        """The number of alternatives equals the number of lower-priority
        sources that also provide the key."""
        key, section, sources, providing_indices = data
        chain = ResolutionChain(sources)  # type: ignore[arg-type]

        result = chain.introspect(key, section)

        # Winner is the first providing source
        winner_index = providing_indices[0]

        # Count providers after the winner
        expected_alternatives = sum(
            1 for idx in providing_indices if idx > winner_index
        )
        assert len(result.alternatives) == expected_alternatives

    @given(data=source_list_with_providers())
    def test_each_alternative_records_correct_source_type_and_id(
        self,
        data: tuple[str, str | None, list[FakeSource], list[int]],
    ) -> None:
        """Each alternative records the correct source_type and source_id
        from the source that produced it."""
        key, section, sources, providing_indices = data
        chain = ResolutionChain(sources)  # type: ignore[arg-type]

        result = chain.introspect(key, section)

        # Winner is the first providing source
        winner_index = providing_indices[0]

        # The alternatives should correspond to the providing sources after
        # the winner, in order
        expected_alt_indices = [idx for idx in providing_indices if idx > winner_index]

        assert len(result.alternatives) == len(expected_alt_indices)

        for alt, expected_idx in zip(
            result.alternatives, expected_alt_indices, strict=True
        ):
            alt_type, alt_id, alt_value = alt
            expected_source = sources[expected_idx]
            assert alt_type == expected_source.source_type
            assert alt_id == expected_source.source_id
            # The alternative value must match what the source provides
            assert alt_value == expected_source.get(key, section)
