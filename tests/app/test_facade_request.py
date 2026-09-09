"""The facade takes a request, and the scope is now unavoidable.

D-13 is the defect this file guards: `interactivity.job.submit` reaches the
engine directly (`_app/impl.py:861`), so its run gets no addressable scope. The
fix is not to mint a second scope there — the engine already mints a persisted
one at `_engine/workflow_runner.py:97` — it is to make the facade the only way
in, so scope creation cannot be skipped.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp, request_for
from functualize.types import RunRequest


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    application = FunctualizeApp(name="testapp")
    application.register_dynamic_job("greet", _greet)
    return application


def _greet(name: str = "world") -> str:
    return f"hello {name}"


def test_facade_accepts_a_request(app: FunctualizeApp) -> None:
    result = app.execute(RunRequest(job_name="greet", surface="app.execute"))
    assert result.return_value == "hello world"


def test_request_carries_kwargs(app: FunctualizeApp) -> None:
    result = app.execute(
        RunRequest(job_name="greet", surface="http", kwargs={"name": "b"})
    )
    assert result.return_value == "hello b"


def test_request_for_is_the_short_spelling(app: FunctualizeApp) -> None:
    assert app.execute(request_for("greet", name="c")).return_value == "hello c"
    assert request_for("greet").surface == "app.execute"


def test_a_request_creates_an_addressable_scope(app: FunctualizeApp) -> None:
    """The D-13 property: every facade run gets a scope you can name.

    Sabotage target — remove the scope creation in `FunctualizeApp.execute` and
    this fails.
    """
    before = set(app._scope_registry)
    app.execute(RunRequest(job_name="greet", surface="app.execute"))
    created = set(app._scope_registry) - before
    assert len(created) == 1
    assert next(iter(created)).startswith("greet-")


def test_explicit_scope_id_on_the_request_is_honoured(app: FunctualizeApp) -> None:
    app.execute(
        RunRequest(job_name="greet", surface="tui.inline", workflow_scope_id="fixed-1")
    )
    assert "fixed-1" in app._scope_registry


def test_request_and_extra_arguments_is_a_type_error(app: FunctualizeApp) -> None:
    """Two answers to 'what scope is this run in?' is not a supported call."""
    with pytest.raises(TypeError, match="takes no other arguments"):
        app.execute(RunRequest(job_name="greet", surface="app.execute"), scope_id="x")


def test_legacy_form_still_works_until_t15(app: FunctualizeApp) -> None:
    """TRANSITIONAL(run-request/T15): wave 3 migrates the doors one at a time."""
    assert app.execute("greet", name="d").return_value == "hello d"
