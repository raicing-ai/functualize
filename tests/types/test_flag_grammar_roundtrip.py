"""Round-trip: what the grammar renders, the dispatch parser accepts.

Spec AC-10's defect class, pinned as properties: two surfaces used to keep
their own copies of the flag vocabulary, and a divergence between the render
side (the click builders) and the accept side (func's pre-boot dispatch
parser) is what ``_types/flag_grammar.py`` exists to end. Each test here
derives its expectation **from the grammar tables** — never from a second
hand-written list — and asks an actual surface whether it honours the entry.

The surfaces asked:

- ``_cli/dispatch.py`` — ``detect_mode`` (routes by skipping flags and their
  values), ``is_known_global_flag`` (the "move it before the group" error
  path), ``_extract_global_options`` (pre-boot value assignment).
- ``app/adapters/click_params.py`` — ``build_click_params_from_fields``, the
  one renderer for job fields, group options and the warm/lazy path.

The ``flag_grammar`` values are data, not behaviour; a table entry no surface
honours is invisible until a user types it. These tests walk every entry in
the tables and check the surface answers for it.
"""

from __future__ import annotations

import pytest

from functualize._cli.dispatch import (
    Mode,
    _extract_global_options,
    detect_mode,
    is_known_global_flag,
)
from functualize._types.descriptors import FieldDescriptor, GroupOptionsSpec
from functualize._types.flag_grammar import (
    GLOBAL_BOOL_FLAGS,
    GLOBAL_OPTIONS_ALWAYS_VALUE,
    GLOBAL_OPTIONS_OPTIONAL_VALUE,
    GLOBAL_OPTIONS_WITH_VALUE,
    OPTIONAL_VALUE_VALID_SET,
    flag_aliases,
    match_group_flag,
    negative_aliases,
    negative_flag_for,
)
from functualize.app.adapters.click_params import build_click_params_from_fields

_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

_ALWAYS_VALUE_SAMPLE = "some-value"  # any non-dash token is fine for dispatch


def _sample_value(flag: str) -> str:
    """A value ``_extract_global_options`` will not reject for ``flag``.

    Most value flags accept any token; ``--log-level`` validates at the end of
    extraction, ``--discovery-depth`` parses an int, and the two optional-value
    flags validate against their own grammar valid-set.
    """
    if flag == "--log-level":
        return "DEBUG"
    if flag == "--discovery-depth":
        return "3"
    valid, _default = OPTIONAL_VALUE_VALID_SET.get(flag, ((), ""))
    if valid:
        return next(iter(valid))
    return _ALWAYS_VALUE_SAMPLE


def _field(
    name: str,
    type_annotation: str = "str",
    default: object = None,
    required: bool = False,
    short_flag: str | None = None,
    from_config_model: bool = False,
) -> FieldDescriptor:
    return FieldDescriptor(
        name=name,
        type_annotation=type_annotation,
        default=default,
        description=f"{name} field",
        required=required,
        short_flag=short_flag,
        from_config_model=from_config_model,
    )


# ─── The tables are internally consistent ───────────────────────────────────


def test_always_and_optional_value_tables_partition_the_union() -> None:
    # The dispatch parser branches on the split (unconditional next-token
    # consumption vs. lookahead); an entry in both would be ambiguous, and an
    # entry in neither would be invisible to --flag=value detection.
    assert GLOBAL_OPTIONS_ALWAYS_VALUE.isdisjoint(GLOBAL_OPTIONS_OPTIONAL_VALUE)
    assert (
        GLOBAL_OPTIONS_WITH_VALUE
        == GLOBAL_OPTIONS_ALWAYS_VALUE | GLOBAL_OPTIONS_OPTIONAL_VALUE
    )


def test_bool_flags_never_take_a_value() -> None:
    # A bool in a value table would make detect_mode eat the command name after
    # it (the --force comment in dispatch.py names exactly this failure).
    assert GLOBAL_BOOL_FLAGS.isdisjoint(GLOBAL_OPTIONS_WITH_VALUE)


def test_optional_valid_set_covers_exactly_the_optional_table() -> None:
    # detect_mode and _extract_global_options both index
    # OPTIONAL_VALUE_VALID_SET[arg] for a member of
    # GLOBAL_OPTIONS_OPTIONAL_VALUE — a member without a row is a KeyError on
    # the pre-boot path, and a row without a member is dead vocabulary.
    assert set(OPTIONAL_VALUE_VALID_SET) == GLOBAL_OPTIONS_OPTIONAL_VALUE
    for flag, (valid, default) in OPTIONAL_VALUE_VALID_SET.items():
        assert valid, f"{flag} has an empty valid set"
        # The bare-flag fallback assigns the default, which is then fed back
        # through validation — so the default must itself be a legal value.
        assert default in valid, f"{flag}: default {default!r} not in its valid set"


# ─── Every value flag is accepted by the pre-boot dispatch parser ───────────


