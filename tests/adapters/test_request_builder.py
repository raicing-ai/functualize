"""The eager and lazy click paths build the *same* request for the same input.

`pitfalls.md` §23 — two dispatch paths, one contract. `create_job_click_command`
builds from a live signature (cold boot); `make_lazy_command` builds from a
cached descriptor (warm boot). Risk R-b is a divergence between them that is
invisible on any single run, because a given machine takes one path or the
other depending on whether the discovery cache happens to be warm.

**This file used to prove nothing.** It called `build_request` twice with
identical arguments and compared the results — and said so in its own docstring:
"the requests are equal by construction". It never imported click,
`click_params` or `lazy_command`, so no change to either dispatch path could
turn it red. An adversarial review found it; the sixth check on this branch that
could not fail.

What it does now: drives one job through **both real constructors**, captures the
`RunRequest` each hands the engine, and compares them field by field.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from functualize._app.state import AppState
from functualize._types.descriptors import JobDescriptor
from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _in_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    AppState.reset()
    yield
    AppState.reset()


def deploy(env: str = "dev") -> str:
    """A job both paths can build a command for."""
    return f"deployed to {env}"


def _app_with_spy() -> tuple[FunctualizeApp, list]:
    """An app whose engine records every request instead of running it."""
    app = FunctualizeApp(name="parity")
    app.register_dynamic_job("deploy", deploy)

    captured: list = []
    engine = app.execution_engine
    real_run = engine.run

    def spy(request):
        captured.append(request)
        return real_run(request)

    engine.run = spy  # type: ignore[method-assign]
    return app, captured


def _descriptor() -> JobDescriptor:
    return JobDescriptor(
        name="deploy",
        group=None,
        function=deploy,
        docstring="A job both paths can build a command for.",
        module_path=__name__,
        config_fields=[],
    )


def _comparable(request: Any) -> dict[str, Any]:
    """Every field the two paths must agree on.

    All of them: unlike MCP's three doors, these two are the *same* door reached
    two ways, so even the surface must match. A difference here is the cold/warm
    split R-b names.
    """
    return {
        "job_name": request.job_name,
        "surface": request.surface,
        "kwargs": dict(request.kwargs),
        "group_option_values": (
            dict(request.group_option_values)
            if request.group_option_values is not None
            else None
        ),
        "workflow_scope_id": request.workflow_scope_id,
        "prompt_gates": request.prompt_gates,
        "output_format": request.output_format,
        "force": request.force,
        "invoke_depth": request.invoke_depth,
        "run_dependencies": request.run_dependencies,
    }


class TestBothConstructorsAgree:
    def test_one_input_produces_one_request(self) -> None:
        from functualize.app.adapters.click_params import create_job_click_command
        from functualize.app.adapters.lazy_command import make_lazy_command

        app, captured = _app_with_spy()

        eager_command = create_job_click_command(
            name="deploy", function=deploy, app=app
        )
        eager_command.callback(env="prod")  # type: ignore[misc]

        lazy_command = make_lazy_command(_descriptor(), app)
        lazy_command.callback(env="prod")  # type: ignore[misc]

        assert len(captured) == 2, (
            f"both constructors must reach the engine; got {len(captured)}"
        )
        eager_request, lazy_request = captured

        assert _comparable(eager_request) == _comparable(lazy_request)

    def test_a_door_that_states_its_surface_states_it_on_both(self) -> None:
        """`func`'s handlers pass a surface; it must survive either path."""
        from functualize.app.adapters.click_params import create_job_click_command
        from functualize.app.adapters.lazy_command import make_lazy_command

        app, captured = _app_with_spy()

        create_job_click_command(
            name="deploy", function=deploy, app=app, surface="func.job"
        ).callback(env="prod")  # type: ignore[misc]
        make_lazy_command(_descriptor(), app, surface="func.job").callback(env="prod")  # type: ignore[misc]

        assert [r.surface for r in captured] == ["func.job", "func.job"]

    def test_the_delivery_inputs_survive_both_paths(self) -> None:
        from functualize.app.adapters.click_params import create_job_click_command
        from functualize.app.adapters.lazy_command import make_lazy_command

        app, captured = _app_with_spy()
        delivery: dict[str, Any] = {
            "prompt_gates": True,
            "output_format": "json",
            "force": True,
        }

        create_job_click_command(
            name="deploy", function=deploy, app=app, **delivery
        ).callback(env="prod")  # type: ignore[misc]
        make_lazy_command(_descriptor(), app, **delivery).callback(env="prod")  # type: ignore[misc]

        for request in captured:
            assert request.prompt_gates is True
            assert request.output_format == "json"
            assert request.force is True
