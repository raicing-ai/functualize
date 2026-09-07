"""The HTTP adapter's status *line* reports the outcome, not only its body.

This surface was half-fixed already: the JSON body carried ``"status":
"failure"`` while the status line said ``200 OK``. Everything that reads only
the line — a load balancer, a retry policy, an uptime probe, ``curl -f`` —
saw success on a failed run. That is the same defect as the Lambda one, one
layer more subtle, and it is why the mapping lives in a shared table rather
than in either plugin.
"""

from __future__ import annotations

import asyncio

import pytest
from functualize_http import HttpServerCore

from functualize.types import RunStatus, http_status_for_status
from tests.conftest import FakeApp, FakeDescriptor, FakeJobResult

TERMINAL = [s for s in RunStatus if s is not RunStatus.RUNNING]


def _execute(status: RunStatus, **kwargs: object) -> tuple[int, dict]:
    app = FakeApp(
        descriptors=[FakeDescriptor(name="greet")],
        execute_results={"greet": FakeJobResult(status=status, **kwargs)},  # type: ignore[arg-type]
    )
    return asyncio.run(
        HttpServerCore(app).handle_request("POST", "/jobs/greet/execute", b"")
    )


class TestTheStatusLine:
    def test_blocked_is_202_not_200(self) -> None:
        assert _execute(RunStatus.BLOCKED)[0] == 202

    def test_a_returned_failure_is_500(self) -> None:
        """`execute()` returned normally — nothing was raised."""
        assert _execute(RunStatus.FAILURE)[0] == 500

    @pytest.mark.parametrize("status", TERMINAL, ids=lambda s: s.name)
    def test_every_terminal_status_matches_the_table(self, status: RunStatus) -> None:
        code, _ = _execute(status)
        assert code == http_status_for_status(status)

    @pytest.mark.parametrize("status", TERMINAL, ids=lambda s: s.name)
    def test_the_line_and_the_body_agree(self, status: RunStatus) -> None:
        """They disagreed for the whole life of this adapter."""
        code, body = _execute(status)
        assert body["status"] == status.value
        assert code == http_status_for_status(status)


class TestTheWire:
    """A code the reason-phrase map does not know goes out as 'Unknown'."""

    @pytest.mark.parametrize("status", TERMINAL, ids=lambda s: s.name)
    def test_every_producible_code_has_a_reason_phrase(self, status: RunStatus) -> None:
        writer = _CapturingWriter()
        asyncio.run(
            HttpServerCore._send_response(
                writer, http_status_for_status(status), {"ok": True}
            )
        )
        status_line = writer.data.split(b"\r\n")[0].decode()
        assert "Unknown" not in status_line, status_line

    def test_the_blocked_status_line_is_well_formed(self) -> None:
        writer = _CapturingWriter()
        asyncio.run(HttpServerCore._send_response(writer, 202, {}))
        assert writer.data.startswith(b"HTTP/1.1 202 Accepted\r\n")


class _CapturingWriter:
    """Enough of `asyncio.StreamWriter` for `_send_response`."""

    def __init__(self) -> None:
        self.data = b""

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        return None


class TestTheBody:
    def test_a_returned_exception_reaches_the_caller(self) -> None:
        _, body = _execute(RunStatus.FAILURE, exception=ValueError("bad region"))
        assert "bad region" in body["error"]

    def test_no_error_key_on_a_clean_run(self) -> None:
        assert "error" not in _execute(RunStatus.SUCCESS)[1]

    def test_the_return_value_is_still_serialized(self) -> None:
        _, body = _execute(RunStatus.SUCCESS, return_value={"n": 1})
        assert body["return_value"] == {"n": 1}


class TestUnchangedPaths:
    def test_a_raised_exception_is_still_500(self) -> None:
        app = FakeApp(
            descriptors=[FakeDescriptor(name="greet")],
            execute_error=RuntimeError("boom"),
        )
        code, body = asyncio.run(
            HttpServerCore(app).handle_request("POST", "/jobs/greet/execute", b"")
        )
        assert code == 500
        assert "boom" in body["error"]

    def test_an_unknown_job_is_still_404(self) -> None:
        code, _ = asyncio.run(
            HttpServerCore(FakeApp()).handle_request("POST", "/jobs/nope/execute", b"")
        )
        assert code == 404

    def test_health_is_still_200(self) -> None:
        code, _ = asyncio.run(
            HttpServerCore(FakeApp()).handle_request("GET", "/health", b"")
        )
        assert code == 200
