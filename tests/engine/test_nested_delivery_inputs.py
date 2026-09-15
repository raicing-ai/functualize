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

import pytest

from functualize._types.run_request import RunRequest, nested_request


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


class TestNoParent:
    def test_a_run_with_no_parent_takes_the_defaults(self) -> None:
        """`None` only for a context built outside `run()` — defaults are right."""
        child = nested_request(None, job_name="child", surface="invoke")

        assert child.prompt_gates is False
        assert child.output_format == "auto"
        assert child.force is False
