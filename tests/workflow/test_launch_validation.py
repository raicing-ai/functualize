"""A `@workflow` job refuses an unbindable launch argument before it walks.

A workflow's kwargs bind to its *epilogue*, which runs after the graph. So an
argument the function cannot accept used to run every step, block at the gate,
wait for a person to approve the release, and only then raise — spending the
approval on a run that could never have succeeded.

The assertion that matters is **not** that the call fails. Both the old and the
new behaviour return a status, so `status is FAILURE` alone would pass against
an implementation that ran the whole graph and failed afterwards. What separates
them is the state store: before the fix a nonsense kwarg wrote four step records
and published a gate. After it, nothing is written at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._primitives.state_store import StateStore
from functualize._types.enums import RunStatus

_JOBS = '''
from pydantic import BaseModel, Field

from functualize import workflow
from functualize.job import Log, job
from functualize.workflow import END, Edge, Gate, Step


class Approval(BaseModel):
    note: str = Field(description="why this is approved")


@job
def alpha(log: Log) -> str:
    log("alpha ran")
    return "a"


@job
def omega(log: Log) -> str:
    log("omega ran")
    return "z"


@workflow(
    steps=[Step(alpha), Gate(name="pause", awaits=Approval), Step(omega)],
    edges=[Edge("alpha", "pause"), Edge("pause", "omega"), Edge("omega", END)],
)
def walk(log: Log) -> str:
    """DI-only signature: every parameter here is filled by the engine."""
    log("walk complete")
    return "done"
'''


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A project with one gated walk, with the cwd pointed at it.

    The engine resolves its state store from the working directory, so the
    chdir is what makes `StateStore.for_project(tmp_path)` below read the same
    file the run wrote.
    """
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "w.py").write_text(_JOBS)
    monkeypatch.chdir(tmp_path)

    from functualize.app import FunctualizeApp, JobSources

    return FunctualizeApp("w", job_sources=JobSources(directories=["jobs"])), tmp_path


def _scope(root: Path, scope_id: str) -> dict:
    """The persisted scope record, or an empty one if nothing was written."""
    return StateStore.for_project(root).get_scope(scope_id) or {}


class TestTheGraphDoesNotRun:
    """A1 — the assertion a status check cannot make."""

    def test_a_refused_launch_writes_no_scope_state(
        self, project: tuple[object, Path]
    ) -> None:
        app, root = project

        result = app.execute("walk", scope_id="a1", zzz_nonsense=1)  # type: ignore[attr-defined]

        assert result.status is RunStatus.FAILURE

        scope = _scope(root, "a1")
        assert not scope.get("steps"), "a step ran; the graph was walked"
        assert not scope.get("gates"), "a gate was published; the walk reached it"
        assert scope.get("position") is None, "the walk recorded a position"

    def test_the_same_walk_does_reach_the_gate_when_launched_cleanly(
        self, project: tuple[object, Path]
    ) -> None:
        """The control for the test above.

        Without it, an implementation that refused *every* launch would satisfy
        A1 perfectly. This is the cell that says the fixture can actually walk.
        """
        app, root = project

        result = app.execute("walk", scope_id="control")  # type: ignore[attr-defined]

        assert result.status is RunStatus.BLOCKED
        scope = _scope(root, "control")
        assert scope.get("steps"), "the walk recorded no steps"
        assert "pause" in scope.get("gates", {})
        assert scope.get("position") == "pause"


class TestParityWithAPlainJob:
    """A2 — the two kinds of job answer the same way."""

    def test_workflow_and_plain_job_refuse_identically(
        self, project: tuple[object, Path]
    ) -> None:
        """Compared against each other, never against a frozen string.

        The wording comes from CPython, so pinning a literal here would be a
        second source of truth for it. If the message ever changes, both sides
        change together and this still means what it says.
        """
        app, _ = project

        from_workflow = app.execute("walk", scope_id="a2", zzz_nonsense=1)  # type: ignore[attr-defined]
        from_plain = app.execute("alpha", zzz_nonsense=1)  # type: ignore[attr-defined]

        assert from_workflow.status is from_plain.status is RunStatus.FAILURE
        assert type(from_workflow.exception) is type(from_plain.exception) is TypeError

        assert "walk()" in str(from_workflow.exception)
        assert "alpha()" in str(from_plain.exception)
        for result in (from_workflow, from_plain):
            assert "zzz_nonsense" in str(result.exception)

    def test_the_message_survives_a_warm_boot(
        self, project: tuple[object, Path]
    ) -> None:
        """RK3 — the function name is right on both the cold and warm paths.

        The message is built from `function.__name__`, and the engine reaches
        the function two ways: directly from the registry, or by materializing
        a lazy entry at invoke. A second app over the now-warm discovery cache
        takes the path the first did not.
        """
        _, root = project
        from functualize.app import FunctualizeApp, JobSources

        cold = FunctualizeApp("w", job_sources=JobSources(directories=["jobs"]))
        cold_error = cold.execute("walk", zzz_nonsense=1).exception

        warm = FunctualizeApp("w", job_sources=JobSources(directories=["jobs"]))
        warm_error = warm.execute("walk", zzz_nonsense=1).exception

        assert str(cold_error) == str(warm_error)
        assert "walk()" in str(warm_error)
        assert not _scope(root, "unused")

    def test_neither_raises(self, project: tuple[object, Path]) -> None:
        """The invariant the refusal shape exists to preserve.

        A refusal that escaped as an exception would reach the CLI as a raw
        traceback instead of a rendered failure panel — the reason config
        resolution was moved inside this handler in the first place.
        """
        app, _ = project

        for job_name in ("walk", "alpha"):
            result = app.execute(job_name, zzz_nonsense=1)  # type: ignore[attr-defined]
            assert result.exception is not None


