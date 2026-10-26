"""`inv(..., capture=True)`, and the default path it must leave alone.

`TestDefaultPathUnchanged` was pinned before capture existed and is not edited:
without `capture=True` a child's output still reaches stdout, and its result
gains neither key.
"""

import time
from collections.abc import Callable, Generator
from typing import Any

import pytest
from click.testing import CliRunner
from pydantic import BaseModel

from functualize._app.state import AppState
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp
from functualize.job import Deps, RunContext, Stdout, job
from functualize.types import JobFailedError, JobResult, RunRequest, RunStatus


class TestDefaultPathUnchanged:
    def test_child_and_parent_both_emit_without_capture(self, tmp_path) -> None:
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (jobs / "chain.py").write_text(
            "from functualize.job import RunContext, Stdout\n"
            "def child(out: Stdout):\n"
            "    out.emit({'step': 'a'})\n"
            "def parent(rc: RunContext, out: Stdout):\n"
            "    result = rc.invoke('child')\n"
            "    assert 'emitted' not in result.metadata\n"
            "    assert 'writes' not in result.metadata\n"
            "    out.emit({'step': 'parent'})\n"
        )
        app = FunctualizeApp(
            name="capture-baseline", job_sources=JobSources(directories=[str(jobs)])
        )

        result = CliRunner().invoke(
            app.cli_command, ["--emit-format", "json", "parent"]
        )

        assert result.exit_code == 0, result.output
        assert result.stdout == '{"step":"a"}\n{"step":"parent"}\n'


# ── capture=True ────────────────────────────────────────────────────────────
#
# Driven through the real engine: `app.execute` runs `parent`, whose
# `rc.invoke(..., capture=True)` is the production `WiredInvoke`, whose child
# gets its `Stdout` from `_make_stdout`. The parent returns the child's result,
# so the test reads it off `return_value`.


class _Opaque:
    """No JSON encoder accepts this; capture must hand it back untouched."""


_OPAQUE = _Opaque()


class _Answer(BaseModel):
    reply: str = ""


def _run(jobs: dict[str, Callable[..., Any]], output_format: str = "json") -> JobResult:
    app = FunctualizeApp(name="capture")
    for name, fn in jobs.items():
        app.register_dynamic_job(name, fn)
    return app.execute(
        RunRequest(
            job_name="parent", surface="app.execute", output_format=output_format
        )
    )


def _child_result(parent: JobResult) -> JobResult:
    assert parent.status is RunStatus.SUCCESS, parent.exception
    child = parent.return_value
    assert isinstance(child, JobResult)
    return child


