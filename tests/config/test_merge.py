"""Unit tests for the deep_merge algorithm."""

import copy

from functualize._config.merge import deep_merge


class TestDeepMergeBasicBehavior:
    """Test basic merge behavior."""

    def test_empty_base_returns_overlay(self) -> None:
        result = deep_merge({}, {"a": 1})
        assert result == {"a": 1}

    def test_empty_overlay_returns_base_copy(self) -> None:
        base = {"a": 1}
        result = deep_merge(base, {})
        assert result == {"a": 1}
        assert result is not base

    def test_both_empty_returns_empty(self) -> None:
        assert deep_merge({}, {}) == {}

    def test_overlay_replaces_leaf_value(self) -> None:
        result = deep_merge({"a": 1}, {"a": 2})
        assert result == {"a": 2}

    def test_overlay_adds_new_keys(self) -> None:
        result = deep_merge({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}


class TestDeepMergeNestedDicts:
    """Test recursive merge of nested dicts."""

    def test_nested_dicts_are_merged_recursively(self) -> None:
        base = {"section": {"key1": "val1", "key2": "val2"}}
        overlay = {"section": {"key2": "override", "key3": "new"}}
        result = deep_merge(base, overlay)
        assert result == {
            "section": {"key1": "val1", "key2": "override", "key3": "new"}
        }

    def test_deeply_nested_merge(self) -> None:
        base = {"a": {"b": {"c": 1, "d": 2}}}
        overlay = {"a": {"b": {"c": 99}}}
        result = deep_merge(base, overlay)
        assert result == {"a": {"b": {"c": 99, "d": 2}}}

    def test_overlay_dict_replaces_non_dict_base(self) -> None:
        result = deep_merge({"a": "string"}, {"a": {"nested": True}})
        assert result == {"a": {"nested": True}}

    def test_overlay_non_dict_replaces_base_dict(self) -> None:
        result = deep_merge({"a": {"nested": True}}, {"a": "flat"})
        assert result == {"a": "flat"}


class TestDeepMergeListHandling:
    """Test that lists are replaced wholesale."""

    def test_lists_are_replaced_not_concatenated(self) -> None:
        base = {"items": [1, 2, 3]}
        overlay = {"items": [4, 5]}
        result = deep_merge(base, overlay)
        assert result == {"items": [4, 5]}

    def test_list_replaces_non_list(self) -> None:
        result = deep_merge({"a": "scalar"}, {"a": [1, 2]})
        assert result == {"a": [1, 2]}

    def test_non_list_replaces_list(self) -> None:
        result = deep_merge({"a": [1, 2]}, {"a": "scalar"})
        assert result == {"a": "scalar"}


class TestDeepMergeImmutability:
    """Test that inputs are not mutated."""

    def test_base_is_not_mutated(self) -> None:
        base = {"a": 1, "section": {"key": "original"}}
        base_copy = copy.deepcopy(base)
        deep_merge(base, {"a": 2, "section": {"key": "new"}})
        assert base == base_copy

    def test_overlay_is_not_mutated(self) -> None:
        overlay = {"a": 2, "section": {"key": "new"}}
        overlay_copy = copy.deepcopy(overlay)
        deep_merge({"a": 1}, overlay)
        assert overlay == overlay_copy

    def test_result_is_new_dict(self) -> None:
        base = {"a": 1}
        overlay = {"b": 2}
        result = deep_merge(base, overlay)
        assert result is not base
        assert result is not overlay
