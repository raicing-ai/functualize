"""Property-based tests for config hook invocation ordering using Hypothesis.

Tests Property 27 from the design document.

**Validates: Requirements 9.1, 9.2**
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from functualize._events.hooks import ConfigHookEvent, HookRegistry

# --- Strategies ---

# Strategy for number of hooks to register per event
hook_counts = st.integers(min_value=1, max_value=5)

# Strategy for the number of resolve cycles to simulate
resolve_cycles = st.integers(min_value=1, max_value=5)


# --- Test helpers ---


class InvocationTracker:
    """Records the order of hook invocations with event names and arguments."""

    def __init__(self) -> None:
        self.invocations: list[tuple[str, tuple[Any, ...]]] = []

    def make_hook(self, event_name: str) -> Callable[..., Any]:
        """Create a hook callable that records its event name and arguments."""

        def hook(*args: Any) -> None:
            self.invocations.append((event_name, args))

        hook.__name__ = f"hook_{event_name}"
        return hook

    def event_order(self) -> list[str]:
        """Return the list of event names in invocation order."""
        return [event for event, _ in self.invocations]


# --- Property 27: Config hook invocation ordering ---


class TestProperty27ConfigHookInvocationOrdering:
    """Config hooks must fire in the correct order during bootstrap and
    model resolution:
    - AFTER_CONFIG_INIT fires first (after ResolutionChain is built)
    - BEFORE_CONFIG_RESOLVE fires before each model resolution
    - AFTER_CONFIG_RESOLVE fires after each model resolution

    The ordering guarantee ensures that plugins registered via entry points
    (Requirements 9.1) or programmatic registration (Requirements 9.2)
    have their providers available before config resolution occurs.

    **Validates: Requirements 9.1, 9.2**
    """

    @given(
        num_init_hooks=hook_counts,
        num_before_hooks=hook_counts,
        num_after_hooks=hook_counts,
    )
    def test_init_always_before_resolve_events(
        self,
        num_init_hooks: int,
        num_before_hooks: int,
        num_after_hooks: int,
    ) -> None:
        """AFTER_CONFIG_INIT hooks always fire before any
        BEFORE_CONFIG_RESOLVE or AFTER_CONFIG_RESOLVE hooks when
        simulating the bootstrap sequence."""
        registry = HookRegistry()
        tracker = InvocationTracker()

        # Register varying numbers of hooks for each event
        for _ in range(num_init_hooks):
            registry.register_global(
                ConfigHookEvent.AFTER_CONFIG_INIT,
                tracker.make_hook(ConfigHookEvent.AFTER_CONFIG_INIT),
            )
        for _ in range(num_before_hooks):
            registry.register_global(
                ConfigHookEvent.BEFORE_CONFIG_RESOLVE,
                tracker.make_hook(ConfigHookEvent.BEFORE_CONFIG_RESOLVE),
            )
        for _ in range(num_after_hooks):
            registry.register_global(
                ConfigHookEvent.AFTER_CONFIG_RESOLVE,
                tracker.make_hook(ConfigHookEvent.AFTER_CONFIG_RESOLVE),
            )

        # Simulate bootstrap: fire AFTER_CONFIG_INIT, then a resolve cycle
        resolution_chain_stub = object()
        registry.invoke_config_event(
            ConfigHookEvent.AFTER_CONFIG_INIT, resolution_chain_stub
        )
        registry.invoke_config_event(
            ConfigHookEvent.BEFORE_CONFIG_RESOLVE, "section", type
        )
        registry.invoke_config_event(
            ConfigHookEvent.AFTER_CONFIG_RESOLVE, "section", object()
        )

        order = tracker.event_order()

        # All AFTER_CONFIG_INIT events must precede BEFORE_CONFIG_RESOLVE
        init_indices = [
            i for i, e in enumerate(order) if e == ConfigHookEvent.AFTER_CONFIG_INIT
        ]
        before_indices = [
            i for i, e in enumerate(order) if e == ConfigHookEvent.BEFORE_CONFIG_RESOLVE
        ]
        after_indices = [
            i for i, e in enumerate(order) if e == ConfigHookEvent.AFTER_CONFIG_RESOLVE
        ]

        # AFTER_CONFIG_INIT always before BEFORE_CONFIG_RESOLVE
        if init_indices and before_indices:
            assert max(init_indices) < min(before_indices)

        # BEFORE_CONFIG_RESOLVE always before AFTER_CONFIG_RESOLVE
        if before_indices and after_indices:
            assert max(before_indices) < min(after_indices)

        # Verify correct counts
        assert len(init_indices) == num_init_hooks
        assert len(before_indices) == num_before_hooks
        assert len(after_indices) == num_after_hooks

    @given(
        num_cycles=resolve_cycles,
        num_before_hooks=hook_counts,
        num_after_hooks=hook_counts,
    )
    def test_before_resolve_always_before_after_resolve_per_cycle(
        self,
        num_cycles: int,
        num_before_hooks: int,
        num_after_hooks: int,
    ) -> None:
        """For each resolution cycle, all BEFORE_CONFIG_RESOLVE hooks fire
        before any AFTER_CONFIG_RESOLVE hooks."""
        registry = HookRegistry()
        tracker = InvocationTracker()

        for _ in range(num_before_hooks):
            registry.register_global(
                ConfigHookEvent.BEFORE_CONFIG_RESOLVE,
                tracker.make_hook(ConfigHookEvent.BEFORE_CONFIG_RESOLVE),
            )
        for _ in range(num_after_hooks):
            registry.register_global(
                ConfigHookEvent.AFTER_CONFIG_RESOLVE,
                tracker.make_hook(ConfigHookEvent.AFTER_CONFIG_RESOLVE),
            )

        # Simulate multiple resolution cycles (as when resolving multiple models)
        for cycle in range(num_cycles):
            registry.invoke_config_event(
                ConfigHookEvent.BEFORE_CONFIG_RESOLVE, f"section_{cycle}", type
            )
            registry.invoke_config_event(
                ConfigHookEvent.AFTER_CONFIG_RESOLVE, f"section_{cycle}", object()
            )

        order = tracker.event_order()

        # Verify ordering within each cycle:
        # The pattern should be (BEFORE * num_before_hooks, AFTER * num_after_hooks) repeated
        events_per_cycle = num_before_hooks + num_after_hooks
        for cycle in range(num_cycles):
            start = cycle * events_per_cycle
            cycle_events = order[start : start + events_per_cycle]

            before_in_cycle = [
                i
                for i, e in enumerate(cycle_events)
                if e == ConfigHookEvent.BEFORE_CONFIG_RESOLVE
            ]
            after_in_cycle = [
                i
                for i, e in enumerate(cycle_events)
                if e == ConfigHookEvent.AFTER_CONFIG_RESOLVE
            ]

            assert len(before_in_cycle) == num_before_hooks
            assert len(after_in_cycle) == num_after_hooks

            # All BEFORE events come before all AFTER events in each cycle
            if before_in_cycle and after_in_cycle:
                assert max(before_in_cycle) < min(after_in_cycle)

    @given(
        num_init_hooks=hook_counts,
        num_before_hooks=hook_counts,
        num_after_hooks=hook_counts,
        num_cycles=resolve_cycles,
    )
    def test_full_bootstrap_ordering_with_multiple_resolutions(
        self,
        num_init_hooks: int,
        num_before_hooks: int,
        num_after_hooks: int,
        num_cycles: int,
    ) -> None:
        """Full bootstrap sequence: AFTER_CONFIG_INIT fires once, then
        multiple (BEFORE_CONFIG_RESOLVE, AFTER_CONFIG_RESOLVE) pairs.
        The init event always precedes all resolve events."""
        registry = HookRegistry()
        tracker = InvocationTracker()

        for _ in range(num_init_hooks):
            registry.register_global(
                ConfigHookEvent.AFTER_CONFIG_INIT,
                tracker.make_hook(ConfigHookEvent.AFTER_CONFIG_INIT),
            )
        for _ in range(num_before_hooks):
            registry.register_global(
                ConfigHookEvent.BEFORE_CONFIG_RESOLVE,
                tracker.make_hook(ConfigHookEvent.BEFORE_CONFIG_RESOLVE),
            )
        for _ in range(num_after_hooks):
            registry.register_global(
                ConfigHookEvent.AFTER_CONFIG_RESOLVE,
                tracker.make_hook(ConfigHookEvent.AFTER_CONFIG_RESOLVE),
            )

        # Step 1: Fire AFTER_CONFIG_INIT (happens once during bootstrap)
        registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())

        # Step 2: Multiple resolve cycles
        for cycle in range(num_cycles):
            registry.invoke_config_event(
                ConfigHookEvent.BEFORE_CONFIG_RESOLVE, f"section_{cycle}", type
            )
            registry.invoke_config_event(
                ConfigHookEvent.AFTER_CONFIG_RESOLVE, f"section_{cycle}", object()
            )

        order = tracker.event_order()

        # All init events must come first
        init_indices = [
            i for i, e in enumerate(order) if e == ConfigHookEvent.AFTER_CONFIG_INIT
        ]
        non_init_indices = [
            i for i, e in enumerate(order) if e != ConfigHookEvent.AFTER_CONFIG_INIT
        ]

        assert len(init_indices) == num_init_hooks

        if init_indices and non_init_indices:
            assert max(init_indices) < min(non_init_indices)

        # Total events expected
        expected_total = num_init_hooks + num_cycles * (
            num_before_hooks + num_after_hooks
        )
        assert len(order) == expected_total

    @given(
        data=st.data(),
        num_hooks=st.integers(min_value=1, max_value=8),
    )
    def test_registration_order_preserved_within_same_event(
        self,
        data: st.DataObject,
        num_hooks: int,
    ) -> None:
        """Hooks registered for the same config event fire in
        registration order (FIFO)."""
        registry = HookRegistry()
        call_order: list[int] = []

        event = data.draw(
            st.sampled_from(
                [
                    ConfigHookEvent.AFTER_CONFIG_INIT,
                    ConfigHookEvent.BEFORE_CONFIG_RESOLVE,
                    ConfigHookEvent.AFTER_CONFIG_RESOLVE,
                ]
            ),
            label="event",
        )

        # Register hooks with unique indices
        for idx in range(num_hooks):

            def make_appender(i: int) -> Callable[..., Any]:
                def hook(*args: Any) -> None:
                    call_order.append(i)

                hook.__name__ = f"hook_{i}"
                return hook

            registry.register_global(event, make_appender(idx))

        # Invoke the event
        if event == ConfigHookEvent.AFTER_CONFIG_INIT:
            registry.invoke_config_event(event, object())
        elif event == ConfigHookEvent.BEFORE_CONFIG_RESOLVE:
            registry.invoke_config_event(event, "section", type)
        else:
            registry.invoke_config_event(event, "section", object())

        # Hooks should fire in registration order
        assert call_order == list(range(num_hooks))

    @given(
        num_init_hooks=hook_counts,
        num_before_hooks=hook_counts,
        num_after_hooks=hook_counts,
    )
    def test_hook_failure_does_not_break_ordering(
        self,
        num_init_hooks: int,
        num_before_hooks: int,
        num_after_hooks: int,
    ) -> None:
        """A failing hook does not prevent subsequent hooks from firing,
        and the overall ordering guarantee is maintained."""
        registry = HookRegistry()
        tracker = InvocationTracker()

        # Register a mix of normal and failing hooks for AFTER_CONFIG_INIT
        for i in range(num_init_hooks):
            if i == 0:
                # First hook fails

                def failing_hook(*args: Any) -> None:
                    tracker.invocations.append(
                        (ConfigHookEvent.AFTER_CONFIG_INIT, args)
                    )
                    raise RuntimeError("hook failure")

                failing_hook.__name__ = "failing_hook"
                registry.register_global(
                    ConfigHookEvent.AFTER_CONFIG_INIT, failing_hook
                )
            else:
                registry.register_global(
                    ConfigHookEvent.AFTER_CONFIG_INIT,
                    tracker.make_hook(ConfigHookEvent.AFTER_CONFIG_INIT),
                )

        for _ in range(num_before_hooks):
            registry.register_global(
                ConfigHookEvent.BEFORE_CONFIG_RESOLVE,
                tracker.make_hook(ConfigHookEvent.BEFORE_CONFIG_RESOLVE),
            )
        for _ in range(num_after_hooks):
            registry.register_global(
                ConfigHookEvent.AFTER_CONFIG_RESOLVE,
                tracker.make_hook(ConfigHookEvent.AFTER_CONFIG_RESOLVE),
            )

        # Simulate bootstrap — should not raise despite the failing hook
        registry.invoke_config_event(ConfigHookEvent.AFTER_CONFIG_INIT, object())
        registry.invoke_config_event(
            ConfigHookEvent.BEFORE_CONFIG_RESOLVE, "section", type
        )
        registry.invoke_config_event(
            ConfigHookEvent.AFTER_CONFIG_RESOLVE, "section", object()
        )

        order = tracker.event_order()

        # Even with a failure, all hooks that didn't fail still fire
        init_count = sum(1 for e in order if e == ConfigHookEvent.AFTER_CONFIG_INIT)
        before_count = sum(
            1 for e in order if e == ConfigHookEvent.BEFORE_CONFIG_RESOLVE
        )
        after_count = sum(1 for e in order if e == ConfigHookEvent.AFTER_CONFIG_RESOLVE)

        # The failing hook still recorded its invocation (it runs, then fails)
        assert init_count == num_init_hooks
        assert before_count == num_before_hooks
        assert after_count == num_after_hooks

        # Ordering property still holds
        init_indices = [
            i for i, e in enumerate(order) if e == ConfigHookEvent.AFTER_CONFIG_INIT
        ]
        before_indices = [
            i for i, e in enumerate(order) if e == ConfigHookEvent.BEFORE_CONFIG_RESOLVE
        ]
        after_indices = [
            i for i, e in enumerate(order) if e == ConfigHookEvent.AFTER_CONFIG_RESOLVE
        ]

        if init_indices and before_indices:
            assert max(init_indices) < min(before_indices)
        if before_indices and after_indices:
            assert max(before_indices) < min(after_indices)
