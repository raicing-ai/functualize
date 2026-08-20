"""Property-based tests for PRE_EXECUTE pipeline (Property 4).

Property 4: PRE_EXECUTE pipeline correctly chains MODIFY, stops at BLOCK,
passes through on PROCEED.

For any sequence of PRE_EXECUTE hooks returning a mix of HookDecision.PROCEED,
HookDecision.MODIFY(new_kwargs), and HookDecision.BLOCK(reason), the engine SHALL:
(a) chain MODIFY transformations — each subsequent hook sees the kwargs as modified
    by preceding hooks,
(b) stop processing at the first BLOCK and return without calling subsequent hooks,
(c) pass through unchanged on PROCEED/None.

**Validates: Requirements 2.2, 2.3, 2.4, 2.5**
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from functualize._events.hooks import HookDecision, HookEvent, HookRegistry
from functualize.job.context import RunContext

# --- Strategies ---

# Strategy to generate a HookDecision action type
decision_actions = st.sampled_from(["proceed", "block", "modify", "none"])

# Strategy for kwargs dictionaries (simple string keys with int values)
kwargs_st = st.dictionaries(
    keys=st.text(
        alphabet=st.characters(whitelist_categories=("L",), whitelist_characters="_"),
        min_size=1,
        max_size=5,
    ),
    values=st.integers(min_value=-100, max_value=100),
    min_size=1,
    max_size=5,
)

# Strategy for block reasons
block_reasons = st.text(min_size=1, max_size=100)

# Strategy for sequences of decision actions (the pipeline)
decision_sequences = st.lists(decision_actions, min_size=1, max_size=10)


class TestPreExecutePipelineProperty:
    """Property 4: PRE_EXECUTE pipeline correctly chains MODIFY, stops at BLOCK,
    passes through on PROCEED.

    **Validates: Requirements 2.2, 2.3, 2.4, 2.5**
    """

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        decisions=decision_sequences,
        initial_kwargs=kwargs_st,
    )
    def test_block_stops_pipeline_immediately(
        self,
        decisions: list[str],
        initial_kwargs: dict[str, int],
    ):
        """**Validates: Requirements 2.2, 2.5**

        For any sequence of decisions containing a BLOCK, hooks after the first
        BLOCK are never invoked, and the result is a BLOCK decision.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invoked_indices: list[int] = []

        for i, action in enumerate(decisions):
            idx = i  # capture

            if action == "block":

                def make_block_hook(index: int):
                    def hook(rc, kwargs):
                        invoked_indices.append(index)
                        return HookDecision.BLOCK(f"blocked_at_{index}")

                    return hook

                registry.register_global(HookEvent.PRE_EXECUTE, make_block_hook(idx))
            elif action == "modify":

                def make_modify_hook(index: int):
                    def hook(rc, kwargs):
                        invoked_indices.append(index)
                        new_kwargs = dict(kwargs)
                        new_kwargs[f"added_by_{index}"] = index
                        return HookDecision.MODIFY(new_kwargs)

                    return hook

                registry.register_global(HookEvent.PRE_EXECUTE, make_modify_hook(idx))
            elif action == "none":

                def make_none_hook(index: int):
                    def hook(rc, kwargs):
                        invoked_indices.append(index)
                        return None

                    return hook

                registry.register_global(HookEvent.PRE_EXECUTE, make_none_hook(idx))
            else:  # proceed

                def make_proceed_hook(index: int):
                    def hook(rc, kwargs):
                        invoked_indices.append(index)
                        return HookDecision.PROCEED()

                    return hook

                registry.register_global(HookEvent.PRE_EXECUTE, make_proceed_hook(idx))

        result = registry.invoke_pre_execute("test_job", mock_rc, initial_kwargs)

        # Find the first BLOCK index (if any)
        first_block_idx = None
        for i, action in enumerate(decisions):
            if action == "block":
                first_block_idx = i
                break

        if first_block_idx is not None:
            # Only hooks up to and including the first BLOCK should be invoked
            assert invoked_indices == list(range(first_block_idx + 1))
            # Result must be a BLOCK decision
            assert result is not None
            assert result.is_block
            assert result.reason == f"blocked_at_{first_block_idx}"
        else:
            # All hooks should be invoked
            assert invoked_indices == list(range(len(decisions)))

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        num_modify_hooks=st.integers(min_value=1, max_value=8),
        initial_kwargs=kwargs_st,
    )
    def test_modify_chains_kwargs_through_pipeline(
        self,
        num_modify_hooks: int,
        initial_kwargs: dict[str, int],
    ):
        """**Validates: Requirements 2.3, 2.5**

        For any sequence of MODIFY hooks, each subsequent hook receives the kwargs
        as modified by all preceding MODIFY hooks. The final result accumulates
        all modifications.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        received_kwargs: list[dict] = []

        for i in range(num_modify_hooks):

            def make_hook(index: int):
                def hook(rc, kwargs):
                    received_kwargs.append(dict(kwargs))
                    new_kwargs = dict(kwargs)
                    new_kwargs[f"key_{index}"] = index * 10
                    return HookDecision.MODIFY(new_kwargs)

                return hook

            registry.register_global(HookEvent.PRE_EXECUTE, make_hook(i))

        result = registry.invoke_pre_execute("test_job", mock_rc, initial_kwargs)

        # Result should be a MODIFY with all accumulated keys
        assert result is not None
        assert result.is_modify
        assert result.kwargs is not None

        # The final kwargs should contain all keys from initial + each hook's addition
        for i in range(num_modify_hooks):
            assert f"key_{i}" in result.kwargs
            assert result.kwargs[f"key_{i}"] == i * 10

        # Each hook receives the kwargs modified by all preceding hooks
        for i, received in enumerate(received_kwargs):
            # Hook i should see initial kwargs + keys added by hooks 0..i-1
            for j in range(i):
                assert f"key_{j}" in received
                assert received[f"key_{j}"] == j * 10
            # Hook i should NOT see its own key yet
            assert f"key_{i}" not in received

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        num_proceed_hooks=st.integers(min_value=1, max_value=8),
        initial_kwargs=kwargs_st,
        use_none=st.lists(st.booleans(), min_size=1, max_size=8),
    )
    def test_proceed_and_none_pass_through_unchanged(
        self,
        num_proceed_hooks: int,
        initial_kwargs: dict[str, int],
        use_none: list[bool],
    ):
        """**Validates: Requirements 2.4, 2.5**

        For any sequence of hooks returning PROCEED or None, the pipeline returns
        None (no changes), and each hook receives the original kwargs unchanged.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        received_kwargs: list[dict] = []

        for i in range(num_proceed_hooks):
            # Decide whether this hook returns None or PROCEED
            returns_none = use_none[i % len(use_none)]

            def make_hook(index: int, ret_none: bool):
                def hook(rc, kwargs):
                    received_kwargs.append(dict(kwargs))
                    return None if ret_none else HookDecision.PROCEED()

                return hook

            registry.register_global(HookEvent.PRE_EXECUTE, make_hook(i, returns_none))

        result = registry.invoke_pre_execute("test_job", mock_rc, initial_kwargs)

        # No modifications, no blocks — result should be None
        assert result is None

        # All hooks should have been invoked
        assert len(received_kwargs) == num_proceed_hooks

        # Each hook should see the original kwargs (since no MODIFY occurred)
        for received in received_kwargs:
            assert received == initial_kwargs

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        decisions=st.lists(
            st.sampled_from(["proceed", "modify", "none"]),
            min_size=2,
            max_size=8,
        ),
        initial_kwargs=kwargs_st,
    )
    def test_modify_among_proceed_chains_correctly(
        self,
        decisions: list[str],
        initial_kwargs: dict[str, int],
    ):
        """**Validates: Requirements 2.3, 2.4, 2.5**

        For any interleaving of MODIFY with PROCEED/None, MODIFY hooks
        accumulate changes while PROCEED/None hooks see current state
        but don't alter it. The final result reflects only MODIFY changes.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        received_kwargs: list[dict] = []

        modify_count = 0
        for i, action in enumerate(decisions):
            if action == "modify":
                modify_idx = modify_count

                def make_modify_hook(index: int, m_idx: int):
                    def hook(rc, kwargs):
                        received_kwargs.append(dict(kwargs))
                        new_kwargs = dict(kwargs)
                        new_kwargs[f"mod_{m_idx}"] = m_idx
                        return HookDecision.MODIFY(new_kwargs)

                    return hook

                registry.register_global(
                    HookEvent.PRE_EXECUTE, make_modify_hook(i, modify_idx)
                )
                modify_count += 1
            else:

                def make_passthrough_hook(index: int, act: str):
                    def hook(rc, kwargs):
                        received_kwargs.append(dict(kwargs))
                        return None if act == "none" else HookDecision.PROCEED()

                    return hook

                registry.register_global(
                    HookEvent.PRE_EXECUTE, make_passthrough_hook(i, action)
                )

        result = registry.invoke_pre_execute("test_job", mock_rc, initial_kwargs)

        if modify_count > 0:
            # There was at least one MODIFY, so result should be a MODIFY
            assert result is not None
            assert result.is_modify
            assert result.kwargs is not None

            # Final kwargs should contain all mod keys
            for m in range(modify_count):
                assert f"mod_{m}" in result.kwargs
                assert result.kwargs[f"mod_{m}"] == m
        else:
            # Only PROCEED/None — result should be None
            assert result is None

        # All hooks should have been invoked (no BLOCK in this test)
        assert len(received_kwargs) == len(decisions)

    @settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(
        pre_block_decisions=st.lists(
            st.sampled_from(["proceed", "modify", "none"]),
            min_size=0,
            max_size=5,
        ),
        post_block_decisions=st.lists(
            st.sampled_from(["proceed", "modify", "none", "block"]),
            min_size=1,
            max_size=5,
        ),
        initial_kwargs=kwargs_st,
        block_reason=block_reasons,
    )
    def test_block_after_modifications_still_blocks(
        self,
        pre_block_decisions: list[str],
        post_block_decisions: list[str],
        initial_kwargs: dict[str, int],
        block_reason: str,
    ):
        """**Validates: Requirements 2.2, 2.3, 2.5**

        For any sequence of PROCEED/MODIFY hooks followed by a BLOCK hook,
        the BLOCK takes precedence. Hooks after the BLOCK are never invoked,
        regardless of preceding modifications.
        """
        registry = HookRegistry()
        mock_rc = MagicMock(spec=RunContext)
        invoked_indices: list[int] = []

        # Register pre-block hooks
        for i, action in enumerate(pre_block_decisions):

            def make_hook(index: int, act: str):
                def hook(rc, kwargs):
                    invoked_indices.append(index)
                    if act == "modify":
                        new_kwargs = dict(kwargs)
                        new_kwargs[f"pre_{index}"] = index
                        return HookDecision.MODIFY(new_kwargs)
                    return None if act == "none" else HookDecision.PROCEED()

                return hook

            registry.register_global(HookEvent.PRE_EXECUTE, make_hook(i, action))

        # Register the BLOCK hook
        block_idx = len(pre_block_decisions)

        def make_block_hook(index: int, reason: str):
            def hook(rc, kwargs):
                invoked_indices.append(index)
                return HookDecision.BLOCK(reason)

            return hook

        registry.register_global(
            HookEvent.PRE_EXECUTE, make_block_hook(block_idx, block_reason)
        )

        # Register post-block hooks (should never be invoked)
        for i, _action in enumerate(post_block_decisions):
            post_idx = block_idx + 1 + i

            def make_post_hook(index: int):
                def hook(rc, kwargs):
                    invoked_indices.append(index)
                    return HookDecision.PROCEED()

                return hook

            registry.register_global(HookEvent.PRE_EXECUTE, make_post_hook(post_idx))

        result = registry.invoke_pre_execute("test_job", mock_rc, initial_kwargs)

        # Result must be a BLOCK
        assert result is not None
        assert result.is_block
        assert result.reason == block_reason

        # Only pre-block hooks and the block hook itself should be invoked
        expected_invoked = list(range(block_idx + 1))
        assert invoked_indices == expected_invoked
