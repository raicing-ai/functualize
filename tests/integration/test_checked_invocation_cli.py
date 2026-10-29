"""The checked lane and capture, through the door a user actually uses.

`app.cli_command` under `CliRunner`, the pattern
`tests/context/test_invoke_failure_hook.py` uses: the jobs are a real job
directory, discovered, injected and run by the engine; what is asserted is
the exit code, stdout and stderr a shell would see.

- `chain` invokes a failing `boom` and carries on. It still exits 0: the
  unchecked lane is untouched.
- `checked_chain` adds `.raise_for_status()`. It exits 1, and stderr names
  the child, its status and its error.
- `parent` is the two-children repro: without capture every child's document
  reaches stdout; `captured_parent` prints one document holding theirs.

Nothing here spawns a subprocess (the refusing precondition is a callable),
so the autouse fake home is enough.
"""

from __future__ import annotations

import textwrap
import traceback
from typing import Any

import pytest
from click.testing import CliRunner, Result

from functualize._app.state import AppState
from functualize._events.hooks import HookEvent
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp
from functualize.types import JobFailedError, RunStatus

_JOBS = """\
    from functualize.job import Guards, Invoke, Precondition, Stdout, job


    def boom() -> None:
        raise RuntimeError("boom failed")


    def chain(inv: Invoke) -> None:
        result = inv("boom")
        print(f"CHAIN CONTINUED: status={result.status} exception={result.exception!r}")


    def checked_chain(inv: Invoke) -> None:
        inv("boom").raise_for_status()


    def grandparent(inv: Invoke) -> None:
        inv("checked_chain").raise_for_status()


    @job(guards=Guards(preconditions=[Precondition(lambda: False, msg="not ready")]))
    def refused() -> None:
        return None


    def checks_refused(inv: Invoke) -> None:
        inv("refused").raise_for_status()


    def child_a(out: Stdout) -> None:
        out.emit({"step": "a"})


    def child_b(out: Stdout) -> None:
        out.emit({"step": "b"})


    def parent(inv: Invoke, out: Stdout) -> None:
        inv("child_a")
        inv("child_b")
        out.emit({"step": "parent"})


    def captured_parent(inv: Invoke, out: Stdout) -> None:
        a = inv("child_a", capture=True)
        b = inv("child_b", capture=True)
        out.emit({"children": [*a.metadata["emitted"], *b.metadata["emitted"]]})
"""


@pytest.fixture(autouse=True)
def _reset_state() -> Any:
    AppState.reset()
    AppState.set("config_directory", ".")
    AppState.set("environment", "DEV")
    yield
    AppState.reset()


@pytest.fixture
def app(tmp_path: Any) -> FunctualizeApp:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "demo.py").write_text(textwrap.dedent(_JOBS))
    return FunctualizeApp(name="demo", job_sources=JobSources(directories=[str(jobs)]))


def _run(app: FunctualizeApp, *argv: str) -> Result:
    return CliRunner().invoke(app.cli_command, list(argv))


class TestCheckedLane:
    def test_unchecked_chain_carries_on_and_exits_zero(
        self, app: FunctualizeApp
    ) -> None:
        result = _run(app, "chain")

        assert result.exit_code == 0, result.output
        assert result.stdout == (
            "CHAIN CONTINUED: status=RunStatus.FAILURE "
            "exception=RuntimeError('boom failed')\n"
        )

    def test_checked_chain_exits_one_and_names_the_child(
        self, app: FunctualizeApp
    ) -> None:
        result = _run(app, "checked-chain")

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == (
            "Error: JobFailedError: job 'boom' did not succeed (Failure): "
            "RuntimeError: boom failed\n"
        )

    def test_debug_shows_the_childs_frames_as_the_cause(
        self, app: FunctualizeApp
    ) -> None:
        result = _run(app, "--log-level", "DEBUG", "checked-chain")

        assert result.exit_code == 1
        assert isinstance(result.exception, JobFailedError)
        assert result.exc_info is not None
        rendered = "".join(traceback.format_exception(*result.exc_info))
        assert 'demo.py", line' in rendered
        assert "in boom" in rendered
        assert "The above exception was the direct cause" in rendered

    def test_a_refused_child_raises(self, app: FunctualizeApp) -> None:
        result = _run(app, "checks-refused")

        assert result.exit_code == 1
        assert "JobFailedError" in result.stderr
        assert "'refused'" in result.stderr
        assert "(Refused)" in result.stderr

    def test_a_nested_parent_that_lets_it_escape_stays_honest(
        self, app: FunctualizeApp
    ) -> None:
        ended: dict[str, Any] = {}
        app.hook_registry.register_global(
            HookEvent.INVOKE_END,
            lambda rc, name, depth, result: ended.setdefault(name, result),
        )

        result = _run(app, "grandparent")

        assert result.exit_code == 1
        boom, chain = ended["boom"], ended["checked-chain"]
        assert boom.status is RunStatus.FAILURE
        assert chain.status is RunStatus.FAILURE
        assert isinstance(chain.exception, JobFailedError)
        assert chain.exception.__cause__ is boom.exception
        assert isinstance(boom.exception, RuntimeError)
        assert result.stderr == (
            "Error: JobFailedError: job 'checked-chain' did not succeed (Failure): "
            "JobFailedError: job 'boom' did not succeed (Failure): "
            "RuntimeError: boom failed\n"
        )


class TestCapture:
    def test_without_capture_every_child_document_reaches_stdout(
        self, app: FunctualizeApp
    ) -> None:
        result = _run(app, "--emit-format", "json", "parent")

        assert result.exit_code == 0, result.output
        assert result.stdout == '{"step":"a"}\n{"step":"b"}\n{"step":"parent"}\n'

    def test_with_capture_only_the_parents_document_reaches_stdout(
        self, app: FunctualizeApp
    ) -> None:
        result = _run(app, "--emit-format", "json", "captured-parent")

        assert result.exit_code == 0, result.output
        assert result.stdout == '{"children":[{"step":"a"},{"step":"b"}]}\n'
