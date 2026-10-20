"""End-to-end witnesses for reading a node produced by the current walk.

The source for each workflow is compiled in both annotation modes.  The
AC1 and AC10 classes passed before the reader existed; every other class
failed on that base and is green only because boot validation and executor
injection now read the walk's own records.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from functualize._app.state import AppState
from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.scope_store import ScopeStore
from functualize._types.enums import RunStatus
from functualize._types.errors import WorkflowDeclarationError
from functualize.app.core import FunctualizeApp, request_for
from functualize.types import RunRequest


@pytest.fixture(autouse=True)
def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture(params=[False, True], ids=["live", "future"])
def future_annotations(request: pytest.FixtureRequest) -> bool:
    return bool(request.param)


def _module(source: str, future: bool) -> ModuleType:
    module = ModuleType("from_step_witness")
    prefix = "from __future__ import annotations\n" if future else ""
    exec(compile(prefix + source, module.__name__, "exec"), module.__dict__)
    return module


def _app(module: ModuleType, *names: str) -> FunctualizeApp:
    app = FunctualizeApp(name="from-step-witness")
    for name in names:
        app.register_dynamic_job(name, getattr(module, name))
    return app


def _run(app: FunctualizeApp, name: str = "walk", scope: str = "one"):
    return app.execute(
        RunRequest(job_name=name, surface="app.execute", workflow_scope_id=scope)
    )


def _mentions(message: str, node: str, parameter: str, reader: str) -> None:
    assert re.search(rf"FromStep\(['\"]{re.escape(node)}['\"]\)", message)
    assert parameter in message
    assert reader in message


class TestAC1BootBlocks:
    def test_an_unanswered_gate_blocks(self, future_annotations: bool) -> None:
        module = _module(
            """
from pydantic import BaseModel
from functualize.workflow import END, Edge, Gate, Step, workflow
class Approval(BaseModel):
    ok: bool
def plan() -> str:
    return "planned"
@workflow(
    steps=[Step(plan), Gate("approve", awaits=Approval)],
    edges=[Edge("plan", "approve"), Edge("approve", END)],
)
def walk() -> str:
    return "done"
""",
            future_annotations,
        )
        assert _run(_app(module, "plan", "walk")).status is RunStatus.BLOCKED


class TestAC2ResumeAcrossProcesses:
    def test_gate_answer_reaches_step_and_epilogue(
        self, future_annotations: bool, tmp_path: Path
    ) -> None:
        project = tmp_path / "fresh-process"
        project.mkdir()
        (project / ".functualize").mkdir()
        (project / ".functualize.toml").write_text(
            'jobs_directories = ["jobs"]\nroot = true\n'
        )
        (project / "jobs").mkdir()
        source = """
from typing import Annotated
from pydantic import BaseModel
from functualize.job import job
from functualize.workflow import END, Edge, FromStep, Gate, Step, workflow
class Approval(BaseModel):
    ok: bool
@job
def plan() -> str:
    return "planned"
@job
def act(ok: Annotated[Approval, FromStep("approve")]) -> str:
    return f"ACT SAW {ok.ok}"
@workflow(
    steps=[Step(plan), Gate("approve", awaits=Approval), Step(act)],
    edges=[Edge("plan", "approve"), Edge("approve", "act"), Edge("act", END)],
)
def walk(ok: Annotated[Approval, FromStep("approve")] = None,
         acted: Annotated[str, FromStep("act")] = "MISSING") -> str:
    return f"BODY SAW {ok.ok}; {acted}"
"""
        if future_annotations:
            source = "from __future__ import annotations\n" + source
        (project / "jobs" / "walk.py").write_text(source)
        env = dict(os.environ)
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            path = project / key.lower()
            path.mkdir()
            env[key] = str(path)

        def cli(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "-m", "functualize", *args],
                cwd=project,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        first = cli("walk")
        assert first.returncode == 5, first.stdout + first.stderr
        scope_ids = ScopeStore.for_project(project).scope_ids()
        assert len(scope_ids) == 1
        resumed = cli(
            "builtin",
            "workflow",
            "resume",
            scope_ids[0],
            "--input",
            '{"ok": true}',
        )
        output = resumed.stdout + resumed.stderr
        assert resumed.returncode == 0, output
        assert "BODY SAW True; ACT SAW True" in output


class TestAC3EpilogueReadsStep:
    def test_body_receives_recorded_step_value(self, future_annotations: bool) -> None:
        module = _module(
            """
