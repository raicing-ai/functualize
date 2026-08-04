"""Tests for the cached @workflow graph shape (schema §2, cache v10).

The point of caching the shape is that listing and describing a workflow —
including over MCP — must not import the module that declared it. So these
tests care about two things: the topology round-trips faithfully, and the
things that *cannot* round-trip (condition callables, gate model classes) are
dropped honestly rather than faked.
"""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from functualize._types.descriptors import JobDescriptor
from functualize._types.workflow import (
    END,
    ConditionalEdge,
    Edge,
    Gate,
    Step,
    WorkflowDeclaration,
    WorkflowShape,
    workflow_shape_of,
)
from functualize.workflow import workflow


class TripPreferences(BaseModel):
    """Gate schema used across these tests."""

    budget: str = "mid"


def _declaration() -> WorkflowDeclaration:
    return WorkflowDeclaration(
        nodes=(
            Step("forecast"),
            Gate(name="preferences", awaits=TripPreferences),
            Step("travel_plan"),
        ),
        edges=(
            Edge(source="forecast", target="preferences"),
            Edge(source="preferences", target="travel_plan"),
            Edge(source="travel_plan", target=END),
        ),
    )


class TestProjection:
    """Declaration -> shape."""

    def test_nodes_keep_name_and_kind(self) -> None:
        """Steps and gates stay distinguishable in the cache."""
        shape = _declaration().shape()
        assert shape.step_names() == ("forecast", "travel-plan")
        assert shape.gate_names() == ("preferences",)

    def test_declaration_order_is_preserved(self) -> None:
        """Order matters — the first node is the entry point."""
        assert [n.name for n in _declaration().shape().nodes] == [
            "forecast",
            "preferences",
            "travel-plan",
        ]
        assert _declaration().shape().entry == "forecast"

    def test_gate_keeps_only_the_model_name(self) -> None:
        """The model *class* cannot be cached; its name can.

        Resolving the name back to a class needs the declaring module, which
        is precisely the import warm boot exists to avoid. The real schema
        materializes on demand.
        """
        gate = next(n for n in _declaration().shape().nodes if n.kind == "gate")
        assert gate.model == "TripPreferences"

    def test_end_target_becomes_none(self) -> None:
        """END is not a node, so it serializes as null rather than a name."""
        last = _declaration().shape().edges[-1]
        assert last.source == "travel-plan"
        assert last.target is None

    def test_conditional_edge_keeps_targets_but_drops_the_condition(self) -> None:
        """Branch targets survive; the callable that chooses between them does not.

        Keeping a stub condition would be worse than dropping it — a cached
        graph that looks routable but always picks the wrong branch is harder
        to debug than one that plainly has no condition.
        """
        declaration = WorkflowDeclaration(
            nodes=(Step("check"), Step("deploy")),
            edges=(
                ConditionalEdge(
                    source="check",
                    condition=lambda _: "ok",
                    targets={"ok": "deploy", "stop": END},
                ),
            ),
        )
        edge = declaration.shape().edges[0]
        assert edge.conditional is True
        assert dict(edge.targets) == {"ok": "deploy", "stop": None}
        assert not hasattr(edge, "condition")

    def test_shape_of_a_non_workflow_is_none(self) -> None:
        """Discovery calls this on every function; ordinary jobs yield None."""

        def ordinary() -> None: ...

        assert workflow_shape_of(ordinary) is None

    def test_shape_of_a_decorated_function(self) -> None:
        """The helper reads the dunder attached by @workflow."""

        @workflow(steps=[Step("a")], edges=[Edge(source="a", target=END)])
        def flow() -> None: ...

        shape = workflow_shape_of(flow)
        assert shape is not None
        assert shape.step_names() == ("a",)


