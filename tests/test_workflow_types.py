"""Unit tests for the workflow vocabulary (Step, Gate, Edge, ConditionalEdge, END).

Covers the narrowed surface: a `Step` is a job reference and nothing else, a
`Gate` is a first-class pause node, and the removed knobs (`Step.name`-as-
identity, `auto`, `awaits_input`, `available_tools`, `force_gate`,
`Edge.map_return_value`) are gone loudly rather than silently accepted.
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import BaseModel

from functualize.workflow import (
    END,
    ConditionalEdge,
    Edge,
    Gate,
    Step,
    Tool,
    _EndSentinel,
)


class SampleInput(BaseModel):
    """Sample BaseModel for testing gate schemas."""

    name: str = "default"
    count: int = 0


def sample_job() -> str:
    """A plain callable standing in for a registered job."""
    return "ok"


class TestEndSentinel:
    """Tests for the END sentinel singleton."""

    def test_end_is_singleton(self) -> None:
        """END is always the same instance."""
        assert END is _EndSentinel()
        assert _EndSentinel() is _EndSentinel()

    def test_end_repr(self) -> None:
        """END has a readable repr."""
        assert repr(END) == "END"


class TestStep:
    """Tests for the Step frozen dataclass."""

    def test_string_ref(self) -> None:
        """A string ref is the node name verbatim."""
        step = Step("build")
        assert step.job == "build"
        assert step.name == "build"

    def test_callable_ref_uses_function_name(self) -> None:
        """A bare callable is addressed by its function name."""
        assert Step(sample_job).name == "sample-job"

    def test_callable_ref_carries_its_group(self) -> None:
        """A grouped job is addressed by its qualified name.

        Users address the job by the name it registers under, so the graph must
        key on that name too — otherwise edges would reference a name that
        appears nowhere in the CLI. Dropping the group here is exactly the bug
        that let boot validate `build.compile_it` while the run looked for
        `compile_it`.
        """

        def compile_it() -> None: ...

        from functualize._types.job_declaration import JobDeclaration

        compile_it.__functualize_job__ = JobDeclaration(group="build")  # type: ignore[attr-defined]
        assert Step(compile_it).name == "build.compile-it"

    def test_is_frozen(self) -> None:
        """Step is immutable."""
        step = Step("build")
        with pytest.raises(dataclasses.FrozenInstanceError):
            step.job = "other"  # type: ignore[misc]

    def test_positional_construction(self) -> None:
        """The single field is positional — Step('build') reads naturally."""
        assert Step("build") == Step(job="build")

    def test_empty_string_rejected(self) -> None:
        """An empty ref names nothing and must not build a graph node."""
        with pytest.raises(ValueError, match="must not be empty"):
            Step("   ")

    def test_non_callable_non_string_rejected(self) -> None:
        """A ref that is neither a name nor a function is a mistake."""
        with pytest.raises(TypeError, match="registered job name or a callable"):
            Step(42)  # type: ignore[arg-type]

    def test_unnamed_callable_rejected(self) -> None:
        """A callable with no usable name cannot key a graph node."""

        class Unnamed:
            def __call__(self) -> None: ...

        with pytest.raises(TypeError, match="named callable"):
            Step(Unnamed()).name  # noqa: B018

    @pytest.mark.parametrize(
        "removed",
        ["name", "auto", "awaits_input", "available_tools", "force_gate"],
    )
    def test_removed_parameters_raise(self, removed: str) -> None:
        """Deleted Step knobs must fail loudly, not be silently ignored.

        These were real parameters before the narrowing. Silently dropping them
        would leave a workflow that looks like it still gates on input but does
        not — the worst possible failure for a pause node.
        """
        with pytest.raises(TypeError):
            Step("build", **{removed: True})  # type: ignore[arg-type]


class TestGate:
    """Tests for the Gate node."""

    def test_minimal(self) -> None:
        """Name plus schema is enough."""
        gate = Gate(name="approval", awaits=SampleInput)
        assert gate.name == "approval"
        assert gate.awaits is SampleInput
        # A tuple, not a list: Gate is frozen, and a mutable field on a frozen
        # dataclass is a hole a caller can widen the tool grant through.
        assert gate.tools == ()

    def test_with_tools(self) -> None:
        """Tools are carried through for the resolving agent."""
        gate = Gate(name="approval", awaits=SampleInput, tools=["search"])
        assert gate.tools == ("search",)
        assert [spec.name for spec in gate.tool_specs()] == ["search"]

    def test_a_tool_wrapper_pins_arguments(self) -> None:
        """`Tool` narrows a job's arguments for this gate only."""
        gate = Gate(
            name="approval",
            awaits=SampleInput,
            tools=[Tool("refund", cap_cents=5000)],
        )
        spec = gate.tool_specs()[0]
        assert spec.name == "refund"
        assert spec.bound == {"cap_cents": 5000}

    def test_is_frozen(self) -> None:
        """Gate is immutable."""
        gate = Gate(name="approval", awaits=SampleInput)
        with pytest.raises(dataclasses.FrozenInstanceError):
            gate.name = "other"  # type: ignore[misc]

    def test_empty_name_rejected(self) -> None:
        """A gate with no name cannot be addressed to resume it."""
        with pytest.raises(ValueError, match="non-empty string"):
            Gate(name="  ", awaits=SampleInput)

    def test_tools_cap(self) -> None:
        """At most 50 tools."""
        with pytest.raises(ValueError, match="at most 50"):
            Gate(name="g", awaits=SampleInput, tools=["t"] * 51)

    def test_tools_cap_boundary(self) -> None:
        """Exactly 50 is allowed."""
        gate = Gate(name="g", awaits=SampleInput, tools=[f"t{i}" for i in range(50)])
        assert len(gate.tools) == 50

    def test_awaits_must_be_model_class(self) -> None:
        """A model *instance* is a common mistake and must be rejected."""
        with pytest.raises(TypeError, match="BaseModel subclass"):
            Gate(name="g", awaits=SampleInput())  # type: ignore[arg-type]

    def test_awaits_must_be_a_model(self) -> None:
        """A non-model class has no JSON schema to publish."""

        class NotAModel:
            pass

        with pytest.raises(TypeError, match="BaseModel subclass"):
            Gate(name="g", awaits=NotAModel)  # type: ignore[arg-type]


