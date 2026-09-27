"""The pull-request half of the spec-gate rule, and the cases it must not miss.

`.github/workflows/spec-task-graph.yml` runs
`.github/scripts/verify_spec_task_graph.py` over a pull request's range, because
`.claude/rules/spec-workflow.md` § *What is mechanically enforced* has required a
`.spec/features/*/tasks.md` wave graph for any change to `src/functualize/**` or
`plugins/**/src/**` since the spec workflow landed, and only a `PreToolUse` hook
ever checked it. A hook sees a worktree and one harness; a merge is a range of
commits made by anything.

The script is exercised by **shelling out**, not by importing it, for the cases
where the answer is a process: the two directories this check reads (the checkout
and a base commit) are inputs of a git invocation, and a fixture that called
`main()` in-process could pass while the workflow's own invocation failed. The
predicates themselves are imported in one test, to assert the script really does
take them from the hook rather than restating them — two definitions of one
contract is how a gate and the check beside it drift, and this pair drifts in the
direction that fails open.

The workflow is read as **text**, not through `yaml.safe_load`, for the reason
`tests/spec/test_message_hygiene_check.py` records: YAML 1.1 parses a bare `on:`
key as the boolean `True`, so the property most worth pinning — that it triggers
on `pull_request` and never on `pull_request_target` — is invisible in a parsed
document.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / ".github" / "scripts" / "verify_spec_task_graph.py"
_WORKFLOW = _ROOT / ".github" / "workflows" / "spec-task-graph.yml"
_CONTRIBUTING = _ROOT / "CONTRIBUTING.md"
_AGENTS = _ROOT / "AGENTS.md"
_SCRIPT_TEXT = _SCRIPT.read_text(encoding="utf-8")

#: The job id. GitHub reports a job by its id, so this string is the status
#: context a ruleset entry would have to name — and the name the docs use.
CONTEXT = "contract-diff-carries-task-graph"

GATED_FILE = "src/functualize/_engine/explain.py"
GROUPED_PLUGIN_FILE = "plugins/aws/functualize-aws/src/functualize_aws/plugin.py"

GRAPH = """\
## tasks

