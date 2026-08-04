"""The SmartBar knows what it is completing (S6b T-S6b-2).

The shell navigates groups by spaces, so "what comes next" depends entirely on
where the cursor sits in the path. Five distinct answers, one per context:

===========================  ===========================================
cursor sits at               offers
===========================  ===========================================
the root                     top-level groups, jobs and builtins
inside a group               that node's children (sub-groups and jobs)
a ``-`` mid-path             the flags declared by consumed groups
a ``-`` after the command    the job's own flags
===========================  ===========================================

Driven by the **same trie walk** execution uses, so the dropdown cannot offer a
path the runner then refuses — which is exactly what it did before this task:
it offered the dotted ``deploy.web.run`` while execution had just started
rejecting that spelling.

The injection parameter is offered by **no** context. It is where the resolved
group instance lands, and it leaked into the flag list here — the fifth surface
in this feature to make that mistake, after the CLI, MCP, the pre-flight table
and the job's own click params.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_GROUP_MODULE = """\
from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
    dry_run: Annotated[bool, Option(help="Preview only")] = False
"""

_WEB_JOB = '''\
from _group import DeployOptions

JOB_GROUP = "deploy.web"


def run(image: str = "nginx", opts: DeployOptions = None) -> str:
    """Deploy the web tier."""
    return image
'''


def _main(item: object) -> str:
    """The dropdown item's primary text, however it is represented."""
    if isinstance(item, dict):
        return str(item.get("main", ""))
    return str(getattr(item, "main", item))


@pytest.fixture()
def complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A callable returning the candidate strings for a typed line."""
    from functualize._cli.completions.provenance import (
        CompletionProvenanceClassifier,
    )
    from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete
    from functualize.app.config import JobSources
    from functualize.app.core import FunctualizeApp

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.chdir(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "_group.py").write_text(_GROUP_MODULE)
    (jobs / "web.py").write_text(_WEB_JOB)

    app = FunctualizeApp(
        name="completion", job_sources=JobSources(directories=[str(jobs)])
    )
    app.get_jobs()  # warm the cache the trie reads
    autocomplete = SmartBarAutoComplete(app, CompletionProvenanceClassifier(app))

    def _complete(text: str) -> list[str]:
        return [
            _main(item)
            for item in autocomplete._command_mode_candidates(text, len(text))
        ]

    return _complete


class TestPathContext:
    def test_the_root_offers_top_level_groups_not_dotted_names(self, complete) -> None:
        """The defect this task fixes: the dropdown used to offer
        ``deploy.web.run``, the spelling execution refuses."""
        names = complete("")

        assert any(n.startswith("deploy") for n in names)
        assert not any("deploy.web.run" in n for n in names)

    def test_inside_a_group_offers_its_children(self, complete) -> None:
        assert any(n.startswith("web") for n in complete("deploy "))

    def test_at_the_leaf_level_offers_the_job(self, complete) -> None:
        assert any(n.startswith("run") for n in complete("deploy web "))

    def test_a_partial_segment_filters(self, complete) -> None:
        assert any(n.startswith("deploy") for n in complete("dep"))

    def test_a_builtin_is_offered_once(self, complete) -> None:
        """It is both a trie node and a registered builtin; offering both
        renders a duplicate row."""
        names = complete("")

        assert len([n for n in names if n.split()[0] == "builtin"]) == 1


class TestFlagContext:
    def test_mid_path_offers_the_groups_flags(self, complete) -> None:
        """`deploy --` is the position where a group's flag is legal."""
        names = complete("deploy --")

        assert any(n.startswith("--env") for n in names)
        assert any(n.startswith("--dry-run") for n in names)

    def test_after_the_command_offers_the_jobs_flags(self, complete) -> None:
        """Position is the scope delimiter: past the command the flags are the
        job's, not the group's."""
        names = complete("deploy web run --")

        assert any(n.startswith("--image") for n in names)
        assert not any(n.startswith("--env") for n in names)

    def test_a_consumed_mid_path_flag_does_not_derail_the_walk(self, complete) -> None:
        """`deploy --env prod web ` still knows it is inside `deploy.web` — the
        flag and its value are stepped over, not treated as path segments."""
        assert any(n.startswith("run") for n in complete("deploy --env prod web "))


class TestInjectionParameterIsNeverOffered:
    def test_not_as_a_job_flag(self, complete) -> None:
        """`--opts` would invite an agent or user to type a model into a flag."""
        assert not any("opts" in n for n in complete("deploy web run --"))

    def test_not_as_a_path_segment(self, complete) -> None:
        assert not any("opts" in n for n in complete("deploy web "))
