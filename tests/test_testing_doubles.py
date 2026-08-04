"""Unit tests for functualize.testing.doubles test doubles.

Tests each test double: CapturingLog, MockInvoke, AutoPrompt, NoopPerf.
Validates Requirements 8.3, 8.4, 8.5.
"""

from __future__ import annotations

import pytest

from functualize.testing.doubles import AutoPrompt, CapturingLog, MockInvoke, NoopPerf


class TestCapturingLog:
    """Tests for CapturingLog — records (level, message) tuples in order."""

    def test_empty_on_creation(self):
        log = CapturingLog()
        assert log.calls == []

    def test_call_default_level(self):
        log = CapturingLog()
        log("hello world")
        assert log.calls == [("info", "hello world")]

    def test_call_explicit_level(self):
        log = CapturingLog()
        log("oops", level="error")
        assert log.calls == [("error", "oops")]

    def test_info_method(self):
        log = CapturingLog()
        log.info("information")
        assert log.calls == [("info", "information")]

    def test_warning_method(self):
        log = CapturingLog()
        log.warning("careful")
        assert log.calls == [("warning", "careful")]

    def test_error_method(self):
        log = CapturingLog()
        log.error("broken")
        assert log.calls == [("error", "broken")]

    def test_debug_method(self):
        log = CapturingLog()
        log.debug("trace")
        assert log.calls == [("debug", "trace")]

    def test_insertion_order_preserved(self):
        log = CapturingLog()
        log.info("first")
        log.warning("second")
        log.error("third")
        log.debug("fourth")
        log("fifth", level="critical")
        assert log.calls == [
            ("info", "first"),
            ("warning", "second"),
            ("error", "third"),
            ("debug", "fourth"),
            ("critical", "fifth"),
        ]

    def test_non_string_message(self):
        log = CapturingLog()
        log(42)
        log.info({"key": "value"})
        assert log.calls == [("info", 42), ("info", {"key": "value"})]


class TestMockInvoke:
    """Tests for MockInvoke — job→result mapping with KeyError on unknown."""

    def test_empty_raises_on_any_job(self):
        invoke = MockInvoke({})
        with pytest.raises(KeyError, match="no configured result"):
            invoke("anything")

    def test_none_results_defaults_to_empty(self):
        invoke = MockInvoke(None)
        with pytest.raises(KeyError):
            invoke("missing")

    def test_returns_configured_result(self):
        result = {"status": "ok"}
        invoke = MockInvoke({"deploy": result})
        assert invoke("deploy") is result

    def test_raises_keyerror_on_unknown(self):
        invoke = MockInvoke({"deploy": "ok"})
        with pytest.raises(KeyError, match="unknown_job"):
            invoke("unknown_job")

    def test_error_message_lists_available(self):
        invoke = MockInvoke({"alpha": 1, "beta": 2})
        with pytest.raises(KeyError, match="Available.*alpha.*beta"):
            invoke("gamma")

    def test_accepts_kwargs(self):
        invoke = MockInvoke({"build": "done"})
        assert invoke("build", env="prod", version=3) == "done"

    def test_accepts_timeout(self):
        invoke = MockInvoke({"slow": "finished"})
        assert invoke("slow", timeout=30.0) == "finished"

    def test_parallel_returns_results_in_order(self):
        invoke = MockInvoke({"a": 1, "b": 2, "c": 3})
        results = invoke.parallel([("b", {}), ("a", {}), ("c", {})])
        assert results == [2, 1, 3]

    def test_parallel_raises_on_unknown(self):
        invoke = MockInvoke({"a": 1})
        with pytest.raises(KeyError, match="missing"):
            invoke.parallel([("a", {}), ("missing", {})])

    def test_schema_returns_configured_value(self):
        invoke = MockInvoke({"deploy": "schema_info"})
        assert invoke.schema("deploy") == "schema_info"

    def test_schema_raises_on_unknown(self):
        invoke = MockInvoke({"deploy": "ok"})
        with pytest.raises(KeyError, match="schema.*no configured result"):
            invoke.schema("missing")


class TestAutoPrompt:
    """Tests for AutoPrompt — FIFO responses, IndexError when exhausted."""

    def test_empty_raises_immediately(self):
        prompt = AutoPrompt([])
        with pytest.raises(IndexError, match="exhausted"):
            prompt.text("Name?")

    def test_none_responses_defaults_to_empty(self):
        prompt = AutoPrompt(None)
        with pytest.raises(IndexError):
            prompt.text("Name?")

    def test_returns_responses_in_fifo_order(self):
        prompt = AutoPrompt(["alice", True, "option_b"])
        assert prompt.text("Name?") == "alice"
        assert prompt.confirm("Sure?") is True
        assert prompt.choice("Pick:", []) == "option_b"

    def test_raises_when_exhausted(self):
        prompt = AutoPrompt(["only_one"])
        assert prompt.text("Q1") == "only_one"
        with pytest.raises(IndexError, match="exhausted"):
            prompt.text("Q2")

    def test_ask_returns_next_response(self):
        prompt = AutoPrompt(["response"])
        assert prompt.ask("request_object") == "response"

    def test_confirm_with_destructive(self):
        prompt = AutoPrompt([False])
        assert prompt.confirm("Delete all?", destructive=True) is False

    def test_error_message_includes_count(self):
        prompt = AutoPrompt(["a", "b"])
        prompt.text("1")
        prompt.text("2")
        with pytest.raises(IndexError, match="2.*responses.*consumed"):
            prompt.text("3")

    def test_does_not_mutate_input_list(self):
        original = ["x", "y"]
        prompt = AutoPrompt(original)
        prompt.text("q")
        assert original == ["x", "y"]


class TestNoopPerf:
    """Tests for NoopPerf — accepts all calls silently."""

    def test_mark_does_not_raise(self):
        perf = NoopPerf()
        perf.mark("init")  # should not raise

    def test_mark_start_does_not_raise(self):
        perf = NoopPerf()
        perf.mark_start("phase_1")  # should not raise

    def test_mark_end_does_not_raise(self):
        perf = NoopPerf()
        perf.mark_end("phase_1")  # should not raise

    def test_phases_returns_empty_list(self):
        perf = NoopPerf()
        assert perf.phases() == []

    def test_phases_with_include_returns_empty(self):
        perf = NoopPerf()
        assert perf.phases(include="boot.*") == []

    def test_phases_with_exclude_returns_empty(self):
        perf = NoopPerf()
        assert perf.phases(exclude="internal") == []

    def test_multiple_calls_no_side_effects(self):
        perf = NoopPerf()
        perf.mark("a")
        perf.mark_start("b")
        perf.mark_end("b")
        perf.mark("c")
        perf.mark_start("d")
        perf.mark_end("d")
        # All calls accepted silently, phases still empty
        assert perf.phases() == []
