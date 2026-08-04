"""Tests for merge_config_layers() — layered config merge with root-stop semantics."""

from __future__ import annotations

from functualize._config.merge import merge_config_layers


class TestMergeConfigLayers:
    """Unit tests for merge_config_layers."""

    def test_empty_layers_returns_empty_dict(self) -> None:
        assert merge_config_layers([]) == {}

    def test_single_layer_returned_as_is(self) -> None:
        result = merge_config_layers([{"a": 1, "b": "hello"}])
        assert result == {"a": 1, "b": "hello"}

    def test_two_layers_nearest_wins(self) -> None:
        """Index 0 = highest priority (nearest). Its values override."""
        result = merge_config_layers([{"a": 1}, {"a": 2, "b": 3}])
        assert result == {"a": 1, "b": 3}

    def test_deep_merge_of_nested_dicts(self) -> None:
        layers = [
            {"discovery": {"depth": 3}},
            {"discovery": {"depth": 1, "prefix": "job_"}},
        ]
        result = merge_config_layers(layers)
        assert result == {"discovery": {"depth": 3, "prefix": "job_"}}

    def test_root_true_stops_processing(self) -> None:
        """Layers after root=true are not merged."""
        result = merge_config_layers(
            [
                {"a": 1},
                {"root": True, "b": 2},
                {"c": 3},  # Should NOT be included
            ]
        )
        assert result == {"a": 1, "b": 2}
        assert "c" not in result

    def test_root_key_stripped_from_output(self) -> None:
        result = merge_config_layers([{"root": True, "x": 42}])
        assert result == {"x": 42}
        assert "root" not in result

    def test_root_false_does_not_stop(self) -> None:
        """Only root=True (exactly) triggers stop. root=False still merges all layers."""
        result = merge_config_layers(
            [
                {"a": 1},
                {"root": False, "b": 2},
                {"c": 3},
            ]
        )
        # root key is always stripped (it's a control key), but all layers are merged
        assert result == {"a": 1, "b": 2, "c": 3}
        assert "c" in result  # Proves processing didn't stop

    def test_root_non_bool_does_not_stop(self) -> None:
        """root="true" (string) does not trigger stop."""
        result = merge_config_layers(
            [
                {"a": 1},
                {"root": "true", "b": 2},
                {"c": 3},
            ]
        )
        assert "c" in result

    def test_custom_root_key(self) -> None:
        result = merge_config_layers(
            [{"a": 1}, {"stop_here": True, "b": 2}, {"c": 3}],
            root_key="stop_here",
        )
        assert result == {"a": 1, "b": 2}
        assert "stop_here" not in result
        assert "c" not in result

    def test_first_layer_is_root(self) -> None:
        """If the nearest layer is root, only it is used."""
        result = merge_config_layers(
            [
                {"root": True, "a": 1},
                {"b": 2},
                {"c": 3},
            ]
        )
        assert result == {"a": 1}

    def test_no_root_merges_all(self) -> None:
        result = merge_config_layers(
            [
                {"a": 1},
                {"b": 2},
                {"c": 3},
            ]
        )
        assert result == {"a": 1, "b": 2, "c": 3}

    def test_list_values_replaced_not_concatenated(self) -> None:
        """Lists follow deep_merge semantics (replace, not concat)."""
        result = merge_config_layers(
            [
                {"paths": ["/a", "/b"]},
                {"paths": ["/c", "/d"]},
            ]
        )
        # Nearest layer wins for list values
        assert result == {"paths": ["/a", "/b"]}

    def test_does_not_mutate_inputs(self) -> None:
        layer1 = {"a": 1}
        layer2 = {"b": 2}
        merge_config_layers([layer1, layer2])
        assert layer1 == {"a": 1}
        assert layer2 == {"b": 2}

    def test_multiple_overlapping_keys(self) -> None:
        result = merge_config_layers(
            [
                {"jobs_directories": ["./tasks"], "import_libs": ["lib"]},
                {
                    "jobs_directories": ["./scripts"],
                    "import_libs": ["shared"],
                    "scan_depth": 2,
                },
                {"scan_depth": 5, "extra": "value"},
            ]
        )
        assert result == {
            "jobs_directories": ["./tasks"],
            "import_libs": ["lib"],
            "scan_depth": 2,
            "extra": "value",
        }
