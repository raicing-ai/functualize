"""Asking for missing config, and the far more important case of not asking (T45).

The resolution chain has four places to look for a required field — default,
config file, environment, CLI — and when all four come up empty the only source
left is the person running the job. On an interactive surface, asking is
strictly better than failing: the value exists, it just was not written down
anywhere yet.

Off an interactive surface, asking is the **worst** possible behaviour. A prompt
written to a pipe, to CI, or to an MCP session is a hang: nothing there can
answer, and the process waits forever holding whatever it had already started.
So the whole feature is gated on a collector actually existing, and the
non-interactive path is left exactly as it was.

"Exactly as it was" is deliberate and is what most of this file pins. The
pre-existing `ValidationError` is a *better* error than any typed substitute
this feature could raise: it drives the CLI's field-level panel and the
config-source hint, which names the files that were really read, the
`config.<slot>.<ext>` rule, and `JOB__<FIELD>`. An earlier cut of T45 replaced
it with a one-line `MissingValueError` and made the CI diagnostic worse while
adding a feature CI can never use. These tests exist so that cannot come back.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from pydantic import BaseModel, Field, ValidationError

from functualize._app.state import AppState
from functualize._engine.missing_value import MissingValueError
from functualize._types.interactivity import (
    PromptIntent,
    PromptRequest,
    PromptResponse,
)
from functualize.app.core import FunctualizeApp
from functualize.job import RunStatus


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    """An empty project with no config anywhere above it, and no inherited env.

    HOME is redirected because discovery silently falls back to the user config
    directory; without this a developer's own config would satisfy the field
    and every test here would pass vacuously.
    """
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("REPORT_CITY", raising=False)
    monkeypatch.delenv("REPORT__CITY", raising=False)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


class NeedsCity(BaseModel):
    city: str = Field(description="Required; no default")
    days: int = 3


class NeedsSecret(BaseModel):
    # The flag spelling rather than `Secret[str]`: a *required* `Secret[str]`
    # field needs `arbitrary_types_allowed`, so the flag is what a config author
    # actually reaches for here. Both markers feed the same `is_secret_field`.
    api_key: str = Field(json_schema_extra={"secret": True})


class NeedsPositive(BaseModel):
    days: int = Field(gt=0)


class Inner(BaseModel):
    host: str


class NeedsNested(BaseModel):
    db: Inner


class NeedsTags(BaseModel):
    tags: list[str]


class NeedsOptionalCity(BaseModel):
    city: str | None


class _Collector:
    """An interactive surface that answers, recording what it was asked."""

    def __init__(self, *answers: str) -> None:
        self._answers = list(answers)
        self.requests: list[PromptRequest] = []

    def collect(self, request: PromptRequest) -> PromptResponse:
        self.requests.append(request)
        return PromptResponse(value=self._answers.pop(0) if self._answers else "")


def _app(config_class: type = NeedsCity, collector: object | None = None):
    app = FunctualizeApp(name="cfgtest")

    def report(config) -> str:  # type: ignore[no-untyped-def]
        return repr(config)

    # The parameter is bound by its *annotation*, so it has to carry the model
    # under test — an unannotated `config` is simply never injected.
    report.__annotations__["config"] = config_class

    app.register_dynamic_job("report", report, config_class=config_class)
    if collector is not None:
        app.register_surface(collector)
    return app


class TestNoSurfaceToAsk:
    """The non-interactive contract, which is the one CI depends on."""

    def test_the_validation_error_is_preserved_not_replaced(self) -> None:
        """The regression guard. A typed substitute loses the field-level panel
        and the config-source hint — a strictly worse error on the path that
        users hit most."""
        result = _app().execute("report")

        assert result.status is RunStatus.FAILURE
        assert isinstance(result.exception, ValidationError)

    def test_it_fails_rather_than_waiting_for_an_answer(self) -> None:
        """Stated directly: with nothing able to collect, the run *ends*.

        If this ever blocks, the test suite hangs rather than fails — which is
        precisely what the feature must never do to a CI job.
        """
        assert _app().execute("report").status is RunStatus.FAILURE

    def test_the_job_body_never_runs(self) -> None:
        app = FunctualizeApp(name="cfgtest")
        ran: list[str] = []

        def report(config: NeedsCity) -> str:
            ran.append("body")
            return "never"

        app.register_dynamic_job("report", report, config_class=NeedsCity)
        app.execute("report")

        assert ran == []


class TestAskingWhenSomethingCanAnswer:
    def test_a_missing_field_is_collected_and_the_job_runs(self) -> None:
        result = _app(collector=_Collector("Kyoto")).execute("report")

        assert result.status is RunStatus.SUCCESS
        assert "Kyoto" in str(result.return_value)

    def test_the_question_names_the_field_and_its_section(self) -> None:
        """`city` alone is ambiguous once several jobs are in play; the section
        is what tells the user which config block they are filling in."""
        collector = _Collector("Kyoto")

        _app(collector=collector).execute("report")

        question = collector.requests[0].question
        assert "city" in question
        assert "report" in question

    def test_a_field_the_chain_supplied_is_not_asked_for(self) -> None:
        """Only what is actually missing. Re-asking for a value the config file
        already provides would make the config file pointless."""
        (Path.cwd() / "config.base.toml").write_text('[report]\ncity = "Osaka"\n')
        AppState.reset()
        collector = _Collector("unused")

        result = _app(collector=collector).execute("report")

        assert result.status is RunStatus.SUCCESS
        assert collector.requests == []

    def test_a_secret_field_is_collected_masked(self) -> None:
        """The same predicate that redacts a value in `state.json` decides
        whether it is echoed while being typed. Two independent answers to "is
        this a secret" is how a masked field gets shoulder-surfed."""
        collector = _Collector("sk-live-1234")

        _app(NeedsSecret, collector=collector).execute("report")

        assert collector.requests[0].intent is PromptIntent.SECRET_INPUT

    def test_a_non_secret_field_is_collected_as_plain_text(self) -> None:
        collector = _Collector("Kyoto")

        _app(collector=collector).execute("report")

        assert collector.requests[0].intent is PromptIntent.TEXT_INPUT


