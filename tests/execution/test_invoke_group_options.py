"""`rc.invoke` can override the group options a child sees (AC-7, AC-8; STATUS #17).

`None` means **inherit**, which is what every call did before this existed and
what every call that says nothing still does. A mapping overrides for that one
call. `invoke_parallel` is deliberately untouched: its items are independent by
design (`parent_scope=None`), and giving a batch one shared override would
quietly re-couple them.

The inheritance test is written first and matters more than the override test.
The risk in adding a parameter to a call used everywhere is not that the new
behaviour is wrong — it is that the *old* behaviour silently changes for callers
who never asked for anything (risk R-f).
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp, request_for
from functualize.job import RunContext  # noqa: TC001 - resolved at runtime for DI


@pytest.fixture(autouse=True)
def _in_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    (tmp_path / ".functualize").mkdir()
    monkeypatch.chdir(tmp_path)
    AppState.reset()
    yield
    AppState.reset()


def _app_with_parent_and_child() -> tuple[FunctualizeApp, list]:
    """A parent that invokes a child; the child records what it received."""
    seen: list = []
    app = FunctualizeApp(name="invoke-group-options")

    def child(rc: RunContext) -> str:
        seen.append(dict(getattr(rc, "group_option_values", None) or {}))
        return "child-ran"

    app.register_dynamic_job("child", child)
    return app, seen


class TestInheritanceIsUnchanged:
    """The behaviour every existing caller depends on."""

    def test_a_bare_invoke_still_runs_the_child(self) -> None:
        app, seen = _app_with_parent_and_child()

        def parent(rc: RunContext) -> str:
            result = rc.invoke("child")
            # Assert the child really ran — otherwise "it received nothing"
            # would pass for the wrong reason.
            assert result.return_value == "child-ran", result
            return "parent-ran"

        app.register_dynamic_job("parent", parent)
        outcome = app.execute(request_for("parent"))

        assert outcome.status.value == "Success", outcome.exception
        assert outcome.return_value == "parent-ran"
        assert len(seen) == 1

    def test_saying_nothing_and_saying_none_are_the_same_call(self) -> None:
        """`None` is the default *and* the inherit signal — not two states."""
        app, seen = _app_with_parent_and_child()

        def parent(rc: RunContext) -> str:
            implicit = rc.invoke("child")
            explicit = rc.invoke("child", group_option_values=None)
            assert implicit.return_value == explicit.return_value
            return "parent-ran"

        app.register_dynamic_job("parent", parent)
        outcome = app.execute(request_for("parent"))

        assert outcome.status.value == "Success", outcome.exception
        assert len(seen) == 2
        assert seen[0] == seen[1], (
            f"an explicit None diverged from saying nothing: {seen}"
        )


class TestAnOverrideReachesTheChild:
    def test_the_mapping_travels_on_the_request(self) -> None:
        """Asserted on the request, which is where the value has to arrive.

        Whether a *declared* group option then resolves from it is
        `_engine/resolution`'s business and is covered by the group-options
        suites; what this task owns is that the door can say it at all.
        """
        from functualize._engine.capabilities.invoke import WiredInvoke

        captured: list = []
        app = FunctualizeApp(name="invoke-group-options")

        def child() -> str:
            return "child-ran"

        app.register_dynamic_job("child", child)
        engine = app.execution_engine
        real_run = engine.run

        def spy(request):
            captured.append(request)
            return real_run(request)

        engine.run = spy  # type: ignore[method-assign]
        try:
            invoke = WiredInvoke(
                execution_engine=engine,
                gate_registry=getattr(app, "_gate_registry", None),
                invoke_depth=0,
                cwd=Path.cwd(),
            )
            invoke("child", group_option_values={"env": "prod"})
        finally:
            engine.run = real_run  # type: ignore[method-assign]

        assert len(captured) == 1, captured
        assert captured[0].group_option_values == {"env": "prod"}
        assert captured[0].surface == "invoke"

    def test_omitting_it_leaves_the_field_none(self) -> None:
        """The inherit signal on the request itself, not just at the call."""
        from functualize._engine.capabilities.invoke import WiredInvoke

        captured: list = []
        app = FunctualizeApp(name="invoke-group-options")

        def child() -> str:
            return "child-ran"

        app.register_dynamic_job("child", child)
        engine = app.execution_engine
        real_run = engine.run

        def spy(request):
            captured.append(request)
            return real_run(request)

        engine.run = spy  # type: ignore[method-assign]
        try:
            invoke = WiredInvoke(
                execution_engine=engine,
                gate_registry=getattr(app, "_gate_registry", None),
                invoke_depth=0,
                cwd=Path.cwd(),
            )
            invoke("child")
        finally:
            engine.run = real_run  # type: ignore[method-assign]

        assert captured[0].group_option_values is None


class TestParallelIsUntouched:
    def test_parallel_items_stay_independent(self) -> None:
        """`parent_scope=None` is the deliberate behaviour AC-17 pins.

        A batch is a set of independent runs; a shared group-option override
        would re-couple them, which is why `invoke_parallel` gains nothing here.
        """
        import inspect

        from functualize._engine.capabilities.invoke import Invoke

        assert (
            "group_option_values" not in inspect.signature(Invoke.parallel).parameters
        )
