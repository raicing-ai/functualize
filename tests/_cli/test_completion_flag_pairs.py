"""Shell completion offers both halves of a boolean's ``--x/--no-x`` pair.

``_flag_opts`` renders a field set through the same click-param builder the CLI
parses with (``build_click_params_from_fields``). A boolean field becomes a
click pair whose positive spelling lives in ``param.opts`` and whose negative
lives in ``param.secondary_opts``; reading only ``opts`` — the historical
behaviour — offered a flag set that omitted every ``--no-`` spelling the CLI
actually accepts. These tests pin completion to the whole partition the shared
builder produced.
"""

from functualize._cli.completions.data import _flag_opts
from functualize._types.descriptors import FieldDescriptor


def _field(
    name: str, type_annotation: str = "bool", default: object = None
) -> FieldDescriptor:
    return FieldDescriptor(
        name=name,
        type_annotation=type_annotation,
        default=default,
        description=f"{name} field",
        required=False,
    )


def test_boolean_field_yields_both_pair_halves() -> None:
    # The builder renders `cache` as the click pair `--cache/--no-cache`; click
    # stores the negative half in `secondary_opts`, which the old loop never read.
    assert _flag_opts([_field("cache", default=True)]) == ["--cache", "--no-cache"]


def test_bool_with_sibling_named_no_cache_gets_no_invented_negative() -> None:
    # negative_flag_for's rule, inherited through the builder: a sibling field
    # literally named `no_cache` owns the `--no-cache` spelling, so `cache`'s
    # pair collapses to `--cache` alone. Completion must mirror that rather
    # than synthesise a `--no-` half of its own — the one `--no-cache` below is
    # `no_cache`'s own positive flag, and `--no-no-cache` is that field's real
    # (if odd) negation, exactly as click parses them.
    fields = [_field("cache", default=True), _field("no_cache", default=True)]
    assert _flag_opts(fields) == ["--cache", "--no-cache", "--no-no-cache"]


def test_non_boolean_field_is_unchanged() -> None:
    # A value-taking option is not a flag pair: no spurious negative appears.
    assert _flag_opts([_field("env", type_annotation="str", default="dev")]) == [
        "--env"
    ]


def test_completion_list_agrees_with_what_click_accepts() -> None:
    from functualize.app.adapters.click_params import build_click_params_from_fields

    fields = [
        _field("cache", default=True),
        _field("no_cache", default=True),
        _field("env", type_annotation="str", default="dev"),
        _field("retries", type_annotation="int", default=3),
    ]
    # The complete partition click will actually parse: every param's positive
    # and negative spellings, in declaration order.
    accepted = [
        opt
        for param in build_click_params_from_fields(fields)
        for opt in (*param.opts, *param.secondary_opts)
    ]
    assert _flag_opts(fields) == accepted
