"""Property-based tests for the deep_merge algorithm using Hypothesis.

Tests Property 5 from the design document.
"""

from __future__ import annotations

import copy
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize._config.merge import deep_merge

# --- Strategies ---

# Strategy for valid config keys (alphanumeric + underscore, starts with letter)
config_keys = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="_"),
    min_size=1,
    max_size=10,
).filter(lambda s: s[0].isalpha())

# Strategy for leaf values (primitives that appear in config dicts)
leaf_values = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
    st.lists(st.integers(min_value=-100, max_value=100), max_size=5),
)


def config_dicts(max_leaves: int = 5) -> st.SearchStrategy[dict[str, Any]]:
    """Strategy for generating nested configuration dictionaries."""
    return st.recursive(
        st.dictionaries(
            keys=config_keys,
            values=leaf_values,
            min_size=0,
            max_size=max_leaves,
        ),
        lambda children: st.dictionaries(
            keys=config_keys,
            values=st.one_of(children, leaf_values),
            min_size=0,
            max_size=max_leaves,
        ),
        max_leaves=3,
    )


# --- Property 5: Deep-merge preserves nested structure ---


class TestProperty5DeepMergePreservesNestedStructure:
    """When multiple configuration files are discovered, the Configuration_System SHALL
    deep-merge them in path priority order where deep-merge means that nested sections
    are merged recursively and only leaf-level values are overridden rather than replacing
    entire sections.

    **Validates: Requirements 5.2**
    """

    @given(
        base=st.dictionaries(
            keys=config_keys,
            values=st.dictionaries(
                keys=config_keys, values=leaf_values, min_size=1, max_size=3
            ),
            min_size=1,
            max_size=3,
        ),
        overlay=st.dictionaries(
            keys=config_keys,
            values=st.dictionaries(
                keys=config_keys, values=leaf_values, min_size=1, max_size=3
            ),
            min_size=1,
            max_size=3,
        ),
    )
    def test_nested_dicts_merged_recursively_not_replaced(
        self, base: dict[str, Any], overlay: dict[str, Any]
    ) -> None:
        """When both base and overlay have a nested dict at the same key,
        the result must contain keys from both (not just overlay's dict)."""
        result = deep_merge(base, overlay)

        for key in base:
            if key in overlay:
                # Both have this key as a dict — keys from base not in overlay must persist
                base_section = base[key]
                overlay_section = overlay[key]
                if isinstance(base_section, dict) and isinstance(overlay_section, dict):
                    result_section = result[key]
                    # All base keys not overridden by overlay should survive
                    for base_sub_key in base_section:
                        assert base_sub_key in result_section
                    # All overlay keys should be present
                    for overlay_sub_key in overlay_section:
                        assert overlay_sub_key in result_section
                        assert (
                            result_section[overlay_sub_key]
                            == overlay_section[overlay_sub_key]
                        )

    @given(base=config_dicts(), overlay=config_dicts())
    def test_all_base_keys_preserved(
        self, base: dict[str, Any], overlay: dict[str, Any]
    ) -> None:
        """All top-level keys from base are present in the result."""
        result = deep_merge(base, overlay)
        for key in base:
            assert key in result

    @given(base=config_dicts(), overlay=config_dicts())
    def test_overlay_values_win_for_leaf_keys(
        self, base: dict[str, Any], overlay: dict[str, Any]
    ) -> None:
        """For any leaf key present in overlay, the result has the overlay value."""
        result = deep_merge(base, overlay)
        for key, value in overlay.items():
            if not isinstance(value, dict) or (
                key in base and not isinstance(base[key], dict)
            ):
                # Leaf replacement case: overlay wins
                assert result[key] == value
            elif (
                isinstance(value, dict) and key in base and isinstance(base[key], dict)
            ):
                # Recursive case: checked separately
                pass
            else:
                # New key or dict replacing non-dict
                assert result[key] == value

    @given(
        base=st.dictionaries(
            keys=config_keys,
            values=st.lists(
                st.integers(min_value=0, max_value=100), min_size=1, max_size=5
            ),
            min_size=1,
            max_size=3,
        ),
        overlay=st.dictionaries(
            keys=config_keys,
            values=st.lists(
                st.integers(min_value=0, max_value=100), min_size=1, max_size=5
            ),
            min_size=1,
            max_size=3,
        ),
    )
    def test_lists_replaced_wholesale(
        self, base: dict[str, Any], overlay: dict[str, Any]
    ) -> None:
        """Lists in overlay replace base lists wholesale (no concatenation)."""
        result = deep_merge(base, overlay)
        for key in overlay:
            assert result[key] == overlay[key]
        # If base had a list at a key not in overlay, it should remain
        for key in base:
            if key not in overlay:
                assert result[key] == base[key]

    @given(base=config_dicts(), overlay=config_dicts())
    def test_inputs_not_mutated(
        self, base: dict[str, Any], overlay: dict[str, Any]
    ) -> None:
        """deep_merge does not mutate either input dict."""
        base_before = copy.deepcopy(base)
        overlay_before = copy.deepcopy(overlay)

        deep_merge(base, overlay)

        assert base == base_before
        assert overlay == overlay_before

    @given(d=config_dicts())
    def test_merge_with_empty_is_identity(self, d: dict[str, Any]) -> None:
        """Merging with empty dict produces equivalent structure.

        deep_merge(d, {}) == d and deep_merge({}, d) == d
        """
        assert deep_merge(d, {}) == d
        assert deep_merge({}, d) == d

    @given(d=config_dicts())
    def test_idempotency(self, d: dict[str, Any]) -> None:
        """deep_merge(d, d) produces a result equal to d for all leaf values."""
        result = deep_merge(d, d)
        assert result == d
