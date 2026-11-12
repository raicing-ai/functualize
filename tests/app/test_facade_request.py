"""The facade takes a request, and the scope is now unavoidable.

D-13 is the defect this file guards: `interactivity.job.submit` reaches the
engine directly (`_app/impl.py:861`), so its run gets no addressable scope. The
fix is not to mint a second scope there — the engine already mints a persisted
one at `_engine/workflow_runner.py:97` — it is to make the facade the only way
in, so scope creation cannot be skipped.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from types import MappingProxyType

import pytest

from functualize._app.state import AppState
from functualize._config import ResolutionChain
from functualize._config.settings_layers import SettingsLayer
from functualize._primitives.run_store import RunStore
from functualize.app.config import (
    ConfigSources,
    JobSources,
    PluginSources,
    RunTagError,
    parse_tag,
    resolve_run_tags,
)
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


def test_public_config_seam_resolves_frozen_tags_for_a_request() -> None:
    layer = SettingsLayer(
        Path("/checkout/.functualize.toml"),
        "project",
        "",
        {"run": {"tags": ["team:alpha"]}},
    )

    tags = resolve_run_tags((layer,), environ={})
    request = RunRequest(job_name="greet", surface="app.execute", run_tags=tags)

    assert request.run_tags == {"team": "alpha"}
    assert isinstance(request.run_tags, MappingProxyType)
    with pytest.raises(RunTagError, match="needs a key"):
        parse_tag(":x", where="--run-tag")


def test_execute_caches_file_and_env_tags_then_overlays_explicit_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".functualize.toml").write_text(
        '[run]\ntags = ["team:file", "file:yes"]\n'
    )
    monkeypatch.chdir(project)
    monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", "team:env,env:yes")
    application = FunctualizeApp(name="tagged")
    application.register_dynamic_job("greet", _greet)

    application.execute(
        RunRequest(
            job_name="greet",
            surface="app.execute",
            run_tags={"team": "request"},
        )
    )
    assert isinstance(application._run_tag_defaults, MappingProxyType)
    monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", "team:changed")
    (project / ".functualize.toml").write_text('[run]\ntags = ["team:changed"]\n')
    application.execute(RunRequest(job_name="greet", surface="app.execute"))

    store = RunStore(application.execution_engine._state_store().substrate)
    records = [store.get_run(run_id) for run_id in store.run_ids()]
    assert [record["run_tags"] for record in records if record] == [
        {"team": "request", "file": "yes", "env": "yes"},
        {"team": "env", "file": "yes", "env": "yes"},
    ]


def test_static_app_defers_tag_file_read_until_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "static"
    project.mkdir()
    (project / ".functualize.toml").write_text('[run]\ntags = ["source:file"]\n')
    monkeypatch.chdir(project)
    application = FunctualizeApp(
        "static",
        job_sources=JobSources(functions=[_greet]),
        config_sources=ConfigSources(
            config_resolution_chain=ResolutionChain([]), dotenv=False
        ),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )
    assert application._static_wiring
    assert application._settings_snapshot is None
    assert application._run_tag_defaults is None

    application.execute(RunRequest(job_name="_greet", surface="app.execute"))

    store = RunStore(application.execution_engine._state_store().substrate)
    records = [store.get_run(run_id) for run_id in store.run_ids()]
    assert [record["run_tags"] for record in records if record] == [{"source": "file"}]


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
    """Two answers to 'what scope is this run in?' is not a supported call.

    `execute` takes the request and nothing else, so the second answer is
    refused by the call itself rather than silently winning or silently
    becoming a job argument.
    """
    with pytest.raises(TypeError, match="scope_id"):
        app.execute(RunRequest(job_name="greet", surface="app.execute"), scope_id="x")


def test_the_legacy_job_name_form_is_gone(app: FunctualizeApp) -> None:
    """T15 removed `execute(job_name, **kwargs)`.

    The guard is inverted rather than deleted: the old spelling is the
    accidental channel spec 1.6a closed, so what is pinned now is that it
    **cannot come back**. Every keyword after the name is refused by the call
    instead of being splatted into the payload half.
    """
    with pytest.raises(TypeError, match="name"):
        app.execute("greet", name="d")  # type: ignore[arg-type]
