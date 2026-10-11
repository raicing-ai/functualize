"""The pre-boot arity parity instrument (AC8).

One rule — a value-required flag consumes the next token as its value unless
a pre-boot-owned token stands there — is stated once
(``value_required_takes_next`` in ``_cli/dispatch.py``) and must be answered
the same way by all three pre-boot scans:

- ``detect_mode`` — routing: which token is the first positional;
- ``_extract_global_options`` — values: which token is assigned to the flag;
- ``version_requested`` — the ``--version`` fast path: which tokens the
  prefix walk skips before the first positional.

The rule cannot be shared as a walker (the three scans produce three
different things — a mode, a value map, a boolean), so the enforcement
mechanism is this parity test: for every value-required flag and every token
shape, the three walks must agree on where the value ends and the command
begins, and a missing value must be a usage error in all of them, never a
silent re-route of the token that follows.

The production order makes the agreement load-bearing:
``version_requested`` answers first in ``_run_cli``, then
``_extract_global_options`` — which exits 2 on a missing value — and only
then does ``detect_mode`` classify what is left. A scan that disagreed would
either print a version for an invocation that is a usage error, or route a
flag's value as a command: the second is the misdiagnosis class this feature
exists to end.
"""

from __future__ import annotations

import pytest

from functualize._cli.dispatch import (
    Mode,
    _extract_global_options,
    detect_mode,
    invalid_value_message,
    is_reserved_pre_boot_token,
    missing_value_message,
    version_requested,
)
from functualize._types.flag_grammar import (
    GLOBAL_OPTIONS_ALWAYS_VALUE,
    OPTIONAL_VALUE_VALID_SET,
)

_JOB = "somejob"


def _sample_value(flag: str) -> str:
    """A token ``_extract_global_options`` will accept for ``flag``.

    ``--log-level`` validates at the end of extraction, ``--discovery-depth``
    parses an int, and the selection-table flags check their own valid set.
    """
    if flag == "--log-level":
        return "DEBUG"
    if flag == "--discovery-depth":
        return "3"
    valid_entry = OPTIONAL_VALUE_VALID_SET.get(flag)
    if valid_entry is not None:
        return next(iter(valid_entry[0]))
    return "somevalue"


#: Token shapes a value-required flag MUST take as its value (B2): an
#: unrecognized dash token and a negative number are value candidates, not
#: flags — only a pre-boot-owned token is refused.
_DASH_CANDIDATES = ["-x", "-1"]

#: Followers that mean the value is missing (B3): end of argv, the version
#: fast path (owned by the pre-boot layer, absent from ``GLOBAL_BOOL_FLAGS``),
#: and an ordinary boolean global.
_MISSING_FOLLOWERS = [
    pytest.param(None, id="end-of-argv"),
    pytest.param("--version", id="version"),
    pytest.param("--force", id="bool-global"),
]


def _version_tail(follower: str | None) -> list[str]:
    """The argv tail ``version_requested`` sees for a missing-value case."""
    if follower is None:
        return []
    if follower == "--version":
        return ["--version"]
    return [follower, "--version"]


# ─── The three scans agree on where the value ends ──────────────────────────


@pytest.mark.parametrize("flag", sorted(GLOBAL_OPTIONS_ALWAYS_VALUE))
def test_all_three_scans_take_the_sample_value(flag: str) -> None:
    # detect_mode consumes the pair: the job after it is the first positional.
    mode, effective = detect_mode(
        ["func", flag, _sample_value(flag), _JOB], job_names={_JOB}
    )
    assert mode is Mode.JOB, f"{flag}: value leaked into routing ({effective})"
    assert effective == [_JOB]

    # _extract_global_options assigns the token to the flag: the first
    # positional index moves past the pair.
    opts, _cli_flags = _extract_global_options(
        ["func", flag, _sample_value(flag), _JOB]
    )
    assert opts.first_positional_index == 2, f"{flag}: value not assigned"

    # version_requested skips the pair: a --version after it still fires.
    assert version_requested([flag, _sample_value(flag), "--version"]) is True


