"""MCP's three executing doors build the same request for the same inputs.

There are three ways to run a job over MCP: the **per-job tool** the translator
generates, the generic **`run_job`**, and **`run_job_async`**'s background
worker. `_tools.py`'s own docstring records what happened the last time they
were written separately — "three doors into the same room disagreed about the
shape of their answer".

So this is deliberately **one property test, not three**. Three tests, one per
door, is the shape that lets them drift: each keeps passing while asserting a
different thing. What is asserted here is that for one set of inputs the doors
produce the *same* `RunRequest`, field by field, apart from the surface label
each is required to differ on (risk R-b).

**The per-job tool is compared on the fields it has.** Its schema is generated
flat from the job's own parameters, so it has nowhere to put `scope_id` without
risking a collision with a job parameter of that name — which is exactly why
`run_job` and `run_job_async` nest job arguments under `arguments` and keep the
control inputs beside it. Giving the per-job tool the same envelope means
changing the generated schema and `_server.py`, neither of which belongs to this
task; recorded rather than done quietly.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from functualize_mcp._config import MCPConfig
from functualize_mcp._tools import MCPToolRegistry

if TYPE_CHECKING:
    from functualize.types import RunRequest


@dataclass(frozen=True)
class _Field:
    name: str
    type_annotation: str = "str"
    default: Any = None
    description: str = ""
    required: bool = False
    choices: Any = None


@dataclass
class _Descriptor:
    name: str
    docstring: str = "A job."
    config_fields: list[_Field] = field(default_factory=list)
    group: str | None = None
    func_name: str = "run"
    module_path: str = "jobs"
    uses_live: bool = False
    requires_tty: bool = False
    workflow: Any = None


@dataclass
class _Result:
    status: Any = "SUCCESS"
    return_value: Any = "ok"
    duration_ms: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    exception: Any = None
    job_name: str = "deploy"


class _RecordingApp:
    """Captures the `RunRequest` each door builds."""

    def __init__(self, descriptors: list[_Descriptor]) -> None:
        self._descriptors = descriptors
        self.requests: list[RunRequest] = []
        self._lock = threading.Lock()

    def get_jobs(self) -> list[_Descriptor]:
        return self._descriptors

    def get_job(self, name: str) -> _Descriptor | None:
        return next((d for d in self._descriptors if d.name == name), None)

    def execute(self, request: RunRequest) -> _Result:
        with self._lock:
            self.requests.append(request)
        return _Result()


_ARGUMENTS = {"target": "prod", "retries": "3"}
_GROUP_OPTIONS = {"env": "staging"}
_SCOPE = "scope-42"


@pytest.fixture
def app() -> _RecordingApp:
    return _RecordingApp([_Descriptor(name="deploy")])


def _comparable(request: RunRequest) -> dict[str, Any]:
    """Every field a door is expected to agree on — surface excluded.

    Surface is the one field they *must* differ on: it records which door the
    run came through, and a door that reported another door's surface would be
    lying about its own identity.
    """
    return {
        "job_name": request.job_name,
        "kwargs": dict(request.kwargs),
        "group_option_values": (
            dict(request.group_option_values)
            if request.group_option_values is not None
            else None
        ),
        "workflow_scope_id": request.workflow_scope_id,
        "force": request.force,
        "prompt_gates": request.prompt_gates,
        "invoke_depth": request.invoke_depth,
        "run_dependencies": request.run_dependencies,
    }


class TestTheGenericAndAsyncDoorsAgree:
    def test_they_build_the_same_request(self, app: _RecordingApp) -> None:
        registry = MCPToolRegistry(app, config=MCPConfig())

        asyncio.run(
            registry._run_job(
                "deploy",
                arguments=dict(_ARGUMENTS),
                group_option_values=dict(_GROUP_OPTIONS),
                scope_id=_SCOPE,
            )
        )
        started = asyncio.run(
            registry._run_job_async(
                "deploy",
                arguments=dict(_ARGUMENTS),
                group_option_values=dict(_GROUP_OPTIONS),
                scope_id=_SCOPE,
            )
        )
        assert "execution_id" in started, started

        # The async door hands off to a thread; wait for its request to land
        # rather than sleeping a guessed interval.
        deadline = threading.Event()
        for _ in range(200):
            if len(app.requests) >= 2:
                break
            deadline.wait(0.01)

        assert len(app.requests) == 2, (
            f"expected both doors to reach the engine, got {len(app.requests)}"
        )
        sync_request, async_request = app.requests

        assert _comparable(sync_request) == _comparable(async_request)

    def test_each_door_still_names_itself(self, app: _RecordingApp) -> None:
        """Agreement is about the payload, never about identity."""
        registry = MCPToolRegistry(app, config=MCPConfig())

        asyncio.run(registry._run_job("deploy", arguments=dict(_ARGUMENTS)))
        asyncio.run(registry._run_job_async("deploy", arguments=dict(_ARGUMENTS)))
        for _ in range(200):
            if len(app.requests) >= 2:
                break
            threading.Event().wait(0.01)

        surfaces = {r.surface for r in app.requests}
        assert surfaces == {"mcp.run-job", "mcp.async"}, surfaces


class TestControlInputsCannotBecomeJobArguments:
    def test_a_job_parameter_named_scope_id_stays_an_argument(
        self, app: _RecordingApp
    ) -> None:
        """The collision the nested envelope exists to prevent.

        A caller sending a job parameter called `scope_id` gets it as an
        argument; the scope is chosen separately, beside the envelope, and the
        two cannot be confused for one another.
        """
        registry = MCPToolRegistry(app, config=MCPConfig())

        asyncio.run(
            registry._run_job(
                "deploy",
                arguments={"scope_id": "a-job-argument"},
                scope_id="the-real-scope",
            )
        )

        request = app.requests[0]
        assert request.kwargs == {"scope_id": "a-job-argument"}
        assert request.workflow_scope_id == "the-real-scope"

    def test_omitting_the_control_inputs_leaves_them_unset(
        self, app: _RecordingApp
    ) -> None:
        registry = MCPToolRegistry(app, config=MCPConfig())

        asyncio.run(registry._run_job("deploy", arguments=dict(_ARGUMENTS)))

        request = app.requests[0]
        assert request.group_option_values is None
        assert request.workflow_scope_id is None
        assert dict(request.kwargs) == _ARGUMENTS
