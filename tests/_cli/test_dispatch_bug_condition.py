"""Bug condition exploration tests for optional-value flag consumption (Bug A).

These tests encode the EXPECTED (correct) behavior — they are designed to FAIL
on unfixed code to confirm the bug exists.

Bug A: --perf-report and --output in _GLOBAL_OPTIONS_WITH_VALUE unconditionally
consume the next token as their value. When the next token is a job name (not a
valid format value), it gets consumed as the flag value, leaving no positional
for detect_mode(), which then incorrectly returns Mode.BARE instead of Mode.JOB.

**Validates: Requirements 1.1, 1.3, 1.6, 2.1, 2.2, 2.8**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.dispatch import (
    _OPTIONAL_VALUE_VALID_SET,
    Mode,
    _extract_global_options,
    detect_mode,
)

# =============================================================================
# Strategies
# =============================================================================

# Valid format values for each optional-value flag, read from the flag table
# itself. These were hardcoded copies and had drifted: --output's list still
# said {"json", "text", "none"} long after the real vocabulary became
# {"auto", "json", "ndjson", "raw", "none"}, so the "non-format token"
# strategies below could emit a value that *is* a format and the assertions
# would be testing the opposite of what they claim.
_PERF_REPORT_VALID, _PERF_REPORT_DEFAULT = _OPTIONAL_VALUE_VALID_SET["--perf-report"]
_OUTPUT_VALID, _OUTPUT_DEFAULT = _OPTIONAL_VALUE_VALID_SET["--output"]

# Characters safe for job-name-like tokens
_identifier_first_char = st.sampled_from("abcdefghijklmnopqrstuvwxyz")
_identifier_rest_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_")

# Builtins to avoid (these would route to BUILTIN mode, not JOB)
_BUILTIN_NAMES = frozenset(
    {"cache", "config", "domains", "scaffold", "version", "show-info", "tui"}
)

# Job-name-like strings that are NOT valid format values for --perf-report
_non_perf_format_job_name = st.builds(
    lambda first, rest: first + rest,
    _identifier_first_char,
    st.text(_identifier_rest_chars, min_size=2, max_size=12),
).filter(
    lambda name: (
        name not in _PERF_REPORT_VALID
        and name not in _OUTPUT_VALID
        and name not in _BUILTIN_NAMES
        and not name.endswith(".py")
    )
)

# Job-name-like strings that are NOT valid format values for --output
_non_output_format_job_name = st.builds(
    lambda first, rest: first + rest,
    _identifier_first_char,
    st.text(_identifier_rest_chars, min_size=2, max_size=12),
).filter(
    lambda name: (
        name not in _OUTPUT_VALID
        and name not in _PERF_REPORT_VALID
        and name not in _BUILTIN_NAMES
        and not name.endswith(".py")
    )
)


# =============================================================================
# Property 1: Bug Condition — Optional-Value Flag Consumes Positional
# =============================================================================


@pytest.mark.slow
class TestBugConditionOptionalValueConsumption:
    """Property 1: Bug Condition - Optional-Value Flag Consumes Positional.

    For any argv where --perf-report or --output is followed by a token that
    is NOT in their valid format set AND the token does not start with "-",
    the token MUST appear in effective_args from detect_mode() (i.e., it is
    NOT consumed as the flag value), and the flag SHALL receive its default
    value ("text" for --perf-report, "none" for --output).

    These tests encode the EXPECTED correct behavior. They are expected to
    FAIL on the unfixed code, confirming Bug A exists.

    **Validates: Requirements 1.1, 1.3, 1.6, 2.1, 2.2, 2.8**
    """

    @given(job_name=_non_perf_format_job_name)
    @settings(max_examples=50)
    def test_perf_report_does_not_consume_non_format_token(self, job_name: str) -> None:
        """--perf-report followed by a non-format token preserves the token.

        When --perf-report is followed by a token not in {"text", "json"},
        the flag should get default "text" and the token should remain as a
        positional argument.

        **Validates: Requirements 2.1, 2.2**
        """
        argv = ["func", "--perf-report", job_name]
        opts, _ = _extract_global_options(argv)

        # EXPECTED: flag gets default "text", token is NOT consumed
        assert opts.perf_report == "text", (
            f"Expected perf_report='text' (default) when followed by "
            f"non-format token '{job_name}', got perf_report='{opts.perf_report}'"
        )

    @given(job_name=_non_perf_format_job_name)
    @settings(max_examples=50)
    def test_perf_report_non_format_token_detected_as_job(self, job_name: str) -> None:
        """detect_mode routes to Mode.JOB when --perf-report precedes a job name.

        When --perf-report is followed by a known job name (not a format value),
        detect_mode should identify it as Mode.JOB with the job name in
        effective_args.

        **Validates: Requirements 1.1, 1.3**
        """
        argv = ["func", "--perf-report", job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, (
            f"Expected Mode.JOB for argv={argv} with job_names={job_names}, got {mode}"
        )
        assert job_name in effective_args, (
            f"Expected '{job_name}' in effective_args={effective_args}"
        )

    @given(job_name=_non_output_format_job_name)
    @settings(max_examples=50)
    def test_output_does_not_consume_non_format_token(self, job_name: str) -> None:
        """--output followed by a non-format token preserves the token.

        When --output is followed by a token that is not one of its valid
        format values, the flag should fall back to its declared default and
        the token should remain a positional argument.

        NOTE: On unfixed code, this fails because the token IS consumed as the
        --output value. The existing validation then rejects it via SystemExit(1).
        The fix should prevent consumption entirely, so no SystemExit occurs.

        **Validates: Requirements 2.8**
        """
        argv = ["func", "--output", job_name]

        # On UNFIXED code: token is consumed as --output value, then validation
        # rejects it with SystemExit(1). This confirms the bug — the token
        # should NOT be consumed in the first place.
        try:
            opts, _ = _extract_global_options(argv)
        except SystemExit:
            # Bug confirmed: token was consumed as --output value and rejected.
            # The correct behavior is to NOT consume it at all.
            pytest.fail(
                f"SystemExit raised because '{job_name}' was consumed as "
                f"--output value and rejected by validation. The token should "
                f"NOT be consumed as the flag value."
            )

        # EXPECTED (after fix): flag falls back to its declared default and
        # the token is NOT consumed. The default is read from the flag table
        # rather than spelled here — this assertion used to hardcode "none"
        # and broke when the real default became "auto".
        assert opts.output == _OUTPUT_DEFAULT, (
            f"Expected output={_OUTPUT_DEFAULT!r} (declared default) when "
            f"followed by non-format token '{job_name}', got "
            f"output='{opts.output}'"
        )

    @given(job_name=_non_output_format_job_name)
    @settings(max_examples=50)
    def test_output_non_format_token_detected_as_job(self, job_name: str) -> None:
        """detect_mode routes to Mode.JOB when --output precedes a job name.

        When --output is followed by a known job name (not a format value),
        detect_mode should identify it as Mode.JOB with the job name in
        effective_args.

        NOTE: On unfixed code, detect_mode unconditionally consumes the next
        token after --output (i += 2), so the job name disappears and mode
        resolves to BARE instead of JOB.

        **Validates: Requirements 1.6, 2.8**
        """
        argv = ["func", "--output", job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, (
            f"Expected Mode.JOB for argv={argv} with job_names={job_names}, got {mode}"
        )
        assert job_name in effective_args, (
            f"Expected '{job_name}' in effective_args={effective_args}"
        )

    def test_perf_report_at_end_of_argv_gets_default(self) -> None:
        """--perf-report at end of argv (no next token) should get default "text".

        When --perf-report is the last token, it should receive its default
        value "text" rather than being left unset.

        **Validates: Requirements 2.2**
        """
        argv = ["func", "--perf-report"]
        opts, _ = _extract_global_options(argv)

        assert opts.perf_report == "text", (
            f"Expected perf_report='text' (default) when flag is at end of argv, "
            f"got perf_report={opts.perf_report!r}"
        )

    def test_detect_mode_perf_report_followed_by_concrete_job(self) -> None:
        """Concrete case: func --perf-report forecast → Mode.JOB.

        **Validates: Requirements 1.1, 1.3**
        """
        argv = ["func", "--perf-report", "forecast"]
        job_names = {"forecast"}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, (
            f"Expected Mode.JOB for 'func --perf-report forecast' "
            f"with job_names={{'forecast'}}, got {mode}"
        )
        assert "forecast" in effective_args, (
            f"Expected 'forecast' in effective_args={effective_args}"
        )

    def test_detect_mode_output_followed_by_concrete_job(self) -> None:
        """Concrete case: func --output forecast → Mode.JOB.

        NOTE: detect_mode does NOT call _extract_global_options and therefore
        does NOT hit the --output validation. It simply skips the flag + value
        unconditionally (i += 2), consuming "forecast" as the flag value.

        **Validates: Requirements 1.6, 2.8**
        """
        argv = ["func", "--output", "forecast"]
        job_names = {"forecast"}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, (
            f"Expected Mode.JOB for 'func --output forecast' "
            f"with job_names={{'forecast'}}, got {mode}"
        )
        assert "forecast" in effective_args, (
            f"Expected 'forecast' in effective_args={effective_args}"
        )
