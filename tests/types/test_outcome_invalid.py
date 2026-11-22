"""An invalid call has one consistent outcome across delivery families."""

from __future__ import annotations

from functualize._types.descriptors import JobResult
from functualize._types.enums import RunStatus
from functualize._types.exit_codes import ExitCode, exit_code_for_status
from functualize._types.http_status import http_status_for_status
from functualize._types.outcome import Family, is_failure, status_from_wire, wire_value


def test_invalid_is_terminal_and_not_resumable() -> None:
    assert RunStatus.INVALID.terminal
    assert not RunStatus.INVALID.resumable
    assert not RunStatus.INVALID.ran


def test_invalid_maps_to_usage_and_bad_request() -> None:
    assert exit_code_for_status(RunStatus.INVALID) is ExitCode.USAGE
    assert http_status_for_status(RunStatus.INVALID) == 400
    assert exit_code_for_status(RunStatus.REFUSED) is ExitCode.REFUSED
    assert http_status_for_status(RunStatus.REFUSED) == 412


def test_every_family_treats_invalid_as_a_failure() -> None:
    assert all(is_failure(RunStatus.INVALID, family=family) for family in Family)
    assert status_from_wire(wire_value(RunStatus.INVALID)) is RunStatus.INVALID


def test_lambda_response_uses_the_http_status_table() -> None:
    from functualize_lambda import _response

    result = JobResult(status=RunStatus.INVALID, return_value=None, duration_ms=0.0)
    assert _response(result)["statusCode"] == 400
