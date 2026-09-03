"""The whole S6a path through the real binary: type a flag, read a value.

Every other test in this package holds one half still — the dispatch tests
walk argv without an engine, the injection tests hand the engine a dict no
command line produced. This is the only place the two halves meet, and the
join is where S6a's bugs have actually lived: the pre-filter that hid
``_group.py`` from the scan, and the walk that kept consuming flags past the
command node. Both passed unit probes while the binary stayed broken.

Marked slow (subprocess + full boot), following the other ``*_e2e`` modules.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

PROJECT_ROOT = Path(__file__).parent.parent.parent

_GROUP_MODULE = '''\
from typing import Annotated

from functualize.job import GroupOptions, Option


class DeployOptions(GroupOptions, group="deploy"):
    """Deploy-level flags."""

    env: Annotated[str, Option("-e", help="Target environment")] = "staging"
    dry_run: Annotated[bool, Option("--dry-run", help="Preview only")] = False
'''

_WEB_JOB = '''\
from _group import DeployOptions

JOB_GROUP = "deploy.web"


def run(image: str = "nginx", opts: DeployOptions = None) -> str:
    """Deploy the web tier."""
    print(f"env={opts.env} dry_run={opts.dry_run} image={image}")
    return image
'''


def _write_project(tmp_path: Path, *, config: str | None = None) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "gopts"\nversion = "0.1.0"\ndependencies = []\n',
        encoding="utf-8",
    )
    (tmp_path / ".functualize.toml").write_text(
        'jobs_directories = ["jobs"]\n', encoding="utf-8"
    )
    if config is not None:
        (tmp_path / "config.base.toml").write_text(config, encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    (jobs / "_group.py").write_text(_GROUP_MODULE, encoding="utf-8")
    (jobs / "web.py").write_text(_WEB_JOB, encoding="utf-8")
    return tmp_path


def _run_func(
    *args: str,
    cwd: str | Path,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    import os

    child_env = dict(os.environ)
    if env:
        child_env.update(env)
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=child_env,
        timeout=timeout,
    )


class TestGroupOptionsEndToEnd:
    def test_a_mid_path_flag_reaches_the_job(self, tmp_path: Path) -> None:
        """`func deploy --env prod web run` — the headline case. The flag sits
        before a group segment the walk has yet to consume."""
        proj = _write_project(tmp_path)

        result = _run_func("deploy", "--env", "prod", "web", "run", cwd=proj)

        assert result.returncode == 0, result.stderr
        assert "env=prod" in result.stdout

    def test_the_declared_default_arrives_when_no_flag_is_given(
        self, tmp_path: Path
    ) -> None:
        proj = _write_project(tmp_path)

        result = _run_func("deploy", "web", "run", cwd=proj)

        assert result.returncode == 0, result.stderr
        assert "env=staging dry_run=False" in result.stdout

    def test_a_bool_flag_does_not_swallow_the_next_path_segment(
        self, tmp_path: Path
    ) -> None:
        """`--dry-run web run` must reach the job, not consume `web` as its
        value. The bug this pins made the walk stop one segment short."""
        proj = _write_project(tmp_path)

        result = _run_func("deploy", "--dry-run", "web", "run", cwd=proj)

        assert result.returncode == 0, result.stderr
        assert "dry_run=True" in result.stdout

    def test_the_job_keeps_its_own_options(self, tmp_path: Path) -> None:
        """Group flags before the job, job flags after it — both land, and the
        job's `--help` does not advertise the group's fields as its own."""
        proj = _write_project(tmp_path)

        run = _run_func(
            "deploy", "--env", "prod", "web", "run", "--image", "custom", cwd=proj
        )
        help_text = _run_func("deploy", "web", "run", "--help", cwd=proj)

        assert run.returncode == 0, run.stderr
        assert "env=prod" in run.stdout
        assert "image=custom" in run.stdout
        assert "--image" in help_text.stdout
        assert "--env" not in help_text.stdout
        assert "--dry-run" not in help_text.stdout

    def test_the_group_config_section_is_read(self, tmp_path: Path) -> None:
        """`[deploy]` — the *group* path, not the job name."""
        proj = _write_project(tmp_path, config='[deploy]\nenv = "fromfile"\n')

        result = _run_func("deploy", "web", "run", cwd=proj)

        assert result.returncode == 0, result.stderr
        assert "env=fromfile" in result.stdout

    def test_the_full_ladder_through_the_binary(self, tmp_path: Path) -> None:
        """default < file < env < group-CLI, each layer displacing the last in
        one project. D-c is the top rung: a typed flag beats an exported
        default, or there would be no point typing it."""
        proj = _write_project(tmp_path, config='[deploy]\nenv = "fromfile"\n')

        from_file = _run_func("deploy", "web", "run", cwd=proj)
        from_env = _run_func(
            "deploy", "web", "run", cwd=proj, env={"DEPLOY__ENV": "fromenv"}
        )
        from_cli = _run_func(
            "deploy",
            "--env",
            "prod",
            "web",
            "run",
            cwd=proj,
            env={"DEPLOY__ENV": "fromenv"},
        )

        assert "env=fromfile" in from_file.stdout, from_file.stderr
        assert "env=fromenv" in from_env.stdout, from_env.stderr
        assert "env=prod" in from_cli.stdout, from_cli.stderr

    def test_the_group_listing_documents_its_options(self, tmp_path: Path) -> None:
        """T-GO-5: the listing is where a user learns `--env` exists at all.
        Without it the flag is parseable but undiscoverable.

        A bool is listed as **`--dry-run, --no-dry-run`**, and this assertion
        has now moved twice, in opposite directions, for the same reason each
        time: *the listing must say what the parser accepts.*

        It first required the pair. #13 inverted it to the positive form only,
        because the warm builder rendered a negative the mid-path parser had
        never recognised — `func deploy --no-dry-run run` answered
        `unknown option`, so the listing was "pinning a documented lie".

        That inversion recorded the gap it could not close: *"a bool group
        option set `true` in config cannot be overridden from the command
        line."* The boolean-flag-negation feature closed exactly that gap —
        `_flag_aliases` now matches the negative spelling through the same
        `negative_flag_for` rule the builder renders from — so the listing
        advertises it again, and this time it is true.

        The invariant that survived both moves is the one worth keeping: this
        test does not assert a *spelling*, it asserts that the listing and the
        parser agree."""
        proj = _write_project(tmp_path)

        result = _run_func("deploy", cwd=proj)

        assert result.returncode == 0, result.stderr
        assert "Options:" in result.stdout
        assert "--env, -e TEXT" in result.stdout
        assert "Target environment" in result.stdout
        assert "--dry-run" in result.stdout
        assert "--no-dry-run" in result.stdout

    def test_a_nested_group_lists_inherited_options(self, tmp_path: Path) -> None:
        """`deploy web` accepts `--env` (an ancestor declared it), so its
        listing has to say so — a listing showing only this node's own
        declarations under-reports what may legally be typed."""
        proj = _write_project(tmp_path)

        result = _run_func("deploy", "web", cwd=proj)

        assert result.returncode == 0, result.stderr
        assert "--env, -e TEXT" in result.stdout

    def test_help_after_a_group_prints_the_listing(self, tmp_path: Path) -> None:
        """`git remote --help` is what people type. The "move it before the
        group" advice is wrong for this one flag — `func --help deploy` prints
        func's help, not deploy's — so `--help` renders the group listing."""
        proj = _write_project(tmp_path)

        result = _run_func("deploy", "--help", cwd=proj)

        assert result.returncode == 0, result.stderr
        assert "Usage: func deploy" in result.stdout
        assert "--env, -e TEXT" in result.stdout

    def test_a_misplaced_global_is_still_an_error(self, tmp_path: Path) -> None:
        """Only `--help` is exempted; every other global keeps model A's
        error, which is the message that teaches the ordering rule."""
        proj = _write_project(tmp_path)

        result = _run_func("deploy", "--log-level", "DEBUG", "web", cwd=proj)

        assert result.returncode == 2
        assert "must come before the group name" in result.stderr

    def test_an_undeclared_mid_path_flag_is_still_an_error(
        self, tmp_path: Path
    ) -> None:
        """Model A is unchanged for everything the group did not declare."""
        proj = _write_project(tmp_path)

        result = _run_func("deploy", "--nope", "x", "web", "run", cwd=proj)

        assert result.returncode == 2
        assert "--nope" in result.stderr
