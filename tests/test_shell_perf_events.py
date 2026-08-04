"""Tests for Shell perf phases + EventBus lifecycle events (S2/T12a, §B.8).

Each shell call records a ``shell.<label>`` perf phase and emits
``shell.command.start`` / ``shell.command.end`` (masked command; output chunks
never on the bus). ``label`` names both.
"""

from __future__ import annotations

import pytest

from functualize._engine.capabilities.shell import WiredShell, _derive_label
from functualize._events.bus import EventBus, StructuredEvent
from functualize._events.perf import PerfTimeline
from functualize._types.redaction import MASK, Secret


class TestDeriveLabel:
    def test_first_token_pathstripped(self) -> None:
        assert _derive_label("/usr/bin/git status") == "git"

    def test_plain_program(self) -> None:
        assert _derive_label("echo hi") == "echo"

    def test_empty_falls_back(self) -> None:
        assert _derive_label("") == "command"


class TestPerfPhases:
    def test_labelled_phase_recorded(self) -> None:
        perf = PerfTimeline()
        sh = WiredShell(perf=perf)
        sh(["true"], label="build")
        report = perf.report()
        assert report.phase("shell.build") is not None

    def test_default_label_derived_from_command(self) -> None:
        perf = PerfTimeline()
        sh = WiredShell(perf=perf)
        sh(["echo", "hi"])
        assert perf.report().phase("shell.echo") is not None

    def test_phase_recorded_even_on_failure(self) -> None:
        perf = PerfTimeline()
        sh = WiredShell(perf=perf)
        sh(["false"], check=False, label="boom")
        assert perf.report().phase("shell.boom") is not None

    def test_no_perf_still_runs(self) -> None:
        # WiredShell() with no perf/bus is the default; must not error.
        assert WiredShell()(["true"]).ok


class TestEventBusLifecycle:
    def _bus_capture(self) -> tuple[EventBus, list[StructuredEvent]]:
        bus = EventBus()
        events: list[StructuredEvent] = []
        bus.subscribe("shell.*", events.append)
        return bus, events

    def test_start_and_end_emitted(self) -> None:
        bus, events = self._bus_capture()
        WiredShell(event_bus=bus)(["true"], label="ok")
        names = [e.event_name for e in events]
        assert names == ["shell.command.start", "shell.command.end"]
        assert events[0].resource == "ok"

    def test_end_carries_returncode_and_status(self) -> None:
        bus, events = self._bus_capture()
        WiredShell(event_bus=bus)(["false"], check=False, label="boom")
        end = events[-1]
        assert end.event_name == "shell.command.end"
        assert end.payload["returncode"] != 0
        assert end.payload["status"] == "failure"
        assert "duration_ms" in end.payload

    def test_end_emitted_even_when_check_raises(self) -> None:
        from functualize.job import ShellError

        bus, events = self._bus_capture()
        with pytest.raises(ShellError):
            WiredShell(event_bus=bus)(["false"], label="boom")
        # The end event still fired before the raise.
        assert events[-1].event_name == "shell.command.end"
        assert events[-1].payload["status"] == "failure"

    def test_command_in_payload_is_masked(self) -> None:
        bus, events = self._bus_capture()
        WiredShell(event_bus=bus)("echo {t}", t=Secret("leaky"))
        for e in events:
            assert "leaky" not in e.payload["command"]
        assert MASK in events[0].payload["command"]

    def test_no_bus_still_runs(self) -> None:
        assert WiredShell()(["true"]).ok