class TestARefusedResumeDisturbsNothing:
    """A4 — the case where a human approval has already been spent."""

    def test_a_bad_kwarg_leaves_a_blocked_scope_byte_identical(
        self, project: tuple[object, Path]
    ) -> None:
        app, root = project
        store = StateStore.for_project(root)

        assert app.execute("walk", scope_id="a4").status is RunStatus.BLOCKED  # type: ignore[attr-defined]
        assert store.deposit_gate_payload("a4", "pause", {"note": "approved"})

        before = _scope(root, "a4")
        result = app.execute("walk", scope_id="a4", zzz_nonsense=1)  # type: ignore[attr-defined]
        after = _scope(root, "a4")

        assert result.status is RunStatus.FAILURE
        assert after == before, "a refused resume advanced the run"

    def test_the_scope_is_still_resumable_afterwards(
        self, project: tuple[object, Path]
    ) -> None:
        """The refusal must not have consumed the approval it declined to use."""
        app, root = project
        store = StateStore.for_project(root)

        app.execute("walk", scope_id="a4b")  # type: ignore[attr-defined]
        store.deposit_gate_payload("a4b", "pause", {"note": "approved"})
        app.execute("walk", scope_id="a4b", zzz_nonsense=1)  # type: ignore[attr-defined]

        resumed = app.execute("walk", scope_id="a4b")  # type: ignore[attr-defined]

        assert resumed.status is RunStatus.SUCCESS
        assert resumed.return_value == "done"


class TestVarKeywordIsHonoured:
    """A5 — Python's rule is the rule; only its timing changed."""

    def test_a_workflow_declaring_kwargs_accepts_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (jobs / "w.py").write_text(
            _JOBS.replace("def walk(log: Log)", "def walk(log: Log, **extra)")
        )
        monkeypatch.chdir(tmp_path)

        from functualize.app import FunctualizeApp, JobSources

        app = FunctualizeApp("w", job_sources=JobSources(directories=["jobs"]))
        result = app.execute("walk", scope_id="a5", anything_at_all=1)

        assert result.status is RunStatus.BLOCKED
        assert _scope(tmp_path, "a5").get("position") == "pause"


_NESTED = (
    _JOBS
    + '''

@workflow(
    steps=[Step("walk")],
    edges=[Edge("walk", END)],
)
def outer(log: Log) -> str:
    """A workflow whose only step is another workflow."""
    log("outer complete")
    return "outer done"
'''
)


