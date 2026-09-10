"""A job reads the freshness verdict its own ``Fingerprint`` produced.

The risk this file exists for is not "does ``Freshness`` compute the right
thing" — it computes nothing; the pre-flight already decided and this capability
only hands the decision over. The risk is **"does the value ever arrive"**. DI
resolution runs *before* the pre-flight, so the instance is injected empty and
completed afterwards, and dropping that completion gives every job ``None`` with
no error anywhere — the "resolves and does nothing" failure
``contributor/guides/wiring-discipline.md`` exists for.

So the cold path and the warm path are both asserted through the public entry
point, and the wave that gives the capability a value carries a sabotage check
that breaks the completion on purpose.
"""

from __future__ import annotations

import hashlib
import textwrap
from collections.abc import Generator
from pathlib import Path

import pytest

from functualize._app.state import AppState
from functualize._engine.guards import GuardState
from functualize.app.core import FunctualizeApp, request_for
from functualize.job import (
    Fingerprint,
    Freshness,
    FreshnessVerdict,
    Guards,
    Log,
    Precondition,
    RunStatus,
    job,
)
from functualize.types import RunRequest


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    """A throwaway project with a state store, like any real one.

    The pre-flight reads its records from ``.functualize/``, so a project
    without one is the degenerate case — every run cold, nothing to compare
    against. The warm path needs the directory to exist.
    """
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


def _app(**jobs: object) -> FunctualizeApp:
    app = FunctualizeApp(name="freshness")
    for name, fn in jobs.items():
        app.register_dynamic_job(name, fn)
    return app


def test_a_job_receives_the_capability_and_reports_no_verdict() -> None:
    """Injected, and honest about having nothing to report.

    This job declares no ``Fingerprint``, so the pre-flight made no decision and
    there is no verdict to hand over. A fabricated one would be a lie the job
    could act on.
    """
    seen: list[Freshness] = []

    @job
    def plain(fresh: Freshness) -> str:
        seen.append(fresh)
        return "ok"

    result = _app(plain=plain).execute(request_for("plain"))

    assert result.status is RunStatus.SUCCESS, result.exception
    assert len(seen) == 1
    assert isinstance(seen[0], Freshness)
    assert seen[0].verdict() is None


def test_the_capability_is_not_a_published_job_argument() -> None:
    """A capability must never surface as an argument a caller can pass.

    It becomes a CLI flag when the name is missing from the injected-name set —
    the defect that published ``SOURCES``, and ``SH`` before it, on every
    descriptor-driven surface. The name set and the registry are held together
    at import by an invariant, and this is the behaviour that invariant exists
    for.
    """

    @job
    def published(fresh: Freshness, log: Log, real: int = 1) -> None:
        log("hi")

    app = _app(published=published)
    descriptor = next(d for d in app.get_jobs() if d.name == "published")

    assert [p.name for p in descriptor.parameters] == ["real"]


def test_the_verdict_is_populated_on_the_cold_path() -> None:
    """No record yet: the engine decided RUN, and the body reads that."""
    Path("input.txt").write_text("v1")
    seen: list[FreshnessVerdict | None] = []

    @job(cache=Fingerprint(sources=["input.txt"], generates=["out.txt"]))
    def build(fresh: Freshness) -> str:
        seen.append(fresh.verdict())
        return "built"

    result = _app(build=build).execute(request_for("build"))

    assert result.status is RunStatus.SUCCESS, result.exception
    assert len(seen) == 1, "the body must have run"
    verdict = seen[0]
    assert verdict is not None, "the verdict never arrived — the bind is unwired"
    assert verdict.state is GuardState.RUN
    assert verdict.key.startswith("build::")
    assert verdict.declared_sources == ("input.txt",)
    assert verdict.declared_generates == ("out.txt",)
    assert verdict.recorded_value is None
    assert (
        verdict.source_map["input.txt"]["sha256"] == hashlib.sha256(b"v1").hexdigest()
    )


def test_the_verdict_is_populated_on_the_warm_path() -> None:
    """A record exists, so the pre-flight reads one and skips on it.

    The body is entered with ``force`` — the pre-existing way a fresh verdict
    still reaches a body (a ``force_fresh`` dependent does the same thing) —
    which is exactly why the completion happens *before* that override in the
    lifecycle. Move it after, and a job gets an empty capability on precisely
    the runs that were rescued from the skip.
    """
    Path("input.txt").write_text("v1")
    seen: list[FreshnessVerdict | None] = []

    @job(cache=Fingerprint(sources=["input.txt"]))
    def build(fresh: Freshness) -> str:
        seen.append(fresh.verdict())
        return "built"

    app = _app(build=build)
    cold = app.execute(request_for("build"))
    assert cold.status is RunStatus.SUCCESS, cold.exception
    assert len(seen) == 1, "setup: the cold run entered the body"

    seen.clear()
    # `force` is a control input, not a job argument: `request_for`'s keywords
    # become arguments, so a caller meaning the override says so on a request.
    forced = app.execute(
        RunRequest(job_name="build", surface="app.execute", force=True)
    )

    assert forced.status is RunStatus.SUCCESS, forced.exception
    assert len(seen) == 1, "setup: the forced run must enter the body"
    verdict = seen[0]
    assert verdict is not None, "the verdict never arrived — the bind is unwired"
    assert verdict.state is GuardState.SKIP_FRESH
    assert verdict.is_fresh is True
    assert verdict.recorded_value == "built", "the previous run's value is missing"
    assert verdict.declared_sources == ("input.txt",)


