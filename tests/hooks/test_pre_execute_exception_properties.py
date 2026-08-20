"""Property-based tests for PRE_EXECUTE hook exception handling.

Property 5: PRE_EXECUTE hook exceptions are treated as PROCEED.

For any PRE_EXECUTE hook that raises an exception during invocation, the engine
SHALL treat it as returning HookDecision.PROCEED, log the error, and continue
invoking remaining PRE_EXECUTE hooks.

**Validates: Requirements 2.6**
"""

import logging
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._events.hooks import HookDecision, HookEvent, HookRegistry
from functualize.job.context import RunContext

# --- Strategies ---

# Exception types that hooks might raise
exception_types = st.sampled_from(
    [
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        OSError,
        ZeroDivisionError,
        NotImplementedError,
        StopIteration,
    ]
)

# Strategy for exception messages
exception_messages = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=50,
)

# Strategy for job names
job_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)

# Strategy for kwargs dictionaries
kwargs_values = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.text(min_size=0, max_size=20),
    st.booleans(),
    st.none(),
)

kwargs_dicts = st.dictionaries(
    keys=st.text(
        alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
        min_size=1,
        max_size=10,
    ),
    values=kwargs_values,
    min_size=1,
    max_size=5,
)

# Strategy for number of hooks
num_hooks_st = st.integers(min_value=1, max_value=8)