- [ ] 1.1 Do the thing.

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["1.1"]}]}
```
"""

GRAPH_LESS_TASKS = """\
## tasks

- [ ] 1.1 Do the thing.

## Task Dependency Graph

The order is obvious from the list above.
"""


def _checker() -> Any:
    """Load the script out-of-tree, under a name of its own.

    Registered in `sys.modules` before execution for the reason
    `tests/spec/test_message_hygiene_check.py::_checker` records.
    """
    name = "_fz_spec_task_graph"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[name]
        raise
    return module


@pytest.fixture()
def check() -> Any:
    return _checker()


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _run(
    repo: Path, base: str, head: str, **env: str
) -> subprocess.CompletedProcess[str]:
    """Run the check the way the workflow does, as a process."""
    return subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "SPEC_TASK_GRAPH_BASE": base,
            "SPEC_TASK_GRAPH_HEAD": head,
            "SPEC_TASK_GRAPH_ROOT": str(repo),
            **env,
        },
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A throwaway repository: one base commit, and a branch to range over."""
    _git(tmp_path, "init", "-b", "master")
    _git(tmp_path, "config", "user.email", "tester@example.invalid")
    _git(tmp_path, "config", "user.name", "Tester")
    _write(tmp_path, "README.md", "base\n")
    _commit(tmp_path, "chore: base")
    _git(tmp_path, "checkout", "-b", "topic")
    return tmp_path


def _base(repo: Path) -> str:
    return _git(repo, "rev-parse", "master")


class TestRefused:
    """The cases the check exists for: shipped code with no task graph behind it."""

    def test_a_contract_change_with_no_artifact_is_refused(self, repo: Path) -> None:
        _write(repo, GATED_FILE, "def explain():\n    return 0\n")
        head = _commit(repo, "fix(cli): make why exit zero")
        result = _run(repo, _base(repo), head)
        assert result.returncode == 1
        assert "::error::" in result.stdout
        assert GATED_FILE in result.stdout
        assert ".spec/features/*/tasks.md" in result.stdout

    def test_the_grouped_plugin_layout_is_refused_too(self, repo: Path) -> None:
        """The hook gates any `plugins/**/src/**`, old layout or grouped."""
        _write(repo, GROUPED_PLUGIN_FILE, "VALUE = 1\n")
        head = _commit(repo, "feat(plugins): a new surface")
        result = _run(repo, _base(repo), head)
        assert result.returncode == 1
        assert GROUPED_PLUGIN_FILE in result.stdout

    def test_a_tasks_file_without_the_graph_does_not_satisfy_it(
        self, repo: Path
    ) -> None:
        """A task list that cannot be executed as designed is not the artifact.

        The write-time gate refuses it with `REASON_NO_GRAPH`; here the graph
        predicate is the same import, so the same file must fail the same way.
        """
        _write(repo, GATED_FILE, "def explain():\n    return 0\n")
        _write(repo, ".spec/features/x/tasks.md", GRAPH_LESS_TASKS)
        head = _commit(repo, "fix(cli): make why exit zero")
        assert _run(repo, _base(repo), head).returncode == 1

    def test_a_graph_in_a_markdown_file_other_than_tasks_is_not_an_artifact(
        self, repo: Path
    ) -> None:
        """`plan.md` may quote a graph; only `tasks.md` is the artifact."""
        _write(repo, GATED_FILE, "def explain():\n    return 0\n")
        _write(repo, ".spec/features/x/plan.md", GRAPH)
        _write(repo, ".spec/features/x/spec.md", "# Spec\n")
        head = _commit(repo, "fix(cli): make why exit zero")
        assert _run(repo, _base(repo), head).returncode == 1

    def test_an_adr_or_a_research_tree_is_not_an_artifact(self, repo: Path) -> None:
        """Only `.spec/features/**` counts, whatever else the branch added."""
        _write(repo, GATED_FILE, "def explain():\n    return 0\n")
        _write(repo, "contributor/adr/099-a-decision.md", GRAPH)
        _write(repo, "contributor/architecture/research/study/tasks.md", GRAPH)
        head = _commit(repo, "fix(cli): make why exit zero")
        assert _run(repo, _base(repo), head).returncode == 1


class TestPassed:
    """The cases it must let through, each of which would be a false refusal."""

    def test_a_branch_that_carried_the_graph_passes(self, repo: Path) -> None:
        _write(repo, ".spec/features/x/tasks.md", GRAPH)
        _write(repo, GATED_FILE, "def explain():\n    return 0\n")
        head = _commit(repo, "fix(cli): make why exit zero")
        result = _run(repo, _base(repo), head)
        assert result.returncode == 0, result.stdout
        assert "OK" in result.stdout

    def test_a_graph_cleared_before_merge_still_counts(self, repo: Path) -> None:
        """The two-push sequence: artifacts in one commit, deleted in the last.

        The branch tip therefore carries no graph while the range does, which is
        why the tip alone cannot be the question — and why a check that read it
        would refuse every correctly finished branch.
        """
        _write(repo, ".spec/features/x/tasks.md", GRAPH)
        _write(repo, GATED_FILE, "def explain():\n    return 0\n")
        _commit(repo, "fix(cli): make why exit zero")
        _git(repo, "rm", "-q", "-r", ".spec/features/x")
        head = _commit(repo, "chore(spec): clear the artifacts")
        result = _run(repo, _base(repo), head)
        assert result.returncode == 0, result.stdout
        assert ".spec/features/x/tasks.md" in result.stdout

    def test_a_sibling_features_graph_satisfies_the_range(self, repo: Path) -> None:
        """Deliberately as loose as the hook, which surveys any feature dir.

        A stricter rule here would refuse work the write-time gate allows, and
        refusing work the gate allows is its own defect: the rule is that the
        branch was specified, not which feature name it chose.
        """
        _write(repo, ".spec/features/other/tasks.md", GRAPH)
        _write(repo, GATED_FILE, "def explain():\n    return 0\n")
        head = _commit(repo, "fix(cli): make why exit zero")
        assert _run(repo, _base(repo), head).returncode == 0

    def test_a_range_that_touches_no_gated_path_passes(self, repo: Path) -> None:
        _write(repo, "tests/cli/test_why_json.py", "def test_x():\n    pass\n")
        _write(repo, "docs/guides/composition.md", "the contract\n")
        head = _commit(repo, "docs(why): teach the payload branch")
        result = _run(repo, _base(repo), head)
        assert result.returncode == 0
        assert "no contract-bearing path changed" in result.stdout

    def test_an_example_or_a_plugin_test_is_not_a_gated_path(self, repo: Path) -> None:
        """`plugins/**/tests/**` and `examples/**` are free at write time too."""
        _write(
            repo,
            "plugins/aws/functualize-aws/tests/test_x.py",
            "def test_x():\n    pass\n",
        )
        _write(repo, "examples/standalone/lab/src/lab/__init__.py", "")
        head = _commit(repo, "test(plugins): a parity probe")
        assert _run(repo, _base(repo), head).returncode == 0

    def test_the_range_is_the_merge_base_not_the_base_tip(self, repo: Path) -> None:
        """A stale branch must not inherit `master`'s contract changes.

        Diffing the two tips would attribute every file `master` moved after the
        branch was cut to the branch, and refuse a docs-only PR for a
        `src/functualize/**` change it never made.
        """
        _write(repo, "docs/guides/composition.md", "the contract\n")
        head = _commit(repo, "docs(why): teach the payload branch")
        _git(repo, "checkout", "-q", "master")
        _write(repo, GATED_FILE, "def explain():\n    return 0\n")
        _commit(repo, "fix(cli): someone else's contract change")
        _git(repo, "checkout", "-q", "topic")
        result = _run(repo, _base(repo), head)
        assert result.returncode == 0, result.stdout
        assert "no contract-bearing path changed" in result.stdout


class TestFailsClosed:
    """Every unresolved input must refuse, because this job exists where the
    write-time gate was silent — its silence must not read as a pass."""

    def test_a_missing_range_refuses(self, repo: Path) -> None:
        result = _run(repo, "", "")
        assert result.returncode == 1
        assert "nothing was checked" in result.stdout

    def test_an_unresolvable_commit_refuses(self, repo: Path) -> None:
        result = _run(repo, "0" * 40, _git(repo, "rev-parse", "HEAD"))
        assert result.returncode == 1
        assert "nothing was checked" in result.stdout

    def test_an_unreadable_checkout_refuses(self, tmp_path: Path) -> None:
        result = _run(tmp_path / "gone", "0" * 40, "1" * 40)
        assert result.returncode == 1
        assert "nothing was checked" in result.stdout


class TestThePredicatesComeFromTheHook:
    """One contract, one definition. A copy would be a second one."""

    def test_the_gated_path_and_graph_predicates_are_the_hooks(
        self, check: Any, repo: Path
    ) -> None:
        gate = check._load_gate()
        assert gate.is_gated(GATED_FILE, str(repo)) is True
        assert gate.is_gated("docs/guides/composition.md", str(repo)) is False
        assert gate.has_wave_graph(GRAPH) is True
        assert gate.has_wave_graph(GRAPH_LESS_TASKS) is False
        # The script binds the hook's functions; it does not restate them.
        assert not hasattr(check, "is_gated")
        assert not hasattr(check, "has_wave_graph")
        assert not hasattr(check, "GATED_DIR")

    def test_the_script_reads_the_path_from_the_hook_not_a_literal(self) -> None:
        """A literal path would keep working after the hook moved, silently
        against a different rule."""
        assert ".claude" in _SCRIPT_TEXT
        assert "spec_gate.py" in _SCRIPT_TEXT


class TestTheWorkflowCannotSilentlyStopChecking:
    """Properties a later edit could remove without any test going red."""

    @pytest.fixture()
    def workflow(self) -> str:
        assert _WORKFLOW.is_file(), f"{_WORKFLOW} is missing"
        return _WORKFLOW.read_text(encoding="utf-8")

    def test_the_job_id_is_the_context(self, workflow: str) -> None:
        """A job's id is the status context, so the id IS what a ruleset names."""
        assert re.search(rf"^  {CONTEXT}:", workflow, re.M), workflow
        assert CONTEXT in _CONTRIBUTING.read_text(encoding="utf-8")
        assert CONTEXT in _AGENTS.read_text(encoding="utf-8")

    def test_it_runs_on_pull_request_and_never_on_pull_request_target(
        self, workflow: str
    ) -> None:
        """`pull_request_target` runs with a write-scoped token in the base
        repo's context for a fork PR. This check only reads the range, so it
        takes the narrow trigger."""
        assert not re.search(r"(?m)^\s*pull_request_target\s*:", workflow)
        assert re.search(r"(?m)^on:\n  pull_request:", workflow)
        trigger = workflow.split("jobs:", maxsplit=1)[0]
        # The file may *say* why there is no `paths:` or `types:`; only a key
        # counts.
        trigger = "\n".join(
            line for line in trigger.splitlines() if not line.lstrip().startswith("#")
        )
        assert "paths:" not in trigger and "paths-ignore:" not in trigger, (
            "a path filter here would decide which pull requests the check sees, "
            "which is the same silent-not-run failure the standalone workflow "
            "exists to avoid; the script decides by reading the range"
        )
        assert "types:" not in trigger, (
            "the default events (opened, synchronize, reopened) are exactly the "
            "ones that can change the range"
        )

    def test_it_reads_the_whole_range_with_a_read_only_token(
        self, workflow: str
    ) -> None:
        assert "fetch-depth: 0" in workflow, (
            "without full history the range's commits cannot be walked, and an "
            "unreachable commit is the one case that could pass while checking "
            "nothing"
        )
        assert "permissions:\n  contents: read" in workflow

    def test_the_job_actually_runs_the_checker(self, workflow: str) -> None:
        """A job that never calls the script passes forever."""
        assert "python3 .github/scripts/verify_spec_task_graph.py" in workflow

    def test_the_workflow_sets_the_variables_the_script_reads(
        self, workflow: str
    ) -> None:
        """The one drift that is invisible in both files separately: the job
        exports one name and the script reads another."""
        exported = set(re.findall(r"^\s+(SPEC_TASK_GRAPH_\w+):", workflow, re.M))
        assert exported == {
            "SPEC_TASK_GRAPH_BASE",
            "SPEC_TASK_GRAPH_HEAD",
            "SPEC_TASK_GRAPH_PR",
        }, exported
        source = _SCRIPT_TEXT
        for name in exported:
            assert name in source, f"{name} is exported and never read"
        assert "github.event.pull_request.base.sha" in workflow
        assert "github.event.pull_request.head.sha" in workflow, (
            "the head of the range is the PR's head commit; `github.sha` is the "
            "merge commit on a pull_request event"
        )

    def test_the_script_is_stdlib_only(self) -> None:
        """The job runs `python3 .github/scripts/...` with no `uv sync`, the way
        the cleanup-predecessor gate does. A third-party import breaks it only
        in CI, which is the slowest possible place to find out."""
        tree = ast.parse(_SCRIPT_TEXT)
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or "").split(".")[0])
        assert modules <= {
            "importlib",
            "os",
            "subprocess",
            "sys",
            "pathlib",
            "__future__",
        }, modules
