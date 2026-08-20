"""Property-based tests for TestRunContext (Properties 13–14).

Tests the functualize.testing module:
- Property 13: TestRunContext override composition
- Property 14: CapturingLog recording fidelity

# Feature: unified-architecture-redesign, Properties 13–14
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize.job.capabilities import Invoke, JobContext, Log, Perf, Prompt, State
from functualize.testing import TestRunContext
from functualize.testing.doubles import AutoPrompt, CapturingLog, MockInvoke, NoopPerf

# =============================================================================
# Property 13: TestRunContext override composition
# =============================================================================

# The six capability keys that can be overridden
_CAPABILITY_KEYS = ["log", "invoke", "prompt", "perf", "state", "job_context"]

# Map from key names to the type used for DI resolution
_KEY_TO_TYPE: dict[str, type] = {
    "log": Log,
    "invoke": Invoke,
    "prompt": Prompt,
    "perf": Perf,
    "state": State,
    "job_context": JobContext,
}


def _make_override(key: str) -> Any:
    """Create a distinct override instance for the given capability key."""
    if key == "log":
        return CapturingLog()
    elif key == "invoke":
        return MockInvoke({"custom_job": "custom_result"})
    elif key == "prompt":
        return AutoPrompt(["custom_response"])
    elif key == "perf":
        return NoopPerf()
    elif key == "state":
        return State()
    elif key == "job_context":
        return JobContext(name="custom_test", trace_id="trace-123")
    raise ValueError(f"Unknown key: {key}")


def _is_default_double(key: str, instance: Any) -> bool:
    """Check if the instance matches the expected default test double for a key."""
    if key == "log":
        return isinstance(instance, CapturingLog) and instance.calls == []
    elif key == "invoke":
        return isinstance(instance, MockInvoke)
    elif key == "prompt":
        return isinstance(instance, AutoPrompt)
    elif key == "perf":
        return isinstance(instance, NoopPerf)
    elif key == "state":
        return isinstance(instance, State)
    elif key == "job_context":
        return isinstance(instance, JobContext) and instance.name == "test"
    return False


# Strategy: generate a random subset of capability keys to override
_override_subset_strategy = st.frozensets(
    st.sampled_from(_CAPABILITY_KEYS), min_size=0, max_size=6
)


class TestTestRunContextOverrideComposition:
    """Property 13: TestRunContext override composition.

    For any subset of capability overrides provided to TestRunContext.create(...),
    the resulting RunContext SHALL use the provided override for each specified
    capability and the corresponding default test double for each omitted capability.

    **Validates: Requirements 8.1, 8.2**
    """

    @given(override_keys=_override_subset_strategy)
    def test_provided_overrides_are_used(self, override_keys: frozenset[str]):
        """Provided overrides are the exact instances resolved from the RunContext.

        **Validates: Requirements 8.1, 8.2**
        """
        # Build kwargs with override instances for the selected keys
        overrides: dict[str, Any] = {}
        override_instances: dict[str, Any] = {}
        for key in override_keys:
            instance = _make_override(key)
            overrides[key] = instance
            override_instances[key] = instance

        rc = TestRunContext.create(**overrides)

        # For each provided override, verify it's the same object in the RunContext
        for key in override_keys:
            resolved = rc[_KEY_TO_TYPE[key]]
            assert resolved is override_instances[key], (
                f"Override for '{key}' was not the same instance. "
                f"Expected id={id(override_instances[key])}, got id={id(resolved)}"
            )

    @given(override_keys=_override_subset_strategy)
    def test_omitted_capabilities_get_defaults(self, override_keys: frozenset[str]):
        """Omitted capabilities get their default test doubles.

        **Validates: Requirements 8.1, 8.2**
        """
        # Build kwargs with override instances for the selected keys
        overrides: dict[str, Any] = {}
        for key in override_keys:
            overrides[key] = _make_override(key)

        rc = TestRunContext.create(**overrides)

        # For each OMITTED key, verify the resolved instance is a default double
        omitted_keys = set(_CAPABILITY_KEYS) - set(override_keys)
        for key in omitted_keys:
            resolved = rc[_KEY_TO_TYPE[key]]
            assert _is_default_double(key, resolved), (
                f"Omitted capability '{key}' did not get a default test double. "
                f"Got: {type(resolved).__name__} = {resolved!r}"
            )

    @given(override_keys=_override_subset_strategy)
    def test_override_instances_distinct_from_defaults(
        self, override_keys: frozenset[str]
    ):
        """Provided overrides are distinct objects from what defaults would produce.

        **Validates: Requirements 8.1, 8.2**
        """
        # Create a baseline RunContext with no overrides
        baseline_rc = TestRunContext.create()

        # Build kwargs with override instances for the selected keys
        overrides: dict[str, Any] = {}
        for key in override_keys:
            overrides[key] = _make_override(key)

        rc = TestRunContext.create(**overrides)

        # For each provided override, the resolved instance should NOT be the
        # same object as the baseline's (since we created fresh instances)
        for key in override_keys:
            resolved = rc[_KEY_TO_TYPE[key]]
            baseline_resolved = baseline_rc[_KEY_TO_TYPE[key]]
            assert resolved is not baseline_resolved, (
                f"Override for '{key}' should be distinct from baseline default"
            )


# =============================================================================
# Property 14: CapturingLog recording fidelity
# =============================================================================

# Strategy: generate a sequence of (level, message) log calls
_LOG_LEVELS = ["info", "warning", "error", "debug"]

_log_entry_strategy = st.tuples(
    st.sampled_from(_LOG_LEVELS),
    st.text(min_size=0, max_size=50),
)

_log_sequence_strategy = st.lists(
    _log_entry_strategy,
    min_size=0,
    max_size=20,
)


class TestCapturingLogRecordingFidelity:
    """Property 14: CapturingLog recording fidelity.

    For any sequence of log calls (level, message) on a CapturingLog instance,
    TestRunContext.captured_logs(rc) SHALL return the identical sequence in
    insertion order.

    **Validates: Requirements 8.3, 8.6**
    """

    @given(log_calls=_log_sequence_strategy)
    def test_captured_logs_returns_identical_sequence(
        self, log_calls: list[tuple[str, str]]
    ):
        """captured_logs returns the exact sequence of (level, message) in order.

        **Validates: Requirements 8.3, 8.6**
        """
        rc = TestRunContext.create()

        # Execute log calls via the CapturingLog
        log_instance = rc[Log]
        for level, message in log_calls:
            log_instance(message, level=level)

        # Verify captured_logs returns the same sequence
        captured = TestRunContext.captured_logs(rc)
        assert captured == log_calls

    @given(log_calls=_log_sequence_strategy)
    def test_captured_logs_preserves_insertion_order(
        self, log_calls: list[tuple[str, str]]
    ):
        """captured_logs preserves the insertion order of log calls.

        **Validates: Requirements 8.3, 8.6**
        """
        rc = TestRunContext.create()

        log_instance = rc[Log]
        for level, message in log_calls:
            log_instance(message, level=level)

        captured = TestRunContext.captured_logs(rc)

        # Verify length matches
        assert len(captured) == len(log_calls)

        # Verify each entry matches in order
        for i, (expected_level, expected_msg) in enumerate(log_calls):
            actual_level, actual_msg = captured[i]
            assert actual_level == expected_level, (
                f"Entry {i}: expected level '{expected_level}', got '{actual_level}'"
            )
            assert actual_msg == expected_msg, (
                f"Entry {i}: expected message '{expected_msg}', got '{actual_msg}'"
            )

    @given(log_calls=_log_sequence_strategy)
    def test_named_level_methods_record_correctly(
        self, log_calls: list[tuple[str, str]]
    ):
        """Named level methods (info, warning, error, debug) record with correct level.

        **Validates: Requirements 8.3, 8.6**
        """
        rc = TestRunContext.create()

        log_instance = rc[Log]
        for level, message in log_calls:
            # Use named methods instead of __call__
            method = getattr(log_instance, level)
            method(message)

        captured = TestRunContext.captured_logs(rc)
        assert captured == log_calls

    @given(
        first_batch=_log_sequence_strategy,
        second_batch=_log_sequence_strategy,
    )
    def test_multiple_batches_accumulate_in_order(
        self,
        first_batch: list[tuple[str, str]],
        second_batch: list[tuple[str, str]],
    ):
        """Multiple batches of log calls accumulate in insertion order.

        **Validates: Requirements 8.3, 8.6**
        """
        rc = TestRunContext.create()

        log_instance = rc[Log]

        # First batch
        for level, message in first_batch:
            log_instance(message, level=level)

        # Second batch
        for level, message in second_batch:
            log_instance(message, level=level)

        captured = TestRunContext.captured_logs(rc)
        expected = first_batch + second_batch
        assert captured == expected


# =============================================================================
# RunContext.log() routes through the injected Log capability
# =============================================================================


class TestRunContextLogRouting:
    """RunContext.log() emits through the injected Log capability.

    Regression coverage for the 0.1.0 known limitation in which rc.log(...)
    bypassed the injected Log and was invisible to captured_logs().

    **Validates: Requirements 8.3, 8.6**
    """

    @given(log_calls=_log_sequence_strategy)
    def test_rc_log_sequence_matches_captured(self, log_calls: list[tuple[str, str]]):
        """For any sequence of rc.log calls, captured_logs returns it verbatim.

        **Validates: Requirements 8.3, 8.6**
        """
        rc = TestRunContext.create()

        for level, message in log_calls:
            rc.log(message, level=level)

        captured = TestRunContext.captured_logs(rc)
        assert captured == [(level, str(message)) for level, message in log_calls]