class TestRoundTrip:
    """shape -> JSON -> shape."""

    def test_survives_json(self) -> None:
        """The cache is a JSON file; the shape must survive a real round-trip."""
        original = _declaration().shape()
        restored = WorkflowShape.from_dict(json.loads(json.dumps(original.to_dict())))
        assert restored == original

    def test_conditional_edge_survives_json(self) -> None:
        """Branch targets round-trip, including END-as-null."""
        declaration = WorkflowDeclaration(
            nodes=(Step("check"), Step("deploy")),
            edges=(
                ConditionalEdge(
                    source="check",
                    condition=lambda _: "ok",
                    targets={"ok": "deploy", "stop": END},
                ),
            ),
        )
        original = declaration.shape()
        restored = WorkflowShape.from_dict(json.loads(json.dumps(original.to_dict())))
        assert restored == original

    def test_empty_graph_round_trips(self) -> None:
        """A workflow with no nodes is degenerate but must not crash."""
        assert WorkflowShape.from_dict(WorkflowShape().to_dict()) == WorkflowShape()

    @pytest.mark.parametrize(
        "corrupt",
        [
            {"steps": [{"neither": "x"}], "edges": []},
            {"steps": ["not-a-dict"], "edges": []},
            {"steps": [], "edges": [{"missing-from": True}]},
            {"steps": [], "edges": [{"from": "a", "conditional": True}]},
            {"steps": [], "edges": [{"from": "a", "conditional": True, "targets": 3}]},
        ],
    )
    def test_corrupt_entry_yields_none(self, corrupt: dict) -> None:
        """A malformed entry rebuilds rather than half-loads.

        A graph silently missing an edge would walk somewhere its author never
        declared — strictly worse than a cache miss.
        """
        assert WorkflowShape.from_dict(corrupt) is None

    def test_non_dict_yields_none(self) -> None:
        """Anything that is not an object is not a graph."""
        assert WorkflowShape.from_dict("nope") is None


class TestDescriptorIntegration:
    """The shape rides on JobDescriptor into cache.json."""

    def _descriptor(self, **kwargs: object) -> JobDescriptor:
        return JobDescriptor(
            name="trip_planner",
            group=None,
            module_path="jobs",
            source_file="jobs.py",
            source_mtime=1.0,
            content_hash="abc",
            docstring=None,
            config_fields=[],
            dependencies={},
            metadata={},
            **kwargs,  # type: ignore[arg-type]
        )

    def test_workflow_round_trips_through_the_descriptor(self) -> None:
        """A workflow job's graph survives cache write + read."""
        descriptor = self._descriptor(workflow=_declaration().shape())
        restored = JobDescriptor.from_dict(json.loads(json.dumps(descriptor.to_dict())))
        assert restored.workflow == _declaration().shape()

    def test_ordinary_job_has_no_workflow(self) -> None:
        """Non-workflow jobs serialize workflow as null."""
        descriptor = self._descriptor()
        assert descriptor.to_dict()["workflow"] is None
        assert JobDescriptor.from_dict(descriptor.to_dict()).workflow is None

    def test_pre_v10_entry_reads_as_not_a_workflow(self) -> None:
        """Cache entries written before v10 have no workflow key at all.

        Backward-compatible on read; the version bump forces the rebuild that
        actually populates it.
        """
        data = self._descriptor().to_dict()
        del data["workflow"]
        assert JobDescriptor.from_dict(data).workflow is None


class TestLazyBootContract:
    """The reason the shape is cached at all."""

    def test_reading_a_cached_workflow_imports_nothing(self, tmp_path) -> None:
        """Describing a cached workflow must not import the declaring module.

        This is the whole justification for caching the topology instead of
        reading ``__functualize_workflow__`` off the live function. The module
        writes to a marker file on import, so any import is observable.
        """
        import sys
        import uuid

        module_name = f"wfmod_{uuid.uuid4().hex[:12]}"
        marker = tmp_path / f"{module_name}.imports.log"
        source = tmp_path / f"{module_name}.py"
        source.write_text(
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).open('a').write('imported\\n')\n"
            "from functualize.workflow import END, Edge, Gate, Step, workflow\n"
            "from pydantic import BaseModel\n"
            "class Prefs(BaseModel):\n"
            "    budget: str = 'mid'\n"
            "@workflow(\n"
            "    steps=[Step('forecast'), Gate(name='prefs', awaits=Prefs)],\n"
            "    edges=[Edge(source='forecast', target='prefs'),\n"
            "           Edge(source='prefs', target=END)],\n"
            ")\n"
            "def trip(): ...\n"
        )

        sys.path.insert(0, str(tmp_path))
        try:
            module = __import__(module_name)
            cached = JobDescriptor(
                name="trip",
                group=None,
                module_path=module_name,
                source_file=str(source),
                docstring=None,
                workflow=workflow_shape_of(module.trip),
            ).to_dict()
            assert marker.read_text().count("imported") == 1

            # Simulate a fresh process reading the cache.
            del sys.modules[module_name]
            restored = JobDescriptor.from_dict(json.loads(json.dumps(cached)))

            assert restored.workflow is not None
            assert restored.workflow.step_names() == ("forecast",)
            assert restored.workflow.gate_names() == ("prefs",)
            assert restored.workflow.entry == "forecast"
            # Still exactly one import — the read did not re-import.
            assert marker.read_text().count("imported") == 1
            assert module_name not in sys.modules
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop(module_name, None)
