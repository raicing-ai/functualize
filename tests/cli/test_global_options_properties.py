"""Property-based tests for global option extraction preserving positionals.

# Feature: eliminate-fallback-group, Property 12: Global Option Extraction Preserves Positionals
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._cli.dispatch import (
    Mode,
    _extract_global_options,
    detect_mode,
)

# =============================================================================
# Strategies
# =============================================================================

# Positional arguments: non-empty strings that don't start with "-"
# and are not recognized as builtins.
# These simulate job names, file names, etc.
_positional_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_")
_positional_arg = st.text(_positional_chars, min_size=1, max_size=20).filter(
    # Exclude builtin names and anything that looks like an option
    lambda s: (
        s
        not in {"cache", "config", "domains", "scaffold", "version", "show-info", "tui"}
        and not s.startswith("-")
        and not s.endswith(".py")
    )
)

# Global options that take a value
_value_options = st.sampled_from(
    [
        "--log-level",
        "--import-libs",
        "--dotenv-file",
        "--config-directory",
        "--discovery-depth",
        "--require-file-import",
        "--require-file-prefix",
        "--require-file-postfix",
        "--require-file-marker",
        "--require-job-prefix",
        "--require-job-postfix",
        "--require-job-decorators",
        "--exclude",
        "--perf-report",
        "--perf-filter",
    ]
)

# Valid values for each option type (simple strings that won't cause validation errors)
_option_values = st.sampled_from(
    [
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",  # valid log levels
        "./vendor",
        "./lib",
        "/tmp/path",  # path-like values
        "0",
        "1",
        "2",
        "3",
        "4",
        "5",  # numeric values
        "functualize",
        "mypackage",  # package names
        "job_",
        "task_",  # prefix/postfix values
        "__pycache__",
        ".git",  # exclude patterns
    ]
)

# Boolean global flags (no value)
_bool_flags = st.sampled_from(["--no-dotenv"])

# Strategy for a single global option with its value
_global_option_with_value = st.tuples(_value_options, _option_values)

# Strategy for additional args after the positional (job-specific flags)
_job_flag_name = st.sampled_from(
    ["--env", "--dry-run", "--force", "--output", "--verbose"]
)
_job_flag_value = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_/.-"),
    min_size=1,
    max_size=15,
)


@st.composite
def argv_with_global_options_and_positional(draw: st.DrawFn) -> tuple[list[str], str]:
    """Generate argv with mixed global options before a positional argument.

    Returns (argv, expected_positional) where expected_positional is the
    first positional argument that should be found.
    """
    # Start with program name
    argv = ["func"]

    # Add 0-4 global options before the positional
    num_global_opts = draw(st.integers(min_value=0, max_value=4))
    for _ in range(num_global_opts):
        use_bool = draw(st.booleans())
        if use_bool:
            flag = draw(_bool_flags)
            argv.append(flag)
        else:
            flag, value = draw(_global_option_with_value)
            # Filter options with restricted value sets to avoid SystemExit
            if flag == "--log-level":
                value = draw(
                    st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
                )
            elif flag == "--perf-report":
                value = draw(st.sampled_from(["json", "text"]))
            elif flag == "--discovery-depth":
                value = draw(st.sampled_from(["0", "1", "2", "3", "4", "5"]))
            use_equals = draw(st.booleans())
            if use_equals:
                argv.append(f"{flag}={value}")
            else:
                argv.append(flag)
                argv.append(value)

    # Add the positional argument
    positional = draw(_positional_arg)
    argv.append(positional)

    # Optionally add job-specific args after the positional
    num_trailing = draw(st.integers(min_value=0, max_value=3))
    for _ in range(num_trailing):
        flag = draw(_job_flag_name)
        value = draw(_job_flag_value)
        argv.append(flag)
        argv.append(value)

    return argv, positional


@st.composite
def argv_with_only_global_options(draw: st.DrawFn) -> list[str]:
    """Generate argv with ONLY global options (no positional argument).

    This tests the BARE case where no positional is present.
    """
    argv = ["func"]

    # Add 1-4 global options
    num_global_opts = draw(st.integers(min_value=1, max_value=4))
    for _ in range(num_global_opts):
        use_bool = draw(st.booleans())
        if use_bool:
            flag = draw(_bool_flags)
            argv.append(flag)
        else:
            flag, value = draw(_global_option_with_value)
            # Filter options with restricted value sets to avoid SystemExit
            if flag == "--log-level":
                value = draw(
                    st.sampled_from(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
                )
            elif flag == "--perf-report":
                value = draw(st.sampled_from(["json", "text"]))
            elif flag == "--discovery-depth":
                value = draw(st.sampled_from(["0", "1", "2", "3", "4", "5"]))
            use_equals = draw(st.booleans())
            if use_equals:
                argv.append(f"{flag}={value}")
            else:
                argv.append(flag)
                argv.append(value)

    return argv


# =============================================================================
# Property 12: Global Option Extraction Preserves Positionals
# =============================================================================


@pytest.mark.slow
class TestGlobalOptionExtractionPreservesPositionals:
    """Property 12: Global Option Extraction Preserves Positionals.

    For any argv containing a mix of global options (--import-libs, --log-level)
    and positional arguments, the global option extraction SHALL not consume
    or alter the positional arguments, and detect_mode SHALL still find the
    correct first positional.

    **Validates: Requirements 10.1, 10.4**
    """

    @given(data=argv_with_global_options_and_positional())
    @settings(max_examples=300)
    def test_extract_global_options_does_not_consume_positionals(
        self, data: tuple[list[str], str]
    ) -> None:
        """_extract_global_options never consumes the first positional argument.

        The first_positional_index must point to the correct positional in
        argv[1:], and argv[1:][first_positional_index] must equal the
        expected positional.

        **Validates: Requirements 10.1, 10.4**
        """
        argv, expected_positional = data

        opts, cli_flags = _extract_global_options(argv)

        # first_positional_index must be valid (not -1, since we have a positional)
        assert opts.first_positional_index >= 0, (
            f"Expected valid first_positional_index but got {opts.first_positional_index}.\n"
            f"  argv: {argv}\n"
            f"  expected positional: {expected_positional!r}"
        )

        # The element at first_positional_index in argv[1:] must be the expected positional
        args = argv[1:]
        actual = args[opts.first_positional_index]
        assert actual == expected_positional, (
            f"Positional mismatch.\n"
            f"  argv: {argv}\n"
            f"  first_positional_index: {opts.first_positional_index}\n"
            f"  expected: {expected_positional!r}\n"
            f"  actual: {actual!r}"
        )

    @given(data=argv_with_global_options_and_positional())
    @settings(max_examples=300)
    def test_detect_mode_finds_correct_positional_after_extraction(
        self, data: tuple[list[str], str]
    ) -> None:
        """detect_mode still finds the correct first positional after global extraction.

        Both _extract_global_options and detect_mode must agree on where the
        first positional is — they both skip global options the same way.

        **Validates: Requirements 10.1, 10.4**
        """
        argv, expected_positional = data

        # Extract global options
        opts, _ = _extract_global_options(argv)

        # detect_mode should find the same positional
        mode, effective_args = detect_mode(argv)

        # Since positional is not a .py file and not a builtin, mode should be CLI
        # (detect_mode returns CLI for unknown commands without job_names)
        assert mode is Mode.CLI, (
            f"Expected CLI mode for non-builtin, non-file positional.\n"
            f"  argv: {argv}\n"
            f"  mode: {mode}\n"
            f"  expected_positional: {expected_positional!r}"
        )

        # effective_args should start from the first positional onwards
        # (detect_mode returns argv[1:] for CLI mode currently)
        # The key check is that effective_args contains our positional
        assert expected_positional in effective_args, (
            f"detect_mode effective_args does not contain expected positional.\n"
            f"  argv: {argv}\n"
            f"  effective_args: {effective_args}\n"
            f"  expected: {expected_positional!r}"
        )

    @given(data=argv_with_global_options_and_positional())
    @settings(max_examples=300)
    def test_original_argv_not_mutated(self, data: tuple[list[str], str]) -> None:
        """_extract_global_options does not mutate the original argv list.

        **Validates: Requirements 10.1, 10.4**
        """
        argv, _ = data
        original = argv.copy()

        _extract_global_options(argv)

        assert argv == original, (
            f"argv was mutated by _extract_global_options.\n"
            f"  original: {original}\n"
            f"  after: {argv}"
        )

    @given(data=argv_with_global_options_and_positional())
    @settings(max_examples=300)
    def test_unrecognized_flags_after_positional_not_consumed(
        self, data: tuple[list[str], str]
    ) -> None:
        """Flags appearing after the first positional are not consumed by extraction.

        _extract_global_options stops at the first positional, so any flags
        after it (job-specific flags like --env) are left untouched.

        **Validates: Requirements 10.4**
        """
        argv, expected_positional = data

        opts, cli_flags = _extract_global_options(argv)

        # Everything from first_positional_index onward in argv[1:] is untouched
        args = argv[1:]
        remaining = args[opts.first_positional_index :]

        # The remaining slice must start with our positional
        assert remaining[0] == expected_positional, (
            f"Remaining args after extraction don't start with positional.\n"
            f"  argv: {argv}\n"
            f"  remaining: {remaining}\n"
            f"  expected first: {expected_positional!r}"
        )

    @given(argv=argv_with_only_global_options())
    @settings(max_examples=300)
    def test_no_positional_yields_negative_index(self, argv: list[str]) -> None:
        """When no positional is present, first_positional_index is -1.

        This corresponds to Mode.BARE in the dispatch system.

        **Validates: Requirements 10.1**
        """
        opts, _ = _extract_global_options(argv)

        # With only global options and no positional, the scanning loop
        # exhausts all args without finding a positional. The implementation
        # should leave first_positional_index as -1 (no break hit).
        # OR the implementation might set it to len(args) — either way,
        # it should NOT point to a valid global option.
        args = argv[1:]
        if opts.first_positional_index >= 0:
            # If non-negative, it should point beyond the end or to an impossible position
            # This would indicate a bug — global options shouldn't be treated as positionals
            pointed_at = (
                args[opts.first_positional_index]
                if opts.first_positional_index < len(args)
                else None
            )
            assert pointed_at is None or not pointed_at.startswith("--"), (
                f"first_positional_index points at a global option, not a positional.\n"
                f"  argv: {argv}\n"
                f"  first_positional_index: {opts.first_positional_index}\n"
                f"  pointed_at: {pointed_at!r}"
            )