def test_the_reading_changes_when_the_decision_changes() -> None:
    """The verdict is the engine's, not a second opinion (AC-6).

    One job, one declaration, one source edited between runs: the same key, and
    a map that follows the file. A capability that worked freshness out for
    itself could pass the first two runs and still disagree here.
    """
    Path("input.txt").write_text("v1")
    seen: list[FreshnessVerdict | None] = []

    @job(cache=Fingerprint(sources=["input.txt"]))
    def build(fresh: Freshness) -> str:
        seen.append(fresh.verdict())
        return "built"

    app = _app(build=build)
    app.execute(request_for("build"))
    first = seen[-1]
    Path("input.txt").write_text("v2, and longer than before")
    app.execute(request_for("build"))
    second = seen[-1]

    assert first is not None and second is not None
    assert first.key == second.key, "one declaration, one fingerprint key"
    assert (
        first.source_map["input.txt"]["sha256"]
        != second.source_map["input.txt"]["sha256"]
    ), "the job read a stale view of the file its own declaration names"
    assert (
        first.source_map["input.txt"]["size"] != second.source_map["input.txt"]["size"]
    )


def test_the_source_map_is_the_decisions_own_object() -> None:
    """Not recomputed, and not copied — the documented contract.

    A defensive ``dict(...)`` here would double the memory of a map holding
    every input a job declared, for a value nobody mutates.
    """
    from functualize._engine.capabilities.freshness import _bind_from_preflight
    from functualize._engine.guards import GuardVerdict
    from functualize._engine.preflight import PreflightDecision

    decision = PreflightDecision(
        GuardVerdict(GuardState.SKIP_FRESH, "up to date"),
        "build::hash::checksum",
        "recorded",
        # This decision stands for a job that declared a `Fingerprint`; a
        # hand-built one has to say so, because the flag is what tells a real
        # freshness verdict from a guard pipeline's answer (jof S4).
        has_fingerprint=True,
        source_map={"input.txt": {"mtime": 1.0, "size": 6, "sha256": "abc"}},
        declared_sources=["input.txt"],
        declared_generates=["out.txt"],
    )
    instance = Freshness()

    _bind_from_preflight(instance, decision)

    verdict = instance.verdict()
    assert verdict is not None
    assert verdict.source_map is decision.source_map
    assert verdict.key == decision.key
    assert verdict.recorded_value == "recorded"
    assert verdict.is_fresh is True


def test_is_fresh_is_only_the_fresh_state() -> None:
    """A satisfied `status` guard is a different claim, and stays distinct.

    ``SKIP_SATISFIED`` means "your own external check says already done" — it
    says nothing about whether the artifact this job exists to produce is on
    disk. A job branching on ``is_fresh`` to reuse its artifact must not be told
    yes by it.
    """
    for state, expected in (
        (GuardState.SKIP_FRESH, True),
        (GuardState.SKIP_SATISFIED, False),
        (GuardState.RUN, False),
    ):
        assert (
            FreshnessVerdict(
                state=state,
                key="k",
                recorded_value=None,
                declared_sources=(),
                declared_generates=(),
                source_map={},
            ).is_fresh
            is expected
        )


