"""Property-based tests for detect_mode dispatch classification.

# Feature: eliminate-fallback-group
# Property 1: Mode Exhaustiveness and Determinism
# Property 2: Mode Priority Ordering
# Property 3: Mode Classification Correctness
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._cli.dispatch import Mode, detect_mode

# =============================================================================
# Strategies
# =============================================================================

# Characters safe for use in argv tokens (no whitespace, no null bytes)
_safe_chars = st.sampled_from(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-./+"
)

# A valid positional argument that is NOT a .py file, NOT a builtin, and NOT a flag
_BUILTIN_NAMES = frozenset(
    {"cache", "config", "domains", "scaffold", "version", "show-info", "tui"}
)

_identifier_first_char = st.sampled_from("abcdefghijklmnopqrstuvwxyz")

_identifier_rest_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789_")

# Job name: lowercase identifier that doesn't collide with builtins
_job_name_strategy = st.builds(
    lambda first, rest: first + rest,
    _identifier_first_char,
    st.text(_identifier_rest_chars, min_size=1, max_size=15),
).filter(lambda name: name not in _BUILTIN_NAMES and not name.endswith(".py"))

# A set of job names (non-empty)
_job_names_set = st.frozensets(_job_name_strategy, min_size=1, max_size=20).map(set)

# Alias name: short identifier that doesn't collide with builtins
_alias_name_strategy = st.builds(
    lambda first, rest: first + rest,
    st.sampled_from("abcdefghijklmnop"),
    st.text(st.sampled_from("0123456789"), min_size=1, max_size=3),
).filter(lambda name: name not in _BUILTIN_NAMES and not name.endswith(".py"))


# =============================================================================
# Property 1: Mode Exhaustiveness and Determinism
# =============================================================================


@pytest.mark.slow
class TestModeExhaustivenessAndDeterminism:
    """Property 1: Mode Exhaustiveness and Determinism.

    For any argv list and job_names set, detect_mode SHALL return exactly one
    of the five Mode values (SINGLE_FILE, BUILTIN, JOB, BARE, UNKNOWN), and
    calling it again with the same inputs SHALL produce the same result.

    **Validates: Requirements 1.1, 1.8**
    """

    _ALL_MODES = frozenset(
        {Mode.SINGLE_FILE, Mode.BUILTIN, Mode.CLI, Mode.JOB, Mode.BARE, Mode.UNKNOWN}
    )

    @given(
        job_names=_job_names_set,
        extra_args=st.lists(st.text(_safe_chars, min_size=1, max_size=10), max_size=5),
    )
    def test_detect_mode_always_returns_valid_mode_with_job_names(
        self, job_names: set[str], extra_args: list[str]
    ) -> None:
        """detect_mode never raises and always returns a valid Mode value.

        **Validates: Requirements 1.1, 1.8**
        """
        # Pick a random job name as the first positional
        first_pos = list(job_names)[0]
        argv = ["func"] + extra_args + [first_pos]

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode in self._ALL_MODES, (
            f"detect_mode returned {mode!r} which is not a valid Mode value"
        )

    @given(
        job_names=_job_names_set,
        positional=st.text(_safe_chars, min_size=1, max_size=15),
    )
    def test_detect_mode_deterministic_same_inputs_same_output(
        self, job_names: set[str], positional: str
    ) -> None:
        """Same inputs always produce the same mode classification.

        **Validates: Requirements 1.1, 1.8**
        """
        argv = ["func", positional]

        result1 = detect_mode(argv, job_names=job_names)
        result2 = detect_mode(argv, job_names=job_names)

        assert result1 == result2, (
            f"Non-deterministic: first call returned {result1}, "
            f"second call returned {result2} for same inputs"
        )

    @given(job_names=_job_names_set)
    def test_bare_invocation_returns_valid_mode(self, job_names: set[str]) -> None:
        """Bare invocation (no positional) returns BARE when job_names provided.

        **Validates: Requirements 1.1, 1.8**
        """
        argv = ["func"]
        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.BARE
        assert effective_args == []

    @given(
        positional=st.text(_safe_chars, min_size=0, max_size=20),
        extra_args=st.lists(st.text(_safe_chars, min_size=1, max_size=10), max_size=5),
    )
    def test_detect_mode_never_raises_without_job_names(
        self, positional: str, extra_args: list[str]
    ) -> None:
        """detect_mode never raises even without job_names (backward compat).

        **Validates: Requirements 1.1, 1.8**
        """
        argv = ["func"] + ([positional] if positional else []) + extra_args

        # Should not raise
        mode, effective_args = detect_mode(argv)

        assert mode in self._ALL_MODES


# =============================================================================
# Property 2: Mode Priority Ordering
# =============================================================================


@pytest.mark.slow
class TestModePriorityOrdering:
    """Property 2: Mode Priority Ordering.

    For any argv where the first positional argument simultaneously qualifies
    as multiple modes, detect_mode SHALL return the highest-priority mode
    following the strict order: SINGLE_FILE > BUILTIN > JOB > UNKNOWN.

    **Validates: Requirements 1.2, 1.7**
    """

    @given(job_name=_job_name_strategy)
    def test_single_file_wins_over_job_name(self, job_name: str) -> None:
        """When a .py file exists AND its stem is in job_names, SINGLE_FILE wins.

        **Validates: Requirements 1.2, 1.7**
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Create a .py file whose stem matches a job name
            py_file = tmp_path / f"{job_name}.py"
            py_file.write_text("def run(): pass", encoding="utf-8")

            job_names = {job_name}
            argv = ["func", str(py_file)]

            mode, effective_args = detect_mode(argv, job_names=job_names)

            assert mode is Mode.SINGLE_FILE, (
                f"Expected SINGLE_FILE for existing .py file '{py_file}' "
                f"even though stem '{job_name}' is in job_names, got {mode}"
            )

    @given(
        job_names=_job_names_set,
        extra_args=st.lists(st.text(_safe_chars, min_size=1, max_size=10), max_size=3),
    )
    def test_builtin_wins_over_job_name(
        self, job_names: set[str], extra_args: list[str]
    ) -> None:
        """When a builtin name also appears in job_names, BUILTIN wins.

        **Validates: Requirements 1.2, 1.7**
        """
        augmented_job_names = job_names | {"builtin"}
        argv = ["func", "builtin"] + extra_args

        mode, effective_args = detect_mode(argv, job_names=augmented_job_names)

        assert mode is Mode.BUILTIN, (
            f"Expected BUILTIN for 'builtin' even though it's in job_names, got {mode}"
        )

    @given(job_name=_job_name_strategy)
    def test_job_wins_over_unknown(self, job_name: str) -> None:
        """When name is in job_names, JOB wins over UNKNOWN.

        **Validates: Requirements 1.7**
        """
        job_names = {job_name}
        argv = ["func", job_name]

        mode, effective_args = detect_mode(argv, job_names=job_names)

        assert mode is Mode.JOB, (
            f"Expected JOB for '{job_name}' which is in job_names, got {mode}"
        )

    @given(job_name=_job_name_strategy, job_names=_job_names_set)
    def test_unknown_when_not_matched(self, job_name: str, job_names: set[str]) -> None:
        """When name is NOT in job_names or builtins or a file, UNKNOWN is returned.

        **Validates: Requirements 1.7**
        """
        # Remove the job_name from job_names to ensure it's unknown
        clean_job_names = job_names - {job_name}
        # Ensure it's not a builtin either
        if job_name in _BUILTIN_NAMES:
            return  # Skip this case — would be BUILTIN

        argv = ["func", job_name]

        mode, effective_args = detect_mode(argv, job_names=clean_job_names)

        assert mode is Mode.UNKNOWN, (
            f"Expected UNKNOWN for '{job_name}' not in job_names, got {mode}"
        )


