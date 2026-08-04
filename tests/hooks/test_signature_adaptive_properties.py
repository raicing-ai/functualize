"""Property-based tests for signature-adaptive hook invocation.

Tests Property 32: Signature-adaptive hook invocation — new kwargs omitted for old signatures.

For any hook callable that does not accept a newly added keyword parameter (e.g., `result`,
`kwargs`), the engine SHALL invoke that hook without the new parameter, preventing TypeError.

**Validates: Requirements 28.1, 1.3**
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._events.hooks import HookEvent, HookRegistry
from functualize._events.introspection import accepts_keyword
from functualize.job.context import RunContext

# --- Strategies ---

# Strategy for generating job names
job_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)

# Strategy for arbitrary result values (including None)
result_values = st.one_of(
    st.none(),
    st.integers(),
    st.text(max_size=50),
    st.lists(st.integers(), max_size=5),
    st.dictionaries(st.text(max_size=10), st.integers(), max_size=5),
    st.booleans(),
    st.floats(allow_nan=False),
)

# Strategy for kwargs dictionaries
kwargs_values = st.dictionaries(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"), whitelist_characters="_"
        ),
        min_size=1,
        max_size=10,
    ),
    st.one_of(st.integers(), st.text(max_size=20), st.booleans(), st.none()),
    min_size=0,
    max_size=5,
)

# Hook signature types relevant to AFTER_SUCCESS (result param)
AFTER_SUCCESS_SIGNATURE_TYPES = [
    "rc_only",  # def hook(rc): ... — legacy, no result
    "rc_result",  # def hook(rc, result=None): ... — accepts result optionally
    "rc_result_kwargs",  # def hook(rc, result=None, kwargs=None): ... — accepts both
    "rc_var_keyword",  # def hook(rc, **kw): ... — catches everything
    "rc_result_kw_only",  # def hook(rc, *, result): ... — keyword-only result (required)
]

# Hook signature types relevant to BEFORE_JOB (kwargs param)
BEFORE_JOB_SIGNATURE_TYPES = [
    "rc_only",  # def hook(rc): ... — legacy, no kwargs
    "rc_kwargs",  # def hook(rc, kwargs=None): ... — accepts kwargs optionally
    "rc_result_kwargs",  # def hook(rc, result=None, kwargs=None): ... — accepts both
    "rc_var_keyword",  # def hook(rc, **kw): ... — catches everything
    "rc_kwargs_kw_only",  # def hook(rc, *, kwargs): ... — keyword-only kwargs (required)
]

# All signature types (for mixed tests)
ALL_SIGNATURE_TYPES = [
    "rc_only",
    "rc_result",
    "rc_kwargs",
    "rc_result_kwargs",
    "rc_var_keyword",
    "rc_result_kw_only",
    "rc_kwargs_kw_only",
]

after_success_sig_type = st.sampled_from(AFTER_SUCCESS_SIGNATURE_TYPES)
before_job_sig_type = st.sampled_from(BEFORE_JOB_SIGNATURE_TYPES)
any_sig_type = st.sampled_from(ALL_SIGNATURE_TYPES)

# Strategy for list of hook signature types (varying number of hooks)
after_success_sig_lists = st.lists(after_success_sig_type, min_size=1, max_size=8)
before_job_sig_lists = st.lists(before_job_sig_type, min_size=1, max_size=8)
any_sig_lists = st.lists(any_sig_type, min_size=1, max_size=8)


def make_hook(sig_type: str, tracker: list[tuple[str, dict[str, Any]]]) -> Any:
    """Create a hook callable with the specified signature type.

    The hook appends a (sig_type, received_kwargs) tuple to `tracker`
    so we can verify what was received.
    """
    if sig_type == "rc_only":

        def hook(rc):
            tracker.append((sig_type, {}))

        hook.__name__ = f"hook_{sig_type}"
        return hook

    elif sig_type == "rc_result":

        def hook(rc, result=None):
            tracker.append((sig_type, {"result": result}))

        hook.__name__ = f"hook_{sig_type}"
        return hook

    elif sig_type == "rc_kwargs":

        def hook(rc, kwargs=None):
            tracker.append((sig_type, {"kwargs": kwargs}))

        hook.__name__ = f"hook_{sig_type}"
        return hook

    elif sig_type == "rc_result_kwargs":

        def hook(rc, result=None, kwargs=None):
            tracker.append((sig_type, {"result": result, "kwargs": kwargs}))

        hook.__name__ = f"hook_{sig_type}"
        return hook

    elif sig_type == "rc_var_keyword":

        def hook(rc, **kw):
            tracker.append((sig_type, kw))

        hook.__name__ = f"hook_{sig_type}"
        return hook

    elif sig_type == "rc_result_kw_only":

        def hook(rc, *, result):
            tracker.append((sig_type, {"result": result}))

        hook.__name__ = f"hook_{sig_type}"
        return hook

    elif sig_type == "rc_kwargs_kw_only":

        def hook(rc, *, kwargs):
            tracker.append((sig_type, {"kwargs": kwargs}))

        hook.__name__ = f"hook_{sig_type}"
        return hook

    else:
        raise ValueError(f"Unknown signature type: {sig_type}")


# --- Property 32 Tests ---


class TestSignatureAdaptiveDispatch:
    """Property 32: Signature-adaptive hook invocation — new kwargs omitted for old signatures.

    For any hook callable that does not accept a newly added keyword parameter
    (e.g., `result`, `kwargs`), the engine SHALL invoke that hook without the
    new parameter, preventing TypeError.

    **Validates: Requirements 28.1, 1.3**
    """

    @settings(
        max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        job_name=job_names,
        signatures=after_success_sig_lists,
        result_value=result_values,
    )
    def test_after_success_never_raises_type_error(
        self,
        job_name: str,
        signatures: list[str],
        result_value: Any,
    ) -> None:
        """AFTER_SUCCESS invocation with result= never raises TypeError regardless
        of hook signature.

        For any combination of hook callables with varying signatures that are
        valid for AFTER_SUCCESS (accept result or don't), invoking AFTER_SUCCESS
        with result= SHALL NOT raise TypeError.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        tracker: list[tuple[str, dict[str, Any]]] = []

        # Register hooks with various signatures
        for sig_type in signatures:
            hook = make_hook(sig_type, tracker)
            registry.register_global(HookEvent.AFTER_SUCCESS, hook)

        # This must NEVER raise TypeError
        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        # All hooks must have been called (no skips due to TypeError)
        assert len(tracker) == len(signatures)

    @settings(
        max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        job_name=job_names,
        signatures=before_job_sig_lists,
        kwargs_value=kwargs_values,
    )
    def test_before_job_never_raises_type_error(
        self,
        job_name: str,
        signatures: list[str],
        kwargs_value: dict[str, Any],
    ) -> None:
        """BEFORE_JOB invocation with kwargs= never raises TypeError regardless
        of hook signature.

        For any combination of hook callables with varying signatures that are
        valid for BEFORE_JOB (accept kwargs or don't), invoking BEFORE_JOB
        with kwargs= SHALL NOT raise TypeError.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        tracker: list[tuple[str, dict[str, Any]]] = []

        # Register hooks with various signatures
        for sig_type in signatures:
            hook = make_hook(sig_type, tracker)
            registry.register_global(HookEvent.BEFORE_JOB, hook)

        # This must NEVER raise TypeError
        registry.invoke(HookEvent.BEFORE_JOB, job_name, mock_rc, kwargs=kwargs_value)

        # All hooks must have been called (no skips due to TypeError)
        assert len(tracker) == len(signatures)

    @settings(
        max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        job_name=job_names,
        signatures=after_success_sig_lists,
        result_value=result_values,
    )
    def test_after_success_hooks_without_result_receive_no_result(
        self,
        job_name: str,
        signatures: list[str],
        result_value: Any,
    ) -> None:
        """For AFTER_SUCCESS: hooks without `result` param get called without it.

        Hooks that don't accept `result` SHALL be invoked with only rc and
        SHALL NOT see the result value in their received arguments.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        tracker: list[tuple[str, dict[str, Any]]] = []

        for sig_type in signatures:
            hook = make_hook(sig_type, tracker)
            registry.register_global(HookEvent.AFTER_SUCCESS, hook)

        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        # Verify: hooks without `result` did NOT receive it;
        # hooks with `result` DID receive the correct value
        for _i, (sig_type, received) in enumerate(tracker):
            if sig_type == "rc_only":
                # Should not have received result
                assert "result" not in received, (
                    f"Hook with signature '{sig_type}' should NOT receive result"
                )
            elif sig_type in ("rc_result", "rc_result_kwargs", "rc_result_kw_only"):
                # Should have received the correct result value
                assert received.get("result") == result_value or (
                    received.get("result") is result_value
                ), (
                    f"Hook with signature '{sig_type}' should receive "
                    f"result={result_value!r}, got {received.get('result')!r}"
                )
            elif sig_type == "rc_var_keyword":
                # **kw catches everything, should have received result
                assert "result" in received, (
                    "Hook with **kw signature should receive result"
                )
                assert received["result"] == result_value or (
                    received["result"] is result_value
                )

    @settings(
        max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        job_name=job_names,
        signatures=before_job_sig_lists,
        kwargs_value=kwargs_values,
    )
    def test_before_job_hooks_without_kwargs_receive_no_kwargs(
        self,
        job_name: str,
        signatures: list[str],
        kwargs_value: dict[str, Any],
    ) -> None:
        """For BEFORE_JOB: hooks without `kwargs` param get called without it.

        Hooks that don't accept `kwargs` SHALL be invoked with only rc and
        SHALL NOT see the kwargs value in their received arguments.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        tracker: list[tuple[str, dict[str, Any]]] = []

        for sig_type in signatures:
            hook = make_hook(sig_type, tracker)
            registry.register_global(HookEvent.BEFORE_JOB, hook)

        registry.invoke(HookEvent.BEFORE_JOB, job_name, mock_rc, kwargs=kwargs_value)

        # Verify: hooks without `kwargs` did NOT receive it;
        # hooks with `kwargs` DID receive a copy of the correct value
        for _i, (sig_type, received) in enumerate(tracker):
            if sig_type == "rc_only":
                # Should not have received kwargs
                assert "kwargs" not in received, (
                    f"Hook with signature '{sig_type}' should NOT receive kwargs"
                )
            elif sig_type in ("rc_kwargs", "rc_result_kwargs", "rc_kwargs_kw_only"):
                # Should have received the kwargs value (shallow copy)
                assert received.get("kwargs") == kwargs_value, (
                    f"Hook with signature '{sig_type}' should receive "
                    f"kwargs={kwargs_value!r}, got {received.get('kwargs')!r}"
                )
            elif sig_type == "rc_var_keyword":
                # **kw catches everything, should have received kwargs
                assert "kwargs" in received, (
                    "Hook with **kw signature should receive kwargs"
                )
                assert received["kwargs"] == kwargs_value

    @settings(
        max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        job_name=job_names,
        signatures=after_success_sig_lists,
        result_value=result_values,
    )
    def test_after_success_hooks_with_result_receive_correct_value(
        self,
        job_name: str,
        signatures: list[str],
        result_value: Any,
    ) -> None:
        """Hooks that accept `result` parameter always receive the correct value.

        For AFTER_SUCCESS, hooks with `result` param or **kwargs SHALL receive
        exactly the result value passed to invoke().
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        tracker: list[tuple[str, dict[str, Any]]] = []

        for sig_type in signatures:
            hook = make_hook(sig_type, tracker)
            registry.register_global(HookEvent.AFTER_SUCCESS, hook)

        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)

        for sig_type, received in tracker:
            if accepts_keyword(make_hook(sig_type, []), "result"):
                # This hook accepts result — verify it got the correct value
                actual = received.get("result")
                assert actual == result_value or actual is result_value, (
                    f"Hook '{sig_type}' should receive result={result_value!r}, "
                    f"got {actual!r}"
                )

    @settings(
        max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        job_name=job_names,
        signatures=before_job_sig_lists,
        kwargs_value=kwargs_values,
    )
    def test_before_job_hooks_with_kwargs_receive_correct_value(
        self,
        job_name: str,
        signatures: list[str],
        kwargs_value: dict[str, Any],
    ) -> None:
        """Hooks that accept `kwargs` parameter always receive the correct value.

        For BEFORE_JOB, hooks with `kwargs` param or **kw SHALL receive
        exactly the kwargs dict (as a shallow copy) passed to invoke().
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        tracker: list[tuple[str, dict[str, Any]]] = []

        for sig_type in signatures:
            hook = make_hook(sig_type, tracker)
            registry.register_global(HookEvent.BEFORE_JOB, hook)

        registry.invoke(HookEvent.BEFORE_JOB, job_name, mock_rc, kwargs=kwargs_value)

        for sig_type, received in tracker:
            if accepts_keyword(make_hook(sig_type, []), "kwargs"):
                # This hook accepts kwargs — verify it got the correct value
                actual = received.get("kwargs")
                assert actual == kwargs_value, (
                    f"Hook '{sig_type}' should receive kwargs={kwargs_value!r}, "
                    f"got {actual!r}"
                )

    @settings(
        max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        job_name=job_names,
        global_sigs=after_success_sig_lists,
        job_sigs=after_success_sig_lists,
        result_value=result_values,
    )
    def test_mixed_global_and_job_scoped_after_success_never_raises(
        self,
        job_name: str,
        global_sigs: list[str],
        job_sigs: list[str],
        result_value: Any,
    ) -> None:
        """Mix of global and job-scoped AFTER_SUCCESS hooks with varied signatures
        never raises TypeError.

        For AFTER_SUCCESS with a mix of global and job-scoped hooks of varying
        signatures, invocation SHALL NOT raise TypeError and all hooks get invoked.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        tracker: list[tuple[str, dict[str, Any]]] = []

        # Register global hooks
        for sig_type in global_sigs:
            hook = make_hook(sig_type, tracker)
            registry.register_global(HookEvent.AFTER_SUCCESS, hook)

        # Register job-scoped hooks
        for sig_type in job_sigs:
            hook = make_hook(sig_type, tracker)
            registry.register_for_job(job_name, HookEvent.AFTER_SUCCESS, hook)

        # AFTER_SUCCESS — must NOT raise
        registry.invoke(HookEvent.AFTER_SUCCESS, job_name, mock_rc, result=result_value)
        assert len(tracker) == len(global_sigs) + len(job_sigs)

    @settings(
        max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(
        job_name=job_names,
        global_sigs=before_job_sig_lists,
        job_sigs=before_job_sig_lists,
        kwargs_value=kwargs_values,
    )
    def test_mixed_global_and_job_scoped_before_job_never_raises(
        self,
        job_name: str,
        global_sigs: list[str],
        job_sigs: list[str],
        kwargs_value: dict[str, Any],
    ) -> None:
        """Mix of global and job-scoped BEFORE_JOB hooks with varied signatures
        never raises TypeError.

        For BEFORE_JOB with a mix of global and job-scoped hooks of varying
        signatures, invocation SHALL NOT raise TypeError and all hooks get invoked.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        tracker: list[tuple[str, dict[str, Any]]] = []

        # Register global hooks
        for sig_type in global_sigs:
            hook = make_hook(sig_type, tracker)
            registry.register_global(HookEvent.BEFORE_JOB, hook)

        # Register job-scoped hooks
        for sig_type in job_sigs:
            hook = make_hook(sig_type, tracker)
            registry.register_for_job(job_name, HookEvent.BEFORE_JOB, hook)

        # BEFORE_JOB — must NOT raise
        registry.invoke(HookEvent.BEFORE_JOB, job_name, mock_rc, kwargs=kwargs_value)
        assert len(tracker) == len(global_sigs) + len(job_sigs)
