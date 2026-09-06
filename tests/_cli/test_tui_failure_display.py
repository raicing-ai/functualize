"""The TUI panel must reflect a run's real status, not just whether it raised.

`FunctualizeApp.execute()` reports a failed run — missing required config, a
raised job body — by **returning** a `JobResult` with `status=FAILURE`, never by
raising (an S5 invariant the CLI relies on). The TUI's execution body used to
wrap only the *call* in `try/except` and print "✓ Done" on any non-exception
return, so a failed run showed as done in the panel while `func builtin history`
(which reads the same status) correctly showed it as a failure — a confusing
split a user actually hit.

These drive the real `run_job` path through a real `FunctualizeInlineTUI` and
read the output panel, per the TUI audit rules (no mocked surface).

**The failing job changed 2026-09-06, and why matters.** These tests used to
reach FAILURE through a *missing required config value*: a dynamically
registered job whose config class has a required field, executed with nothing
filled in. That worked only because `register_dynamic_job` built its descriptor
with `parameters=[]` and no `config_fields` — so the SmartBar could not see the
required field, reported READY, and executed a run that was bound to fail
validation. The same job discovered from a file reported PENDING and opened the
pre-flight panel instead.

Closing that defect (`discovery-and-gate-defects` B3) makes the two paths
agree, and the dynamic job now correctly goes PENDING too — so that route to a
FAILURE result is no longer reachable through the bar, by design. The assertion
these tests exist for is unchanged; only the way the run is made to fail is. A
job body that raises is now the vehicle, and `test_a_config_job_now_blocks_at_the_bar`
below pins the behaviour that replaced the old one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, Field
from textual.widgets import RichLog

from functualize._cli.tui.app import FunctualizeInlineTUI
from functualize.app.core import FunctualizeApp


class NeedsCity(BaseModel):
    city: str = Field(description="required, no default")


@pytest.fixture()
def tui_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FunctualizeInlineTUI:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)

    func_app = FunctualizeApp(name="faildisplay")

    def ok() -> str:
        return "fine"

    # A job body that raises → execute() returns FAILURE without raising.
    def boom() -> str:
        raise RuntimeError("job body exploded")

    # Kept so the *other* half of the story stays covered: the bar must refuse
    # to run this rather than execute it into a validation error.
    def needs_config(config: NeedsCity) -> str:
        return config.city

    func_app.register_dynamic_job("ok", ok)
    func_app.register_dynamic_job("boom", boom)
    func_app.register_dynamic_job("needsconfig", needs_config, config_class=NeedsCity)
    return FunctualizeInlineTUI(func_app)


def _panel_text(app: FunctualizeInlineTUI) -> str:
    log = app.query_one("#output-log", RichLog)
    return "\n".join(str(getattr(line, "text", line)) for line in log.lines)


async def test_a_failed_run_shows_failed_not_done(tui_app) -> None:
    """The regression: a run execute() reports as FAILURE must not read as
    "Done" in the panel."""
    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "boom"
        await pilot.pause()
        tui_app.action_execute()
        await pilot.pause()
        await tui_app.workers.wait_for_complete()
        await pilot.pause()

        panel = _panel_text(tui_app)

    assert "Done" not in panel, f"a failed run printed Done:\n{panel}"
    assert "Failed" in panel or "Error" in panel


async def test_a_failed_run_records_failure_not_success(tui_app) -> None:
    """The panel and the snapshot/history must agree — the whole point."""
    from unittest.mock import MagicMock

    tui_app._snapshot_store.record = MagicMock(  # type: ignore[method-assign]
        wraps=tui_app._snapshot_store.record
    )

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "boom"
        await pilot.pause()
        tui_app.action_execute()
        await pilot.pause()
        await tui_app.workers.wait_for_complete()
        await pilot.pause()

    # record(job_name, values, outcome) — the outcome must be "failure".
    assert tui_app._snapshot_store.record.call_count == 1
    outcome = tui_app._snapshot_store.record.call_args.args[2]
    assert outcome == "failure"


async def test_a_config_job_now_blocks_at_the_bar(tui_app) -> None:
    """The behaviour that replaced the old route to FAILURE.

    A dynamically registered job with a required config field now reports
    PENDING and never executes, exactly as the same job discovered from a file
    always did. Before `register_dynamic_job` extracted `parameters` and
    `config_fields`, the bar could not see `city`, reported READY, and ran a
    job guaranteed to fail validation.
    """
    from functualize._cli.tui.bar import BarReadiness

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "needsconfig"
        await pilot.pause()

        assert tui_app._smart_bar.readiness == BarReadiness.PENDING

        tui_app.action_execute()
        await pilot.pause()
        await tui_app.workers.wait_for_complete()
        await pilot.pause()

        assert _panel_text(tui_app) == "", "a PENDING bar must not run the job"


async def test_a_successful_run_still_shows_done(tui_app) -> None:
    """The fix must not turn every run into a failure — a real success still
    reads as Done and records success."""
    from unittest.mock import MagicMock

    tui_app._snapshot_store.record = MagicMock(  # type: ignore[method-assign]
        wraps=tui_app._snapshot_store.record
    )

    async with tui_app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        tui_app._smart_bar.value = "ok"
        await pilot.pause()
        tui_app.action_execute()
        await pilot.pause()
        await tui_app.workers.wait_for_complete()
        await pilot.pause()

        panel = _panel_text(tui_app)

    assert "Done" in panel
    assert tui_app._snapshot_store.record.call_args.args[2] == "success"
