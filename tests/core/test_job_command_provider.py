"""C1.2 — `JobCommandProvider` over the namespace trie.

Three things are pinned, matching the task's acceptance:

1. **Drill-down** — a nested `infra.aws.provision` fixture yields
   `infra` -> `aws` -> `provision` through `children()`, one node per dotted
   segment (never a single node named "infra.aws").
2. **`params()` does not materialize** — it reads cached descriptor metadata, so
   listing a job's parameters imports no job module. This is the property the
   warm-boot-zero-imports harness protects globally; here it is asserted
   directly against `sys.modules`.
3. **Duality** — a node that is both runnable and navigable exposes both, the
   same way the trie models it.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from functualize.app.commands import JobCommandProvider
from functualize.app.config import JobSources
from functualize.app.core import FunctualizeApp
from functualize.plugin import CommandNode, CommandProvider


def _write(jobs_dir: Path, name: str, body: str) -> None:
    (jobs_dir / name).write_text(textwrap.dedent(body))


@pytest.fixture
def nested_app(tmp_path: Path) -> FunctualizeApp:
    """`infra.aws.provision`, a top-level `deploy`, and `deploy.web` (duality)."""
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    _write(
        jobs_dir,
        "infra_aws.py",
        """
        JOB_GROUP = "infra.aws"

        def provision():
            '''Provision AWS infrastructure.'''
            print("provisioned")
        """,
    )
    _write(
        jobs_dir,
        "deploy.py",
        """
        def deploy(env: str = "dev"):
            '''Deploy the application.'''
            print(f"deploying {env}")
        """,
    )
    _write(
        jobs_dir,
        "deploy_web.py",
        """
        JOB_GROUP = "deploy"

        def web():
            '''Deploy the web tier.'''
            print("web")
        """,
    )
    return FunctualizeApp(
        name="testapp", job_sources=JobSources(directories=[str(jobs_dir)])
    )


def _by_name(nodes: list[CommandNode], name: str) -> CommandNode:
    for node in nodes:
        if node.name == name:
            return node
    raise AssertionError(f"no node {name!r} in {[n.name for n in nodes]}")


class TestProtocolConformance:
    def test_provider_satisfies_command_provider(self, nested_app) -> None:
        assert isinstance(JobCommandProvider(nested_app), CommandProvider)

    def test_nodes_satisfy_command_node(self, nested_app) -> None:
        for node in JobCommandProvider(nested_app).nodes():
            assert isinstance(node, CommandNode)


class TestDrillDown:
    """One node per dotted segment — never a node literally named "infra.aws"."""

    def test_top_level_has_infra_not_infra_aws(self, nested_app) -> None:
        names = {n.name for n in JobCommandProvider(nested_app).nodes()}
        assert "infra" in names
        assert "infra.aws" not in names

    def test_three_level_drill_down(self, nested_app) -> None:
        top = JobCommandProvider(nested_app).nodes()
        infra = _by_name(top, "infra")
        aws = _by_name(infra.children(), "aws")
        provision = _by_name(aws.children(), "provision")

        assert provision.children() == []
        assert "Provision AWS" in provision.help_text

    def test_children_are_sorted(self, nested_app) -> None:
        names = [n.name for n in JobCommandProvider(nested_app).nodes()]
        assert names == sorted(names)


class TestDuality:
    """`deploy` is a job AND a group; the node exposes both."""

    def test_node_is_runnable_and_navigable(self, nested_app) -> None:
        deploy = _by_name(JobCommandProvider(nested_app).nodes(), "deploy")

        # navigable
        assert [c.name for c in deploy.children()] == ["web"]
        # runnable — its own params come from its own descriptor
        assert "env" in {p.name for p in deploy.params()}
        assert "Deploy the application" in deploy.help_text

    def test_child_is_independent_of_the_parent_payload(self, nested_app) -> None:
        deploy = _by_name(JobCommandProvider(nested_app).nodes(), "deploy")
        web = _by_name(deploy.children(), "web")
        assert web.children() == []
        assert "web tier" in web.help_text


class TestParamsDoNotMaterialize:
    """`params()` reads cached metadata; listing must not import job modules."""

    def test_params_available_without_importing_the_job_module(
        self, nested_app
    ) -> None:
        top = JobCommandProvider(nested_app).nodes()
        deploy = _by_name(top, "deploy")

        before = set(sys.modules)
        params = deploy.params()
        newly_imported = set(sys.modules) - before

        assert {p.name for p in params} == {"env"}
        assert not [m for m in newly_imported if "deploy" in m], (
            f"params() imported job modules: {newly_imported}"
        )

    def test_full_tree_walk_imports_no_job_module(self, nested_app) -> None:
        """Drill-down + params over the whole tree stays import-free."""
        before = set(sys.modules)

        def walk(nodes: list[CommandNode]) -> None:
            for node in nodes:
                node.params()
                _ = node.help_text
                _ = node.needs_terminal
                walk(node.children())

        walk(JobCommandProvider(nested_app).nodes())
        newly_imported = set(sys.modules) - before

        offenders = [
            m
            for m in newly_imported
            if m.endswith(("deploy", "infra_aws", "deploy_web"))
        ]
        assert not offenders, f"tree walk imported job modules: {offenders}"


class TestNeedsTerminal:
    def test_plain_job_does_not_need_terminal(self, nested_app) -> None:
        deploy = _by_name(JobCommandProvider(nested_app).nodes(), "deploy")
        assert deploy.needs_terminal is False

    def test_pure_group_never_needs_terminal(self, nested_app) -> None:
        infra = _by_name(JobCommandProvider(nested_app).nodes(), "infra")
        assert infra.needs_terminal is False

    def test_is_a_bool_not_a_callable(self, nested_app) -> None:
        """The C1.1 shape decision, enforced on a real node."""
        deploy = _by_name(JobCommandProvider(nested_app).nodes(), "deploy")
        assert isinstance(deploy.needs_terminal, bool)


class TestExecute:
    def test_runs_the_job(self, nested_app, capsys) -> None:
        deploy = _by_name(JobCommandProvider(nested_app).nodes(), "deploy")
        exit_code = deploy.execute(["--env", "prod"])
        assert exit_code == 0
        assert "deploying prod" in capsys.readouterr().out

    def test_runs_a_nested_job(self, nested_app, capsys) -> None:
        top = JobCommandProvider(nested_app).nodes()
        aws = _by_name(_by_name(top, "infra").children(), "aws")
        provision = _by_name(aws.children(), "provision")

        assert provision.execute([]) == 0
        assert "provisioned" in capsys.readouterr().out

    def test_pure_group_execute_is_a_noop_failure(self, nested_app) -> None:
        """A group has no payload to run; it reports failure rather than raising."""
        infra = _by_name(JobCommandProvider(nested_app).nodes(), "infra")
        assert infra.execute([]) == 1


class TestUserNamespaceOnly:
    def test_builtin_is_not_in_this_provider(self, nested_app) -> None:
        """The reserved subtree comes from ClickCommandProvider (C1.3)."""
        names = {n.name for n in JobCommandProvider(nested_app).nodes()}
        assert "builtin" not in names