@pytest.mark.parametrize("flag", sorted(GLOBAL_OPTIONS_WITH_VALUE))
def test_dispatch_knows_every_value_flag(flag: str) -> None:
    # is_known_global_flag answers "one of func's own global flags" for the
    # misplaced-after-the-group error. Both spellings must be known.
    assert is_known_global_flag(flag)
    assert is_known_global_flag(f"{flag}=value")


@pytest.mark.parametrize("flag", sorted(GLOBAL_OPTIONS_WITH_VALUE))
def test_detect_mode_consumes_every_value_flag_with_its_value(
    flag: str,
) -> None:
    # `func <flag> <value> <job>` must route to the job: the flag and its value
    # are skipped, the job name is the first positional. For optional-value
    # flags the sample comes from the grammar's own valid set so the lookahead
    # consumes it.
    argv = ["func", flag, _sample_value(flag), "job"]
    mode, effective = detect_mode(argv, job_names={"job"})
    assert mode is Mode.JOB, f"{argv}: expected JOB, got {mode}"
    assert effective == ["job"], f"{argv}: value leaked as positional: {effective}"


def test_detect_mode_bool_flags_stand_alone() -> None:
    # A boolean never eats the next token: `func --no-dotenv deploy` routes to
    # the job, and the job name is the first positional.
    for flag in sorted(GLOBAL_BOOL_FLAGS):
        argv = ["func", flag, "job"]
        mode, effective = detect_mode(argv, job_names={"job"})
        assert mode is Mode.JOB, f"{argv}: expected JOB, got {mode}"
        assert effective == ["job"], f"{argv}: bool consumed the job name"
        assert is_known_global_flag(flag)


@pytest.mark.parametrize("flag", sorted(GLOBAL_OPTIONS_ALWAYS_VALUE))
def test_extract_assigns_value_after_every_always_value_flag(flag: str) -> None:
    # `--flag value`: both tokens consumed, the positional is the next one.
    opts, _cli = _extract_global_options(["func", flag, _sample_value(flag), "job"])
    assert opts.first_positional_index == 2, f"{flag}: value not consumed"


@pytest.mark.parametrize("flag", sorted(GLOBAL_OPTIONS_WITH_VALUE))
def test_extract_accepts_equals_spelling_for_every_value_flag(flag: str) -> None:
    # `--flag=value`: one token, value stored, positional is the next one.
    value = _sample_value(flag)
    opts, _cli = _extract_global_options(["func", f"{flag}={value}", "job"])
    assert opts.first_positional_index == 1, f"{flag}=value: not consumed as one"
    # The value must actually have been stored, not merely skipped.
    assigned = {
        name: getattr(opts, name)
        for name in (
            "log_level",
            "dotenv_file",
            "config_directory",
            "discovery_depth",
            "require_file_import",
            "require_file_prefix",
            "require_file_postfix",
            "require_file_marker",
            "require_job_prefix",
            "require_job_postfix",
            "require_job_decorators",
            "exclude",
            "perf_report",
            "perf_filter",
            "output",
            "import_libs",
        )
    }
    assert any(v is not None for v in assigned.values()), f"{flag}=value: dropped"


@pytest.mark.parametrize("flag", sorted(GLOBAL_OPTIONS_OPTIONAL_VALUE))
def test_optional_lookahead_follows_the_grammar_valid_set(flag: str) -> None:
    # The optional-value lookahead is deliberately dispatch-local behaviour,
    # but the *valid set* it consults must be the grammar's: a token inside
    # the set is consumed as the value, a token outside is left as the first
    # positional. Membership is read from OPTIONAL_VALUE_VALID_SET at runtime,
    # so the two cannot drift.
    valid, default = OPTIONAL_VALUE_VALID_SET[flag]
    value = next(iter(valid))
    opts, _cli = _extract_global_options(["func", flag, value, "job"])
    assert opts.first_positional_index == 2, f"{flag} {value}: not consumed"
    outside = "job"  # a job name is by construction not a valid value
    assert outside not in valid
    opts, _cli = _extract_global_options(["func", flag, outside])
    assert opts.first_positional_index == 1, f"{flag} {outside}: consumed wrongly"
    assert (
        getattr(opts, "perf_report" if flag == "--perf-report" else "output") == default
    )


# ─── The click builder's flag pair agrees with the negative rule ────────────


@pytest.mark.parametrize(
    "name", ["cache", "dry_run", "force", "prompt_gates", "a_long_field_name"]
)
def test_builder_renders_the_pair_negative_flag_for_names(name: str) -> None:
    # A plain boolean field renders as the click pair --x/--no-x: positive in
    # param.opts, negative in param.secondary_opts — and the negative half is
    # exactly negative_flag_for's answer. If the builder ever invented its own
    # spelling, the pre-boot matcher would stop recognising what click parses.
    param = build_click_params_from_fields(
        [_field(name, type_annotation="bool", default=True)]
    )[0]
    assert param.opts == [f"--{name.replace('_', '-')}"]
    assert param.secondary_opts == [negative_flag_for(name, {name})]


