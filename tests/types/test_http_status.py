"""The RunStatus → HTTP mapping is total, and agrees with the exit-code table.

The guard that matters here is coverage: this table exists because three
delivery surfaces were each answering "what does this status mean" on their
own. A tenth `RunStatus` member added without a decision would quietly become
a 500, which is how the drift starts again.
"""

from __future__ import annotations

import pytest

from functualize._types.enums import RunStatus
from functualize._types.exit_codes import ExitCode, exit_code_for_status
from functualize._types.http_status import _STATUS_HTTP_CODES, http_status_for_status

# RUNNING is deliberately unmapped: a synchronous request cannot return while
# its job is still running. Every other member must be an explicit decision.
_TRANSIENT = {RunStatus.RUNNING}
_TERMINAL = set(RunStatus) - _TRANSIENT


class TestCoverage:
    def test_every_terminal_status_is_mapped_explicitly(self) -> None:
        """A new RunStatus member must be decided, not defaulted.

        Asserting set equality rather than a subset is the whole point: it
        fails when a member is *added* as well as when one is removed.
        """
        assert set(_STATUS_HTTP_CODES) == _TERMINAL

    @pytest.mark.parametrize("status", list(RunStatus))
    def test_every_status_resolves_to_a_valid_code(self, status: RunStatus) -> None:
        code = http_status_for_status(status)
        assert 200 <= code <= 599

    def test_running_falls_back_rather_than_raising(self) -> None:
        """Unmapped is a caller bug, not a crash — same rule as exit codes."""
        assert http_status_for_status(RunStatus.RUNNING) == 500


class TestTheDecisions:
    """Each of these is a documented choice, not an incidental value."""

    def test_success_is_200(self) -> None:
        assert http_status_for_status(RunStatus.SUCCESS) == 200

    def test_skipped_is_a_success_at_the_boundary(self) -> None:
        """'Already up to date' must not read as an error to a caller."""
        assert http_status_for_status(RunStatus.SKIPPED) == 200

    def test_blocked_is_202_not_200(self) -> None:
        """The regression this table was written for.

        A workflow paused at a gate previously reached a Lambda caller as
        `{"statusCode": 200, "body": null}` — indistinguishable from success.
        """
        assert http_status_for_status(RunStatus.BLOCKED) == 202

    def test_refused_is_distinct_from_failure(self) -> None:
        """'I refused' is not 'I ran and threw' — the exit table's D-a rule."""
        refused = http_status_for_status(RunStatus.REFUSED)
        assert refused == 412
        assert refused != http_status_for_status(RunStatus.FAILURE)

    def test_timeout_is_distinguishable_from_a_plain_failure(self) -> None:
        """A timeout is the one failure a caller can sensibly retry."""
        assert http_status_for_status(RunStatus.TIMEOUT) == 504
        assert http_status_for_status(RunStatus.FAILURE) == 500


class TestAgreementWithExitCodes:
    """The two boundaries answer the same question and must not disagree."""

    @pytest.mark.parametrize("status", sorted(_TERMINAL, key=lambda s: s.name))
    def test_ok_exit_iff_2xx(self, status: RunStatus) -> None:
        """Exit code 0 and a 2xx response must classify identically.

        BLOCKED is the deliberate exception: it exits 5 (so a shell pipeline
        stops) while returning 202 (so an HTTP caller knows to resume). That
        divergence is intentional and pinned here so it cannot drift silently.
        """
        if status is RunStatus.BLOCKED:
            assert exit_code_for_status(status) == ExitCode.BLOCKED
            assert http_status_for_status(status) == 202
            return

        exits_ok = exit_code_for_status(status) == ExitCode.OK
        is_2xx = 200 <= http_status_for_status(status) < 300
        assert exits_ok is is_2xx, status.name
