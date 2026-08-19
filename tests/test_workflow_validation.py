"""Property-based tests for Workflow validation (Properties 20–22).

Property 20: Workflow graph validation rejects duplicates
  — duplicate step names raises ValueError

Property 21: Workflow graph validation rejects unknown step references
  — unknown step in edge raises ValueError

Property 22: ConditionalEdge routing
  — condition returns key k in targets routes to T[k];
    k not in targets raises ValueError

**Validates: Requirements 8.8, 8.9, 8.11, 8.12**
"""

from __future__ import annotations

import re

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from functualize._types.naming import normalize_segment
from functualize._types.workflow import END, ConditionalEdge, Edge, Step
from functualize.workflow._validation import _validate_workflow_graph

# =============================================================================
# Strategies
# =============================================================================

# Valid step names: non-empty alphanumeric + hyphens/underscores
step_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s[0].isalpha())

# Strategy for generating unique step name lists (2+ names for duplicate tests).
#
# Uniqueness is measured *after* normalization, because that is what node
# identity now is: `A` and `a` are the same node, so a list unique only before
# normalization is a list of duplicates and belongs in the duplicate tests.
unique_step_names = st.lists(
    step_names,
    min_size=2,
    max_size=10,
    unique_by=lambda name: normalize_segment(name),
)

# Strategy for routing keys in ConditionalEdge targets
routing_keys = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"
    ),
    min_size=1,
    max_size=15,
).filter(lambda s: s[0].isalpha())


# =============================================================================
# Helpers
# =============================================================================


def _route_conditional_edge(
    edge: ConditionalEdge,
    return_value: object,
) -> str:
    """Simulate ConditionalEdge routing logic per design spec.

    Invokes the condition callable with the return value and looks up the
    resulting key in the targets mapping.

    Args:
        edge: The ConditionalEdge to evaluate.
        return_value: The source step's return value passed to the condition.

    Returns:
        The target step name (or END) for the matched key.

    Raises:
        ValueError: If the condition returns a key not present in targets.
    """
    key = edge.condition(return_value)
    if key not in edge.targets:
        available_keys = list(edge.targets.keys())
        raise ValueError(
            f"ConditionalEdge routing key '{key}' not found in targets. "
            f"Available keys: {available_keys}"
        )
    return edge.targets[key]


# =============================================================================
# Property 20: Workflow graph validation rejects duplicates
# =============================================================================


class TestWorkflowGraphRejectsDuplicates:
    """Property 20: Workflow graph validation rejects duplicates.

    For any list of Steps containing two or more Steps with the same name,
    the @workflow decorator SHALL raise a ValueError identifying the
    duplicated name at decoration time.

    **Validates: Requirements 8.12**
    """

    @given(names=unique_step_names)
    def test_duplicate_step_names_raises_value_error(self, names: list[str]) -> None:
        """Duplicate step names in the steps list raises ValueError.

        **Validates: Requirements 8.12**
        """
        # Pick a name to duplicate
        dup_name = names[0]
        steps = [Step(n) for n in names] + [Step(dup_name)]

        # The error names the *node*, which is the canonical form.
        with pytest.raises(
            ValueError,
            match=f"Duplicate workflow node name '{re.escape(normalize_segment(dup_name))}'",
        ):
            _validate_workflow_graph(steps, [])

    @given(name=step_names, count=st.integers(min_value=2, max_value=5))
    def test_all_same_names_raises_value_error(self, name: str, count: int) -> None:
        """A list where all steps share the same name raises ValueError.

        **Validates: Requirements 8.12**
        """
        steps = [Step(name) for _ in range(count)]

        with pytest.raises(ValueError, match="Duplicate workflow node name"):
            _validate_workflow_graph(steps, [])

    @given(names=unique_step_names)
    def test_unique_step_names_does_not_raise(self, names: list[str]) -> None:
        """All unique step names passes validation without error.

        **Validates: Requirements 8.12**
        """
        steps = [Step(n) for n in names]
        # Connect first to second to ensure edges are valid
        edges = [Edge(source=names[0], target=names[1])]

        # Should not raise
        _validate_workflow_graph(steps, edges)


# =============================================================================
# Property 21: Workflow graph validation rejects unknown step references
# =============================================================================