def test_builder_pair_with_short_flag_and_underscore_name() -> None:
    # The short spelling rides the positive half; the negative half still is
    # negative_flag_for's answer (hyphenated), not an underscore variant.
    field = _field("dry_run", type_annotation="bool", default=True, short_flag="-n")
    param = build_click_params_from_fields([field])[0]
    assert param.opts == ["--dry-run", "-n"]
    assert param.secondary_opts == ["--no-dry-run"]


def test_sibling_named_no_x_collapses_the_pair_to_the_positive_half() -> None:
    # negative_flag_for's ownership rule, through the builder: a sibling field
    # literally named no_cache owns the --no-cache spelling, so cache renders
    # with no negative half while no_cache renders --no-cache/--no-no-cache.
    fields = [
        _field("cache", type_annotation="bool", default=True),
        _field("no_cache", type_annotation="bool", default=True),
    ]
    params = build_click_params_from_fields(fields)
    by_opts = {param.opts[0]: param for param in params}
    assert by_opts["--cache"].secondary_opts == []
    assert by_opts["--no-cache"].secondary_opts == [
        negative_flag_for("no_cache", {"cache", "no_cache"})
    ]


def test_config_model_bool_renders_the_same_pair() -> None:
    # Group options are config-model fields (from_config_model=True) rendered
    # by the config rule — the same negative_flag_for decision must survive.
    field = _field(
        "cache", type_annotation="bool", default=True, from_config_model=True
    )
    param = build_click_params_from_fields([field])[0]
    assert param.opts == ["--cache"]
    assert param.secondary_opts == ["--no-cache"]


def test_value_field_renders_no_negative_half() -> None:
    # negative_flag_for does not know the field's type; the builder asks it
    # only for flags, so a str field must not grow a --no- half.
    param = build_click_params_from_fields(
        [_field("env", type_annotation="str", default="dev")]
    )[0]
    assert param.opts == ["--env"]
    assert param.secondary_opts == []


# ─── Aliases the grammar produces are aliases match_group_flag matches ──────


@pytest.mark.parametrize(
    "name,type_annotation",
    [
        ("dry_run", "bool"),
        ("cache", "bool"),
        ("env", "str"),
        ("max_retries", "int"),
    ],
)
def test_every_positive_alias_matches_back_to_its_field(
    name: str, type_annotation: str
) -> None:
    field = _field(name, type_annotation=type_annotation, default=None)
    spec = GroupOptionsSpec(group="deploy", class_name="DeployOptions", fields=[field])
    for alias in flag_aliases(field):
        matched = match_group_flag(alias, [spec])
        assert matched is not None, f"{alias}: grammar alias not matched back"
        matched_field, inline, negated = matched
        assert matched_field.name == name, f"{alias} resolved to {matched_field.name}"
        assert inline is None
        assert negated is False


@pytest.mark.parametrize("name", ["dry_run", "cache"])
def test_every_negative_alias_matches_back_as_a_negation(name: str) -> None:
    field = _field(name, type_annotation="bool", default=True)
    spec = GroupOptionsSpec(group="deploy", class_name="DeployOptions", fields=[field])
    for alias in negative_aliases(field, [field.name]):
        matched = match_group_flag(alias, [spec])
        assert matched is not None, f"{alias}: negative alias not matched back"
        matched_field, inline, negated = matched
        assert matched_field.name == name
        assert inline is None
        assert negated is True


def test_rendered_pair_spellings_match_back_through_the_group_matcher() -> None:
    # The full circle for one surface: build the click params a group renders,
    # then walk the mid-path matcher over every spelling click will accept.
    # A spelling the builder renders that match_group_flag does not recognise
    # is a flag the CLI accepts after the group name but cannot resolve.
    fields = [
        _field("cache", type_annotation="bool", default=True),
        _field("no_cache", type_annotation="bool", default=True),
        _field("env", type_annotation="str", default="dev"),
    ]
    spec = GroupOptionsSpec(group="deploy", class_name="DeployOptions", fields=fields)
    rendered = [
        opt
        for param in build_click_params_from_fields(fields)
        for opt in (*param.opts, *param.secondary_opts)
    ]
    # Ownership comes from the grammar's own alias sets: a rendered spelling
    # must resolve to the one field that declares it. --no-cache selects
    # no_cache positively (its own name) — not cache negatively — which is
    # exactly the collision negative_flag_for decides.
    names = [field.name for field in fields]
    resolved = [match_group_flag(spelling, [spec]) for spelling in rendered]
    assert all(m is not None for m in resolved), "a rendered spelling is unparseable"
    for spelling, matched in zip(rendered, resolved, strict=True):
        field, _inline, _negated = matched
        owners = [
            f.name
            for f in fields
            if spelling in flag_aliases(f) or spelling in negative_aliases(f, names)
        ]
        assert owners == [field.name], (
            f"{spelling}: matcher said {field.name}, grammar owners are {owners}"
        )