class TestPreExecuteExceptionTreatedAsProceed:
    """Property 5: PRE_EXECUTE hook exceptions are treated as PROCEED.

    **Validates: Requirements 2.6**
    """

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        job_name=job_names,
        exc_type=exception_types,
        exc_msg=exception_messages,
        hook_kwargs=kwargs_dicts,
    )
    def test_any_exception_type_treated_as_proceed(
        self,
        job_name: str,
        exc_type: type,
        exc_msg: str,
        hook_kwargs: dict,
    ):
        """**Validates: Requirements 2.6**

        For any exception type raised by a PRE_EXECUTE hook, the engine treats
        it as HookDecision.PROCEED and continues to the next hook.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        subsequent_called = []

        def raising_hook(rc, kwargs):
            raise exc_type(exc_msg)

        def subsequent_hook(rc, kwargs):
            subsequent_called.append(True)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, raising_hook)
        registry.register_global(HookEvent.PRE_EXECUTE, subsequent_hook)

        # Set up logging capture
        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        hook_logger = logging.getLogger("functualize._events.hooks")
        hook_logger.addHandler(handler)
        hook_logger.setLevel(logging.ERROR)

        try:
            result = registry.invoke_pre_execute(job_name, mock_rc, hook_kwargs)

            # Exception treated as PROCEED: subsequent hook ran
            assert subsequent_called == [True]
            # Overall result is None (all treated as PROCEED)
            assert result is None
            # Error was logged
            assert len(log_records) >= 1
        finally:
            hook_logger.removeHandler(handler)

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        job_name=job_names,
        num_raising=st.integers(min_value=1, max_value=5),
        exc_types=st.lists(exception_types, min_size=1, max_size=5),
        hook_kwargs=kwargs_dicts,
    )
    def test_multiple_exceptions_dont_stop_chain(
        self,
        job_name: str,
        num_raising: int,
        exc_types: list[type],
        hook_kwargs: dict,
    ):
        """**Validates: Requirements 2.6**

        Multiple hooks raising exceptions do not prevent subsequent hooks from running.
        Each exception is independently treated as PROCEED.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        good_hook_calls: list[str] = []

        # Ensure we have enough exception types
        actual_raising = min(num_raising, len(exc_types))

        # Register raising hooks
        for i in range(actual_raising):

            def make_raising(idx, etype):
                def hook(rc, kwargs):
                    raise etype(f"error_{idx}")

                hook.__name__ = f"raising_hook_{idx}"
                return hook

            registry.register_global(
                HookEvent.PRE_EXECUTE, make_raising(i, exc_types[i])
            )

        # Register a good hook at the end
        def good_hook(rc, kwargs):
            good_hook_calls.append("called")
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, good_hook)

        # Set up logging capture
        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        hook_logger = logging.getLogger("functualize._events.hooks")
        hook_logger.addHandler(handler)
        hook_logger.setLevel(logging.ERROR)

        try:
            result = registry.invoke_pre_execute(job_name, mock_rc, hook_kwargs)

            # Good hook at the end was still called
            assert good_hook_calls == ["called"]
            # Result is None (all exceptions treated as PROCEED, good hook also PROCEEDs)
            assert result is None
            # All exceptions were logged
            assert len(log_records) >= actual_raising
        finally:
            hook_logger.removeHandler(handler)

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        job_name=job_names,
        exc_type=exception_types,
        hook_kwargs=kwargs_dicts,
    )
    def test_exception_after_block_hook_still_blocks(
        self,
        job_name: str,
        exc_type: type,
        hook_kwargs: dict,
    ):
        """**Validates: Requirements 2.6**

        If a hook after an exception returns BLOCK, it still takes effect.
        The exception is treated as PROCEED, so subsequent hooks including
        BLOCK hooks still run and their decisions are respected.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)

        def raising_hook(rc, kwargs):
            raise exc_type("something went wrong")

        def blocking_hook(rc, kwargs):
            return HookDecision.BLOCK("access denied")

        # A hook after the block should NOT be called (chain stops at BLOCK)
        after_block_called = []

        def after_block_hook(rc, kwargs):
            after_block_called.append(True)
            return HookDecision.PROCEED()

        registry.register_global(HookEvent.PRE_EXECUTE, raising_hook)
        registry.register_global(HookEvent.PRE_EXECUTE, blocking_hook)
        registry.register_global(HookEvent.PRE_EXECUTE, after_block_hook)

        # Set up logging capture
        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        hook_logger = logging.getLogger("functualize._events.hooks")
        hook_logger.addHandler(handler)
        hook_logger.setLevel(logging.ERROR)

        try:
            result = registry.invoke_pre_execute(job_name, mock_rc, hook_kwargs)

            # The blocking hook's decision takes effect
            assert result is not None
            assert result.is_block
            assert result.reason == "access denied"
            # Chain stopped at BLOCK, so after_block_hook was NOT called
            assert after_block_called == []
            # The exception was still logged
            assert len(log_records) >= 1
        finally:
            hook_logger.removeHandler(handler)

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        job_name=job_names,
        num_hooks=st.integers(min_value=2, max_value=8),
        raising_indices=st.frozensets(
            st.integers(min_value=0, max_value=7), min_size=1, max_size=4
        ),
        hook_kwargs=kwargs_dicts,
    )
    def test_non_raising_hooks_all_invoked_despite_exceptions(
        self,
        job_name: str,
        num_hooks: int,
        raising_indices: frozenset[int],
        hook_kwargs: dict,
    ):
        """**Validates: Requirements 2.6**

        For any configuration of raising and non-raising PRE_EXECUTE hooks,
        all non-raising hooks are still invoked (exceptions don't interrupt
        the chain for subsequent hooks).
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invoked_indices: list[int] = []

        for i in range(num_hooks):
            if i in raising_indices:

                def make_raising(idx):
                    def hook(rc, kwargs):
                        raise RuntimeError(f"hook_{idx}_failed")

                    hook.__name__ = f"raising_hook_{idx}"
                    return hook

                registry.register_global(HookEvent.PRE_EXECUTE, make_raising(i))
            else:

                def make_good(idx):
                    def hook(rc, kwargs):
                        invoked_indices.append(idx)
                        return HookDecision.PROCEED()

                    hook.__name__ = f"good_hook_{idx}"
                    return hook

                registry.register_global(HookEvent.PRE_EXECUTE, make_good(i))

        # Set up logging capture
        log_records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = lambda record: log_records.append(record)
        hook_logger = logging.getLogger("functualize._events.hooks")
        hook_logger.addHandler(handler)
        hook_logger.setLevel(logging.ERROR)

        try:
            registry.invoke_pre_execute(job_name, mock_rc, hook_kwargs)

            # All non-raising hooks within range should have been invoked
            expected = sorted(i for i in range(num_hooks) if i not in raising_indices)
            assert sorted(invoked_indices) == expected

            # Number of logged errors matches number of raising hooks within range
            actual_raising = [i for i in raising_indices if i < num_hooks]
            assert len(log_records) >= len(actual_raising)
        finally:
            hook_logger.removeHandler(handler)