from typing import Annotated
from functualize.workflow import FromStep
from functualize.workflow import END, Edge, Step, workflow
def plan() -> str:
    return "this-walk"
@workflow(steps=[Step(plan)], edges=[Edge("plan", END)])
def walk(seen: Annotated[str, FromStep("plan")] = "MISSING") -> str:
    return seen
""",
            future_annotations,
        )
        result = _run(_app(module, "plan", "walk"))
        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "this-walk"


class TestAC4UnknownName:
    def test_boot_refuses_unknown_reader(self, future_annotations: bool) -> None:
        module = _module(
            """
from typing import Annotated
from functualize.workflow import FromStep
from functualize.workflow import END, Edge, Step, workflow
def act(value: Annotated[str, FromStep("missing")]) -> str:
    return value
@workflow(steps=[Step(act)], edges=[Edge("act", END)])
def walk() -> None:
    pass
""",
            future_annotations,
        )
        with pytest.raises(WorkflowDeclarationError) as exc:
            _run(_app(module, "act", "walk"))
        _mentions(str(exc.value), "missing", "value", "act")


class TestAC5Ordering:
    def test_later_step_is_refused_at_boot(self, future_annotations: bool) -> None:
        module = _module(
            """
from typing import Annotated
from functualize.workflow import FromStep
from functualize.workflow import END, Edge, Step, workflow
def first(value: Annotated[str, FromStep("later")]) -> str:
    return value
def later() -> str:
    return "late"
@workflow(steps=[Step(first), Step(later)],
          edges=[Edge("first", "later"), Edge("later", END)])
def walk() -> None:
    pass
""",
            future_annotations,
        )
        with pytest.raises(WorkflowDeclarationError) as exc:
            _run(_app(module, "first", "later", "walk"))
        _mentions(str(exc.value), "later", "value", "first")

    def test_gate_cannot_bind_its_own_answer(self, future_annotations: bool) -> None:
        module = _module(
            """
from pydantic import BaseModel
from functualize.workflow import FromStep
from functualize.workflow import END, Edge, Gate, Step, Tool, workflow
class Approval(BaseModel):
    ok: bool
def plan() -> str:
    return "plan"
def inspect(allowed: object) -> None:
    pass
@workflow(steps=[Step(plan), Gate("approve", awaits=Approval,
                                tools=[Tool(inspect, allowed=FromStep("approve"))])],
          edges=[Edge("plan", "approve"), Edge("approve", END)])
def walk() -> None:
    pass
""",
            future_annotations,
        )
        with pytest.raises(WorkflowDeclarationError) as exc:
            _run(_app(module, "plan", "inspect", "walk"))
        _mentions(str(exc.value), "approve", "allowed", "approve")


class TestAC6ScopeIsolation:
    def test_a_second_walk_ignores_first_walk_and_fingerprint(
        self, future_annotations: bool
    ) -> None:
        module = _module(
            """
from typing import Annotated
from functualize.job import Fingerprint, job
from functualize.workflow import FromStep
from functualize.workflow import END, ConditionalEdge, Edge, Step, workflow
walks = 0
def choose() -> str:
    global walks
    walks += 1
    return "take" if walks == 1 else "skip"
@job(cache=Fingerprint(sources=["seed.txt"]))
def source() -> str:
    return "FIRST"
def reader(value: Annotated[str, FromStep("source")]) -> str:
    return value
@workflow(steps=[Step(choose), Step(source), Step(reader)],
          edges=[ConditionalEdge("choose", lambda result: result,
                                 {"take": "source", "skip": "reader"}),
                 Edge("source", "reader"), Edge("reader", END)])
def walk() -> str:
    return "done"
""",
            future_annotations,
        )
        Path("seed.txt").write_text("stable")
        app = _app(module, "choose", "source", "reader", "walk")
        first = _run(app, scope="first")
        second = _run(app, scope="second")
        assert first.status is RunStatus.SUCCESS
        assert second.status is RunStatus.FAILURE
        assert (
            ScopeStore.for_project(Path.cwd()).get_scope("first")["steps"]["source::"][
                "return_value"
            ]
            == "FIRST"
        )
        assert FreshStore.for_project(Path.cwd()).fingerprint_keys(prefix="source")
        _mentions(str(second.exception), "source", "value", "reader")


class TestAC7OutsideWalk:
    def test_standalone_job_refuses_the_read(self, future_annotations: bool) -> None:
        module = _module(
            """