class TestEdge:
    """Tests for the Edge dataclass."""

    def test_explicit_target(self) -> None:
        """Edge connects two named nodes."""
        edge = Edge(source="a", target="b")
        assert (edge.source, edge.target) == ("a", "b")

    def test_end_target(self) -> None:
        """END is a valid target."""
        assert Edge(source="a", target=END).target is END

    def test_target_defaults_to_end(self) -> None:
        """Omitting the target terminates the walk."""
        assert Edge(source="a").target is END

    def test_is_frozen(self) -> None:
        """Edge is immutable."""
        edge = Edge(source="a", target="b")
        with pytest.raises(dataclasses.FrozenInstanceError):
            edge.target = "c"  # type: ignore[misc]

    def test_map_return_value_removed(self) -> None:
        """`map_return_value` is gone and must fail loudly.

        It was an untyped value-transform hook that the walker does not honor;
        accepting and ignoring it would silently drop a user's transform.
        """
        with pytest.raises(TypeError):
            Edge(source="a", target="b", map_return_value=lambda x: x)  # type: ignore[call-arg]


class TestConditionalEdge:
    """Tests for the ConditionalEdge dataclass."""

    def test_targets_mapping(self) -> None:
        """Condition keys map to node names."""
        edge = ConditionalEdge(
            source="check", condition=lambda _: "ok", targets={"ok": "deploy"}
        )
        assert edge.targets == {"ok": "deploy"}
        assert edge.condition(None) == "ok"

    def test_end_in_targets(self) -> None:
        """A branch may terminate the walk."""
        edge = ConditionalEdge(
            source="check",
            condition=lambda _: "stop",
            targets={"stop": END, "go": "deploy"},
        )
        assert edge.targets["stop"] is END

    def test_is_frozen(self) -> None:
        """ConditionalEdge is immutable."""
        edge = ConditionalEdge(source="a", condition=lambda _: "b", targets={"b": "c"})
        with pytest.raises(dataclasses.FrozenInstanceError):
            edge.source = "z"  # type: ignore[misc]
