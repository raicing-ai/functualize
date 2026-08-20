"""Property-based tests for BEFORE_JOB kwargs isolation.

Property 16: BEFORE_JOB hooks receive a shallow copy of original kwargs.

For any kwargs dictionary passed to engine.execute(), BEFORE_JOB hooks SHALL
receive a shallow copy of the original kwargs (before config resolution).
Mutations by one hook SHALL NOT affect subsequent hooks or the job function's
actual arguments.

**Validates: Requirements 9.1, 9.3**
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._events.hooks import HookEvent, HookRegistry
from functualize.job.context import RunContext

# --- Strategies ---

# Strategy for kwargs keys: simple identifiers
kwargs_keys = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=20,
)

# Strategy for kwargs values: JSON-like primitives and simple containers
kwargs_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1000, max_value=1000),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=50),
    ),
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(kwargs_keys, children, max_size=5),
    ),
    max_leaves=10,
)

# Strategy for generating kwargs dicts
kwargs_dicts = st.dictionaries(
    kwargs_keys,
    kwargs_values,
    min_size=0,
    max_size=10,
)

# Strategy for number of hooks
num_hooks_st = st.integers(min_value=2, max_value=6)


class TestBeforeJobKwargsShallowCopyProperty:
    """Property 16: BEFORE_JOB hooks receive a shallow copy of original kwargs.

    **Validates: Requirements 9.1, 9.3**
    """

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        original_kwargs=kwargs_dicts,
        num_hooks=num_hooks_st,
    )
    def test_each_hook_receives_independent_copy_mutations_do_not_propagate(
        self,
        original_kwargs: dict[str, Any],
        num_hooks: int,
    ) -> None:
        """For any kwargs dict and N hooks that mutate their received kwargs,
        each hook receives the original values unaffected by prior hooks' mutations."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)

        # Track what each hook received BEFORE any mutation
        received_before_mutation: list[dict[str, Any]] = []

        for i in range(num_hooks):

            def make_hook(idx: int):
                def hook(rc, kwargs=None):
                    # Record the kwargs as received (before this hook mutates)
                    received_before_mutation.append(dict(kwargs))
                    # Mutate the copy: add a key, modify existing keys
                    kwargs[f"__mutated_by_{idx}__"] = True
                    for key in list(kwargs.keys()):
                        if key != f"__mutated_by_{idx}__":
                            kwargs[key] = f"corrupted_by_{idx}"

                return hook

            registry.register_global(HookEvent.BEFORE_JOB, make_hook(i))

        # Invoke with the original kwargs
        registry.invoke(
            HookEvent.BEFORE_JOB, "test_job", mock_rc, kwargs=original_kwargs
        )

        # Property: Every hook received kwargs equal to the original
        assert len(received_before_mutation) == num_hooks
        for i, received in enumerate(received_before_mutation):
            assert received == original_kwargs, (
                f"Hook {i} received kwargs different from original. "
                f"Expected: {original_kwargs}, Got: {received}"
            )

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        original_kwargs=kwargs_dicts,
        num_hooks=num_hooks_st,
    )
    def test_original_kwargs_never_modified_by_hooks(
        self,
        original_kwargs: dict[str, Any],
        num_hooks: int,
    ) -> None:
        """For any kwargs dict passed to invoke(), the original dict object
        is never modified regardless of how many hooks mutate their copies."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)

        # Take a snapshot of the original before invocation
        snapshot = dict(original_kwargs)

        for i in range(num_hooks):

            def make_hook(idx: int):
                def hook(rc, kwargs=None):
                    # Aggressive mutation: clear, add, delete
                    kwargs.clear()
                    kwargs[f"replaced_by_{idx}"] = idx

                return hook

            registry.register_global(HookEvent.BEFORE_JOB, make_hook(i))

        # Invoke
        registry.invoke(
            HookEvent.BEFORE_JOB, "test_job", mock_rc, kwargs=original_kwargs
        )

        # Property: Original kwargs is unchanged
        assert original_kwargs == snapshot, (
            f"Original kwargs was modified! "
            f"Expected: {snapshot}, Got: {original_kwargs}"
        )

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        original_kwargs=kwargs_dicts,
        num_hooks=num_hooks_st,
    )
    def test_each_hook_receives_distinct_dict_object(
        self,
        original_kwargs: dict[str, Any],
        num_hooks: int,
    ) -> None:
        """For any kwargs dict and N hooks, each hook receives a distinct
        dict object (not the same reference as the original or as other hooks'),
        confirming shallow copy semantics via concurrent reference holding."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)

        # Hold references to all received dicts to prevent GC/memory reuse
        received_dicts: list[dict] = []

        for _i in range(num_hooks):

            def make_hook():
                def hook(rc, kwargs=None):
                    received_dicts.append(kwargs)

                return hook

            registry.register_global(HookEvent.BEFORE_JOB, make_hook())

        registry.invoke(
            HookEvent.BEFORE_JOB, "test_job", mock_rc, kwargs=original_kwargs
        )

        # Property: All received dicts are distinct objects from each other
        assert len(received_dicts) == num_hooks
        for i in range(num_hooks):
            for j in range(i + 1, num_hooks):
                assert received_dicts[i] is not received_dicts[j], (
                    f"Hooks {i} and {j} received the same dict object"
                )
            # Also distinct from the original
            assert received_dicts[i] is not original_kwargs, (
                f"Hook {i} received the original dict, not a copy"
            )

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        original_kwargs=kwargs_dicts,
    )
    def test_global_and_job_scoped_hooks_both_get_isolated_copies(
        self,
        original_kwargs: dict[str, Any],
    ) -> None:
        """For any kwargs dict, both global and job-scoped BEFORE_JOB hooks
        receive independent shallow copies isolated from each other."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)

        received_values: list[dict[str, Any]] = []

        def global_hook(rc, kwargs=None):
            received_values.append(dict(kwargs))
            # Mutate aggressively
            kwargs["__global_was_here__"] = True
            kwargs.clear()

        def job_hook(rc, kwargs=None):
            received_values.append(dict(kwargs))
            # Mutate aggressively
            kwargs["__job_was_here__"] = True

        registry.register_global(HookEvent.BEFORE_JOB, global_hook)
        registry.register_for_job("test_job", HookEvent.BEFORE_JOB, job_hook)

        registry.invoke(
            HookEvent.BEFORE_JOB, "test_job", mock_rc, kwargs=original_kwargs
        )

        # Property: Both hooks received the original kwargs, unaffected by each other
        assert len(received_values) == 2
        assert received_values[0] == original_kwargs
        assert received_values[1] == original_kwargs

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        original_kwargs=kwargs_dicts,
        num_hooks=num_hooks_st,
    )
    def test_hooks_without_kwargs_param_do_not_interfere_with_isolation(
        self,
        original_kwargs: dict[str, Any],
        num_hooks: int,
    ) -> None:
        """For any mix of hooks (with and without kwargs param), the kwargs-accepting
        hooks still receive correct isolated copies."""
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)

        received_by_kwargs_hooks: list[dict[str, Any]] = []

        # Alternate between legacy hooks (no kwargs) and new hooks (with kwargs)
        for i in range(num_hooks):
            if i % 2 == 0:
                # Legacy hook without kwargs param
                def make_legacy():
                    def hook(rc):
                        pass  # does nothing, has no kwargs param

                    return hook

                registry.register_global(HookEvent.BEFORE_JOB, make_legacy())
            else:
                # New hook with kwargs param
                def make_kwargs_hook():
                    def hook(rc, kwargs=None):
                        received_by_kwargs_hooks.append(dict(kwargs))

                    return hook

                registry.register_global(HookEvent.BEFORE_JOB, make_kwargs_hook())

        registry.invoke(
            HookEvent.BEFORE_JOB, "test_job", mock_rc, kwargs=original_kwargs
        )

        # Property: All kwargs-accepting hooks received the original values
        expected_count = num_hooks // 2  # odd-indexed hooks
        assert len(received_by_kwargs_hooks) == expected_count
        for received in received_by_kwargs_hooks:
            assert received == original_kwargs
