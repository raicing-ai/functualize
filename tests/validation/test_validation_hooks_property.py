"""Property-based tests for validation-before-hooks ordering (Property 10).

Tests that for any invalid kwargs violating Field() constraints:
- PRE_EXECUTE hook is NEVER invoked
- AFTER_FAILURE hook IS invoked with the ValidationError
- The function itself is NEVER called

This proves the engine validates arguments BEFORE dispatching to PRE_EXECUTE
hooks, ensuring hooks always receive validated data when they do fire.

# Feature: cli-unix-compatibility, Task 2.4
"""

from __future__ import annotations

from typing import Annotated, Any
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import Field, ValidationError

from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.hooks import HookEvent, HookRegistry
from functualize._primitives import DIRegistry
from functualize._types.enums import RunStatus

# Import the constrained function from a module WITHOUT `from __future__ import
# annotations` so that _build_validation_model can inspect the Annotated metadata.
from tests.validation._constrained_functions import constrained_fn

# =============================================================================
# Strategies
# =============================================================================


@st.composite
def _invalid_kwargs_for_constrained_fn(draw: st.DrawFn) -> dict[str, Any]:
    """Generate kwargs that ALWAYS violate the Field constraints of constrained_fn.

    constrained_fn has:
    - name: str (min_length=2, max_length=10)
    - count: int (ge=1, le=50)

    We generate at least one violation per draw to guarantee validation failure.
    """
    violation_type = draw(
        st.sampled_from(
            [
                "name_too_short",
                "name_too_long",
                "count_too_low",
                "count_too_high",
                "both_invalid",
            ]
        )
    )

    if violation_type == "name_too_short":
        # name violates min_length=2 (empty or single char)
        name = draw(
            st.text(max_size=1, alphabet=st.characters(whitelist_categories=("L",)))
        )
        count = draw(st.integers(min_value=1, max_value=50))
    elif violation_type == "name_too_long":
        # name violates max_length=10
        name = draw(
            st.text(
                min_size=11,
                max_size=30,
                alphabet=st.characters(whitelist_categories=("L",)),
            )
        )
        count = draw(st.integers(min_value=1, max_value=50))
    elif violation_type == "count_too_low":
        # count violates ge=1
        name = draw(
            st.text(
                min_size=2,
                max_size=10,
                alphabet=st.characters(whitelist_categories=("L",)),
            )
        )
        count = draw(st.integers(max_value=0))
    elif violation_type == "count_too_high":
        # count violates le=50
        name = draw(
            st.text(
                min_size=2,
                max_size=10,
                alphabet=st.characters(whitelist_categories=("L",)),
            )
        )
        count = draw(st.integers(min_value=51, max_value=10000))
    else:
        # Both invalid
        name = ""
        count = draw(st.integers(max_value=0))

    return {"name": name, "count": count}


# =============================================================================
# Helpers
# =============================================================================


def _build_engine() -> tuple[JobExecutionEngine, HookRegistry]:
    """Build a minimal engine with a real HookRegistry for testing.

    Uses a real DIRegistry (empty) so resolution plans correctly classify
    str/int parameters as "skip" (not DI-resolved).
    """
    hook_registry = HookRegistry()
    di_registry = DIRegistry()
    engine = JobExecutionEngine(
        di_registry=di_registry,
        event_bus=MagicMock(),
        hook_registry=hook_registry,
        middleware_chain=ExecutionMiddlewareChain(),
    )
    return engine, hook_registry


# =============================================================================
# Property 10: Validation Before Hooks
# =============================================================================