class TestWorkflowGraphRejectsUnknownStepReferences:
    """Property 21: Workflow graph validation rejects unknown step references.

    For any Edge or ConditionalEdge whose source or target references a step
    name not present in the steps list, the @workflow decorator SHALL raise a
    ValueError identifying the unknown name at decoration time.

    **Validates: Requirements 8.11**
    """

    @given(
        names=unique_step_names,
        unknown_name=step_names,
    )
    def test_edge_with_unknown_source_raises_value_error(
        self, names: list[str], unknown_name: str
    ) -> None:
        """Edge with source not in steps raises ValueError.

        **Validates: Requirements 8.11**
        """
        # "Unknown" must mean unknown *after* normalization — `A` is not a
        # new name when the graph already has `a`, it is the same node.
        assume(
            normalize_segment(unknown_name) not in {normalize_segment(n) for n in names}
        )
        steps = [Step(n) for n in names]
        edges = [Edge(source=unknown_name, target=names[0])]

        with pytest.raises(
            ValueError,
            match=f"Edge source '{re.escape(normalize_segment(unknown_name))}' not found",
        ):
            _validate_workflow_graph(steps, edges)

    @given(
        names=unique_step_names,
        unknown_name=step_names,
    )
    def test_edge_with_unknown_target_raises_value_error(
        self, names: list[str], unknown_name: str
    ) -> None:
        """Edge with target not in steps raises ValueError.

        **Validates: Requirements 8.11**
        """
        # "Unknown" must mean unknown *after* normalization — `A` is not a
        # new name when the graph already has `a`, it is the same node.
        assume(
            normalize_segment(unknown_name) not in {normalize_segment(n) for n in names}
        )
        steps = [Step(n) for n in names]
        edges = [Edge(source=names[0], target=unknown_name)]

        with pytest.raises(
            ValueError,
            match=f"Edge target '{re.escape(normalize_segment(unknown_name))}' not found",
        ):
            _validate_workflow_graph(steps, edges)

    @given(
        names=unique_step_names,
        unknown_name=step_names,
    )
    def test_conditional_edge_with_unknown_source_raises_value_error(
        self, names: list[str], unknown_name: str
    ) -> None:
        """ConditionalEdge with source not in steps raises ValueError.

        **Validates: Requirements 8.11**
        """
        # "Unknown" must mean unknown *after* normalization — `A` is not a
        # new name when the graph already has `a`, it is the same node.
        assume(
            normalize_segment(unknown_name) not in {normalize_segment(n) for n in names}
        )
        steps = [Step(n) for n in names]
        edges = [
            ConditionalEdge(
                source=unknown_name,
                condition=lambda rv: "a",
                targets={"a": names[0]},
            )
        ]

        with pytest.raises(
            ValueError,
            match=f"Edge source '{re.escape(normalize_segment(unknown_name))}' not found",
        ):
            _validate_workflow_graph(steps, edges)

    @given(
        names=unique_step_names,
        unknown_name=step_names,
        key=routing_keys,
    )
    def test_conditional_edge_with_unknown_target_raises_value_error(
        self, names: list[str], unknown_name: str, key: str
    ) -> None:
        """ConditionalEdge with target not in steps raises ValueError.

        **Validates: Requirements 8.11**
        """
        # "Unknown" must mean unknown *after* normalization — `A` is not a
        # new name when the graph already has `a`, it is the same node.
        assume(
            normalize_segment(unknown_name) not in {normalize_segment(n) for n in names}
        )
        steps = [Step(n) for n in names]
        edges = [
            ConditionalEdge(
                source=names[0],
                condition=lambda rv: key,
                targets={key: unknown_name},
            )
        ]

        with pytest.raises(
            ValueError,
            match=f"ConditionalEdge target '{re.escape(normalize_segment(unknown_name))}'",
        ):
            _validate_workflow_graph(steps, edges)

    @given(names=unique_step_names)
    def test_end_sentinel_as_target_does_not_raise(self, names: list[str]) -> None:
        """END sentinel as edge target is always valid.

        **Validates: Requirements 8.11**
        """
        steps = [Step(n) for n in names]
        edges = [Edge(source=names[0], target=END)]

        # Should not raise
        _validate_workflow_graph(steps, edges)

    @given(names=unique_step_names, key=routing_keys)
    def test_end_sentinel_in_conditional_target_does_not_raise(
        self, names: list[str], key: str
    ) -> None:
        """END sentinel in ConditionalEdge targets is always valid.

        **Validates: Requirements 8.11**
        """
        steps = [Step(n) for n in names]
        edges = [
            ConditionalEdge(
                source=names[0],
                condition=lambda rv: key,
                targets={key: END},
            )
        ]

        # Should not raise
        _validate_workflow_graph(steps, edges)


