"""Preservation property tests for non-buggy flag inputs.

These tests capture the CURRENT CORRECT behavior for inputs where the bug
condition does NOT hold. They MUST PASS on unfixed code and serve as
regression guards after the fix is applied.

Non-buggy inputs include:
- Always-consumes-value flags (--log-level, --config-directory, etc.) followed
  by their value and then a positional
- Boolean flags (--no-dotenv) with a positional
- Equals-style flags (--perf-report=text, --output=json) with a positional
- Explicit valid values for optional-value flags (--perf-report text)

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.dispatch import (
    Mode,
    _extract_global_options,
    detect_mode,
)

# =============================================================================
# Strategies
# =============================================================================

# Characters safe for identifiers (job names, values)
_identifier_first_char = st.sampled_from("abcdefghijklmnopqrstuvwxyz")
_identifier_rest_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_")

# Builtins to avoid (would route to BUILTIN, not JOB)
_BUILTIN_NAMES = frozenset(
    {"cache", "config", "domains", "scaffold", "version", "show-info", "tui"}
)

# Valid log levels that won't cause SystemExit
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Job name strategy: lowercase identifiers not colliding with builtins or flags
_job_name = st.builds(
    lambda first, rest: first + rest,
    _identifier_first_char,
    st.text(_identifier_rest_chars, min_size=2, max_size=12),
).filter(
    lambda name: (
        name not in _BUILTIN_NAMES
        and not name.startswith("-")
        and not name.endswith(".py")
        and name not in {"text", "json", "none"}
    )  # avoid valid format values
)

# Arbitrary string values for flags (no leading dash, non-empty)
_arbitrary_value = st.text(
    st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_./-"),
    min_size=1,
    max_size=15,
).filter(lambda v: not v.startswith("-"))

# Discovery depth values (valid integers as strings)
_discovery_depth_value = st.integers(min_value=0, max_value=10).map(str)

# Always-consumes-value flags (these unconditionally eat the next token)
_ALWAYS_CONSUMES_VALUE_FLAGS = [
    "--log-level",
    "--config-directory",
    "--perf-filter",
    "--discovery-depth",
    "--exclude",
    "--import-libs",
    "--require-file-import",
    "--require-file-prefix",
    "--require-file-postfix",
    "--require-file-marker",
    "--require-job-prefix",
    "--require-job-postfix",
    "--require-job-decorators",
    "--dotenv-file",
]

# Strategy for a single always-consumes-value flag with a safe value
_always_value_flag_strategy = st.sampled_from(_ALWAYS_CONSUMES_VALUE_FLAGS)

# Safe values per flag to avoid validation errors
_SAFE_VALUES = {
    "--log-level": st.sampled_from(_VALID_LOG_LEVELS),
    "--config-directory": st.sampled_from(["./conf", "/tmp/cfg", "./mydir"]),
    "--perf-filter": st.sampled_from(["pattern", "my_func", "test_*"]),
    "--discovery-depth": _discovery_depth_value,
    "--exclude": st.sampled_from(["*.tmp", "__pycache__", ".git"]),
    "--import-libs": st.sampled_from(["./lib", "./vendor", "/opt/libs"]),
    "--require-file-import": st.sampled_from(["functualize", "mypackage"]),
    "--require-file-prefix": st.sampled_from(["job_", "task_", "fn_"]),
    "--require-file-postfix": st.sampled_from(["_task", "_job", "_fn"]),
    "--require-file-marker": st.sampled_from(["__functualize__", "__jobs__"]),
    "--require-job-prefix": st.sampled_from(["run_", "job_", "do_"]),
    "--require-job-postfix": st.sampled_from(["_job", "_task", "_fn"]),
    "--require-job-decorators": st.sampled_from(["@job", "@task", "@workflow"]),
    "--dotenv-file": st.sampled_from([".env.local", ".env.prod", ".env"]),
}


def _safe_value_for_flag(flag: str) -> st.SearchStrategy[str]:
    """Return a strategy that generates safe values for the given flag."""
    return _SAFE_VALUES.get(flag, _arbitrary_value)


# =============================================================================
# Property Tests
# =============================================================================


@pytest.mark.slow
class TestPreservationAlwaysConsumesValueFlags:
    """Property 2: Preservation — Always-consumes-value flags route correctly.

    For all argv with always-consumes-value flags followed by an arbitrary
    value and a job name, detect_mode() returns Mode.JOB with the job name
    in effective_args.

    **Validates: Requirements 3.3, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13**
    """

    @given(
        flag=st.sampled_from(["--log-level"]),
        value=st.sampled_from(_VALID_LOG_LEVELS),
        job_name=_job_name,
    )
    def test_log_level_flag_routes_job_correctly(
        self, flag: str, value: str, job_name: str
    ) -> None:
        """--log-level VALUE job_name → Mode.JOB with job_name in effective_args.

        **Validates: Requirements 3.3**
        """
        argv = ["func", flag, value, job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args, (
            f"Expected '{job_name}' in effective_args={effective_args}"
        )

    @given(
        flag=st.sampled_from(["--config-directory"]),
        value=st.sampled_from(["./conf", "/tmp/cfg", "./mydir", "/opt/config"]),
        job_name=_job_name,
    )
    def test_config_directory_flag_routes_job_correctly(
        self, flag: str, value: str, job_name: str
    ) -> None:
        """--config-directory VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.8**
        """
        argv = ["func", flag, value, job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args

    @given(
        flag=st.sampled_from(["--perf-filter"]),
        value=st.sampled_from(["pattern", "my_func", "test_*", "deploy"]),
        job_name=_job_name,
    )
    def test_perf_filter_flag_routes_job_correctly(
        self, flag: str, value: str, job_name: str
    ) -> None:
        """--perf-filter VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.9**
        """
        argv = ["func", flag, value, job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args

    @given(
        flag=st.sampled_from(["--discovery-depth"]),
        value=_discovery_depth_value,
        job_name=_job_name,
    )
    def test_discovery_depth_flag_routes_job_correctly(
        self, flag: str, value: str, job_name: str
    ) -> None:
        """--discovery-depth VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.10**
        """
        argv = ["func", flag, value, job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args

    @given(
        flag=st.sampled_from(["--exclude"]),
        value=st.sampled_from(["*.tmp", "__pycache__", ".git", "*.pyc"]),
        job_name=_job_name,
    )
    def test_exclude_flag_routes_job_correctly(
        self, flag: str, value: str, job_name: str
    ) -> None:
        """--exclude VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.11**
        """
        argv = ["func", flag, value, job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args

    @given(
        flag=st.sampled_from(["--import-libs"]),
        value=st.sampled_from(["./lib", "./vendor", "/opt/libs"]),
        job_name=_job_name,
    )
    def test_import_libs_flag_routes_job_correctly(
        self, flag: str, value: str, job_name: str
    ) -> None:
        """--import-libs VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.12**
        """
        argv = ["func", flag, value, job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args

    @given(
        flag=st.sampled_from(
            [
                "--require-file-import",
                "--require-file-prefix",
                "--require-file-postfix",
                "--require-job-decorators",
                "--dotenv-file",
            ]
        ),
        job_name=_job_name,
    )
    def test_other_always_value_flags_route_job_correctly(
        self, flag: str, job_name: str
    ) -> None:
        """Other always-consumes-value flags → Mode.JOB.

        **Validates: Requirements 3.13**
        """
        # Use a safe value that won't collide with anything
        value = "safe_value_123"
        argv = ["func", flag, value, job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args


@pytest.mark.slow
class TestPreservationBooleanFlags:
    """Property 2: Preservation — Boolean flags don't affect routing.

    For all argv with boolean flags (--no-dotenv) and a job name,
    detect_mode() returns Mode.JOB.

    **Validates: Requirements 3.6**
    """

    @given(job_name=_job_name)
    def test_no_dotenv_flag_routes_job_correctly(self, job_name: str) -> None:
        """--no-dotenv job_name → Mode.JOB with job_name in effective_args.

        **Validates: Requirements 3.6**
        """
        argv = ["func", "--no-dotenv", job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args

    @given(job_name=_job_name)
    def test_no_dotenv_extract_sets_flag(self, job_name: str) -> None:
        """--no-dotenv job_name → no_dotenv=True, first_positional_index=1.

        **Validates: Requirements 3.6**
        """
        argv = ["func", "--no-dotenv", job_name]

        opts, _ = _extract_global_options(argv)

        assert opts.no_dotenv is True
        assert opts.first_positional_index == 1


@pytest.mark.slow
class TestPreservationEqualsStyleSyntax:
    """Property 2: Preservation — Equals-style flags parse correctly.

    For all argv with =-style syntax (--perf-report=text, --output=json) and
    a job name, detect_mode() returns Mode.JOB with correct parsing.

    **Validates: Requirements 3.1, 3.2, 3.7**
    """

    @given(
        format_value=st.sampled_from(["text", "json"]),
        job_name=_job_name,
    )
    def test_perf_report_equals_syntax_routes_job(
        self, format_value: str, job_name: str
    ) -> None:
        """--perf-report=VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.7**
        """
        argv = ["func", f"--perf-report={format_value}", job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args

    @given(
        format_value=st.sampled_from(["text", "json"]),
        job_name=_job_name,
    )
    def test_perf_report_equals_syntax_parses_value(
        self, format_value: str, job_name: str
    ) -> None:
        """--perf-report=VALUE job_name → perf_report=VALUE, first_positional_index=1.

        **Validates: Requirements 3.7**
        """
        argv = ["func", f"--perf-report={format_value}", job_name]

        opts, _ = _extract_global_options(argv)

        assert opts.perf_report == format_value
        assert opts.first_positional_index == 1

    @given(
        format_value=st.sampled_from(["json", "text", "none"]),
        job_name=_job_name,
    )
    def test_output_equals_syntax_routes_job(
        self, format_value: str, job_name: str
    ) -> None:
        """--output=VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.7**
        """
        argv = ["func", f"--output={format_value}", job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args

    @given(
        format_value=st.sampled_from(["json", "text", "none"]),
        job_name=_job_name,
    )
    def test_output_equals_syntax_parses_value(
        self, format_value: str, job_name: str
    ) -> None:
        """--output=VALUE job_name → output=VALUE, first_positional_index=1.

        **Validates: Requirements 3.7**
        """
        argv = ["func", f"--output={format_value}", job_name]

        opts, _ = _extract_global_options(argv)

        assert opts.output == format_value
        assert opts.first_positional_index == 1

    @given(job_name=_job_name)
    def test_perf_report_explicit_valid_value_consumes_correctly(
        self, job_name: str
    ) -> None:
        """--perf-report text job_name → perf_report="text", first_positional_index=2.

        When an explicit valid format value ("text" or "json") follows --perf-report,
        it IS consumed as the flag's value. This behavior must be preserved.

        **Validates: Requirements 3.1, 3.2**
        """
        for format_value in ("text", "json"):
            argv = ["func", "--perf-report", format_value, job_name]
            opts, _ = _extract_global_options(argv)

            assert opts.perf_report == format_value, (
                f"Expected perf_report='{format_value}' for argv={argv}, "
                f"got '{opts.perf_report}'"
            )
            assert opts.first_positional_index == 2, (
                f"Expected first_positional_index=2 for argv={argv}, "
                f"got {opts.first_positional_index}"
            )

    @given(job_name=_job_name)
    def test_perf_report_explicit_value_routes_to_bare_without_positional(
        self, job_name: str
    ) -> None:
        """--perf-report text (no trailing positional) → Mode.BARE.

        When --perf-report consumes a valid format value and there's no
        remaining positional, mode should be BARE.

        **Validates: Requirements 3.1, 3.2**
        """
        for format_value in ("text", "json"):
            argv = ["func", "--perf-report", format_value]
            mode, effective_args = detect_mode(argv, job_names={job_name})

            assert mode is Mode.BARE, f"Expected Mode.BARE for argv={argv}, got {mode}"
            assert effective_args == []


@pytest.mark.slow
class TestPreservationMultipleFlags:
    """Property 2: Preservation — Multiple non-buggy flags with a trailing positional.

    For random orderings of multiple non-buggy flags with a trailing positional,
    mode detection returns Mode.JOB.

    **Validates: Requirements 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**
    """

    @given(job_name=_job_name)
    def test_bare_invocation_returns_bare(self, job_name: str) -> None:
        """func (no args) → Mode.BARE.

        **Validates: Requirements 3.5**
        """
        argv = ["func"]
        mode, effective_args = detect_mode(argv, job_names={job_name})

        assert mode is Mode.BARE
        assert effective_args == []

    @given(job_name=_job_name)
    def test_just_job_name_returns_job(self, job_name: str) -> None:
        """func job_name → Mode.JOB.

        **Validates: Requirements 3.4**
        """
        argv = ["func", job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB
        assert job_name in effective_args

    @given(
        log_level=st.sampled_from(_VALID_LOG_LEVELS),
        job_name=_job_name,
    )
    def test_log_level_and_no_dotenv_combined(
        self, log_level: str, job_name: str
    ) -> None:
        """--log-level VALUE --no-dotenv job_name → Mode.JOB.

        **Validates: Requirements 3.3, 3.6**
        """
        argv = ["func", "--log-level", log_level, "--no-dotenv", job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB
        assert job_name in effective_args

    @given(
        log_level=st.sampled_from(_VALID_LOG_LEVELS),
        perf_format=st.sampled_from(["text", "json"]),
        job_name=_job_name,
    )
    def test_log_level_perf_report_equals_no_dotenv_combined(
        self, log_level: str, perf_format: str, job_name: str
    ) -> None:
        """--log-level VALUE --perf-report=FORMAT --no-dotenv job_name → Mode.JOB.

        **Validates: Requirements 3.3, 3.6, 3.7**
        """
        argv = [
            "func",
            "--log-level",
            log_level,
            "--no-dotenv",
            f"--perf-report={perf_format}",
            job_name,
        ]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB
        assert job_name in effective_args

    @given(
        log_level=st.sampled_from(_VALID_LOG_LEVELS),
        depth=_discovery_depth_value,
        job_name=_job_name,
    )
    def test_log_level_and_discovery_depth_combined(
        self, log_level: str, depth: str, job_name: str
    ) -> None:
        """--log-level VALUE --discovery-depth VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.3, 3.10**
        """
        argv = ["func", "--log-level", log_level, "--discovery-depth", depth, job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB
        assert job_name in effective_args

    @given(
        config_dir=st.sampled_from(["./conf", "/tmp/cfg"]),
        perf_filter=st.sampled_from(["pattern", "my_func"]),
        job_name=_job_name,
    )
    def test_config_dir_and_perf_filter_combined(
        self, config_dir: str, perf_filter: str, job_name: str
    ) -> None:
        """--config-directory VALUE --perf-filter VALUE job_name → Mode.JOB.

        **Validates: Requirements 3.8, 3.9**
        """
        argv = [
            "func",
            "--config-directory",
            config_dir,
            "--perf-filter",
            perf_filter,
            job_name,
        ]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB
        assert job_name in effective_args

    @given(
        data=st.data(),
        job_name=_job_name,
    )
    def test_random_ordering_multiple_non_buggy_flags(
        self, data: st.DataObject, job_name: str
    ) -> None:
        """Random orderings of multiple non-buggy flags with trailing positional → Mode.JOB.

        Generates a random subset of non-buggy flag combinations (always-value flags,
        boolean flags, equals-style flags) in random order, appends a job name,
        and asserts Mode.JOB.

        **Validates: Requirements 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**
        """
        # Build a random set of flag tokens
        flag_tokens: list[str] = []

        # Optionally add --log-level
        if data.draw(st.booleans()):
            level = data.draw(st.sampled_from(_VALID_LOG_LEVELS))
            flag_tokens.extend(["--log-level", level])

        # Optionally add --no-dotenv
        if data.draw(st.booleans()):
            flag_tokens.append("--no-dotenv")

        # Optionally add --config-directory
        if data.draw(st.booleans()):
            flag_tokens.extend(["--config-directory", "./conf"])

        # Optionally add --discovery-depth
        if data.draw(st.booleans()):
            depth = data.draw(_discovery_depth_value)
            flag_tokens.extend(["--discovery-depth", depth])

        # Optionally add --perf-filter
        if data.draw(st.booleans()):
            flag_tokens.extend(["--perf-filter", "pattern"])

        # Optionally add --perf-report=FORMAT (equals style only)
        if data.draw(st.booleans()):
            fmt = data.draw(st.sampled_from(["text", "json"]))
            flag_tokens.append(f"--perf-report={fmt}")

        # Optionally add --output=FORMAT (equals style only)
        if data.draw(st.booleans()):
            fmt = data.draw(st.sampled_from(["json", "text", "none"]))
            flag_tokens.append(f"--output={fmt}")

        # Optionally add --exclude
        if data.draw(st.booleans()):
            flag_tokens.extend(["--exclude", "*.tmp"])

        # Build argv: func + flags + job_name
        argv = ["func"] + flag_tokens + [job_name]
        job_names = {job_name}

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, f"Expected Mode.JOB for argv={argv}, got {mode}"
        assert job_name in effective_args, (
            f"Expected '{job_name}' in effective_args={effective_args}"
        )