# =============================================================================
# Property 3: Mode Classification Correctness
# =============================================================================


@pytest.mark.slow
class TestModeClassificationCorrectness:
    """Property 3: Mode Classification Correctness.

    For any first positional argument cmd, job_names set, and aliases dict:
    - If cmd is in job_names (and not a .py file or builtin), returns Mode.JOB
    - If cmd is in aliases (and not a .py file, builtin, or direct job name),
      returns Mode.JOB
    - If cmd is not in any category, returns Mode.UNKNOWN
    - If an alias key matches a direct job name, the direct job name takes
      precedence (alias is shadowed)

    **Validates: Requirements 1.4, 1.6, 12.2, 12.4**
    """

    @given(job_name=_job_name_strategy, job_names=_job_names_set)
    def test_job_name_in_set_returns_job_mode(
        self, job_name: str, job_names: set[str]
    ) -> None:
        """cmd in job_names and not a .py file or builtin → Mode.JOB.

        **Validates: Requirements 1.4, 12.2**
        """
        # Ensure job_name is in the set
        augmented = job_names | {job_name}
        argv = ["func", job_name]

        mode, effective_args = detect_mode(argv, job_names=augmented)

        assert mode is Mode.JOB, (
            f"Expected JOB for '{job_name}' in job_names, got {mode}"
        )
        assert effective_args[0] == job_name

    @given(
        alias_name=_alias_name_strategy,
        target_job=_job_name_strategy,
        job_names=_job_names_set,
    )
    def test_alias_in_aliases_returns_job_mode(
        self, alias_name: str, target_job: str, job_names: set[str]
    ) -> None:
        """cmd in aliases dict (not a direct job name) → Mode.JOB.

        **Validates: Requirements 1.4, 12.2**
        """
        # Ensure alias is not in job_names (so it routes via alias, not direct match)
        clean_job_names = job_names - {alias_name}
        aliases = {alias_name: target_job}
        argv = ["func", alias_name]

        mode, effective_args = detect_mode(
            argv, job_names=clean_job_names, aliases=aliases
        )

        assert mode is Mode.JOB, (
            f"Expected JOB for alias '{alias_name}' → '{target_job}', got {mode}"
        )
        assert effective_args[0] == alias_name

    @given(
        shared_name=_job_name_strategy,
        target_job=_job_name_strategy,
        job_names=_job_names_set,
    )
    def test_alias_shadowed_by_direct_job_name(
        self, shared_name: str, target_job: str, job_names: set[str]
    ) -> None:
        """When alias name matches a direct job name, job name wins (shadowing).

        **Validates: Requirements 12.4**
        """
        # Add shared_name to job_names so it's both a job and an alias key
        augmented = job_names | {shared_name}
        aliases = {shared_name: target_job}
        argv = ["func", shared_name]

        mode, effective_args = detect_mode(argv, job_names=augmented, aliases=aliases)

        # Should be Mode.JOB via direct job_names match (priority over alias)
        assert mode is Mode.JOB, (
            f"Expected JOB for '{shared_name}' in both job_names and aliases, "
            f"got {mode}"
        )
        # The effective args should contain the original name (not alias target)
        # — alias expansion happens later in _handle_job, not in detect_mode
        assert effective_args[0] == shared_name

    @given(
        unknown_cmd=_job_name_strategy,
        job_names=_job_names_set,
    )
    def test_unknown_command_returns_unknown_mode(
        self, unknown_cmd: str, job_names: set[str]
    ) -> None:
        """cmd not in job_names, aliases, builtins, or .py files → Mode.UNKNOWN.

        **Validates: Requirements 1.6**
        """
        # Remove unknown_cmd from job_names to ensure it's not found
        clean_job_names = job_names - {unknown_cmd}
        aliases: dict[str, str] = {}  # Empty aliases
        argv = ["func", unknown_cmd]

        mode, effective_args = detect_mode(
            argv, job_names=clean_job_names, aliases=aliases
        )

        assert mode is Mode.UNKNOWN, (
            f"Expected UNKNOWN for '{unknown_cmd}' not in job_names or aliases, "
            f"got {mode}"
        )
        assert effective_args[0] == unknown_cmd

    @given(
        alias_name=_alias_name_strategy,
        target_job=_job_name_strategy,
    )
    def test_alias_not_in_job_names_without_alias_dict_is_unknown(
        self, alias_name: str, target_job: str
    ) -> None:
        """When aliases dict is None, an alias name not in job_names → UNKNOWN.

        **Validates: Requirements 1.6**
        """
        # No aliases provided, alias_name not in job_names
        job_names: set[str] = set()
        argv = ["func", alias_name]

        mode, effective_args = detect_mode(argv, job_names=job_names, aliases=None)

        assert mode is Mode.UNKNOWN, (
            f"Expected UNKNOWN for '{alias_name}' without aliases dict, got {mode}"
        )
