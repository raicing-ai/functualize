"""An unresolvable gate blocks — including one naming a strategy nobody
registered.

The walker's contract is that any gate it cannot resolve blocks and stays
resumable. That held for `strategy=None`, for `"ai_outbound"`, and for a
registered resolver that raises. It did **not** hold when the strategy *name*
itself was unregistered: `GateRegistry.resolve_gate` raised a plain
`ValueError` from outside its per-strategy `try`, and the walker catches only
`GateResolutionError`.

The practical asymmetry: a broken API key degraded gracefully, and a forgotten
`pip install functualize-ai` raised out of `app.execute()`.

The regression that made this dangerous to fix in isolation is closed. On the
Lambda surface the old `ValueError` reached the handler's `except` and became
a visible 500; turning it into `BLOCKED` would silently have produced
`{"statusCode": 200, "body": null}`, because the handler never read
`result.status`. `remote-source-activation` tasks 1.3 (the `RunStatus` → HTTP
table) and 4.2 (the plugins consuming it) landed first — `STATUS #21` — so
`BLOCKED` now maps to its own status code rather than falling through as
success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from functualize._types.enums import RunStatus
from functualize.app import FunctualizeApp
from functualize.app.core import request_for
from functualize.workflow import END, Edge, Gate, Step, workflow

if TYPE_CHECKING:
    from functualize._gate._context import GateContext


class Approval(BaseModel):
    approved: bool


class _Boom:
    """A registered resolver that raises — the case that was always correct."""

    def resolve(self, ctx: GateContext) -> BaseModel:
        raise RuntimeError("resolver exploded")


def _app(strategy: str | None, *, register_boom: str | None = None) -> FunctualizeApp:
    app = FunctualizeApp(name="gateapp")

    def prepare() -> str:
        return "ready"

    @workflow(
        steps=[
            Step("prepare"),
            Gate(name="triage", awaits=Approval, strategy=strategy),
        ],
        edges=[
            Edge(source="prepare", target="triage"),
            Edge(source="triage", target=END),
        ],
    )
    def review() -> str:
        return "reviewed"

    app.register_dynamic_job("prepare", prepare)
    app.register_dynamic_job("review", review)
    if register_boom is not None:
        app.register_gate_strategy(register_boom, _Boom())
    return app


class TestAnUnregisteredStrategyBlocks:
    """The defect. Before this, `execute()` raised `ValueError`."""

    def test_it_blocks_instead_of_raising(self) -> None:
        result = _app("ai_inbound").execute(request_for("review"))
        assert result.status is RunStatus.BLOCKED

    def test_the_block_stays_resumable(self) -> None:
        """A block that cannot be resumed is a failure wearing the wrong
        name — the whole reason this is a block and not an error."""
        result = _app("ai_inbound").execute(request_for("review"))
        assert result.status.resumable
        assert result.metadata["blocked_on"] == "triage"

    def test_the_reason_names_the_missing_plugin(self) -> None:
        """`blocked_on: triage` alone reads identically to a gate waiting by
        design. Which package to install is the missing half."""
        result = _app("ai_inbound").execute(request_for("review"))
        reason = result.metadata["blocked_reason"]
        assert "ai_inbound" in reason
        assert "functualize-ai" in reason

    def test_the_body_did_not_run(self) -> None:
        assert _app("ai_inbound").execute(request_for("review")).return_value is None


class TestTheAlreadyCorrectCasesStayCorrect:
    """Regression guard. Three ways to reach BLOCKED that already worked, and
    which a fix in the wrong place would have broken."""

    @pytest.mark.parametrize(
        ("strategy", "boom"),
        [
            pytest.param(None, None, id="no-strategy"),
            pytest.param("ai_outbound", None, id="ai_outbound-always-blocks"),
            pytest.param("ai_inbound", "ai_inbound", id="registered-resolver-raises"),
        ],
    )
    def test_it_blocks(self, strategy: str | None, boom: str | None) -> None:
        result = _app(strategy, register_boom=boom).execute(request_for("review"))
        assert result.status is RunStatus.BLOCKED
        assert result.metadata["blocked_on"] == "triage"


class TestTheReasonIsOnlyThereWhenThereIsOne:
    """`blocked_reason` is additive and optional. An always-present empty key
    would make every consumer guard for it."""

    def test_a_gate_waiting_by_design_carries_no_reason(self) -> None:
        result = _app(None).execute(request_for("review"))
        assert result.status is RunStatus.BLOCKED
        assert "blocked_reason" not in result.metadata

    def test_ai_outbound_carries_no_reason(self) -> None:
        """`ai_outbound` blocks by policy, not by failure — the walker never
        even builds a strategy list for it, so there is nothing to report."""
        result = _app("ai_outbound").execute(request_for("review"))
        assert "blocked_reason" not in result.metadata

    def test_a_registered_resolver_produces_no_install_hint(self) -> None:
        """The strategy exists; it failed. Telling the operator to install
        `functualize-ai` when `ai_inbound` is already registered would send
        them the wrong way entirely.

        The text is the *last* rung's error, not `_Boom`'s: the ladder
        `["ai_inbound", "prompt", "resolve"]` keeps going after `ai_inbound`
        raises, and `GateResolutionError.last_error` means last. Whether first
        would be more diagnostic than last is a pre-existing question about
        that field, not about this task.
        """
        result = _app("ai_inbound", register_boom="ai_inbound").execute(
            request_for("review")
        )
        reason = result.metadata["blocked_reason"]
        assert reason
        assert "functualize-ai" not in reason
        assert "unregistered" not in reason

    def test_blocked_on_is_unaffected_in_every_case(self) -> None:
        """The pre-existing key keeps its meaning, which is what makes
        `blocked_reason` additive rather than a change."""
        for strategy in (None, "ai_inbound", "ai_outbound"):
            result = _app(strategy).execute(request_for("review"))
            assert result.metadata["blocked_on"] == "triage"


class TestTheWalkReportCarriesIt:
    """One level down, so a break between the walker and the executor is
    attributable rather than just visible at the top."""

    def test_the_report_and_the_metadata_agree(self) -> None:
        from functualize._engine.workflow_walker import WalkOutcome, WalkReport

        # The default must be empty, not None: `if run.blocked_reason` is what
        # decides whether the key is published at all.
        assert WalkReport(WalkOutcome.BLOCKED, "s").blocked_reason == ""

        result = _app("ai_inbound").execute(request_for("review"))
        assert result.metadata["blocked_reason"]


class TestTheLambdaSurfaceNoLongerReadsItAsSuccess:
    """STATUS #21, the reason this task was sequenced behind
    `remote-source-activation`. Turning the `ValueError` into a `BLOCKED`
    result would have been a silent regression while the Lambda handler
    ignored `result.status`."""

    def test_blocked_maps_to_a_non_success_http_status(self) -> None:
        from functualize._types.http_status import http_status_for_status

        assert http_status_for_status(RunStatus.BLOCKED) != 200

    def test_the_status_table_covers_the_result_this_task_produces(self) -> None:
        result: Any = _app("ai_inbound").execute(request_for("review"))
        from functualize._types.http_status import http_status_for_status

        assert http_status_for_status(result.status) != 200
