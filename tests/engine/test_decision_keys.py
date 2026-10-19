"""The decision-key encoding: what the walker writes, and how it reads back."""

from __future__ import annotations

from functualize._engine.decision_keys import (
    ROUTED_TO_END,
    RecordedRoute,
    failure_key,
    notify_key,
    recorded_route,
)
from functualize._types.workflow import Notify


def test_the_encoders_write_the_recorded_bytes() -> None:
    """Stored keys are byte-identical to what the walker always wrote."""
    assert failure_key("publish") == "publish\x00onfailure"
    assert ROUTED_TO_END == "\x00end"
    declared = Notify(on="completed", to="ops")
    assert notify_key(declared) == f"\x00notify\x00{declared.key}"


def test_a_conditional_choice_is_a_branch() -> None:
    assert recorded_route({"score-submission": "approve"}) == RecordedRoute(
        branches={"score-submission": "approve"}, failure_routes={}
    )


def test_a_failure_key_is_a_failure_route() -> None:
    assert recorded_route({failure_key("publish"): "rollback"}) == RecordedRoute(
        branches={}, failure_routes={"publish": "rollback"}
    )


def test_a_failure_routed_to_end_reads_end() -> None:
    route = recorded_route({failure_key("archive"): ROUTED_TO_END})
    assert route.failure_routes == {"archive": "END"}


def test_a_notification_marker_is_dropped() -> None:
    marker = notify_key(Notify(on="completed", to="ops"))
    assert recorded_route({marker: "sent"}) == RecordedRoute()


def test_an_unknown_nul_key_is_dropped() -> None:
    route = recorded_route(
        {
            "\x00future\x00kind": "x",
            "node\x00somethingelse": "y",
            "\x00onfailure": "z",
            "a\x00b\x00onfailure": "w",
        }
    )
    assert route == RecordedRoute()


def test_recording_order_is_kept_within_each_kind() -> None:
    route = recorded_route(
        {
            "score-submission": "approve",
            failure_key("publish"): "rollback",
            "check": "review",
            failure_key("archive"): ROUTED_TO_END,
        }
    )
    assert list(route.branches.items()) == [
        ("score-submission", "approve"),
        ("check", "review"),
    ]
    assert list(route.failure_routes.items()) == [
        ("publish", "rollback"),
        ("archive", "END"),
    ]
