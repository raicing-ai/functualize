"""Every feature, on both entry points — coverage §B's matrix as a suite.

The audit's coverage half is a 16 × 8 grid of *"does this feature work through
this door?"*, and it was a grid of prose. Prose does not fail. This file is the
grid as tests: sixteen rows, each run twice by the `cli_run` fixture — once
through the `func` console script's dispatch, once through a project's own
`main.py` under `CliAdapter`.

**Why a matrix rather than a convention.** The two doors build their command
trees from different places — click parameters from a live signature on a cold
boot, from a cached descriptor on a warm one — and `deliver_job_result`'s own
docstring records what it cost the last time only one of them handled a case:
*"Cold boot exited 1, warm boot exited 0, for the same job and the same
failure."* A convention that both doors "go through `RunRequest`" is exactly the
kind of claim that is true of the code someone last looked at. Sixteen rows that
run twice is the claim being checked.

**A row that cannot be expressed as a test is a row that was never true.** Two
resisted and neither is dropped silently — see `TestRowsThatNeededTheirOwnDoor`
at the foot of this file, which pins what each door actually does and says why
the two answers differ.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

#: `ExitCode`, restated as the numbers a *process* returns. Deliberately literal:
#: this file is about what a user's shell sees, and importing the enum would let
#: a renumbering pass silently.
_OK, _JOB_RAISED, _USAGE, _REFUSED, _STALE, _BLOCKED = 0, 1, 2, 3, 4, 5


def _tree(project_tree: Any, **jobs: str) -> Path:
    return project_tree(
        jobs={name + ".py": textwrap.dedent(src) for name, src in jobs.items()}
    )


def _scope_id_of(root: Path) -> str:
    """The one workflow scope this project has, read from its state store.

    Read rather than parsed out of the blocked run's output: the scope id is
    the walk's identity, and taking it from the store is taking it from the
    same place `resume` will look.
    """
    from functualize._primitives.state_store import StateStore

    store = StateStore.for_project(root / ".functualize")
    scope_ids = store.scope_ids()
    assert len(scope_ids) == 1, f"expected exactly one scope, got {scope_ids}"
    return scope_ids[0]


# ─── Rows 1-4: the `@job` declaration reaches the run ──────────────────────


class TestDepsRunFirst:
    """Row 1. A declared upstream runs before its dependent, on both doors."""

    _JOBS = {
        "pipeline": '''
            from functualize.job import Deps, job

            @job
            def upstream() -> str:
                """Run first."""
                print("UPSTREAM")
                return "up"

            @job(deps=Deps("upstream"))
            def downstream() -> str:
                """Run second."""
                print("DOWNSTREAM")
                return "down"
        ''',
    }

    def test_the_upstream_runs_and_runs_first(self, cli_run, project_tree) -> None:
        result = cli_run(["downstream"], cwd=_tree(project_tree, **self._JOBS))

        assert result.exit_code == _OK, result.stderr
        assert "UPSTREAM" in result.stdout, result.stdout
        assert result.stdout.index("UPSTREAM") < result.stdout.index("DOWNSTREAM")


class TestFingerprintFreshness:
    """Row 2. A second run of an unchanged job is skipped, on both doors."""

    _JOBS = {
        "build": '''
            from functualize.job import Fingerprint, job

            @job(cache=Fingerprint(sources=["input.txt"]))
            def build() -> str:
                """Rebuild."""
                print("BUILT")
                return "built"
        ''',
    }

    def test_the_second_run_is_skipped(self, cli_run, project_tree) -> None:
        root = _tree(project_tree, **self._JOBS)
        (root / "input.txt").write_text("x")

        first = cli_run(["build"], cwd=root)
        second = cli_run(["build"], cwd=root)

        assert first.exit_code == _OK, first.stderr
        assert "BUILT" in first.stdout
        assert second.exit_code == _OK, second.stderr
        assert "BUILT" not in second.stdout, f"the warm run rebuilt: {second.stdout}"


class TestGuardsRefuse:
    """Row 3. A failing precondition refuses with exit 3, on both doors."""

    _JOBS = {
        "guarded": '''
            from functualize.job import Guards, Precondition, job

            @job(guards=Guards(preconditions=[Precondition("exit 1", "always fails")]))
            def guarded() -> str:
                """Never reached."""
                print("RAN")
                return "ran"
        ''',
    }

    def test_it_refuses_rather_than_running(self, cli_run, project_tree) -> None:
        result = cli_run(["guarded"], cwd=_tree(project_tree, **self._JOBS))

        assert result.exit_code == _REFUSED, (result.exit_code, result.stderr)
        assert "RAN" not in result.stdout


class TestExecRetry:
    """Row 4. A declared retry actually retries, on both doors."""

    _JOBS = {
        "flaky": '''
            from pathlib import Path

            from functualize.job import Exec, Retry, job

            @job(exec=Exec(retry=Retry(attempts=3, backoff="constant")))
            def flaky() -> str:
                """Fail twice, then succeed."""
                counter = Path("attempts.txt")
                n = int(counter.read_text()) if counter.exists() else 0
                counter.write_text(str(n + 1))
                if n < 2:
                    raise RuntimeError(f"attempt {n}")
                print(f"SUCCEEDED_AFTER={n}")
                return "ok"
        ''',
    }

    def test_it_retries_to_success(self, cli_run, project_tree) -> None:
        result = cli_run(["flaky"], cwd=_tree(project_tree, **self._JOBS))

        assert result.exit_code == _OK, result.stderr
        assert "SUCCEEDED_AFTER=2" in result.stdout, result.stdout


# ─── Rows 5-8: the graph and its pauses ────────────────────────────────────


class TestGroupOptions:
    """Row 5. A group's mid-path flag reaches the job, on both doors.

    This is the row `surface-request-parity` exists for: the flags used to stop
    at the click boundary, so a run through any other door got the field's
    default and no error.
    """

    _JOBS = {
        "_group": '''
            from typing import Annotated

            from functualize.job import GroupOptions, Option

            class DeployOptions(GroupOptions, group="deploy"):
                """Deploy-level flags."""

                env: Annotated[str, Option("-e", help="Target environment")] = "staging"
        ''',
        "web": '''
            from _group import DeployOptions

            JOB_GROUP = "deploy"

            def web(opts: DeployOptions = None) -> str:
                """Deploy the web tier."""
                print(f"ENV={opts.env}")
                return "web"
        ''',
    }

    def test_the_flag_reaches_the_job(self, cli_run, project_tree) -> None:
        result = cli_run(
            ["deploy", "--env", "prod", "web"], cwd=_tree(project_tree, **self._JOBS)
        )

        assert result.exit_code == _OK, result.stderr
        assert "ENV=prod" in result.stdout, result.stdout

    def test_the_default_applies_when_the_flag_is_absent(
        self, cli_run, project_tree
    ) -> None:
        """The falsifier: a job that always printed the default would pass above."""
        result = cli_run(["deploy", "web"], cwd=_tree(project_tree, **self._JOBS))

        assert result.exit_code == _OK, result.stderr
        assert "ENV=staging" in result.stdout, result.stdout


class TestWorkflowAndGate:
    """Row 6. A `@workflow` whose graph reaches a `Gate` blocks with exit 5."""

    _JOBS = {
        "release": '''
            from pydantic import BaseModel

            from functualize.job import job
            from functualize.workflow import END, Edge, Gate, Step, workflow

            class Approval(BaseModel):
                approved: bool = True

            @job
            def prepare() -> str:
                """Prepare."""
                print("PREPARED")
                return "prepared"

            @workflow(
                steps=[Step(prepare), Gate("approve", awaits=Approval)],
                edges=[Edge("prepare", "approve"), Edge("approve", END)],
            )
            def release() -> str:
                """The epilogue."""
                print("RELEASED")
                return "released"
        ''',
    }

    def test_it_blocks_at_the_gate(self, cli_run, project_tree) -> None:
        result = cli_run(["release"], cwd=_tree(project_tree, **self._JOBS))

        assert result.exit_code == _BLOCKED, (result.exit_code, result.stderr)
        assert "PREPARED" in result.stdout, result.stdout
        assert "RELEASED" not in result.stdout, (
            "the epilogue ran despite the gate blocking"
        )


class TestCapabilityInjection:
    """Row 9. A declared capability is injected, on both doors."""

    _JOBS = {
        "report": '''
            from functualize.job import Log, RunContext, job

            @job
            def report(rc: RunContext, log: Log) -> str:
                """Read two capabilities."""
                print(f"NAME={rc.name}")
                print(f"HAS_LOG={log is not None}")
                return "reported"
        ''',
    }

    def test_both_capabilities_arrive(self, cli_run, project_tree) -> None:
        result = cli_run(["report"], cwd=_tree(project_tree, **self._JOBS))

        assert result.exit_code == _OK, result.stderr
        assert "NAME=report" in result.stdout, result.stdout
        assert "HAS_LOG=True" in result.stdout, result.stdout


class TestConfigPrecedence:
    """Row 10. A CLI flag beats a config file, on both doors."""

    _JOBS = {
        "serve": '''
            from pydantic import BaseModel

            from functualize.job import job

            class ServeConfig(BaseModel):
                port: int = 8000

            @job
            def serve(config: ServeConfig) -> str:
                """Print the resolved port."""
                print(f"PORT={config.port}")
                return "served"
        ''',
    }

    def test_the_flag_beats_the_file(self, cli_run, project_tree) -> None:
        # `config.<env>.<ext>` is the default file pattern
        # (`ConfigSources.file_pattern`), and DEV is the default environment.
        # `.functualize.toml` is the *CLI tool's* config, not a job's — an easy
        # confusion, and the reason this row asserts the value came from the
        # file before asserting the flag beats it.
        root = project_tree(
            jobs={"serve.py": textwrap.dedent(self._JOBS["serve"])},
            extra_files={"config.dev.toml": "[serve]\nport = 9000\n"},
        )

        from_file = cli_run(["serve"], cwd=root)
        from_flag = cli_run(["serve", "--port", "9999"], cwd=root)

        assert from_file.exit_code == _OK, from_file.stderr
        assert "PORT=9000" in from_file.stdout, from_file.stdout
        assert from_flag.exit_code == _OK, from_flag.stderr
        assert "PORT=9999" in from_flag.stdout, from_flag.stdout


# ─── Rows 11-16: delivery, routing and diagnosis ───────────────────────────


class TestForceOverridesFreshness:
    """Row 11. `--force` runs a job the fingerprint would have skipped."""

    def test_it_runs_anyway(self, cli_run, project_tree) -> None:
        root = _tree(project_tree, **TestFingerprintFreshness._JOBS)
        (root / "input.txt").write_text("x")

        cli_run(["build"], cwd=root)
        skipped = cli_run(["build"], cwd=root)
        forced = cli_run(["--force", "build"], cwd=root)

        assert "BUILT" not in skipped.stdout, "the warm run should have skipped"
        assert forced.exit_code == _OK, forced.stderr
        assert "BUILT" in forced.stdout, forced.stdout


class TestEmitFormat:
    """Row 12. `--emit-format` selects how `out.emit()` is rendered.

    The task file calls this row `--output`; the flag was renamed to
    `--emit-format` this branch, because it governs `out.emit()` and nothing
    else while `--output` reads as a destination.
    """

    _JOBS = {
        "emitter": '''
            from functualize.job import Stdout, job

            @job
            def emitter(out: Stdout) -> None:
                """Emit a value."""
                out.emit({"from": "emit"})
        ''',
    }

    def test_json_renders_the_emitted_value(self, cli_run, project_tree) -> None:
        result = cli_run(
            ["--emit-format", "json", "emitter"], cwd=_tree(project_tree, **self._JOBS)
        )

        assert result.exit_code == _OK, result.stderr
        assert '"from":"emit"' in result.stdout.replace(" ", ""), result.stdout

    def test_none_suppresses_it(self, cli_run, project_tree) -> None:
        result = cli_run(
            ["--emit-format", "none", "emitter"], cwd=_tree(project_tree, **self._JOBS)
        )

        assert result.exit_code == _OK, result.stderr
        assert "from" not in result.stdout, result.stdout


class TestTheExitCodeContract:
    """Row 13. One status, one number — the same number on both doors."""

    _JOBS = {
        "outcomes": '''
            from functualize.job import Guards, Precondition, job

            @job
            def succeeds() -> str:
                """Exit 0."""
                return "ok"

            @job
            def raises() -> str:
                """Exit 1."""
                raise RuntimeError("boom")

            @job(guards=Guards(preconditions=[Precondition("exit 1", "no")]))
            def refused() -> str:
                """Exit 3."""
                return "never"
        ''',
    }

    @pytest.mark.parametrize(
        ("job_name", "expected"),
        [("succeeds", _OK), ("raises", _JOB_RAISED), ("refused", _REFUSED)],
    )
    def test_the_number_is_the_same_on_both_doors(
        self, job_name: str, expected: int, cli_run, project_tree
    ) -> None:
        result = cli_run([job_name], cwd=_tree(project_tree, **self._JOBS))

        assert result.exit_code == expected, (result.exit_code, result.stderr)


class TestDiscoveryFilters:
    """Row 15. A configured discovery filter hides a job — on `func`.

    **This row does not hold on both doors, and that is the boundary rather
    than a defect.** `[discovery] exclude_patterns` and `--exclude` are the bare
    `func` CLI's filters: it resolves them from the project's config and hands
    them to the app it builds. An embedded `main.py` constructs its own
    `FunctualizeApp` and declares `discovery_config=` itself — reading the file
    behind its back would mean a project's config silently overriding what the
    author wrote in code.

    `tests/discovery/test_cache_filter_awareness.py` records the same scoping
    ("`--exclude` is a pre-command global flag of the bare `func` CLI"). The
    matrix repeats it because a row missing from the matrix reads as a row
    nobody checked, and `TestRowsThatNeededTheirOwnDoor` asserts what the *app*
    surface does instead — so both halves are pinned rather than one being a
    silent absence.
    """

    pytestmark = pytest.mark.surfaces("func")

    def test_an_excluded_module_defines_no_command(self, cli_run, project_tree) -> None:
        root = project_tree(
            jobs={
                "kept.py": 'def kept() -> str:\n    """Kept."""\n    return "kept"\n',
                "hidden.py": 'def hidden() -> str:\n    """Hidden."""\n    return "h"\n',
            },
            functualize_toml='[discovery]\nexclude_patterns = ["hidden.py"]\n',
        )

        kept = cli_run(["kept"], cwd=root)
        hidden = cli_run(["hidden"], cwd=root)

        assert kept.exit_code == _OK, kept.stderr
        assert hidden.exit_code != _OK, (
            f"an excluded module still defined a command: {hidden.stdout}"
        )


class TestTheUnknownCommandExplainsItself:
    """Row 16. A typo is explained the same way on both doors.

    Already true, and asserted here as a *row* rather than only in
    `tests/cli/`: this file is where someone looks to ask "does the matrix
    hold", and a row missing from it reads as a row nobody checked.
    """

    def test_a_typo_is_reported_and_exits_one(self, cli_run, project_tree) -> None:
        root = project_tree(
            jobs={"greet.py": 'def greet() -> str:\n    """Hi."""\n    return "hi"\n'}
        )

        result = cli_run(["typoo"], cwd=root)

        combined = result.stdout + result.stderr
        assert result.exit_code == _JOB_RAISED, (result.exit_code, combined)
        assert "Unknown command 'typoo'" in combined, combined


# ─── Rows 7, 8, 14 ─────────────────────────────────────────────────────────


class TestGateResume:
    """Row 7. A blocked walk resumes and finishes, on both doors.

    The pair with row 6: blocking is only half a gate. A walk that cannot be
    resumed through the door it blocked on is a workflow that ran once.
    """

    def test_a_blocked_walk_resumes_to_completion(self, cli_run, project_tree) -> None:
        root = _tree(project_tree, **TestWorkflowAndGate._JOBS)

        blocked = cli_run(["release"], cwd=root)
        assert blocked.exit_code == _BLOCKED, blocked.stderr

        scope = _scope_id_of(root)
        resumed = cli_run(
            ["builtin", "workflow", "resume", scope, "--input", '{"approved": true}'],
            cwd=root,
        )

        combined = resumed.stdout + resumed.stderr
        assert resumed.exit_code == _OK, (resumed.exit_code, combined)
        assert "RELEASED" in combined, combined


class TestPromptGates:
    """Row 8. `--prompt-gates` is accepted and forwarded, on both doors.

    Narrow on purpose: whether a prompt *renders* needs a tty, and asserting it
    here would make this a test of the harness. What the matrix owns is that the
    flag exists on both doors and reaches the walk — the half that was missing
    on the `app` surface until `run-request-entry`/T13 (audit D-1).
    """

    def test_the_flag_is_accepted_on_both_doors(self, cli_run, project_tree) -> None:
        root = _tree(project_tree, **TestWorkflowAndGate._JOBS)

        result = cli_run(["--prompt-gates", "release"], cwd=root)

        combined = result.stdout + result.stderr
        assert "No such option" not in combined, combined
        assert "PREPARED" in result.stdout, result.stdout


class TestAliases:
    """Row 14. A configured alias resolves to its job — on `func`.

    **The second row that does not hold on both doors.** Aliases are resolved in
    `_cli/dispatch.detect_mode`, the bare CLI's *pre-boot* routing: it reads
    `[aliases]` from the merged config and rewrites the first positional before
    anything is built. An embedded `main.py` never runs that routing — click
    resolves its own command tree — so `main.py g` reports an unknown command
    and suggests `greet`.

    Unlike row 15 this one is **not** obviously deliberate. Nothing in the code
    states the scoping, and `docs/cli/aliases.md` documents the feature entirely
    in terms of `func` without saying an app's own entry point lacks it. It is
    recorded as a finding in `.spec/STATUS.md` rather than dropped, which is
    what this feature's brief asks for; `TestRowsThatNeededTheirOwnDoor` pins
    what the app surface does today so the finding cannot rot into a surprise.
    """

    pytestmark = pytest.mark.surfaces("func")

    def test_the_alias_runs_the_job(self, cli_run, project_tree) -> None:
        root = project_tree(
            jobs={
                "greet.py": (
                    "def greet() -> str:\n"
                    '    """Hi."""\n'
                    '    print("GREETED")\n'
                    '    return "hi"\n'
                )
            },
            functualize_toml='[aliases]\ng = "greet"\n',
        )

        result = cli_run(["g"], cwd=root)

        assert result.exit_code == _OK, result.stderr
        assert "GREETED" in result.stdout, result.stdout


# ─── The rows that are not the same on both doors ─────────────────────────


class TestRowsThatNeededTheirOwnDoor:
    """Where the two surfaces differ, what each one does — asserted, not noted.

    The task this file implements says a row that cannot be expressed as a test
    is a row that was never true, and that any row which resists is recorded
    rather than quietly dropped. One resisted. It is not a gap in `RunRequest` —
    it is a boundary that exists on purpose, and the way to keep a deliberate
    boundary deliberate is to assert both sides of it.
    """

    def test_an_embedded_app_honours_the_config_it_was_given(
        self, tmp_path: Path
    ) -> None:
        """Row 15, the app half: an app filters by what its author declared.

        Not by what a TOML in the working directory says. `func` reads
        `[discovery]` and passes it in; an embedded app is handed one, and a
        file quietly overriding the author's code would be the surprise.
        """
        from functualize.app import DiscoveryConfig, FunctualizeApp
        from functualize.app.config import JobSources

        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (jobs / "kept.py").write_text(
            'def kept() -> str:\n    """Kept."""\n    return "kept"\n'
        )
        (jobs / "hidden.py").write_text(
            'def hidden() -> str:\n    """Hidden."""\n    return "h"\n'
        )

        unfiltered = FunctualizeApp(
            "unfiltered", job_sources=JobSources(directories=[str(jobs)])
        )
        filtered = FunctualizeApp(
            "filtered",
            job_sources=JobSources(directories=[str(jobs)]),
            discovery_config=DiscoveryConfig(exclude_patterns=("hidden.py",)),
        )

        assert {j.name for j in unfiltered.get_jobs()} == {"kept", "hidden"}
        assert {j.name for j in filtered.get_jobs()} == {"kept"}, (
            "the app ignored the DiscoveryConfig it was constructed with"
        )

    @pytest.mark.surfaces("app")
    def test_an_alias_is_not_resolved_on_an_apps_own_entry_point(
        self, cli_run, project_tree
    ) -> None:
        """Row 14, the app half — today's behaviour, pinned as a finding.

        Aliases live in `_cli/dispatch.detect_mode`, which rewrites the first
        positional *before* anything is built. An embedded app never runs that
        routing, so a configured alias is an unknown command with a suggestion.

        Asserted rather than left as prose because this is the one divergence
        the matrix found that nothing had declared deliberate (`.spec/STATUS.md`
        #40). If it is closed, this test fails and points at the finding —
        which is the right way for a recorded gap to be retired.
        """
        root = project_tree(
            jobs={
                "greet.py": (
                    "def greet() -> str:\n"
                    '    """Hi."""\n'
                    '    print("GREETED")\n'
                    '    return "hi"\n'
                )
            },
            functualize_toml='[aliases]\ng = "greet"\n',
        )

        result = cli_run(["g"], cwd=root)

        combined = result.stdout + result.stderr
        assert result.exit_code != _OK, combined
        assert "Unknown command 'g'" in combined, combined
        assert "greet" in combined, "the suggestion should still name the job"
