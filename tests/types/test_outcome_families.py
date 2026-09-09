"""The difference that lived in a comment becomes an assertion.

Nine sites translated a `RunStatus` into something a caller could act on, and
two of them disagreed — MCP's `wire_status` docstring says "Three doors
disagreed" in as many words. The families exist because the disagreement was
partly *legitimate*: a gate pause really is a failure to a shell and really is
not one to a live panel. What was illegitimate was that each site decided
alone.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from functualize.types import (
    Family,
    RunStatus,
    exit_code_for_status,
    http_status_for_status,
    is_failure,
    report_line,
    status_from_wire,
    wire_value,
)


class TestTheFamiliesDisagreeOnPurpose:
    def test_blocked_is_a_failure_to_a_process(self) -> None:
        """Exit 5 — "paused, not done". A resuming script must be able to tell."""
        assert is_failure(RunStatus.BLOCKED, family=Family.PROCESS) is True

    def test_blocked_is_not_a_failure_to_a_panel(self) -> None:
        """D-7: the TUI painting a pause red is how BLOCKED came to read as success."""
        assert is_failure(RunStatus.BLOCKED, family=Family.PANEL) is False

    def test_blocked_is_not_a_failure_on_the_wire(self) -> None:
        """202 Accepted is not an error class."""
        assert is_failure(RunStatus.BLOCKED, family=Family.WIRE) is False
        assert http_status_for_status(RunStatus.BLOCKED) == 202

    @pytest.mark.parametrize("family", list(Family))
    def test_success_and_skipped_never_fail_anywhere(self, family: Family) -> None:
        assert not is_failure(RunStatus.SUCCESS, family=family)
        assert not is_failure(RunStatus.SKIPPED, family=family)

    @pytest.mark.parametrize("family", list(Family))
    @pytest.mark.parametrize(
        "status",
        [RunStatus.FAILURE, RunStatus.TIMEOUT, RunStatus.CANCELLED, RunStatus.UNKNOWN],
    )
    def test_real_failures_fail_everywhere(
        self, status: RunStatus, family: Family
    ) -> None:
        assert is_failure(status, family=family)

    def test_refused_is_a_failure_in_every_family(self) -> None:
        """A refusal that reads as success is the false clean."""
        for family in Family:
            assert is_failure(RunStatus.REFUSED, family=family)

    @pytest.mark.parametrize("family", list(Family))
    def test_every_status_has_an_answer(self, family: Family) -> None:
        """No status may fall off the table into a KeyError."""
        for status in RunStatus:
            assert isinstance(is_failure(status, family=family), bool)


class TestTheTwoTablesStayAligned:
    """`http_status.py` says a divergence from `exit_codes.py` is a defect.

    Until now that was a comment. This is the test it asked for.
    """

    def test_process_and_wire_agree_on_what_succeeded(self) -> None:
        for status in RunStatus:
            if status is RunStatus.RUNNING:
                continue
            process_ok = exit_code_for_status(status) == 0
            wire_ok = http_status_for_status(status) < 400
            # BLOCKED is the one deliberate exception: exit 5, HTTP 202.
            if status is RunStatus.BLOCKED:
                assert not process_ok and wire_ok
                continue
            assert process_ok == wire_ok, f"{status} disagrees across boundaries"


class TestTheStringsRoundTrip:
    @pytest.mark.parametrize("status", list(RunStatus))
    def test_wire_value_round_trips(self, status: RunStatus) -> None:
        assert status_from_wire(wire_value(status)) is status

    def test_unknown_string_returns_none_rather_than_guessing(self) -> None:
        """`_resume_exit` mapped anything unrecognised to 1, or to 0 for two
        strings that name no status at all. `None` hands the fact back."""
        assert status_from_wire("answered") is None
        assert status_from_wire("drafted") is None
        assert status_from_wire("") is None

    def test_lookup_is_forgiving_about_case_and_space(self) -> None:
        assert status_from_wire("  SUCCESS ") is RunStatus.SUCCESS


class TestReportLine:
    def test_only_blocked_and_refused_owe_a_line(self) -> None:
        owing = {s for s in RunStatus if report_line(s) is not None}
        assert owing == {RunStatus.BLOCKED, RunStatus.REFUSED}

    def test_the_lines_say_what_happened(self) -> None:
        assert "resumable" in (report_line(RunStatus.BLOCKED) or "")
        assert "precondition" in (report_line(RunStatus.REFUSED) or "")


def test_module_imports_no_upper_layer() -> None:
    """Stdlib and `_types` only — every surface must be able to import it."""
    tree = ast.parse(
        pathlib.Path("src/functualize/_types/outcome.py").read_text()
    )
    bad = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith(
            ("functualize.app", "functualize._app", "functualize._engine", "functualize._cli")
        )
    ]
    assert not bad, bad
