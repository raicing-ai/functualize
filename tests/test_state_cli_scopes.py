"""`func builtin state` and `builtin workflow` across the two-store split.

`show` and `clear` are tested in one file on purpose. `contributor/reference/
pitfalls.md` §5 records that this codebase once shipped two persisted stores
whose `show` and `clear` could report contradictory answers; keeping the pair's
tests together is the guardrail against repeating it, so neither is edited
without the other in view.
"""

from __future__ import annotations

import json

import pytest

from functualize._primitives.scope_format import SCOPES_FILENAME
from functualize._primitives.state_format import STATE_FILENAME


@pytest.fixture
def project(tmp_path):
    """A declared project with one blocked run and one fingerprint."""
    (tmp_path / ".functualize").mkdir()
    (tmp_path / ".functualize" / STATE_FILENAME).write_text(
        json.dumps(
            {
                "format_version": 1,
                "fingerprints": {"build::h::checksum": {"n": 1}},
                "history": [],
                "session": {"preconditions": {}},
            }
        )
    )
    (tmp_path / ".functualize" / SCOPES_FILENAME).write_text(
        json.dumps(
            {
                "format_version": 1,
                "scopes": {
                    "rel-1": {
                        "workflow": "release",
                        "status": "blocked",
                        "steps": {},
                        "branches": {},
                        "gates": {"approve": {"payload": {"by": "sam"}}},
                        "position": "approve",
                        "epilogue": None,
                        "tool_calls": [],
                    }
                },
            }
        )
    )
    return tmp_path


def _poison(root, *, version=99, scopes=None):
    """Make the scope store unreadable, with a secret planted in it."""
    (root / ".functualize" / SCOPES_FILENAME).write_text(
        json.dumps(
            {
                "format_version": version,
                "scopes": scopes
                or {
                    "rel-1": {"gates": {"approve": {"payload": "hunter2-SECRET"}}},
                    "rel-2": {},
                },
            }
        )
    )


class TestClearKeepsRuns:
    """AC-7, AC-8. Clearing stale fingerprints used to destroy every blocked
    run, under help text naming only "fingerprints, history"."""

    def test_clear_keeps_scopes_and_says_so(self, cli_run, project) -> None:
        result = cli_run(["builtin", "state", "clear"], cwd=project)
        assert result.exit_code == 0
        assert "Cleared fingerprints, history and session state." in result.stdout
        assert "Kept 1 workflow scope" in result.stdout
        assert "--scopes" in result.stdout

    def test_the_blocked_run_is_still_there_afterwards(self, cli_run, project) -> None:
        cli_run(["builtin", "state", "clear"], cwd=project)
        listed = cli_run(["builtin", "workflow", "list"], cwd=project)
        assert "rel-1" in listed.stdout

    def test_the_recorded_gate_payload_survives(self, cli_run, project) -> None:
        cli_run(["builtin", "state", "clear"], cwd=project)
        raw = json.loads((project / ".functualize" / SCOPES_FILENAME).read_text())
        assert raw["scopes"]["rel-1"]["gates"]["approve"]["payload"] == {"by": "sam"}

    def test_derived_state_really_is_cleared(self, cli_run, project) -> None:
        cli_run(["builtin", "state", "clear"], cwd=project)
        raw = json.loads((project / ".functualize" / STATE_FILENAME).read_text())
        assert raw["fingerprints"] == {}

    def test_singular_and_plural_are_both_right(self, cli_run, project) -> None:
        raw = json.loads((project / ".functualize" / SCOPES_FILENAME).read_text())
        raw["scopes"]["rel-2"] = dict(raw["scopes"]["rel-1"])
        (project / ".functualize" / SCOPES_FILENAME).write_text(json.dumps(raw))
        result = cli_run(["builtin", "state", "clear"], cwd=project)
        assert "Kept 2 workflow scopes" in result.stdout


