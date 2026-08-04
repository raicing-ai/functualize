"""What dispatch does today, pinned as literals (convergence plan A2).

`detect_mode` and `_dispatch_group` are scheduled to be rebased onto a group
trie (`trie.resolve()`), which replaces the flat prefix set, the greedy
string-matching loop, and the priority ladder in one change. A rewrite that
size needs an oracle that does not move with it.

So this file asserts against literal `(Mode, effective_args)` pairs. It is a
characterization test in the strict sense — it records what the code does, not
what it should do. `tests/cli/test_dispatch_properties.py` covers the same
function with properties; properties survive a rewrite by design, which is
exactly why they cannot catch a rewrite that changes behavior uniformly.

The value of writing it *before* the trie: when A4 lands, every line that
changes here is a `func` invocation that used to route one way and now routes
another. That diff is the review.

Two things deliberately pinned even though they look wrong — see
`TestKnownOddities`. Recording them is the point: the rebase should either
preserve them or change them on purpose, not by accident.
"""

from __future__ import annotations

import pytest

from functualize._cli.dispatch import Mode, detect_mode

# A small fixed namespace used across the corpus. Names are canonical
# (lowercase-hyphenated) because that is what registration produces.
# `overlap` is deliberately BOTH a job and a group — that collision is the
# only thing pinning the priority order, and a corpus without it lets a
# reordering of the ladder pass unnoticed. (Found by sabotaging the source:
# the first version of this file used a group-only name and caught nothing.)
JOBS = {"deploy", "build-wheel", "infra.provision", "data-ops.run-etl", "overlap"}
GROUPS = {"infra", "data-ops", "deploy-env", "deploy-env.staging", "overlap"}
ALIASES = {"d": "deploy", "bw": "build-wheel"}


def _detect(*args: str) -> tuple[Mode, list[str]]:
    """Run detect_mode over the fixed namespace, argv[0] included."""
    return detect_mode(["func", *args], JOBS, GROUPS, ALIASES)


class TestNoPositional:
    def test_bare_invocation(self) -> None:
        assert detect_mode(["func"], JOBS, GROUPS, ALIASES) == (Mode.BARE, [])

    def test_only_global_flags_is_still_bare(self) -> None:
        assert _detect("--no-dotenv") == (Mode.BARE, [])

    def test_without_job_names_bare_falls_through_to_cli(self) -> None:
        """The `job_names is None` path is the pre-enumeration compatibility
        route, and it answers CLI where the enumerated path answers BARE."""
        assert detect_mode(["func"]) == (Mode.CLI, [])


class TestGlobalOptionSkipping:
    """Finding the first positional means knowing each flag's arity."""

    def test_bool_flag_does_not_consume_the_next_token(self) -> None:
        assert _detect("--no-dotenv", "deploy") == (Mode.JOB, ["deploy"])

    def test_always_value_flag_consumes_its_value(self) -> None:
        assert _detect("--log-level", "DEBUG", "deploy") == (Mode.JOB, ["deploy"])

    def test_optional_value_flag_consumes_a_valid_value(self) -> None:
        assert _detect("--output", "json", "deploy") == (Mode.JOB, ["deploy"])

    def test_optional_value_flag_releases_an_invalid_value(self) -> None:
        """`--output deploy` is `--output` (defaulted) followed by the job —
        the lookahead is what keeps a job name from being eaten as a value."""
        assert _detect("--output", "deploy") == (Mode.JOB, ["deploy"])

    def test_equals_form_is_one_token(self) -> None:
        assert _detect("--log-level=DEBUG", "deploy") == (Mode.JOB, ["deploy"])

    def test_short_option_is_skipped(self) -> None:
        assert _detect("-h", "deploy") == (Mode.JOB, ["deploy"])


