"""The wire body is an envelope: job arguments nested, control inputs beside.

Spec AC-5, AC-6, AC-9. The flat body this replaces is what let a caller's key
bind to a control parameter — send `{"scope_id": "x"}` and you were choosing the
workflow scope the run joined, not passing an argument (risk R-a).

**Breaking, deliberately.** Job parameters used to be the whole body (HTTP) or
the `kwargs` key (Lambda); they are now under `arguments`.
"""

from __future__ import annotations

from typing import Any

import pytest
from functualize_http import _envelope

_SURFACE = "http"


class TestJobArgumentsAreNested:
    def test_arguments_reach_the_job_as_kwargs(self) -> None:
        request = _envelope({"arguments": {"target": "prod"}}, "deploy")

        assert request.kwargs == {"target": "prod"}
        assert request.job_name == "deploy"
        assert request.surface == _SURFACE

    def test_an_empty_body_is_an_empty_call(self) -> None:
        request = _envelope({}, "deploy")

        assert request.kwargs == {}
        assert request.group_option_values is None
        assert request.workflow_scope_id is None
        assert request.force is False


class TestAControlInputCannotArriveAsAnArgument:
    """AC-9 — the whole reason for the nesting."""

    def test_a_job_parameter_named_scope_id_stays_an_argument(self) -> None:
        request = _envelope(
            {"arguments": {"scope_id": "a-job-argument"}, "scope_id": "the-real-scope"},
            "deploy",
        )

        assert request.kwargs == {"scope_id": "a-job-argument"}
        assert request.workflow_scope_id == "the-real-scope"

    def test_a_bare_scope_id_at_the_top_addresses_a_scope_not_the_job(self) -> None:
        """The old flat shape read this as a job argument; now it is a control input.

        Both readings are defensible in isolation. What is not defensible is a
        body where the *caller* decides which one it gets by choosing a key
        name — that is the accidental channel this envelope removes.
        """
        request = _envelope({"scope_id": "run-42"}, "deploy")

        assert request.workflow_scope_id == "run-42"
        assert request.kwargs == {}

    def test_group_options_do_not_leak_into_the_job(self) -> None:
        request = _envelope(
            {"arguments": {"target": "prod"}, "group_option_values": {"env": "stg"}},
            "deploy",
        )

        assert request.kwargs == {"target": "prod"}
        assert request.group_option_values == {"env": "stg"}

    def test_force_is_a_control_input_too(self) -> None:
        request = _envelope({"arguments": {}, "force": True}, "deploy")

        assert request.force is True
        assert request.kwargs == {}


class TestAGatedWorkflowCanBeResumedOverTheWire:
    """AC-6 — the story D-6 recorded as impossible.

    Start a gated workflow, read the scope id back, answer the gate, send the
    same id again. It was impossible not because the engine could not do it but
    because **the wire had no field to put the id in**: the body was the job's
    arguments and nothing else. These assert the field exists and round-trips;
    the engine half is covered by the workflow suites.
    """

    def test_a_scope_id_sent_back_addresses_the_same_scope(self) -> None:
        started = _envelope({"arguments": {"city": "Tokyo"}}, "trip-planner")
        assert started.workflow_scope_id is None, "a first run names no scope"

        resumed = _envelope(
            {"arguments": {"city": "Tokyo"}, "scope_id": "trip-1"}, "trip-planner"
        )

        assert resumed.workflow_scope_id == "trip-1"
        assert resumed.kwargs == started.kwargs, (
            "resuming must not change what the job is asked to do"
        )


class TestAMalformedEnvelopeIsRefused:
    @pytest.mark.parametrize(
        "payload",
        [
            {"arguments": "not-an-object"},
            {"arguments": [1, 2, 3]},
            {"group_option_values": "not-an-object"},
            {"scope_id": 42},
        ],
    )
    def test_it_raises_rather_than_guessing(self, payload: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            _envelope(payload, "deploy")