class TestANestedWorkflowIsUnaffected:
    """RK4 — the check is a no-op for a workflow reached as a `Step`.

    `run_step` invokes a step with `kwargs={}`, so an inner workflow can never
    see a launch argument and can never be refused for one. Proven rather than
    reasoned: the risk was that refusing the outer launch would also break the
    inner walk's ability to block and resume.
    """

    @pytest.fixture
    def nested(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (jobs / "w.py").write_text(_NESTED)
        monkeypatch.chdir(tmp_path)

        from functualize.app import FunctualizeApp, JobSources

        return FunctualizeApp(
            "w", job_sources=JobSources(directories=["jobs"])
        ), tmp_path

    def test_the_outer_launch_is_still_refused(
        self, nested: tuple[object, Path]
    ) -> None:
        app, root = nested

        result = app.execute("outer", scope_id="rk4", zzz_nonsense=1)  # type: ignore[attr-defined]

        assert result.status is RunStatus.FAILURE
        assert not _scope(root, "rk4").get("steps")

    def test_a_clean_nested_walk_still_blocks_and_resumes(
        self, nested: tuple[object, Path]
    ) -> None:
        app, root = nested
        store = StateStore.for_project(root)

        assert app.execute("outer", scope_id="rk4b").status is RunStatus.BLOCKED  # type: ignore[attr-defined]

        # The inner workflow owns a derived scope, not the parent's (§A.7).
        inner = "rk4b::walk"
        assert store.deposit_gate_payload(inner, "pause", {"note": "ok"})

        resumed = app.execute("outer", scope_id="rk4b")  # type: ignore[attr-defined]

        assert resumed.status is RunStatus.SUCCESS
        assert resumed.return_value == "outer done"


class TestTheInMemoryScopeRegistry:
    """RK5 — what a refused launch leaves on the app object.

    `FunctualizeApp.execute` mints a `WorkflowScope` in its own registry
    *before* delegating to the engine, so a refusal cannot prevent that entry
    existing. The durable half — the state store — is untouched, which is what
    the contract promises and what A1 asserts. This cell pins the in-memory
    half so the asymmetry is documented rather than discovered.
    """

    def test_a_refused_launch_still_mints_an_in_memory_scope(
        self, project: tuple[object, Path]
    ) -> None:
        app, root = project

        app.execute("walk", scope_id="rk5", zzz_nonsense=1)  # type: ignore[attr-defined]

        registry = app._scope_registry  # type: ignore[attr-defined]
        assert "rk5" in registry, (
            "app.execute mints the scope before the engine is reached; "
            "if this ever stops being true, the contract note can be dropped"
        )
        assert not _scope(root, "rk5"), "the durable half must stay untouched"


_CONFIG_WORKFLOW = '''
from pydantic import BaseModel, Field

from functualize import workflow
from functualize.job import Log, job
from functualize.workflow import END, Edge, Gate, Step


class Cfg(BaseModel):
    city: str = Field(default="Tokyo", description="City to check")


class Approval(BaseModel):
    note: str = Field(description="why this is approved")


@job
def forecast(config: Cfg, log: Log) -> str:
    return f"{config.city}: sunny"


@workflow(
    steps=[Step(forecast), Gate(name="pause", awaits=Approval)],
    edges=[Edge("forecast", "pause"), Edge("pause", END)],
)
def trip(config: Cfg, log: Log) -> str:
    """A workflow whose launch arguments are config fields, not parameters."""
    return f"done: {config.city}"
'''


class TestConfigModelFieldsAreLegitimate:
    """The regression the full suite caught, and the feature's own gap.

    `--city Tokyo` reaches `execute()` as `city="Tokyo"`, and `city` is a
    parameter of *nothing*: `_resolve_config_model` pops each config field out
    of `call_kwargs` and replaces them with the built model. The first
    implementation of the launch check saw only the signature and refused the
    CLI's own spelling of a documented flag.

    Every A1-A5 fixture above declares a DI-only workflow with no config model,
    which is exactly why none of them could see this. The cells here are the
    shape those were missing.
    """

    @pytest.fixture
    def configured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (jobs / "w.py").write_text(_CONFIG_WORKFLOW)
        monkeypatch.chdir(tmp_path)

        from functualize.app import FunctualizeApp, JobSources

        return (
            FunctualizeApp("w", job_sources=JobSources(directories=["jobs"])),
            tmp_path,
        )

    def test_a_config_field_is_accepted_and_reaches_the_walk(
        self, configured: tuple[object, Path]
    ) -> None:
        app, root = configured

        result = app.execute("trip", scope_id="cfg", city="Kyoto")  # type: ignore[attr-defined]

        assert result.status is RunStatus.BLOCKED, (
            "a config field was refused as an unknown launch argument"
        )
        assert _scope(root, "cfg").get("position") == "pause"

    def test_an_unknown_name_is_still_refused(
        self, configured: tuple[object, Path]
    ) -> None:
        """The control: accepting config fields must not accept everything."""
        app, root = configured

        result = app.execute("trip", scope_id="cfg2", nonsense=1)  # type: ignore[attr-defined]

        assert result.status is RunStatus.FAILURE
        assert "nonsense" in str(result.exception)
        assert not _scope(root, "cfg2").get("steps")

    def test_the_plain_job_beneath_it_agrees(
        self, configured: tuple[object, Path]
    ) -> None:
        """A plain job sharing the config model answers the same way.

        Parity here is what says the launch check reproduced the existing rule
        rather than inventing a stricter one for workflows only.
        """
        app, _ = configured

        assert app.execute("forecast", city="Osaka").status is RunStatus.SUCCESS  # type: ignore[attr-defined]
        assert app.execute("forecast", nonsense=1).status is RunStatus.FAILURE  # type: ignore[attr-defined]
