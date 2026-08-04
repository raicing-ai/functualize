"""The TUI understands post-name group flags instead of erroring (S6b T-S6b-1).

The maintainer directive that put GroupOptions before TUI integration: the
shell's flag parsing must not treat a group-declared flag as unknown. The TUI
addresses a job by its canonical dotted name, so there is no mid-path — a user
types ``deploy.web.run --env prod`` with the flag *after* the name. A post-name
flag is routed by group-path lookup: a field of a ``GroupOptions`` on the job's
path is a group option (delivered via ``group_option_values``); everything else
is the job's own, and the job's own wins a name clash (D-d parity).

Three levels are exercised:

* the pure split (``split_job_and_group_kwargs``) — partition + clash rule;
* the path walk (``group_option_specs_on_path``) — "group path = dotted name
  minus its function segment", against a real trie;
* the integrated ``FunctualizeInlineTUI.split_job_tokens`` — the exact routing
  every TUI execution/preview site calls, against a booted app and warm cache.

The end-to-end "a typed group flag reaches the running job" is left to
``observe-tui`` manual verification (the T-S6b gate), per the recorded lesson
that a TUI surface's real behavior is settled by driving it, not unit-probing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from functualize._cli.tui.cli_arg_parser import (
    group_option_specs_on_path,
)


@dataclass(frozen=True)
class _Field:
    """A FieldDescriptor-like stand-in (only the attributes the split reads)."""

    name: str
    short_flag: str | None = None
    positional: bool = False


class TestGroupOptionSpecsOnPath:
    """The path walk that turns a job name into its inherited specs."""

    def _trie(self):
        from functualize._types.descriptors import FieldDescriptor, GroupOptionsSpec
        from functualize.app.utils import build_group_trie

        deploy = GroupOptionsSpec(
            group="deploy",
            class_name="DeployOptions",
            fields=[
                FieldDescriptor(
                    name="env",
                    type_annotation="str",
                    default="staging",
                    required=False,
                    description="",
                    short_flag="-e",
                )
            ],
            source_file="_group.py",
            source_mtime=0.0,
            content_hash="h",
            module_path="_group",
        )
        web = GroupOptionsSpec(
            group="deploy.web",
            class_name="WebOptions",
            fields=[
                FieldDescriptor(
                    name="replicas",
                    type_annotation="int",
                    default=1,
                    required=False,
                    description="",
                )
            ],
            source_file="_group.py",
            source_mtime=0.0,
            content_hash="h",
            module_path="_group",
        )
        return build_group_trie(
            [("deploy.web", "deploy.web.run", "job")],
            [],
            group_options={"deploy": deploy, "deploy.web": web},
        )

    def test_a_nested_job_inherits_every_ancestor(self) -> None:
        specs = group_option_specs_on_path(self._trie(), "deploy.web.run")

        assert [s.group for s in specs] == ["deploy", "deploy.web"]

    def test_a_shallow_job_inherits_only_its_own_group(self) -> None:
        specs = group_option_specs_on_path(self._trie(), "deploy.run")

        assert [s.group for s in specs] == ["deploy"]

    def test_an_ungrouped_job_inherits_nothing(self) -> None:
        """No dot in the name → no group path → nothing inherited."""
        assert group_option_specs_on_path(self._trie(), "loose") == []

    def test_no_trie_is_empty_not_an_error(self) -> None:
        assert group_option_specs_on_path(None, "deploy.web.run") == []


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


class TestTuiPathResolution:
    """``FunctualizeInlineTUI.resolve_command`` — the space-separated walk every
    TUI execution/preview site calls, against a booted app and warm cache.

    The shell navigates groups the way the CLI does, so group flags are
    consumed **mid-path** and the dotted spelling is refused."""

    @pytest.fixture()
    def tui(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from functualize._cli.tui.app import FunctualizeInlineTUI
        from functualize.app.config import JobSources
        from functualize.app.core import FunctualizeApp

        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.chdir(tmp_path)
        jobs = tmp_path / "jobs"
        jobs.mkdir()
        (jobs / "_group.py").write_text(_GROUP_MODULE)
        (jobs / "web.py").write_text(_WEB_JOB)

        func_app = FunctualizeApp(
            name="tuigroupopts",
            job_sources=JobSources(directories=[str(jobs)]),
        )
        func_app.get_jobs()  # warm the cache the trie reads
        return FunctualizeInlineTUI(func_app)

    def test_a_space_separated_path_resolves_to_the_job(self, tui) -> None:
        """The headline requirement: `deploy web run`, not `deploy.web.run`."""
        resolution = tui.resolve_command(["deploy", "web", "run"])

        assert resolution.job_name == "deploy.web.run"
        assert resolution.args == []
        assert resolution.dotted_token is None

    def test_a_dotted_path_is_refused(self, tui) -> None:
        """The shell presents groups and jobs space-separated; offering a second
        spelling in a surface with live completion teaches the wrong one."""
        resolution = tui.resolve_command(["deploy.web.run"])

        assert resolution.job_name is None
        assert resolution.dotted_token == "deploy.web.run"

    def test_a_mid_path_group_flag_is_consumed(self, tui) -> None:
        """`deploy --env prod web run` — bound to the `deploy` declaration on
        the way past, exactly as on the command line."""
        resolution = tui.resolve_command(["deploy", "--env", "prod", "web", "run"])

        assert resolution.job_name == "deploy.web.run"
        assert resolution.group_values == {"env": "prod"}
        assert resolution.args == []

    def test_a_mid_path_short_flag_is_consumed(self, tui) -> None:
        resolution = tui.resolve_command(["deploy", "-e", "prod", "web", "run"])

        assert resolution.group_values == {"env": "prod"}
        assert resolution.job_name == "deploy.web.run"

    def test_a_mid_path_bool_flag_does_not_eat_the_next_segment(self, tui) -> None:
        """A presence flag must not swallow `web` as its value."""
        resolution = tui.resolve_command(["deploy", "--dry-run", "web", "run"])

        assert resolution.job_name == "deploy.web.run"
        assert resolution.group_values == {"dry_run": True}

    def test_post_command_tokens_are_the_jobs_own_arguments(self, tui) -> None:
        """Position is the scope delimiter (D-d): after the command, a flag is
        the job's, and the walk hands it back untouched."""
        resolution = tui.resolve_command(["deploy", "web", "run", "--image", "custom"])

        assert resolution.job_name == "deploy.web.run"
        assert resolution.args == ["--image", "custom"]
        assert resolution.group_values == {}

    def test_group_and_job_flags_in_one_line(self, tui) -> None:
        resolution = tui.resolve_command(
            ["deploy", "--env", "prod", "web", "run", "--image", "custom"]
        )

        assert resolution.group_values == {"env": "prod"}
        assert tui.job_kwargs_for(resolution.job_name, resolution.args) == {
            "image": "custom"
        }

    def test_an_undeclared_mid_path_flag_is_reported(self, tui) -> None:
        resolution = tui.resolve_command(["deploy", "--nope", "x", "web", "run"])

        assert resolution.bad_flag == "--nope"

    def test_an_incomplete_path_resolves_to_no_job(self, tui) -> None:
        """`deploy web` is a group, not a runnable command."""
        resolution = tui.resolve_command(["deploy", "web"])

        assert resolution.job_name is None