class TestClearWithScopes:
    """AC-9. The deliberate discard, and it stays recoverable."""

    def test_scopes_flag_clears_them_and_reports_where_they_went(
        self, cli_run, project
    ) -> None:
        result = cli_run(["builtin", "state", "clear", "--scopes"], cwd=project)
        assert result.exit_code == 0
        assert "Cleared 1 workflow scope" in result.stdout
        assert "Moved aside to:" in result.stdout

    def test_a_discarded_run_is_moved_aside_not_deleted(self, cli_run, project) -> None:
        cli_run(["builtin", "state", "clear", "--scopes"], cwd=project)
        backup = project / ".functualize" / (SCOPES_FILENAME + ".bak")
        assert backup.exists()
        raw = json.loads(backup.read_text())
        assert raw["scopes"]["rel-1"]["gates"]["approve"]["payload"] == {"by": "sam"}

    def test_afterwards_there_are_no_scopes(self, cli_run, project) -> None:
        cli_run(["builtin", "state", "clear", "--scopes"], cwd=project)
        shown = cli_run(["builtin", "state", "show"], cwd=project)
        assert "Scopes: 0" in shown.stdout


class TestHelpNamesWhatItTouches:
    """AC-10. The help text is the whole reason the old behaviour was a trap."""

    def test_group_help_names_scopes(self, cli_run, project) -> None:
        result = cli_run(["builtin", "state", "--help"], cwd=project)
        assert "workflow scopes" in result.stdout

    def test_clear_help_names_the_scopes_flag(self, cli_run, project) -> None:
        result = cli_run(["builtin", "state", "clear", "--help"], cwd=project)
        assert "--scopes" in result.stdout
        assert "kept unless --scopes" in result.stdout.replace("\n", " ")


class TestShowReportsBothStores:
    """AC-11."""

    def test_show_reports_the_scope_path_and_version(self, cli_run, project) -> None:
        result = cli_run(["builtin", "state", "show"], cwd=project)
        assert result.exit_code == 0
        assert SCOPES_FILENAME in result.stdout
        assert "Scopes format: v" in result.stdout
        assert "Scopes: 1" in result.stdout

    def test_info_reports_the_scope_path_too(self, cli_run, project) -> None:
        result = cli_run(["builtin", "info"], cwd=project)
        assert SCOPES_FILENAME in result.stdout


class TestUnreadableStoreRefuses:
    """AC-4, AC-6. Never an empty list and exit 0."""

    def test_workflow_list_refuses_with_exit_2(self, cli_run, project) -> None:
        _poison(project)
        result = cli_run(["builtin", "workflow", "list"], cwd=project)
        assert result.exit_code == 2
        assert "cannot be read" in result.stderr
        assert "2 workflow scopes" in result.stderr

    def test_the_refusal_leaks_no_payload(self, cli_run, project) -> None:
        _poison(project)
        result = cli_run(["builtin", "workflow", "list"], cwd=project)
        assert "hunter2-SECRET" not in result.stderr
        assert "hunter2-SECRET" not in result.stdout

    def test_the_refusal_names_the_escape_hatch(self, cli_run, project) -> None:
        _poison(project)
        result = cli_run(["builtin", "workflow", "list"], cwd=project)
        assert "func builtin state clear --scopes" in result.stderr

    @pytest.mark.parametrize(
        "argv",
        [
            ["builtin", "workflow", "list"],
            ["builtin", "workflow", "state", "rel-1"],
            ["builtin", "workflow", "cancel", "rel-1"],
        ],
    )
    def test_every_workflow_subcommand_refuses_identically(
        self, cli_run, project, argv
    ) -> None:
        """One helper, so four subcommands cannot form four opinions."""
        _poison(project)
        assert cli_run(argv, cwd=project).exit_code == 2

    def test_refusing_is_repeatable_and_leaves_the_file(self, cli_run, project) -> None:
        """If the read moved the file aside, run two would find nothing, read
        it as "no scopes", and start the workflow over."""
        _poison(project)
        before = (project / ".functualize" / SCOPES_FILENAME).read_text()
        for _ in range(3):
            assert cli_run(["builtin", "workflow", "list"], cwd=project).exit_code == 2
        assert (project / ".functualize" / SCOPES_FILENAME).read_text() == before


