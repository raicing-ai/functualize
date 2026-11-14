"""The pre-boot run-tag grammar and layer merge."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from functualize._config.run_tags import (
    RunTagError,
    merge_layers,
    parse_config_list,
    parse_env,
    parse_flag_list,
    parse_tag,
    resolve_run_tags,
)
from functualize._config.settings_layers import SettingsLayer


def test_parse_tag_splits_only_first_colon() -> None:
    assert parse_tag("url:https://x", where="--run-tag") == ("url", "https://x")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("harness", "--run-tag 'harness': a run tag is key:value (missing ':')."),
        (":claude", "--run-tag ':claude': a run tag needs a key before ':'."),
        ("harness:", "--run-tag 'harness:': a run tag needs a value after ':'."),
        (
            "model: opus",
            "--run-tag 'model: opus': a run tag cannot contain whitespace.",
        ),
        (
            "k:a,b",
            "--run-tag 'k:a,b': a run tag value cannot contain ','.",
        ),
        (
            "Model:opus",
            "--run-tag 'Model:opus': a run tag key uses a-z, 0-9, '.', '_' and '-'.",
        ),
    ],
)
def test_tag_refusals_are_typed_and_source_specific(text: str, message: str) -> None:
    with pytest.raises(RunTagError) as error:
        parse_tag(text, where="--run-tag")
    assert isinstance(error.value, RunTagError)
    assert str(error.value) == message


def test_value_length_boundary() -> None:
    assert parse_tag("k:" + "x" * 256, where="--run-tag")[1] == "x" * 256
    with pytest.raises(RunTagError, match="cannot exceed 256 characters"):
        parse_tag("k:" + "x" * 257, where="--run-tag")


def test_env_skips_blank_items_and_trims() -> None:
    assert parse_env("${unset}, model:opus".replace("${unset}", "")) == {
        "model": "opus"
    }
    assert parse_env(",,") == {}


@pytest.mark.parametrize(
    ("parse", "items", "message"),
    [
        (
            parse_env,
            "a:b, :x",
            "FUNCTUALIZE_RUN_TAGS item 2 ':x': a run tag needs a key before ':'.",
        ),
        (
            parse_env,
            "s:1,s:2",
            "FUNCTUALIZE_RUN_TAGS gives run tag key 's' twice (items 1 and 2).",
        ),
        (
            parse_config_list,
            ["a:b", ":x"],
            "[run] tags item 2 ':x': a run tag needs a key before ':'.",
        ),
        (
            parse_config_list,
            ["s:1", "s:2"],
            "[run] tags gives run tag key 's' twice (items 1 and 2).",
        ),
        (
            parse_flag_list,
            ["s:1", "s:2"],
            "run tag key 's' is given twice (--run-tag s:1, --run-tag s:2).",
        ),
    ],
)
def test_layer_refusals_are_typed(parse: object, items: object, message: str) -> None:
    with pytest.raises(RunTagError) as error:
        parse(items)  # type: ignore[operator]
    assert isinstance(error.value, RunTagError)
    assert str(error.value) == message


def test_config_type_refusals() -> None:
    with pytest.raises(RunTagError, match="global config must be a list"):
        parse_config_list("a:b")
    with pytest.raises(RunTagError, match="item 2: a run tag must be a string"):
        parse_config_list(["a:b", 42])


def test_cross_layer_override_and_immutable_result() -> None:
    tags = merge_layers(
        parse_config_list(["host:laptop", "model:old"]),
        parse_env("model:opus"),
        parse_flag_list(["model:sonnet"]),
    )
    assert tags == {"host": "laptop", "model": "sonnet"}
    assert isinstance(tags, MappingProxyType)
    with pytest.raises(TypeError):
        tags["model"] = "changed"  # type: ignore[index]


def test_maximum_counts_distinct_merged_keys() -> None:
    first = {f"k{i}": "x" for i in range(32)}
    assert len(merge_layers(first, {"k0": "y"})) == 32
    with pytest.raises(RunTagError, match="at most 32 run tags"):
        merge_layers(first, {"extra": "x"})


def _layer(path: str, kind: str, items: object) -> SettingsLayer:
    prefix = "tool.functualize" if path.endswith("pyproject.toml") else ""
    return SettingsLayer(Path(path), kind, prefix, {"run": {"tags": items}})


def test_selected_layers_merge_from_global_to_nearest_then_env_and_flag() -> None:
    layers = (
        _layer("/checkout/child/.functualize.toml", "project", ["tier:near"]),
        _layer(
            "/checkout/pyproject.toml",
            "project",
            ["host:outer", "tier:outer"],
        ),
        _layer("/home/config.toml", "global", ["host:global", "base:yes"]),
    )

    result = resolve_run_tags(
        layers,
        environ={"FUNCTUALIZE_RUN_TAGS": "tier:env,model:old"},
        flag_items=["model:new"],
    )

    assert dict(result) == {
        "host": "outer",
        "base": "yes",
        "tier": "env",
        "model": "new",
    }
    assert isinstance(result, MappingProxyType)


@pytest.mark.parametrize(
    ("path", "items", "detail"),
    [
        ("/checkout/.functualize.toml", ["a:1", ":x"], "item 2 ':x'"),
        (
            "/checkout/pyproject.toml",
            ["s:1", "s:2"],
            "gives run tag key 's' twice (items 1 and 2)",
        ),
        ("/checkout/.functualize.toml", "a:1", "must be a list of strings"),
    ],
)
def test_selected_file_refusal_names_path_and_item(
    path: str, items: object, detail: str
) -> None:
    with pytest.raises(RunTagError) as error:
        resolve_run_tags((_layer(path, "project", items),), environ={})
    assert path in str(error.value)
    assert detail in str(error.value)
    if path.endswith("pyproject.toml"):
        assert "[tool.functualize.run] tags" in str(error.value)


def test_environment_still_uses_strict_grammar_through_layer_resolver() -> None:
    with pytest.raises(RunTagError, match="FUNCTUALIZE_RUN_TAGS"):
        resolve_run_tags((), environ={"FUNCTUALIZE_RUN_TAGS": "a:1,b"})