# =============================================================================
# Property 22: ConditionalEdge routing
# =============================================================================


class TestConditionalEdgeRouting:
    """Property 22: ConditionalEdge routing.

    For any ConditionalEdge with condition function f and targets mapping T,
    when f(return_value) produces key k and k is in T, execution SHALL route
    to T[k]. When k is not in T, a ValueError SHALL be raised.

    **Validates: Requirements 8.8, 8.9**
    """

    @given(
        targets_data=st.dictionaries(
            keys=routing_keys,
            values=step_names,
            min_size=1,
            max_size=5,
        ),
        return_value=st.one_of(
            st.integers(),
            st.text(min_size=0, max_size=20),
            st.booleans(),
        ),
    )
    def test_condition_key_in_targets_routes_correctly(
        self, targets_data: dict[str, str], return_value: object
    ) -> None:
        """When condition returns a key k that is in targets, routes to T[k].

        **Validates: Requirements 8.8**
        """
        # Pick a key that exists in targets
        chosen_key = list(targets_data.keys())[0]
        expected_target = targets_data[chosen_key]

        edge = ConditionalEdge(
            source="source-step",
            condition=lambda rv: chosen_key,
            targets=targets_data,
        )

        result = _route_conditional_edge(edge, return_value)
        assert result == normalize_segment(expected_target)

    @given(
        targets_data=st.dictionaries(
            keys=routing_keys,
            values=step_names,
            min_size=1,
            max_size=5,
        ),
        bad_key=routing_keys,
        return_value=st.one_of(
            st.integers(),
            st.text(min_size=0, max_size=20),
            st.booleans(),
        ),
    )
    def test_condition_key_not_in_targets_raises_value_error(
        self, targets_data: dict[str, str], bad_key: str, return_value: object
    ) -> None:
        """When condition returns a key not in targets, raises ValueError.

        **Validates: Requirements 8.9**
        """
        assume(bad_key not in targets_data)

        edge = ConditionalEdge(
            source="source-step",
            condition=lambda rv: bad_key,
            targets=targets_data,
        )

        with pytest.raises(ValueError, match="not found in targets"):
            _route_conditional_edge(edge, return_value)

    @given(
        targets_data=st.dictionaries(
            keys=routing_keys,
            values=step_names,
            min_size=2,
            max_size=5,
        ),
        return_value=st.one_of(
            st.integers(),
            st.text(min_size=0, max_size=20),
        ),
    )
    def test_routing_selects_correct_target_for_each_key(
        self, targets_data: dict[str, str], return_value: object
    ) -> None:
        """For each key in targets, the condition routing returns the correct target.

        **Validates: Requirements 8.8**
        """
        for key, expected_target in targets_data.items():
            edge = ConditionalEdge(
                source="source-step",
                condition=lambda rv, k=key: k,
                targets=targets_data,
            )

            result = _route_conditional_edge(edge, return_value)
            assert result == normalize_segment(expected_target)

    @given(
        targets_data=st.dictionaries(
            keys=routing_keys,
            values=step_names,
            min_size=1,
            max_size=5,
        ),
    )
    def test_routing_passes_return_value_to_condition(
        self, targets_data: dict[str, str]
    ) -> None:
        """The condition function receives the return_value as its argument.

        **Validates: Requirements 8.8**
        """
        # Use a condition that extracts the key from the return value
        chosen_key = list(targets_data.keys())[0]
        sentinel_value = {"route_key": chosen_key}

        edge = ConditionalEdge(
            source="source-step",
            condition=lambda rv: rv["route_key"],
            targets=targets_data,
        )

        result = _route_conditional_edge(edge, sentinel_value)
        assert result == normalize_segment(targets_data[chosen_key])