class TestTheDocstringExampleRuns:
    """The snippet on `functualize.job.Freshness` is executed, not just read.

    It was wrong: it omitted `decides=True`, so the engine skipped the job
    before the body ran and the `is_fresh` branch it demonstrates was dead
    code. A user copying it got a silent skip — the exact misconception this
    capability was built to remove, reproduced in its own API documentation,
    with nothing to catch it (jof S1).

    So the docstring is now the fixture: the snippet is lifted out of it and
    run. Rewriting the example into something that does not work fails here,
    which is the only durable way an example stays true.
    """

    @staticmethod
    def _snippet() -> str:
        """The indented code block from `Freshness.__doc__`."""
        doc = Freshness.__doc__ or ""
        _, _, after = doc.partition("like every other capability::")
        block, _, _ = after.partition("\n\n``decides=True``")
        return textwrap.dedent(block).strip()

    def test_the_snippet_is_findable(self) -> None:
        """The falsifier for the two tests below.

        If the docstring is reworded so the extractor finds nothing, both of
        them would pass over an empty string and assert about nothing.
        """
        snippet = self._snippet()

        assert snippet.startswith("@job(")
        assert "def build(fresh: Freshness)" in snippet

    def test_the_snippet_takes_the_decision_back(self) -> None:
        """Without `decides=True` the branch below cannot be reached at all."""
        assert "decides=True" in self._snippet()

    def test_the_branch_the_snippet_demonstrates_is_reachable(self) -> None:
        """Run it. Two runs: the first rebuilds, the second takes the branch.

        This is the assertion the review's repro made and got `is_fresh=False`
        on the only verdict the body ever saw, because the body ran once.
        """
        Path("src").mkdir()
        Path("src/a.py").write_text("x")

        namespace: dict[str, object] = {
            "job": job,
            "Fingerprint": Fingerprint,
            "Freshness": Freshness,
            "rebuild": lambda: "rebuilt",
        }
        exec(self._snippet(), namespace)  # noqa: S102 - the docstring is the fixture
        app = _app(build=namespace["build"])

        first = app.execute(request_for("build"))
        second = app.execute(request_for("build"))

        assert first.status is RunStatus.SUCCESS, first.exception
        assert first.return_value == "rebuilt", (
            "the first run should reach `rebuild()` — nothing has been built yet"
        )
        assert second.status is RunStatus.SUCCESS, second.exception
        assert second.return_value == "artifact already current", (
            f"the second run returned {second.return_value!r} with status "
            f"{second.status.value}; the snippet's `is_fresh` branch is still "
            f"unreachable, which is the defect jof S1 found"
        )


class TestAskingNothingIsNotAnswerRun:
    """`verdict()` returns None when the job declared no `Fingerprint` — the
    contract the module's own docstring, `docs/guides/task-runner.md` and the
    capabilities skill reference all state.

    It was false for a job declaring `Guards` and no `cache`. A pre-flight
    decision exists for *any* declaration carrying guards or platforms, and
    `_bind` copied `decision.verdict.state` unconditionally, so such a job was
    handed a verdict reading "state=RUN, sources=()" — "asked nothing about
    freshness, answered RUN". `_bind_from_preflight`'s docstring had always
    forbidden exactly that conflation; nothing enforced it (jof S4).

    The impact was bounded — `is_fresh` needs `SKIP_FRESH`, which needs a
    fingerprint, so it was always `False` — but a job branching on
    `verdict is None`, or on `state is RUN`, was told something untrue.
    """

    def test_a_guarded_job_with_no_fingerprint_gets_no_verdict(self) -> None:
        seen: list[FreshnessVerdict | None] = []

        @job(guards=Guards(preconditions=[Precondition("exit 0")]))
        def guarded(fresh: Freshness) -> str:
            seen.append(fresh.verdict())
            return "ran"

        app = _app(guarded=guarded)

        result = app.execute(request_for("guarded"))

        assert result.status is RunStatus.SUCCESS, result.exception
        assert seen == [None], (
            f"a job that declared no Fingerprint was handed {seen[0]!r}; the "
            f"state on it comes from the guard pipeline, not from a freshness "
            f"decision"
        )

    def test_a_fingerprinted_job_still_gets_one(self) -> None:
        """The falsifier. Returning None unconditionally would pass the test
        above and delete the capability."""
        Path("src").mkdir()
        Path("src/a.py").write_text("x")
        seen: list[FreshnessVerdict | None] = []

        @job(cache=Fingerprint(sources=["src/**/*.py"], decides=True))
        def build(fresh: Freshness) -> str:
            seen.append(fresh.verdict())
            return "built"

        app = _app(build=build)

        result = app.execute(request_for("build"))

        assert result.status is RunStatus.SUCCESS, result.exception
        assert seen[0] is not None
        assert seen[0].declared_sources == ("src/**/*.py",)

    def test_both_guards_and_a_fingerprint_still_reports(self) -> None:
        """Declaring guards does not take the verdict away from a job that also
        declared a `Fingerprint` — the flag is about the declaration, not about
        which pipeline produced the state."""
        Path("src").mkdir()
        Path("src/a.py").write_text("x")
        seen: list[FreshnessVerdict | None] = []

        @job(
            cache=Fingerprint(sources=["src/**/*.py"], decides=True),
            guards=Guards(preconditions=[Precondition("exit 0")]),
        )
        def both(fresh: Freshness) -> str:
            seen.append(fresh.verdict())
            return "built"

        app = _app(both=both)

        result = app.execute(request_for("both"))

        assert result.status is RunStatus.SUCCESS, result.exception
        assert seen[0] is not None