@pytest.mark.parametrize("flag", sorted(GLOBAL_OPTIONS_ALWAYS_VALUE))
@pytest.mark.parametrize("token", _DASH_CANDIDATES)
def test_routing_and_version_scans_take_dash_tokens_as_values(
    flag: str, token: str
) -> None:
    # The two scans that do not validate values still consume an
    # unrecognized dash token and a negative number (B2, AC5).
    # _extract_global_options validates, so its answer for these tokens is
    # the invalid-value sentence, not a routing question — pinned for the
    # selection flag below.
    mode, effective = detect_mode(["func", flag, token, _JOB], job_names={_JOB})
    assert mode is Mode.JOB, f"{flag} {token}: dash token leaked ({effective})"
    assert effective == [_JOB]

    assert version_requested([flag, token, "--version"]) is True


@pytest.mark.parametrize("flag", sorted(GLOBAL_OPTIONS_ALWAYS_VALUE))
@pytest.mark.parametrize("follower", _MISSING_FOLLOWERS)
def test_a_missing_value_is_a_usage_error_in_every_scan(
    flag: str, follower: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    # Nothing follows, or a pre-boot-owned token does: the value is missing.
    assert follower is None or is_reserved_pre_boot_token(follower)

    tail = [flag] if follower is None else [flag, follower, _JOB]
    argv = ["func", *tail]

    # _extract_global_options exits 2 with the missing-value sentence —
    # never assigns, never leaves the follower standing as a command.
    with pytest.raises(SystemExit) as exc_info:
        _extract_global_options(argv)
    assert exc_info.value.code == 2, f"{flag} {follower}: not exit 2"
    stderr = capsys.readouterr().err
    assert stderr.splitlines()[0] == missing_value_message(flag)

    # version_requested rejects the prefix: the invocation is a usage error,
    # so --version must not fire even when it is the follower (AC6).
    assert version_requested([flag, *_version_tail(follower)]) is False

    # detect_mode did not consume the follower as the flag's value. For
    # `--version` that is observable: an unconsumed --version becomes the
    # first positional, so the mode is UNKNOWN, not JOB. For a boolean
    # global both walks reach the job either way — production order makes
    # the question moot (extraction has already exited), so only the
    # observable half is asserted.
    if follower == "--version":
        mode, effective = detect_mode(argv, job_names={_JOB})
        assert mode is Mode.UNKNOWN, f"{flag}: --version consumed as a value"
        assert effective == ["--version", _JOB]


# ─── The sentence shapes, agreed with the tables ────────────────────────────


def test_selection_table_flags_name_their_accepted_values() -> None:
    # A flag with a selection table carries the repair on the same line, and
    # the values are the grammar's own, sorted and comma-joined.
    for flag, (values, _default) in OPTIONAL_VALUE_VALID_SET.items():
        expected = (
            f"Error: {flag} requires a value: one of {{{', '.join(sorted(values))}}}."
        )
        assert missing_value_message(flag) == expected


def test_plain_value_flags_get_the_plain_sentence() -> None:
    plain = GLOBAL_OPTIONS_ALWAYS_VALUE - set(OPTIONAL_VALUE_VALID_SET)
    assert plain, "every value flag grew a selection table?"
    for flag in sorted(plain):
        assert missing_value_message(flag) == f"Error: {flag} requires a value."


def test_the_documented_sentences_are_exact() -> None:
    # The two contracts.md §3 spellings and the invalid-value sibling, pinned
    # verbatim so format drift (separator, trailing period) cannot pass.
    assert (
        missing_value_message("--emit-format")
        == "Error: --emit-format requires a value: one of "
        "{auto, json, ndjson, none, raw}."
    )
    assert (
        missing_value_message("--config-directory")
        == "Error: --config-directory requires a value."
    )
    assert (
        invalid_value_message("--emit-format", "shortcut")
        == "Error: --emit-format must be one of "
        "{auto, json, ndjson, none, raw}, got 'shortcut'."
    )


def test_an_unrecognized_dash_token_gets_the_invalid_value_sentence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # AC5: `-x` after a value-required flag is its value — an invalid one for
    # a selection-table flag, reported with the flag's valid set.
    with pytest.raises(SystemExit) as exc_info:
        _extract_global_options(["func", "--emit-format", "-x", _JOB])
    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert stderr.splitlines()[0] == invalid_value_message("--emit-format", "-x")


def test_a_negative_number_reaches_the_depth_parser() -> None:
    # AC5's second half: -1 is a value candidate, so --discovery-depth -1
    # parses rather than routing -1 anywhere.
    opts, _cli_flags = _extract_global_options(["func", "--discovery-depth", "-1"])
    assert opts.discovery_depth == -1
    assert version_requested(["--discovery-depth", "-1", "--version"]) is True
