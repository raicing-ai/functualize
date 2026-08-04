"""A required group option is asked for exactly like a required job field (T45).

Group options resolve through the same ladder as a job's own config — default <
config file < env < CLI, with the group path substituted for the job name — so
they must fail, and recover, the same way. If a missing `[deploy] token` were
prompted for but a missing `[report] city` were not (or the reverse), then
"does this field get asked for?" would depend on which *kind* of field it is,
which is the one distinction the whole S6a surface-parity work exists to keep
invisible to users. It is also the shape of leak that shipped green five times
during this feature: two surfaces internally consistent and disagreeing.

The non-interactive half is the same contract too — the original
`ValidationError`, not a typed substitute, because that is what carries the
config-source hint a CI reader needs.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import ValidationError

from functualize._app.state import AppState
from functualize._types.interactivity import (
    PromptIntent,
    PromptRequest,
    PromptResponse,
)
from functualize.app.core import FunctualizeApp
from functualize.job import GroupOptions, RunStatus


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DEPLOY_TOKEN", raising=False)
    monkeypatch.delenv("DEPLOY__TOKEN", raising=False)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


class DeployOptions(GroupOptions, group="deploy"):
    token: str  # required, and nothing supplies it
    dry_run: bool = False


class _Collector:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list[PromptRequest] = []

    def collect(self, request: PromptRequest) -> PromptResponse:
        self.requests.append(request)
        return PromptResponse(value=self.answer)


def _app(collector: object | None = None) -> FunctualizeApp:
    app = FunctualizeApp(name="gotest")

    def run(opts: DeployOptions = None) -> str:  # type: ignore[assignment]
        return f"token={opts.token}"

    app.register_dynamic_job("run", run)
    if collector is not None:
        app.register_surface(collector)
    return app


def test_a_missing_group_option_is_prompted_for() -> None:
    collector = _Collector("t0ken")

    result = _app(collector).execute("run")

    assert result.status is RunStatus.SUCCESS
    assert result.return_value == "token=t0ken"


def test_the_question_is_scoped_to_the_group_not_the_job() -> None:
    """`deploy`, not `run`. The group path is the section the value belongs to
    and the one the user would write it into — naming the job would send them
    to the wrong config block."""
    collector = _Collector("t0ken")

    _app(collector).execute("run")

    assert "deploy" in collector.requests[0].question
    assert "token" in collector.requests[0].question


def test_it_is_collected_as_plain_text_when_not_secret() -> None:
    collector = _Collector("t0ken")

    _app(collector).execute("run")

    assert collector.requests[0].intent is PromptIntent.TEXT_INPUT


def test_with_nothing_to_ask_the_validation_error_is_preserved() -> None:
    """Same as the job-config path: the typed substitute would lose the
    field-level panel and the config-source hint."""
    result = _app().execute("run")

    assert result.status is RunStatus.FAILURE
    assert isinstance(result.exception, ValidationError)


def test_a_group_option_the_chain_supplied_is_not_asked_for(tmp_path: Path) -> None:
    (Path.cwd() / "config.base.toml").write_text('[deploy]\ntoken = "from-file"\n')
    AppState.reset()
    collector = _Collector("unused")

    result = _app(collector).execute("run")

    assert result.return_value == "token=from-file"
    assert collector.requests == []
