"""One real decision against the live Jev endpoint.

Skipped, at module level, unless ``OPENCODE_API_KEY`` is set: it is the only
test in the suite that makes a network request, and a run without the
credential has nothing to measure. A ``429`` also skips, naming the wait the
service asked for, as the capability probe does — the free tier's burst budget
is a fact about the account, not a defect in the adapter.

The request is the capability matrix's row C stable decision. Its three values
are copied from ``tests/jev_probe/contract.py`` (``QUIET_STATE``, ``OWNER``,
``INTENT``) rather than imported, because that package skips at module level
too. The test asserts the answer's *shape* and never which option wins: the
matrix measured the winner as a distribution, not a constant (row C2).
"""

from __future__ import annotations

import os

import pytest

if not os.environ.get("OPENCODE_API_KEY"):
    pytest.skip(
        "OPENCODE_API_KEY is not set: the live Jev decision needs a credential",
        allow_module_level=True,
    )

from functualize_decision_jev._provider import JevDecisionProvider

from functualize.plugin import (
    ChoiceRequest,
    DecisionFailure,
    DecisionUnavailableError,
)

#: `tests/jev_probe/contract.py` `QUIET_STATE` — row C's stable state.
QUIET_STATE = (
    "Ticket: my parcel was delivered to the wrong address and I want a refund."
)
#: `tests/jev_probe/contract.py` `OWNER`.
OWNER = "Which team owns this ticket?"
#: `tests/jev_probe/contract.py` `INTENT`.
INTENT = {
    "shipping": "the parcel's journey",
    "billing": "money",
    "returns": "the customer wants a refund",
}


def test_one_live_choice() -> None:
    request = ChoiceRequest(state=QUIET_STATE, instructions=OWNER, options=INTENT)

    try:
        result = JevDecisionProvider().choose(request)
    except DecisionUnavailableError as error:
        if error.kind is DecisionFailure.RATE_LIMITED:
            pytest.skip(
                f"NOT MEASURED (rate limited): Retry-After {error.retry_after} s — {error}"
            )
        raise

    assert result.provider == "jev"
    assert result.value in INTENT
    assert result.distribution is not None
    assert set(result.distribution) == set(INTENT)
