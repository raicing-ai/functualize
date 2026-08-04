"""`invoke()`'s gate parameters actually do something (S9/T35, cell G×I).

`invoke()` accepts `awaits_input`, `force_gate` and `gate_strategy`, documents
them, and — until this was fixed — ignored all three. Two bugs, the first
masking the second:

1. `WiredInvoke` was constructed without a gate registry, and the dispatch is
   guarded by `self._gate_registry is not None`. So the gate never ran, no
   matter what was passed.
2. Once it did run, `resolve_gate`'s **return value was discarded** — called
   without assignment — and the child job then executed with the original
   kwargs. A gate that successfully collected input threw the answer away.

Both were invisible to the suite: nothing asserted that a gate's answer
reached the job, so an inert gate looked exactly like a working one.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.job import RunContext, job


class Approval(BaseModel):
    ok: bool = True
    note: str = "from-gate"


@pytest.fixture(autouse=True)
def _reset() -> object:
    AppState.reset()
    yield
    AppState.reset()


def _app() -> FunctualizeApp:
    @job
    def helper(ok: bool = False, note: str = "default") -> str:
        return f"ok={ok} note={note}"

    @job
    def caller(rc: RunContext) -> str:
        return str(
            rc.invoke("helper", awaits_input=Approval, force_gate=True).return_value
        )

    @job
    def caller_explicit(rc: RunContext) -> str:
        return str(
            rc.invoke(
                "helper", awaits_input=Approval, force_gate=True, ok=False
            ).return_value
        )

    @job
    def caller_no_gate(rc: RunContext) -> str:
        return str(rc.invoke("helper").return_value)

    app = FunctualizeApp(name="gate-wiring")
    for name, fn in [
        ("helper", helper),
        ("caller", caller),
        ("caller_explicit", caller_explicit),
        ("caller_no_gate", caller_no_gate),
    ]:
        app.register_dynamic_job(name, fn)
    return app


class TestTheGateIsWired:
    def test_the_registry_reaches_the_invoke_capability(self) -> None:
        """The guard that made every gate parameter inert."""
        app = _app()
        rc = app.execution_engine  # engine owns the registry
        assert getattr(rc, "_gate_registry", None) is not None

    def test_a_resolved_gate_value_reaches_the_job(self) -> None:
        """The discarded-return-value bug: the job used to see its defaults."""
        assert _app().execute("caller").return_value == "ok=True note=from-gate"

    def test_an_explicitly_passed_argument_still_wins(self) -> None:
        """A caller naming a value is not overridden by a gate filling the
        same field — only the fields it did not name are filled."""
        result = _app().execute("caller-explicit").return_value
        assert result == "ok=False note=from-gate"

    def test_invoking_without_a_gate_is_unaffected(self) -> None:
        """The common path pays nothing: no gate parameters, no gate."""
        assert _app().execute("caller-no-gate").return_value == "ok=False note=default"
