"""Delivery inputs travel to nested runs (found by review, not by the suite).

`--emit-format`, `--prompt-gates` and `--force` describe how *this invocation of the
program* behaves, not how one job behaves. So a workflow step, a dependency and
an `rc.invoke` child must answer them the way the run the user started does.

**This regressed and no test noticed.** Before `run-request-entry` these lived on
the app as process-globals (`app._output_format` and friends), so nesting
inherited them by accident of storage. Making them per-request made the
inheritance something the code has to *say* — and for a while it did not:

    $ func --emit-format none outer      # outer invokes child
    {"from":"child"}                # the flag stopped at the first hop

Every one of the four nesting sites built its `RunRequest` from scratch, so all
three fields took their defaults. An adversarial review found it by reading the
constructors; the suite could not, because nothing asserted across a hop.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from functualize._types.run_request import (
    EmissionRecord,
    RunRequest,
    nested_request,
    request_from_envelope,
)


def _parent(**kw: object) -> RunRequest:
    base = {
        "job_name": "outer",
        "surface": "func.job",
        "kwargs": {"a": 1},
        "prompt_gates": True,
        "output_format": "none",
        "force": True,
        "workflow_scope_id": "scope-1",
        "group_option_values": {"env": "prod"},
    }
    base.update(kw)
    return RunRequest(**base)  # type: ignore[arg-type]


class TestTheDeliveryInputsTravelDown:
    @pytest.mark.parametrize(
        "surface", ["engine.step", "engine.dependency", "invoke", "invoke.parallel"]
    )
    def test_every_nesting_site_inherits_all_three(self, surface: str) -> None:
        child = nested_request(_parent(), job_name="child", surface=surface)

        assert child.prompt_gates is True
        assert child.output_format == "none"
        assert child.force is True
        assert child.surface == surface


class TestEverythingElseResets:
    """A child's arguments, scope and dependency policy are its own."""

    def test_the_parents_arguments_do_not_leak(self) -> None:
        child = nested_request(_parent(), job_name="child", surface="invoke")

        assert child.kwargs == {}

    def test_scope_and_group_options_reset(self) -> None:
        child = nested_request(_parent(), job_name="child", surface="invoke")

        assert child.workflow_scope_id is None
        assert child.parent_scope is None
        assert child.group_option_values is None

    def test_a_site_that_states_a_field_overrides_the_reset(self) -> None:
        """A workflow step *does* join the parent's scope, and says so."""
        child = nested_request(
            _parent(),
            job_name="step",
            surface="engine.step",
            workflow_scope_id="scope-1",
            run_dependencies=False,
        )

        assert child.workflow_scope_id == "scope-1"
        assert child.run_dependencies is False
        assert child.output_format == "none", "stating one field must not drop the rest"

    def test_capture_resets(self) -> None:
        """Capture belongs to the invocation that asked for it (B7)."""
        parent = _parent(capture=EmissionRecord(emitted=["one"], writes=["x"]))
        child = nested_request(parent, job_name="child", surface="invoke")

        assert child.capture is None

    def test_a_site_that_states_capture_keeps_it(self) -> None:
        """The invoke wiring hands the child its own record, and says so."""
        record = EmissionRecord()
        child = nested_request(
            _parent(),
            job_name="child",
            surface="invoke",
            capture=record,
        )

        assert child.capture is record
        assert child.output_format == "none", "stating one field must not drop the rest"


class TestCaptureStaysOutOfIdentity:
    """A live collector on a value object is not part of its identity (S1)."""

    def test_differing_only_in_capture_compare_equal_and_hash_equal(self) -> None:
        left = _parent(capture=EmissionRecord(emitted=["one"]))
        right = _parent(capture=EmissionRecord())

        assert left == right
        assert hash(left) == hash(right)


class TestNoParent:
    def test_a_run_with_no_parent_takes_the_defaults(self) -> None:
        """`None` only for a context built outside `run()` — defaults are right."""
        child = nested_request(None, job_name="child", surface="invoke")

        assert child.prompt_gates is False
        assert child.output_format == "auto"
        assert child.force is False


class TestRunTagsTravelDown:
    @pytest.mark.parametrize(
        ("kind", "surface"),
        [
            ("workflow step", "engine.step"),
            ("nested workflow", "engine.step"),
            ("Invoke", "invoke"),
            ("rc.invoke_parallel", "invoke.parallel"),
            ("dependency", "engine.dependency"),
        ],
    )
    def test_each_child_kind_keeps_the_frozen_map(
        self, kind: str, surface: str
    ) -> None:
        tags = MappingProxyType({"harness": "claude"})
        parent = _parent(run_tags=tags)
        child = nested_request(parent, job_name=kind, surface=surface)

        assert child.run_tags == {"harness": "claude"}
        assert child.run_tags is tags
        assert parent.run_tags == child.run_tags
        with pytest.raises(TypeError):
            child.run_tags["harness"] = "other"  # type: ignore[index]
        with pytest.raises(TypeError):
            child.run_tags["new"] = "value"  # type: ignore[index]

    def test_caller_stated_override_replaces_the_whole_map(self) -> None:
        parent = _parent(run_tags=MappingProxyType({"harness": "claude"}))
        replacement = MappingProxyType({"session": "other"})
        child = nested_request(
            parent, job_name="child", surface="invoke", run_tags=replacement
        )
        assert child.run_tags is replacement
        assert parent.run_tags == {"harness": "claude"}

    def test_unstated_child_tags_are_neither_added_changed_nor_removed(self) -> None:
        tags = MappingProxyType({"a": "1", "b": "2"})
        parent = _parent(run_tags=tags)
        child = nested_request(parent, job_name="child", surface="invoke")
        grandchild = nested_request(child, job_name="grandchild", surface="invoke")
        assert child.run_tags == grandchild.run_tags == parent.run_tags

    def test_wire_payload_cannot_supply_tags(self) -> None:
        request = request_from_envelope(
            {"arguments": {}, "run_tags": {"harness": "other"}},
            job_name="job",
            surface="http",
        )
        assert request.run_tags == {}
        with pytest.raises(TypeError):
            request.run_tags["new"] = "value"  # type: ignore[index]

    def test_tags_do_not_change_request_hash(self) -> None:
        first = _parent(run_tags=MappingProxyType({"harness": "claude"}))
        second = _parent(run_tags=MappingProxyType({"harness": "other"}))
        assert first != second
        assert hash(first) == hash(second)