class TestShowDiagnosesRatherThanDies:
    """R-b: `show` is the command someone runs to find out what is wrong."""

    def test_show_still_reports_every_other_statistic(self, cli_run, project) -> None:
        _poison(project)
        result = cli_run(["builtin", "state", "show"], cwd=project)
        assert "Fingerprints: 1" in result.stdout
        # `History entries` left this command with `durable-run-layer`/T3b:
        # `state.json` no longer holds history, and reporting a count of
        # something the file does not hold would be a lie in the one command a
        # user runs to find out what is wrong. What remains is asserted above.
        assert "Fingerprints:" in result.stdout
        assert "State path:" in result.stdout

    def test_show_renders_the_scope_line_as_the_fault(self, cli_run, project) -> None:
        _poison(project)
        result = cli_run(["builtin", "state", "show"], cwd=project)
        assert "unreadable" in result.stdout
        assert "found version 99" in result.stdout

    def test_show_still_exits_2(self, cli_run, project) -> None:
        _poison(project)
        assert cli_run(["builtin", "state", "show"], cwd=project).exit_code == 2


class TestEscapeHatchWorksOnAnUnreadableStore:
    """`clear --scopes` is what the refusal tells you to run, so it must work
    on precisely the content the reader refuses."""

    def test_clear_scopes_recovers_an_unreadable_store(self, cli_run, project) -> None:
        _poison(project)
        result = cli_run(["builtin", "state", "clear", "--scopes"], cwd=project)
        assert result.exit_code == 0
        assert cli_run(["builtin", "workflow", "list"], cwd=project).exit_code == 0

    def test_clear_without_scopes_says_it_could_not_read_them(
        self, cli_run, project
    ) -> None:
        _poison(project)
        result = cli_run(["builtin", "state", "clear"], cwd=project)
        assert result.exit_code == 0
        assert "could not be read" in result.stdout


WORKFLOW_JOB = """
from pydantic import BaseModel

from functualize.workflow import END, Edge, Gate, Step, workflow


class Approval(BaseModel):
    approved: bool


def build() -> str:
    return "artifact"


@workflow(
    steps=[Step("build"), Gate(name="approve", awaits=Approval)],
    edges=[Edge(source="build", target="approve"), Edge(source="approve", target=END)],
)
def release() -> str:
    return "shipped"
"""


class TestRunningAWorkflowJobRefuses:
    """The job-invocation path, not the `builtin workflow` path.

    **Cold and warm, or neither.** These are two different dispatch paths —
    `click_params` builds the command from a live signature, `lazy_command`
    from a cached descriptor — and `deliver_job_result`'s docstring records what
    happened the last time only one of them handled a case: "Cold boot exited 1,
    warm boot exited 0, for the same job and the same failure."
    (`contributor/reference/pitfalls.md` §23.)

    Written after a sabotage check found the warm path uncovered: deleting its
    refusal broke no test, which is exactly the hole this class fills.
    """

    @pytest.fixture
    def wf_project(self, project_tree):
        return project_tree(jobs={"release.py": WORKFLOW_JOB})

    def test_cold_cache_refuses(self, cli_run, wf_project) -> None:
        """First invocation in a project: the eager path in click_params."""
        (wf_project / ".functualize").mkdir(exist_ok=True)
        _poison(wf_project)
        result = cli_run(["release"], cwd=wf_project)
        assert result.exit_code == 2
        assert "cannot be read" in result.stderr

    def test_warm_cache_refuses_too(self, cli_run, wf_project) -> None:
        """Second invocation: the lazy path in lazy_command, built from the
        cached descriptor. This is the one a sabotage check found uncovered."""
        (wf_project / ".functualize").mkdir(exist_ok=True)

        first = cli_run(["release"], cwd=wf_project)
        assert first.exit_code == 5, "expected a gate block to warm the cache"

        _poison(wf_project)
        result = cli_run(["release"], cwd=wf_project)
        assert result.exit_code == 2, (
            "warm dispatch must refuse identically to cold — this is the "
            "cold-1/warm-0 split deliver_job_result documents"
        )
        assert "cannot be read" in result.stderr

    def test_neither_path_leaks_the_payload(self, cli_run, wf_project) -> None:
        (wf_project / ".functualize").mkdir(exist_ok=True)
        cli_run(["release"], cwd=wf_project)
        _poison(wf_project)
        result = cli_run(["release"], cwd=wf_project)
        assert "hunter2-SECRET" not in result.stderr + result.stdout