from typing import Annotated
from functualize.workflow import FromStep
def reader(value: Annotated[str, FromStep("source")]) -> str:
    return value
""",
            future_annotations,
        )
        result = _app(module, "reader").execute(request_for("reader"))
        assert result.status is RunStatus.FAILURE
        _mentions(str(result.exception), "source", "value", "reader")


class TestR4InvokedChildIsOutsideTheWalk:
    def test_a_job_invoked_from_a_step_refuses_the_read(
        self, future_annotations: bool
    ) -> None:
        module = _module(
            """
from typing import Annotated
from functualize.job import Invoke
from functualize.workflow import FromStep
from functualize.workflow import END, Edge, Step, workflow
children = []
def plan() -> str:
    return "this-walk"
def reader(value: Annotated[str, FromStep("plan")]) -> str:
    return value
def caller(invoke: Invoke) -> str:
    child = invoke("reader")
    children.append(child)
    return "called"
@workflow(steps=[Step(plan), Step(caller)],
          edges=[Edge("plan", "caller"), Edge("caller", END)])
def walk() -> str:
    return "done"
""",
            future_annotations,
        )
        result = _run(_app(module, "plan", "reader", "caller", "walk"))
        assert result.status is RunStatus.SUCCESS, result.exception
        [child] = module.children
        assert child.status is RunStatus.FAILURE
        message = str(child.exception)
        _mentions(message, "plan", "value", "reader")
        assert "outside a walk" in message


class TestAC9SkippedBranch:
    def test_declared_default_is_used_only_for_a_skipped_node(
        self, future_annotations: bool
    ) -> None:
        module = _module(
            """
from typing import Annotated
from functualize.workflow import FromStep
from functualize.workflow import END, ConditionalEdge, Edge, Step, workflow
def choose() -> str:
    return "skip"
def optional() -> str:
    return "RAN"
def reader(value: Annotated[str, FromStep("optional")] = "DEFAULT") -> str:
    return value
@workflow(steps=[Step(choose), Step(optional), Step(reader)],
          edges=[ConditionalEdge("choose", lambda _: "skip",
                                 {"take": "optional", "skip": "reader"}),
                 Edge("optional", "reader"), Edge("reader", END)])
def walk(seen: Annotated[str, FromStep("reader")] = "MISSING") -> str:
    return seen
""",
            future_annotations,
        )
        result = _run(_app(module, "choose", "optional", "reader", "walk"))
        assert result.status is RunStatus.SUCCESS
        assert result.return_value == "DEFAULT"

    def test_no_default_is_a_named_failure(self, future_annotations: bool) -> None:
        module = _module(
            """
from typing import Annotated
from functualize.workflow import FromStep
from functualize.workflow import END, ConditionalEdge, Edge, Step, workflow
def choose() -> str:
    return "skip"
def optional() -> str:
    return "RAN"
def reader(value: Annotated[str, FromStep("optional")]) -> str:
    return value
@workflow(steps=[Step(choose), Step(optional), Step(reader)],
          edges=[ConditionalEdge("choose", lambda _: "skip",
                                 {"take": "optional", "skip": "reader"}),
                 Edge("optional", "reader"), Edge("reader", END)])
def walk() -> None:
    pass
""",
            future_annotations,
        )
        result = _run(_app(module, "choose", "optional", "reader", "walk"))
        assert result.status is RunStatus.FAILURE
        _mentions(str(result.exception), "optional", "value", "reader")


class TestAC10GateDepositTarget:
    def test_a_step_name_is_not_a_gate_deposit_target(
        self, future_annotations: bool
    ) -> None:
        module = _module(
            """
from functualize.workflow import END, Edge, Step, workflow
def plan() -> str:
    return "plan"
@workflow(steps=[Step(plan)], edges=[Edge("plan", END)])
def walk() -> str:
    return "done"
""",
            future_annotations,
        )
        assert _run(_app(module, "plan", "walk")).status is RunStatus.SUCCESS
        assert (
            ScopeStore.for_project(Path.cwd()).deposit_gate_payload(
                "one", "plan", {"ok": True}
            )
            is False
        )