class TestWhatIsNotWorthAsking:
    def test_a_constraint_violation_is_never_prompted(self) -> None:
        """A value that was supplied and failed its constraint is a *wrong*
        answer, not an absent one. Re-asking would loop the user through a
        question whose answer they already gave."""
        collector = _Collector("5")

        result = _app(NeedsPositive, collector=collector).execute("report", days=-1)

        assert result.status is RunStatus.FAILURE
        assert collector.requests == []

    def test_a_field_whose_type_is_a_sub_model_is_never_prompted(self) -> None:
        """A prompt collects one line of text, and no line of text is an
        `Inner`. Asking would interrogate the user and *then* show them the
        field error they would have got for free.

        Note the shape: a missing `db` reports `loc == ("db",)`, so the
        location check alone lets it through — it takes a look at the field's
        *type* to refuse it.
        """
        collector = _Collector("localhost")

        result = _app(NeedsNested, collector=collector).execute("report")

        assert result.status is RunStatus.FAILURE
        assert collector.requests == []

    def test_a_field_inside_a_sub_model_is_never_prompted(self) -> None:
        """`("db", "host")` is not a name the retry could pass back — the
        collected value would be silently dropped and the run would fail
        anyway."""
        collector = _Collector("localhost")

        result = _app(NeedsNested, collector=collector).execute("report", db={})

        assert result.status is RunStatus.FAILURE
        assert collector.requests == []

    def test_a_list_field_is_never_prompted(self) -> None:
        """Same reason as the sub-model, and the more common shape in practice
        (`tags: list[str]`)."""
        collector = _Collector("a,b")

        result = _app(NeedsTags, collector=collector).execute("report")

        assert result.status is RunStatus.FAILURE
        assert collector.requests == []


class TestWhatIsStillWorthAsking:
    """The filter refuses shapes a typed line cannot satisfy — and must not
    over-reach into the scalars that are the whole point of the feature."""

    def test_an_int_is_promptable_because_pydantic_coerces_it(self) -> None:
        collector = _Collector("7")

        result = _app(NeedsPositive, collector=collector).execute("report")

        assert result.status is RunStatus.SUCCESS
        assert "days=7" in str(result.return_value)

    def test_an_optional_field_is_promptable(self) -> None:
        """`str | None` is still answerable by typing a string; only the
        *wrapper* is optional, and Pydantic still reports it missing when it
        has no default."""
        collector = _Collector("Kyoto")

        result = _app(NeedsOptionalCity, collector=collector).execute("report")

        assert result.status is RunStatus.SUCCESS
        assert collector.requests != []


class TestDeclining:
    def test_an_empty_answer_ends_the_run(self) -> None:
        """Pressing enter did not supply the value. Proceeding would fail later
        and further from the cause; re-asking would trap the user in a prompt
        they cannot escape."""
        result = _app(collector=_Collector("")).execute("report")

        assert result.status is RunStatus.FAILURE
        assert isinstance(result.exception, MissingValueError)

    def test_the_user_is_asked_exactly_once(self) -> None:
        collector = _Collector("")

        _app(collector=collector).execute("report")

        assert len(collector.requests) == 1

    def test_an_answer_that_still_does_not_validate_is_not_re_asked(self) -> None:
        """One retry only. A second round would be an interrogation, and the
        field-level error is the more useful outcome."""
        collector = _Collector("not-a-number", "12")

        result = _app(NeedsPositive, collector=collector).execute("report")

        assert result.status is RunStatus.FAILURE
        assert len(collector.requests) == 1
