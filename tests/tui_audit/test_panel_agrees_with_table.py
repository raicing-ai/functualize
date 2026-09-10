"""The panel and the exit code answer from the same table — for every status.

`tasks.md` named this file as a T7 deliverable and it was never written. The
task's own declared sabotage — *"change the panel's family from `PANEL` to
`PROCESS`; the parity test must fail"* — therefore could not fail, and
`contributor/adr/020-engine-entrypoint-encapsulation.md` names it as **the**
mechanism that makes regrowth visible: *"divergence in those classes requires
adding a new authority, which the absence-tests (…, panel≡table parity) … make
visible as a failing test rather than a convention drift."* The mechanism the
ADR promised for regrowth resistance was the one thing not built.

Nothing in the repo ran a BLOCKED run through the TUI at all, which is the
status the whole D3 decision is about: the panel calls a paused run **done**
(it did what it was asked and is still addressable right there), while the
process exits **5** (a script resuming in a loop has to know it has not
finished). Two answers, deliberately, from one module — and until now, from one
module and no test.

**Why this is a `tui_audit` test.** The panel is real: a real
`FunctualizeInlineTUI`, a real `RichLog`, the real `execute_job_sync` branch.
Only the *status* is supplied, because there is no job that can be made to
return `TIMEOUT` or `CANCELLED` on demand — and the status is the input to the
decision under test, not part of it.

The expectations are derived from `functualize.types` rather than written down
here. A second hand-written list is exactly what this feature deleted; a test
carrying one would put it straight back, in the file meant to prevent it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.widgets import RichLog

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize.app.core import FunctualizeApp
from functualize.types import (
    Family,
    JobResult,
    RunStatus,
    exit_code_for_status,
    is_failure,
)

#: Every status a finished run can carry at a boundary. `RUNNING` is transient
#: and never observed at one, so asking about it is a caller bug rather than a
#: case (`_types/outcome.py` says so, and answers `True` for it).
_TERMINAL = [s for s in RunStatus if s is not RunStatus.RUNNING]


@pytest.fixture()
def tui_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name="panelparity")

    def anything() -> str:
        return "ran"

    func_app.register_dynamic_job("anything", anything)
    return FunctualizeInlineTUI(func_app)


def _panel_text(app: FunctualizeInlineTUI) -> str:
    log = app.query_one("#output-log", RichLog)
    return "\n".join(str(getattr(line, "text", line)) for line in log.lines)


async def _run_with_status(
    tui_app: FunctualizeInlineTUI,
    monkeypatch: pytest.MonkeyPatch,
    status: RunStatus,
) -> tuple[str, int]:
    """Drive the real panel for a run that ended with ``status``.

    Through `action_execute` and the thread worker, not by calling
    `execute_job_sync` inline: the panel's writes are marshalled from the worker
    thread, so an inline call renders nothing and every assertion here would
    pass or fail for the wrong reason.

    The code comes back off `app.return_code`, which is the wiring
    `run-outcome-authority` B1 was about — `run_worker` discards its callable's
    return value, so the number `execute_job_sync` computes only reaches the
    process if something assigns it.
    """

    def _fake_execute(request: Any) -> JobResult:
        return JobResult(
            job_name="anything", status=status, return_value=None, duration_ms=0.0
        )

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(tui_app._func_app, "execute", _fake_execute)
        tui_app._smart_bar.value = "anything"
        await pilot.pause()
        tui_app.action_execute()
        await pilot.pause()
        await tui_app.workers.wait_for_complete()
        await pilot.pause()
        return _panel_text(tui_app), tui_app.return_code


@pytest.mark.parametrize("status", _TERMINAL, ids=[s.value for s in _TERMINAL])
async def test_the_panel_verdict_matches_the_panel_family(
    tui_app, monkeypatch, status: RunStatus
) -> None:
    panel, _ = await _run_with_status(tui_app, monkeypatch, status)

    if is_failure(status, family=Family.PANEL):
        assert "✗ Failed" in panel, f"{status.value} should read as failed:\n{panel}"
    else:
        assert "✓ Done" in panel, f"{status.value} should read as done:\n{panel}"
        assert "✗ Failed" not in panel


@pytest.mark.parametrize("status", _TERMINAL, ids=[s.value for s in _TERMINAL])
async def test_the_return_code_matches_the_process_family(
    tui_app, monkeypatch, status: RunStatus
) -> None:
    _, code = await _run_with_status(tui_app, monkeypatch, status)

    expected = (
        int(exit_code_for_status(status))
        if is_failure(status, family=Family.PROCESS)
        else 0
    )
    assert code == expected, f"{status.value}: expected exit {expected}, got {code}"


async def test_blocked_is_the_case_the_two_families_disagree_about(
    tui_app, monkeypatch
) -> None:
    """Stated on its own, because it is the whole reason `Family` exists.

    If the two families ever agree about every status, `Family` has become an
    elaborate way of writing one list and the parametrized tests above pass
    vacuously — they would be asserting the same thing twice.
    """
    panel, code = await _run_with_status(tui_app, monkeypatch, RunStatus.BLOCKED)

    assert "✓ Done" in panel, f"a paused run is not a failure in the panel:\n{panel}"
    assert code == 5, "a paused run has not finished, and a shell needs to know"


def test_the_two_families_actually_differ_somewhere() -> None:
    """The falsifier for the test above, without touching the TUI."""
    differing = {
        s
        for s in _TERMINAL
        if is_failure(s, family=Family.PANEL) != is_failure(s, family=Family.PROCESS)
    }
    assert differing, (
        "PANEL and PROCESS agree about every status, which makes every parity "
        "assertion in this file vacuous"
    )
