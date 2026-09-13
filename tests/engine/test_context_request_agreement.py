"""`ExecutionContext.request` and the context's own scalars must agree — rre F9.

The context carries `job_name`, `invoke_depth`, `cwd`, `job_directory`,
`parent_scope` and `config_class` as fields, **and** a whole `RunRequest` that
holds several of the same values. Two shapes answering "what was this run asked
for" is precisely what `_types/protocols.py` says must not exist — *"a second
shape for those would be a second answer to where a run came from"* — and that
sentence is written about the *other* context, which got it right.

The duplication is kept on purpose for now (the field's docstring says why, and
`engine-sealed-construction` T6–T11 is the feature that collapses it). What is
**not** acceptable is the two drifting, because then a capability factory
reading `ctx.request.cwd` and the lifecycle reading `ctx.cwd` disagree about the
same run. So the invariant is asserted here instead of assumed.

The comparison is only meaningful at **depth 0**: a nested run's context
legitimately differs from the request that began it — that is what
`nested_request` exists to express — so the assertion is scoped to a top-level
run, where "the door asked for exactly this" must hold.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from functualize.app.core import FunctualizeApp, request_for


@pytest.fixture
def captured_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Any]:
    """Every `ExecutionContext` the lifecycle builds, in order."""
    monkeypatch.chdir(tmp_path)
    seen: list[Any] = []

    # Patched **where it is used**, not where it is defined: `executor.py`
    # binds the name at import time, so replacing `context.ExecutionContext`
    # intercepts nothing and every assertion below runs over an empty list.
    # `test_the_recorder_actually_saw_something` is what caught that.
    from functualize._engine import executor as executor_module

    original = executor_module.ExecutionContext

    def _recording(*args: Any, **kwargs: Any) -> Any:
        context = original(*args, **kwargs)
        seen.append(context)
        return context

    monkeypatch.setattr(executor_module, "ExecutionContext", _recording)
    return seen


def _app() -> FunctualizeApp:
    app = FunctualizeApp("agreement")

    def echo(value: str = "x") -> str:
        return value

    app.register_dynamic_job("echo", echo)
    return app


def test_a_context_built_by_run_carries_the_same_job_name(
    tmp_path, monkeypatch, captured_context
) -> None:
    """The narrow, checkable half of the invariant, on the real path."""
    monkeypatch.chdir(tmp_path)
    app = _app()

    app.execute(request_for("echo", value="hi"))

    with_request = [c for c in captured_context if getattr(c, "request", None)]
    assert with_request, "no ExecutionContext carried a request"

    for ctx in with_request:
        assert ctx.job_name == ctx.request.job_name, (
            f"the context is running {ctx.job_name!r} while its request says "
            f"{ctx.request.job_name!r} — two answers to what this run is"
        )
        if ctx.invoke_depth == 0:
            assert ctx.invoke_depth == ctx.request.invoke_depth
            assert ctx.parent_scope == ctx.request.parent_scope


def test_the_recorder_actually_saw_something(
    tmp_path, monkeypatch, captured_context
) -> None:
    """The falsifier. If the monkeypatch stops intercepting, the test above
    passes over an empty list and proves nothing."""
    monkeypatch.chdir(tmp_path)
    app = _app()

    app.execute(request_for("echo"))

    assert captured_context, (
        "no ExecutionContext was intercepted, so the agreement assertions "
        "above ran over an empty list"
    )