class TestPriorityLadder:
    """Priorities 1-7, in the order `detect_mode` applies them."""

    def test_1_an_existing_py_file_wins(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "deploy.py").write_text("def deploy(): ...\n")
        assert _detect("deploy.py") == (Mode.SINGLE_FILE, ["deploy.py"])

    def test_1_a_missing_py_file_does_not_win(self) -> None:
        """A `.py` name that is not on disk falls through the ladder."""
        assert _detect("nope.py") == (Mode.UNKNOWN, ["nope.py"])

    def test_2_a_builtin_returns_the_whole_arg_list(self) -> None:
        """BUILTIN is the one branch that returns `args`, not `args[i:]`, so
        preceding global flags stay attached."""
        mode, effective = detect_mode(
            ["func", "--no-dotenv", "builtin", "config"], JOBS, GROUPS, ALIASES
        )
        assert mode is Mode.BUILTIN
        assert effective == ["--no-dotenv", "builtin", "config"]

    def test_3_a_group_routes_to_group(self) -> None:
        assert _detect("infra", "provision") == (Mode.GROUP, ["infra", "provision"])

    def test_3_a_group_beats_a_job_of_the_same_name(self) -> None:
        """`overlap` is registered as both. The group check runs first, so it
        routes to GROUP and the job is unreachable by that spelling.

        This is the single assertion pinning group-over-job precedence.
        """
        assert "overlap" in JOBS and "overlap" in GROUPS
        assert _detect("overlap") == (Mode.GROUP, ["overlap"])

    def test_4_an_exact_job_name(self) -> None:
        assert _detect("deploy", "--flag") == (Mode.JOB, ["deploy", "--flag"])

    def test_4b_the_python_spelling_of_a_job(self) -> None:
        """Names register canonically; typing the function's own spelling
        still routes to JOB (normalization, not aliasing)."""
        assert _detect("build_wheel") == (Mode.JOB, ["build_wheel"])

    def test_5_a_configured_alias(self) -> None:
        assert _detect("d") == (Mode.JOB, ["d"])

    def test_5_a_direct_job_name_beats_an_alias(self) -> None:
        mode, effective = detect_mode(
            ["func", "deploy"], JOBS, GROUPS, {"deploy": "something-else"}
        )
        assert (mode, effective) == (Mode.JOB, ["deploy"])

    def test_7_anything_else_is_unknown(self) -> None:
        assert _detect("nonexistent") == (Mode.UNKNOWN, ["nonexistent"])


class TestEffectiveArgsSlicing:
    """`effective_args` is what the downstream handler receives."""

    def test_leading_globals_are_dropped_for_job_mode(self) -> None:
        assert _detect("--log-level", "DEBUG", "deploy", "--x", "1") == (
            Mode.JOB,
            ["deploy", "--x", "1"],
        )

    def test_trailing_args_survive_for_group_mode(self) -> None:
        assert _detect("infra", "provision", "--dry-run") == (
            Mode.GROUP,
            ["infra", "provision", "--dry-run"],
        )


class TestKnownOddities:
    """Behavior that looks wrong and is pinned anyway.

    A characterization test that quietly "fixes" what it finds stops being an
    oracle. These are recorded so the trie rebase decides about them on
    purpose.
    """

    def test_the_greedy_group_loop_has_no_observable_effect(self) -> None:
        """`detect_mode`'s priority-3 loop computes a longest match and then
        discards it — every exit is a `break` and neither `end` nor
        `candidate` is read again. The return is unconditionally
        `(GROUP, args[i:])`.

        So a one-segment group and a two-segment group produce identical
        slices, and the real consumption happens later in `_dispatch_group`.
        `trie.resolve()` is specified to return `(node, remaining_args)` — it
        should *replace* this loop, not preserve it.
        """
        one = _detect("deploy-env", "staging", "run")
        assert one == (Mode.GROUP, ["deploy-env", "staging", "run"])

        # Identical shape for a group that matches only its first segment.
        two = _detect("infra", "staging", "run")
        assert two == (Mode.GROUP, ["infra", "staging", "run"])

    def test_an_empty_group_set_disables_group_routing(self) -> None:
        """`len(group_names) > 0` guards priority 3, so an empty set routes a
        group name onward — to UNKNOWN, since it is not a job."""
        assert detect_mode(["func", "infra"], JOBS, set(), ALIASES) == (
            Mode.UNKNOWN,
            ["infra"],
        )

    def test_group_routing_ignores_aliases_entirely(self) -> None:
        """An alias pointing at a grouped job is not expanded before the group
        check, so it routes as a plain JOB and the group path is never
        considered."""
        mode, _ = detect_mode(["func", "ip"], JOBS, GROUPS, {"ip": "infra.provision"})
        assert mode is Mode.JOB


class TestNoneNamespaces:
    """`job_names=None` is the pre-boot compatibility route."""

    @pytest.mark.parametrize("argv", [["func", "deploy"], ["func", "whatever"]])
    def test_without_job_names_everything_is_cli(self, argv: list[str]) -> None:
        mode, _ = detect_mode(argv)
        assert mode is Mode.CLI

    def test_a_builtin_is_still_detected_without_job_names(self) -> None:
        """Priority 2 runs before the `job_names is not None` guard."""
        mode, _ = detect_mode(["func", "builtin"])
        assert mode is Mode.BUILTIN
