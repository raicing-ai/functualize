"""Which sink `RunContext.log()` emits to, and why it must be the job's own Log.

`rc.log()` used to write straight to its stdlib logger, so a job's own `Log`
capability never saw those messages — invisible to `TestRunContext.captured_logs()`
and to anything else wrapping `Log`. The fix routes `rc.log()` through the
per-invocation capability map, which is the *same* map a `log: Log` parameter is
resolved from, so the two cannot drift to different sinks.

The DI registry is deliberately not consulted: `executor._resolve_di_parameters`
treats `Log` as a per-invocation capability and skips the registry for it, so
reading the registry here would make `rc.log()` disagree with the job's own
parameter — see `TestRegistryIsNotConsulted`.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from functualize._app.state import AppState
from functualize._engine.capabilities.log import Log
from functualize._engine.capabilities.runcontext import RunContext
from functualize._primitives.di import DIRegistry
from functualize.app.core import FunctualizeApp
from functualize.job import job
from functualize.testing import CapturingLog


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock()
    config.set_prefix = MagicMock()
    return config


def _rc(config: MagicMock, **kwargs: object) -> RunContext:
    return RunContext(
        name="test-job",
        config=config,
        logger=logging.getLogger("functualize.job.test-job"),
        **kwargs,  # type: ignore[arg-type]
    )


class TestSinkSelection:
    """log() prefers the per-invocation Log and falls back to its own logger."""

    def test_emits_through_the_caps_log(self, mock_config: MagicMock) -> None:
        sink = CapturingLog()
        rc = _rc(mock_config, _caps={Log: sink})

        rc.log("hello")
        rc.log("careful", level="warning")

        assert sink.calls == [("info", "hello"), ("warning", "careful")]

    def test_falls_back_to_the_job_logger_without_caps(
        self, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The production path for a job that never asks for Log."""
        rc = _rc(mock_config)

        with caplog.at_level(logging.DEBUG, logger="functualize.job.test-job"):
            rc.log("no capability here")

        assert [(r.name, r.levelname, r.message) for r in caplog.records] == [
            ("functualize.job.test-job", "INFO", "no capability here")
        ]

    def test_falls_back_when_caps_has_no_log(
        self, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        rc = _rc(mock_config, _caps={})

        with caplog.at_level(logging.DEBUG, logger="functualize.job.test-job"):
            rc.log("still the logger")

        assert [r.message for r in caplog.records] == ["still the logger"]

    def test_reads_the_caps_map_live(self, mock_config: MagicMock) -> None:
        """Binding order must not matter: Log may land in caps after the rc does."""
        caps: dict[type, object] = {}
        rc = _rc(mock_config, _caps=caps)

        sink = CapturingLog()
        caps[Log] = sink
        rc.log("late arrival")

        assert sink.calls == [("info", "late arrival")]

    def test_ignores_a_non_log_entry(
        self, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        rc = _rc(mock_config, _caps={Log: "not a Log"})

        with caplog.at_level(logging.DEBUG, logger="functualize.job.test-job"):
            rc.log("fallback")

        assert [r.message for r in caplog.records] == ["fallback"]


class TestRegistryIsNotConsulted:
    """The unqualified DI registry is not a sink — it would invert engine precedence."""

    def test_registry_log_is_not_used(
        self, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry = DIRegistry()
        registry.provide(Log, CapturingLog())
        rc = _rc(mock_config, _di_registry=registry)

        with caplog.at_level(logging.DEBUG, logger="functualize.job.test-job"):
            rc.log("to the logger")

        assert rc[Log].calls == []
        assert [r.message for r in caplog.records] == ["to the logger"]

    def test_a_qualified_registry_log_does_not_break_logging(
        self, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A qualified-only Log made an earlier fix raise AmbiguousProviderError."""
        registry = DIRegistry()
        registry.provide(Log, CapturingLog(), qualifier="audit")
        rc = _rc(mock_config, _di_registry=registry)

        with caplog.at_level(logging.DEBUG, logger="functualize.job.test-job"):
            rc.log("survives")

        assert [r.message for r in caplog.records] == ["survives"]


class TestLevelValidation:
    """An invalid level fails the same way whichever sink is behind it."""

    @pytest.mark.parametrize("level", ["nonexistent", "exception", "warn", "FATAL"])
    def test_invalid_level_rejected_with_a_log(
        self, mock_config: MagicMock, level: str
    ) -> None:
        sink = CapturingLog()
        rc = _rc(mock_config, _caps={Log: sink})

        with pytest.raises(ValueError, match="Invalid log level"):
            rc.log("msg", level=level)
        assert sink.calls == []

    @pytest.mark.parametrize("level", ["nonexistent", "exception", "warn", "FATAL"])
    def test_invalid_level_rejected_without_a_log(
        self, mock_config: MagicMock, level: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        rc = _rc(mock_config)

        with (
            caplog.at_level(logging.DEBUG, logger="functualize.job.test-job"),
            pytest.raises(ValueError, match="Invalid log level"),
        ):
            rc.log("msg", level=level)
        assert caplog.records == []

    def test_invalid_level_rejected_before_callbacks(
        self, mock_config: MagicMock
    ) -> None:
        seen: list[tuple[str, str]] = []
        rc = _rc(mock_config, _caps={Log: CapturingLog()})
        rc.on_log(lambda level, msg: seen.append((level, msg)))

        with pytest.raises(ValueError, match="Invalid log level"):
            rc.log("msg", level="nope")
        assert seen == []

    def test_capturing_log_rejects_what_the_real_log_rejects(self) -> None:
        """The double must not accept a level production would refuse."""
        sink = CapturingLog()

        with pytest.raises(ValueError, match="Invalid log level"):
            sink("msg", level="exception")
        assert sink.calls == []


class TestCallbacksStillApply:
    """Suppress/replace semantics sit ahead of the sink, not around it."""

    def test_callback_can_suppress(self, mock_config: MagicMock) -> None:
        sink = CapturingLog()
        rc = _rc(mock_config, _caps={Log: sink})
        rc.on_log(lambda level, msg: None)

        rc.log("suppressed")

        assert sink.calls == []

    def test_callback_can_rewrite(self, mock_config: MagicMock) -> None:
        sink = CapturingLog()
        rc = _rc(mock_config, _caps={Log: sink})
        rc.on_log(lambda level, msg: "rewritten")

        rc.log("original")

        assert sink.calls == [("info", "rewritten")]


# ---------------------------------------------------------------------------
# Through the front door: a real invocation, both logging routes at once
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


@pytest.mark.usefixtures("_isolated_project")
class TestOneSinkPerInvocation:
    """A job that uses both routes must not get two different Logs."""

    def test_rc_log_and_log_param_share_one_instance(self) -> None:
        seen: dict[str, object] = {}

        @job
        def emit(rc: RunContext, log: Log) -> None:
            seen["param"] = log
            seen["sink"] = rc._log_sink()

        app = FunctualizeApp(name="logsink")
        app.register_dynamic_job("emit", emit)
        app.execute("emit")

        assert seen["sink"] is seen["param"], (
            "rc.log() and the `log: Log` parameter resolved to different sinks"
        )

    def test_both_routes_reach_the_job_logger(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        @job
        def emit(rc: RunContext, log: Log) -> None:
            log("from the parameter")
            rc.log("from the context")

        app = FunctualizeApp(name="logsink")
        app.register_dynamic_job("emit", emit)

        with caplog.at_level(logging.DEBUG, logger="functualize.job.emit"):
            app.execute("emit")

        messages = [
            r.message for r in caplog.records if r.name == "functualize.job.emit"
        ]
        assert messages == ["from the parameter", "from the context"]

    def test_rc_log_without_a_log_param_still_reaches_the_job_logger(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The fallback path, end to end — no Log is created for this job."""

        @job
        def quiet(rc: RunContext) -> None:
            rc.log("context only")

        app = FunctualizeApp(name="logsink")
        app.register_dynamic_job("quiet", quiet)

        with caplog.at_level(logging.DEBUG, logger="functualize.job.quiet"):
            app.execute("quiet")

        messages = [
            r.message for r in caplog.records if r.name == "functualize.job.quiet"
        ]
        assert messages == ["context only"]