class TestCapture:
    @pytest.fixture(autouse=True)
    def _reset_state(self) -> Generator[None]:
        AppState.reset()
        yield
        AppState.reset()

    def test_emits_and_writes_are_recorded_in_order_and_not_written(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def child(out: Stdout) -> None:
            out.emit({"a": 1})
            out.write("w")
            out.emit(None)
            out.write(b"b")

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("child", capture=True)

        result = _child_result(_run({"child": child, "parent": parent}))

        assert result.metadata["emitted"] == ({"a": 1}, None)
        assert result.metadata["writes"] == ("w", b"b")
        assert type(result.metadata["emitted"]) is tuple
        assert type(result.metadata["writes"]) is tuple
        assert capsys.readouterr().out == ""

    def test_a_child_that_records_nothing_gets_two_empty_tuples(self) -> None:
        def quiet(out: Stdout) -> None:
            return None

        def no_stdout() -> int:
            return 1

        def parent(rc: RunContext) -> tuple[JobResult, JobResult]:
            return (
                rc.invoke("quiet", capture=True),
                rc.invoke("no_stdout", capture=True),
            )

        outcome = _run({"quiet": quiet, "no_stdout": no_stdout, "parent": parent})

        assert outcome.status is RunStatus.SUCCESS, outcome.exception
        for child in outcome.return_value:
            assert child.metadata["emitted"] == ()
            assert child.metadata["writes"] == ()

    def test_a_failing_child_keeps_what_it_emitted(self) -> None:
        def boom(out: Stdout) -> None:
            out.emit("before")
            raise RuntimeError("boom failed")

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("boom", capture=True)

        result = _child_result(_run({"boom": boom, "parent": parent}))

        assert result.status is RunStatus.FAILURE
        assert result.metadata["emitted"] == ("before",)
        with pytest.raises(JobFailedError) as error:
            result.raise_for_status()
        assert error.value.result.metadata["emitted"] == ("before",)

    def test_emit_format_none_still_records(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def child(out: Stdout) -> None:
            out.emit({"kept": True})
            out.write("raw")

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("child", capture=True)

        result = _child_result(
            _run({"child": child, "parent": parent}, output_format="none")
        )

        assert result.metadata["emitted"] == ({"kept": True},)
        assert result.metadata["writes"] == ("raw",)
        assert capsys.readouterr().out == ""

    def test_an_object_no_format_accepts_is_returned_itself(self) -> None:
        def child(out: Stdout) -> None:
            out.emit(_OPAQUE)

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("child", capture=True)

        result = _child_result(_run({"child": child, "parent": parent}))

        assert result.metadata["emitted"][0] is _OPAQUE

    def test_an_uncaptured_grandchild_reaches_stdout(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def grand(out: Stdout) -> None:
            out.emit({"from": "grand"})

        def child(rc: RunContext, out: Stdout) -> None:
            rc.invoke("grand")
            out.emit({"from": "child"})

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("child", capture=True)

        result = _child_result(_run({"grand": grand, "child": child, "parent": parent}))

        assert result.metadata["emitted"] == ({"from": "child"},)
        assert capsys.readouterr().out == '{"from":"grand"}\n'

    def test_a_captured_grandchild_is_in_the_childs_result_only(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def grand(out: Stdout) -> None:
            out.emit({"from": "grand"})

        def child(rc: RunContext) -> JobResult:
            return rc.invoke("grand", capture=True)

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("child", capture=True)

        result = _child_result(_run({"grand": grand, "child": child, "parent": parent}))

        inner = result.return_value
        assert inner.metadata["emitted"] == ({"from": "grand"},)
        assert result.metadata["emitted"] == ()
        assert capsys.readouterr().out == ""

    def test_a_captured_childs_dependency_is_not_captured(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Only `invoke` states `capture`; every other nested run inherits the
        reset in `nested_request`, so a dependency writes as it does today."""

        def prep(out: Stdout) -> None:
            out.emit({"from": "prep"})

        @job(deps=Deps("prep"))
        def child(out: Stdout) -> None:
            out.emit({"from": "child"})

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("child", capture=True)

        result = _child_result(_run({"prep": prep, "child": child, "parent": parent}))

        assert result.metadata["emitted"] == ({"from": "child"},)
        assert capsys.readouterr().out == '{"from":"prep"}\n'

    def test_awaits_input_and_capture_keys_sit_side_by_side(self) -> None:
        def child(out: Stdout) -> None:
            out.emit("x")

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("child", capture=True, awaits_input=_Answer)

        result = _child_result(_run({"child": child, "parent": parent}))

        assert result.metadata["_awaits_input"] is True
        assert "_input_schema" in result.metadata
        assert result.metadata["emitted"] == ("x",)
        assert result.metadata["writes"] == ()

    def test_a_timed_out_child_returns_what_it_recorded_by_the_deadline(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def slow(out: Stdout) -> None:
            out.emit("before")
            time.sleep(0.5)
            out.emit("after")

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("slow", capture=True, timeout=0.1)

        result = _child_result(_run({"slow": slow, "parent": parent}))

        assert result.status is RunStatus.TIMEOUT
        assert result.metadata["emitted"] == ("before",)
        assert result.metadata["writes"] == ()
        assert capsys.readouterr().out == ""

    def test_capture_is_a_control_input_not_a_job_argument(self) -> None:
        def child(out: Stdout, value: int = 0) -> None:
            out.emit(value)

        def parent(rc: RunContext) -> JobResult:
            return rc.invoke("child", capture=True, value=7)

        result = _child_result(_run({"child": child, "parent": parent}))

        assert result.status is RunStatus.SUCCESS
        assert result.metadata["emitted"] == (7,)