@pytest.mark.slow
class TestValidationBeforeHooks:
    """Property 10: Validation Before Hooks.

    For any function with Field-annotated parameters and for any invalid kwargs
    that violate Field constraints, the PRE_EXECUTE hook SHALL never be invoked —
    validation errors fire AFTER_FAILURE instead, ensuring hooks always receive
    validated data.

    **Validates: Requirements 2.3, 2.6, 2.7**
    """

    @given(invalid_kwargs=_invalid_kwargs_for_constrained_fn())
    @settings(max_examples=200)
    def test_pre_execute_never_fires_on_invalid_kwargs(
        self, invalid_kwargs: dict[str, Any]
    ):
        """PRE_EXECUTE hook is never invoked when kwargs violate Field constraints.

        **Validates: Requirements 2.3, 2.6, 2.7**
        """
        engine, hook_registry = _build_engine()

        pre_execute_calls: list[Any] = []

        def pre_execute_spy(rc: Any) -> None:
            pre_execute_calls.append(rc)

        hook_registry.register_global(HookEvent.PRE_EXECUTE, pre_execute_spy)

        result = engine.execute("test_job", constrained_fn, kwargs=invalid_kwargs)

        assert result.status == RunStatus.FAILURE, (
            f"Expected FAILURE for invalid kwargs {invalid_kwargs}, got {result.status}"
        )
        assert pre_execute_calls == [], (
            f"PRE_EXECUTE hook was invoked {len(pre_execute_calls)} time(s) "
            f"despite invalid kwargs {invalid_kwargs}"
        )

    @given(invalid_kwargs=_invalid_kwargs_for_constrained_fn())
    @settings(max_examples=200)
    def test_after_failure_fires_with_validation_error(
        self, invalid_kwargs: dict[str, Any]
    ):
        """AFTER_FAILURE hook fires with ValidationError when kwargs are invalid.

        **Validates: Requirements 2.3, 2.6, 2.7**
        """
        engine, hook_registry = _build_engine()

        after_failure_calls: list[tuple[Any, Exception]] = []

        def after_failure_spy(rc: Any, exception: Exception) -> None:
            after_failure_calls.append((rc, exception))

        hook_registry.register_global(HookEvent.AFTER_FAILURE, after_failure_spy)

        result = engine.execute("test_job", constrained_fn, kwargs=invalid_kwargs)

        assert result.status == RunStatus.FAILURE
        assert len(after_failure_calls) == 1, (
            f"Expected exactly 1 AFTER_FAILURE call, got {len(after_failure_calls)} "
            f"for invalid kwargs {invalid_kwargs}"
        )
        _, exc = after_failure_calls[0]
        assert isinstance(exc, ValidationError), (
            f"Expected ValidationError, got {type(exc).__name__}: {exc}"
        )

    @given(invalid_kwargs=_invalid_kwargs_for_constrained_fn())
    @settings(max_examples=200)
    def test_function_never_executes_on_invalid_kwargs(
        self, invalid_kwargs: dict[str, Any]
    ):
        """The job function body is never reached when kwargs are invalid.

        **Validates: Requirements 2.3, 2.6, 2.7**
        """
        engine, hook_registry = _build_engine()

        function_calls: list[dict[str, Any]] = []

        import functools
        import inspect

        # Import from the helper module (no future annotations) to define a
        # tracked version of the constrained function
        from tests.validation._constrained_functions import constrained_fn as _base_fn

        @functools.wraps(_base_fn)
        def tracked_fn(
            name: Annotated[str, Field(min_length=2, max_length=10)],
            count: Annotated[int, Field(ge=1, le=50)],
        ) -> str:
            function_calls.append({"name": name, "count": count})
            return f"{name}:{count}"

        # Manually set annotations from the base function (eagerly evaluated)
        tracked_fn.__annotations__ = inspect.get_annotations(_base_fn, eval_str=True)

        result = engine.execute("test_job", tracked_fn, kwargs=invalid_kwargs)

        assert result.status == RunStatus.FAILURE
        assert function_calls == [], (
            f"Function body was executed with {function_calls} "
            f"despite invalid kwargs {invalid_kwargs}"
        )

    @given(invalid_kwargs=_invalid_kwargs_for_constrained_fn())
    @settings(max_examples=200)
    def test_ordering_invariant_only_after_failure_in_event_log(
        self, invalid_kwargs: dict[str, Any]
    ):
        """Verifies hook invocation order: AFTER_FAILURE fires, PRE_EXECUTE does not.

        Uses a shared event log to prove ordering — if both hooks are registered,
        only AFTER_FAILURE appears in the log for invalid kwargs.

        **Validates: Requirements 2.3, 2.6, 2.7**
        """
        engine, hook_registry = _build_engine()

        event_log: list[str] = []

        def pre_execute_hook(rc: Any) -> None:
            event_log.append("PRE_EXECUTE")

        def after_failure_hook(rc: Any, exception: Exception) -> None:
            event_log.append("AFTER_FAILURE")

        hook_registry.register_global(HookEvent.PRE_EXECUTE, pre_execute_hook)
        hook_registry.register_global(HookEvent.AFTER_FAILURE, after_failure_hook)

        result = engine.execute("test_job", constrained_fn, kwargs=invalid_kwargs)

        assert result.status == RunStatus.FAILURE
        assert "PRE_EXECUTE" not in event_log, (
            f"PRE_EXECUTE appeared in event log {event_log} for invalid kwargs"
        )
        assert "AFTER_FAILURE" in event_log, (
            f"AFTER_FAILURE missing from event log {event_log} for invalid kwargs"
        )
