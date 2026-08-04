"""Property-based tests for decorator hook registration (Property 10).

Tests that decorators correctly register hooks in the appropriate scope:
- Bare form (@decorator) → global hooks
- Parameterized form (@decorator("job_name")) → job-scoped hooks

Uses _make_hook_decorator factory directly for isolated testing.

**Validates: Requirements 14.1, 14.2, 15.1, 15.2, 16.1, 16.2, 17.1, 17.2,
22.1, 23.1, 24.1, 25.1, 26.1, 27.1, 33.1, 34.1, 34.2**
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize.job.decorators import (
    _make_global_only_decorator,
    _make_hook_decorator,
)

# --- Helpers ---


class FakeRegistry:
    """Simple registry that tracks registered functions and their context."""

    def __init__(self) -> None:
        self.global_hooks: list[Callable[..., Any]] = []
        self.job_hooks: dict[str, list[Callable[..., Any]]] = {}

    def register_global(self, fn: Callable[..., Any]) -> None:
        self.global_hooks.append(fn)

    def register_for_job(self, job_name: str, fn: Callable[..., Any]) -> None:
        if job_name not in self.job_hooks:
            self.job_hooks[job_name] = []
        self.job_hooks[job_name].append(fn)


# --- Strategies ---

# Strategy for valid function names (Python identifiers)
func_names = st.from_regex(r"^[a-z_][a-z0-9_]{0,30}$", fullmatch=True)

# Strategy for valid non-empty job name strings
job_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=50,
)

# Strategy for event names (used in _make_hook_decorator)
event_names = st.sampled_from(
    [
        "on_job_failure",
        "on_job_success",
        "on_job_teardown",
        "before_job",
        "pre_execute",
    ]
)


# --- Property 10: Decorator hook registration ---


class TestDecoratorHookRegistrationBareForm:
    """Property: bare decorator form registers function in global hooks."""

    @settings(max_examples=100)
    @given(func_name=func_names, event_name=event_names)
    def test_bare_form_registers_in_global_hooks(
        self, func_name: str, event_name: str
    ) -> None:
        """When _make_hook_decorator is used in bare form (callable passed directly),
        the function ends up in the global hooks list.

        **Validates: Requirements 14.1, 15.1, 16.1, 17.1, 34.1**
        """
        registry = FakeRegistry()
        decorator = _make_hook_decorator(
            register_global=registry.register_global,
            register_for_job=registry.register_for_job,
            event_name=event_name,
        )

        # Create a function with a dynamic name
        def hook_fn(rc: Any) -> None:
            pass

        hook_fn.__name__ = func_name

        # Apply bare decorator
        result = decorator(hook_fn)

        # Verify it appears in global hooks
        assert hook_fn in registry.global_hooks
        # Verify it does NOT appear in any job-scoped hooks
        for hooks_list in registry.job_hooks.values():
            assert hook_fn not in hooks_list
        # Verify identity preservation
        assert result is hook_fn

    @settings(max_examples=100)
    @given(func_name=func_names, event_name=event_names)
    def test_empty_parens_form_registers_in_global_hooks(
        self, func_name: str, event_name: str
    ) -> None:
        """When _make_hook_decorator is used with empty parens (),
        the function ends up in the global hooks list.

        **Validates: Requirements 14.1, 15.1, 16.1, 17.3, 34.1**
        """
        registry = FakeRegistry()
        decorator = _make_hook_decorator(
            register_global=registry.register_global,
            register_for_job=registry.register_for_job,
            event_name=event_name,
        )

        # Create a function with a dynamic name
        def hook_fn(rc: Any) -> None:
            pass

        hook_fn.__name__ = func_name

        # Apply empty-parens form
        wrapper = decorator()
        result = wrapper(hook_fn)

        # Verify it appears in global hooks
        assert hook_fn in registry.global_hooks
        # Verify it does NOT appear in any job-scoped hooks
        for hooks_list in registry.job_hooks.values():
            assert hook_fn not in hooks_list
        # Verify identity preservation
        assert result is hook_fn


class TestDecoratorHookRegistrationParameterizedForm:
    """Property: parameterized decorator form registers function in job-scoped hooks."""

    @settings(max_examples=100)
    @given(func_name=func_names, job_name=job_names, event_name=event_names)
    def test_parameterized_form_registers_in_job_scoped_hooks(
        self, func_name: str, job_name: str, event_name: str
    ) -> None:
        """When _make_hook_decorator is used with a job name string,
        the function ends up in the job-scoped hooks for that job name.

        **Validates: Requirements 14.2, 15.2, 16.2, 17.2, 34.2**
        """
        registry = FakeRegistry()
        decorator = _make_hook_decorator(
            register_global=registry.register_global,
            register_for_job=registry.register_for_job,
            event_name=event_name,
        )

        # Create a function with a dynamic name
        def hook_fn(rc: Any) -> None:
            pass

        hook_fn.__name__ = func_name

        # Apply parameterized decorator with job name
        wrapper = decorator(job_name)
        result = wrapper(hook_fn)

        # Verify it appears in the correct job-scoped hooks
        assert job_name in registry.job_hooks
        assert hook_fn in registry.job_hooks[job_name]
        # Verify it does NOT appear in global hooks
        assert hook_fn not in registry.global_hooks
        # Verify identity preservation
        assert result is hook_fn

    @settings(max_examples=100)
    @given(
        func_name=func_names,
        job_name_a=job_names,
        job_name_b=job_names,
        event_name=event_names,
    )
    def test_different_job_names_register_independently(
        self, func_name: str, job_name_a: str, job_name_b: str, event_name: str
    ) -> None:
        """Functions registered for different job names end up in separate
        job-scoped hook lists.

        **Validates: Requirements 14.2, 15.2, 16.2, 17.2, 34.2**
        """
        registry = FakeRegistry()
        decorator = _make_hook_decorator(
            register_global=registry.register_global,
            register_for_job=registry.register_for_job,
            event_name=event_name,
        )

        def hook_a(rc: Any) -> None:
            pass

        hook_a.__name__ = func_name + "_a"

        def hook_b(rc: Any) -> None:
            pass

        hook_b.__name__ = func_name + "_b"

        # Register for different job names
        decorator(job_name_a)(hook_a)
        decorator(job_name_b)(hook_b)

        # Verify hook_a is in job_name_a's hooks
        assert job_name_a in registry.job_hooks
        assert hook_a in registry.job_hooks[job_name_a]

        # Verify hook_b is in job_name_b's hooks
        assert job_name_b in registry.job_hooks
        assert hook_b in registry.job_hooks[job_name_b]

        # Verify neither appears in global hooks
        assert hook_a not in registry.global_hooks
        assert hook_b not in registry.global_hooks


class TestGlobalOnlyDecoratorRegistration:
    """Property: global-only decorator registers function in global hooks.

    Tests decorators that use _make_global_only_decorator (on_phase_failure,
    on_phase_complete, on_phase_start, on_invoke_failure, on_invoke_start,
    on_invoke_end, on_ready).
    """

    @settings(max_examples=100)
    @given(func_name=func_names)
    def test_global_only_decorator_registers_globally(self, func_name: str) -> None:
        """When _make_global_only_decorator is applied, the function
        ends up in the global hooks list.

        **Validates: Requirements 22.1, 23.1, 24.1, 25.1, 26.1, 27.1, 33.1**
        """
        registry = FakeRegistry()
        decorator = _make_global_only_decorator(
            register=registry.register_global,
        )

        # Create a function with a dynamic name
        def hook_fn(rc: Any, step_name: str, status: Any, msg: str) -> None:
            pass

        hook_fn.__name__ = func_name

        # Apply decorator
        result = decorator(hook_fn)

        # Verify it appears in global hooks
        assert hook_fn in registry.global_hooks
        # Verify identity preservation
        assert result is hook_fn

    @settings(max_examples=100)
    @given(func_names_list=st.lists(func_names, min_size=2, max_size=10, unique=True))
    def test_multiple_global_registrations_preserve_order(
        self, func_names_list: list[str]
    ) -> None:
        """Multiple global-only decorator applications register functions
        in the order they were applied.

        **Validates: Requirements 22.1, 23.1, 24.1, 25.1, 26.1, 27.1, 33.1**
        """
        registry = FakeRegistry()
        decorator = _make_global_only_decorator(
            register=registry.register_global,
        )

        functions: list[Callable[..., Any]] = []
        for name in func_names_list:

            def hook_fn(rc: Any) -> None:
                pass

            hook_fn.__name__ = name
            functions.append(hook_fn)
            decorator(hook_fn)

        # All functions should be in global hooks in order
        assert registry.global_hooks == functions


class TestMixedRegistrationScopes:
    """Property: mixing bare and parameterized forms places hooks in correct scope."""

    @settings(max_examples=100)
    @given(func_name=func_names, job_name=job_names, event_name=event_names)
    def test_bare_and_parameterized_register_to_correct_scope(
        self, func_name: str, job_name: str, event_name: str
    ) -> None:
        """When both bare and parameterized forms are used with the same decorator,
        each function ends up in the correct scope (global vs job-scoped).

        **Validates: Requirements 14.1, 14.2, 15.1, 15.2, 16.1, 16.2, 17.1, 17.2, 34.1, 34.2**
        """
        registry = FakeRegistry()
        decorator = _make_hook_decorator(
            register_global=registry.register_global,
            register_for_job=registry.register_for_job,
            event_name=event_name,
        )

        # Function for global registration
        def global_hook(rc: Any) -> None:
            pass

        global_hook.__name__ = func_name + "_global"

        # Function for job-scoped registration
        def scoped_hook(rc: Any) -> None:
            pass

        scoped_hook.__name__ = func_name + "_scoped"

        # Register bare (global)
        decorator(global_hook)
        # Register parameterized (job-scoped)
        decorator(job_name)(scoped_hook)

        # Verify global hook is in global list only
        assert global_hook in registry.global_hooks
        for hooks_list in registry.job_hooks.values():
            assert global_hook not in hooks_list

        # Verify scoped hook is in job-scoped list only
        assert scoped_hook not in registry.global_hooks
        assert job_name in registry.job_hooks
        assert scoped_hook in registry.job_hooks[job_name]
