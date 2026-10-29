"""Run tags are merged before boot, refused with exit 2, and reach every door.

`main()` builds the run-tag map right after `_extract_global_options` and
before `auto_discover`, so the map is complete before any app object exists. A
refused tag is a usage error — exit **2**, unlike the `cli_app` validation
block's exit 1 — and it stops the process before a job module is imported, let
alone a job body run. The merged map is then forwarded at the four routing
calls that build a run: SINGLE_FILE, JOB, GROUP and the UNKNOWN fallback.

BUILTIN mode builds no run, so it gets no edit: Click refuses `--run-tag`
there exactly as it refuses `--force`. The environment variable, though, is
read for every mode, so a malformed `FUNCTUALIZE_RUN_TAGS` blocks
`func builtin info` too (spec R3 — intended).

The run record is read from the store file directly: the read side
(`run list` / `run show` printing the map) lands in a later wave.
"""

from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import surfaces

# `func`-only: this is the pre-boot dispatch layer of `_cli/main.py`; an app
# entry point has no pre-command globals to merge.
pytestmark = surfaces("func")

_SENTINEL_JOB = """\
from pathlib import Path

Path({imported!r}).write_text("imported")


def release():
    Path({ran!r}).write_text("ran")
    print("released")
"""


def _records(*roots: Path) -> dict[str, dict[str, Any]]:
    """Every run record under the given roots, keyed by run id."""
    found: dict[str, dict[str, Any]] = {}
    for root in roots:
        for path in root.rglob("runs.json"):
            found.update(json.loads(path.read_text()).get("runs", {}))
    return found


def _release_project(project_tree: Any, tmp_path: Path) -> types.SimpleNamespace:
    """A project whose `release` job leaves a file when imported and when run."""
    imported = tmp_path / "imported.txt"
    ran = tmp_path / "ran.txt"
    root = project_tree(
        jobs={"release.py": _SENTINEL_JOB.format(imported=str(imported), ran=str(ran))}
    )
    return types.SimpleNamespace(root=root, imported=imported, ran=ran)


class TestOneFlagTagsTheRun:
    def test_one_flag_is_one_tagged_run(
        self, cli_run, project_tree, tmp_path: Path, xdg_dirs
    ) -> None:
        """AC1: `func --run-tag harness:claude release` → exit 0, one tagged run."""
        project = _release_project(project_tree, tmp_path)

        result = cli_run(["--run-tag", "harness:claude", "release"], cwd=project.root)

        assert result.exit_code == 0, result.stderr
        assert "released" in result.stdout
        listed = cli_run(
            ["builtin", "run", "list", "--format", "json"], cwd=project.root
        )
        assert listed.exit_code == 0, listed.stderr
        assert len(json.loads(listed.stdout)["runs"]) == 1
        records = _records(project.root, xdg_dirs.cache)
        assert [r["run_tags"] for r in records.values()] == [{"harness": "claude"}]

    def test_no_source_at_all_records_an_empty_map(
        self, cli_run, project_tree, tmp_path: Path, xdg_dirs
    ) -> None:
        project = _release_project(project_tree, tmp_path)

        result = cli_run(["release"], cwd=project.root)

        assert result.exit_code == 0, result.stderr
        records = _records(project.root, xdg_dirs.cache)
        assert [r["run_tags"] for r in records.values()] == [{}]


class TestEveryDoorForwardsTheMap:
    """SINGLE_FILE, GROUP and UNKNOWN carry the map as JOB does."""

    def test_single_file(self, cli_run, tmp_path: Path, xdg_dirs) -> None:
        script = tmp_path / "task.py"
        script.write_text("def run():\n    print('from single file')\n")

        result = cli_run(["--run-tag", "door:single-file", str(script), "run"])

        assert result.exit_code == 0, result.stderr
        records = _records(tmp_path)
        assert [r["run_tags"] for r in records.values()] == [{"door": "single-file"}]

    def test_group(self, cli_run, project_tree, xdg_dirs) -> None:
        root = project_tree(
            jobs={
                "infra.py": (
                    "JOB_GROUP = 'infra'\n\n"
                    "def provision():\n    print('provisioned')\n"
                )
            }
        )

        result = cli_run(["--run-tag", "door:group", "infra", "provision"], cwd=root)

        assert result.exit_code == 0, result.stderr
        records = _records(root, xdg_dirs.cache)
        assert [r["run_tags"] for r in records.values()] == [{"door": "group"}]

    def test_unknown_on_a_cold_cache(self, cli_run, project_tree, xdg_dirs) -> None:
        """A function-level job whose name is not a file stem routes UNKNOWN.

        The UNKNOWN branch is the same job about to run; a value it failed to
        forward would be dropped on a cold cache and honoured once warm.
        """
        from functualize._cli.dispatch import Mode, detect_mode
        from functualize.app.utils import enumerate_job_names

        root = project_tree(jobs={"plans.py": "def trip():\n    print('planned')\n"})
        names = enumerate_job_names([str(root / ".functualize" / "jobs")])
        mode, _ = detect_mode(
            ["func", "--run-tag", "door:unknown", "trip"],
            job_names=names,
            group_names=set(),
            aliases={},
        )
        assert mode is Mode.UNKNOWN, "precondition: the cold route is UNKNOWN"

        result = cli_run(["--run-tag", "door:unknown", "trip"], cwd=root)

        assert result.exit_code == 0, result.stderr
        assert "planned" in result.stdout
        records = _records(root, xdg_dirs.cache)
        assert [r["run_tags"] for r in records.values()] == [{"door": "unknown"}]


_LONG = "v" * 257

#: (flag spellings, env value, config `[run] tags` TOML, expected message)
_REFUSED = [
    pytest.param(
        ["harness"],
        None,
        None,
        "--run-tag 'harness': a run tag is key:value (missing ':').",
        id="flag-missing-colon",
    ),
    pytest.param(
        [":claude"],
        None,
        None,
        "--run-tag ':claude': a run tag needs a key before ':'.",
        id="flag-empty-key",
    ),
    pytest.param(
        ["harness:"],
        None,
        None,
        "--run-tag 'harness:': a run tag needs a value after ':'.",
        id="flag-empty-value",
    ),
    pytest.param(
        ["Model:opus"],
        None,
        None,
        "--run-tag 'Model:opus': a run tag key uses a-z, 0-9, '.', '_' and '-'.",
        id="flag-key-grammar",
    ),
    pytest.param(
        [f"k:{_LONG}"],
        None,
        None,
        f"--run-tag 'k:{_LONG}': a run tag value cannot exceed 256 characters.",
        id="flag-value-too-long",
    ),
    pytest.param(
        None,
        "tier:2,bad",
        None,
        "FUNCTUALIZE_RUN_TAGS item 2 'bad': a run tag is key:value (missing ':').",
        id="env-missing-colon",
    ),
    pytest.param(
        None,
        "a b:c",
        None,
        "FUNCTUALIZE_RUN_TAGS item 1 'a b:c': a run tag cannot contain whitespace.",
        id="env-whitespace",
    ),
    pytest.param(
        None,
        None,
        '[run]\ntags = ["a:b", ":x"]\n',
        "[run] tags item 2 ':x': a run tag needs a key before ':'.",
        id="config-empty-key",
    ),
    pytest.param(
        None,
        None,
        '[run]\ntags = "a:b"\n',
        "[run] tags in the global config must be a list of strings.",
        id="config-not-a-list",
    ),
    pytest.param(
        [f"f{i}:v" for i in range(11)],
        ",".join(f"e{i}:v" for i in range(11)),
        "[run]\ntags = [" + ", ".join(f'"c{i}:v"' for i in range(11)) + "]\n",
        "a run may have at most 32 run tags.",
        id="thirty-three-across-layers",
    ),
]


class TestARefusedTagStopsBeforeBoot:
    @pytest.mark.parametrize(("flags", "env", "config", "message"), _REFUSED)
    def test_refused_spelling_exits_2_and_runs_nothing(
        self,
        cli_run,
        project_tree,
        tmp_path: Path,
        xdg_dirs,
        monkeypatch: pytest.MonkeyPatch,
        flags: list[str] | None,
        env: str | None,
        config: str | None,
        message: str,
    ) -> None:
        """AC8: the row's message, exit 2, no job body, no run record."""
        project = _release_project(project_tree, tmp_path)
        if config is not None:
            xdg_dirs.functualize_config.mkdir(parents=True)
            (xdg_dirs.functualize_config / "config.toml").write_text(config)
        if env is not None:
            monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", env)
        argv = [arg for flag in flags or [] for arg in ("--run-tag", flag)]

        result = cli_run([*argv, "release"], cwd=project.root)

        assert result.exit_code == 2, result.stderr
        assert f"Error: {message}" in result.stderr
        assert "released" not in result.stdout
        assert not project.ran.exists(), "the job body ran"
        assert not project.imported.exists(), "the job module was imported"
        assert _records(project.root, xdg_dirs.cache) == {}

        monkeypatch.delenv("FUNCTUALIZE_RUN_TAGS", raising=False)
        (xdg_dirs.functualize_config / "config.toml").unlink(missing_ok=True)
        listed = cli_run(
            ["builtin", "run", "list", "--format", "json"], cwd=project.root
        )
        assert listed.exit_code == 0, listed.stderr
        assert json.loads(listed.stdout)["runs"] == []

    def test_the_merge_happens_before_discovery(
        self, cli_run, project_tree, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No tag is parsed after boot: merge, then discover — never the reverse."""
        import functualize._cli.main as cli_main
        import functualize.app.utils as app_utils

        order: list[str] = []
        real_merge = cli_main._merge_run_tags
        real_discover = app_utils.auto_discover

        def _merge(*args: Any, **kwargs: Any) -> Any:
            order.append("merge")
            return real_merge(*args, **kwargs)

        def _discover(*args: Any, **kwargs: Any) -> Any:
            order.append("discover")
            return real_discover(*args, **kwargs)

        monkeypatch.setattr(cli_main, "_merge_run_tags", _merge)
        monkeypatch.setattr(app_utils, "auto_discover", _discover)
        project = _release_project(project_tree, tmp_path)

        assert cli_run(["--run-tag", "a:b", "release"], cwd=project.root).exit_code == 0
        assert order[:2] == ["merge", "discover"]

        order.clear()
        refused = cli_run(["--run-tag", "A:b", "release"], cwd=project.root)
        assert refused.exit_code == 2
        assert order == ["merge"], "a refused tag must stop before discovery"


class TestBuiltinMode:
    def test_the_flag_is_clicks_own_refusal(self, cli_run) -> None:
        """AC10: BUILTIN declares no delivery input, so Click refuses it."""
        result = cli_run(["--run-tag", "a:b", "builtin", "run", "list"])

        assert result.exit_code == 2
        assert "Error: No such option '--run-tag'." in result.stderr

    def test_a_malformed_env_blocks_builtin_info(
        self, cli_run, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R3, intended: the environment is read for every mode."""
        monkeypatch.setenv("FUNCTUALIZE_RUN_TAGS", "Bad:x")

        result = cli_run(["builtin", "info"])

        assert result.exit_code == 2
        assert (
            "Error: FUNCTUALIZE_RUN_TAGS item 1 'Bad:x': a run tag key uses "
            "a-z, 0-9, '.', '_' and '-'." in result.stderr
        )


class TestTheHandlersTakeTheMap:
    def test_four_handler_signatures(self) -> None:
        from functualize._cli import main as cli_main

        for handler in (
            cli_main._handle_bare,
            cli_main._handle_job,
            cli_main._handle_group,
            cli_main._handle_single_file,
        ):
            parameter = inspect.signature(handler).parameters["run_tags"]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, handler
        assert (
            inspect.signature(cli_main._handle_bare).parameters["run_tags"].default
            is None
        )


def _func(
    cwd: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(Path(sys.executable).parent / "func"), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=120,
    )


class TestARealProcess:
    """The same contract through a real `func` process, not `main()` in-process."""

    @pytest.mark.parametrize("source", ["flag", "env", "config"])
    def test_comma_value_is_refused_before_job_import(
        self, source: str, project_tree, tmp_path: Path, xdg_dirs
    ) -> None:
        project = _release_project(project_tree, tmp_path)
        env = {
            **os.environ,
            "HOME": str(xdg_dirs.home),
            "XDG_CONFIG_HOME": str(xdg_dirs.config),
            "XDG_CACHE_HOME": str(xdg_dirs.cache),
            "XDG_DATA_HOME": str(xdg_dirs.data),
        }
        args = ["release"]
        if source == "flag":
            args[:0] = ["--run-tag", "k:a,b"]
        elif source == "env":
            env["FUNCTUALIZE_RUN_TAGS"] = "k:a,b"
        else:
            xdg_dirs.functualize_config.mkdir(parents=True)
            (xdg_dirs.functualize_config / "config.toml").write_text(
                '[run]\ntags = ["k:a,b"]\n'
            )

        result = _func(project.root, env, *args)
        assert result.returncode == 2, result.stderr
        if source == "env":
            assert "Error: FUNCTUALIZE_RUN_TAGS" in result.stderr
        else:
            assert "a run tag value cannot contain ','" in result.stderr
        assert not project.imported.exists()

    def test_flag_tags_the_run_and_a_bad_env_blocks_builtin_info(
        self, project_tree, tmp_path: Path, xdg_dirs
    ) -> None:
        project = _release_project(project_tree, tmp_path)
        env = {
            **os.environ,
            "HOME": str(xdg_dirs.home),
            "XDG_CONFIG_HOME": str(xdg_dirs.config),
            "XDG_CACHE_HOME": str(xdg_dirs.cache),
            "XDG_DATA_HOME": str(xdg_dirs.data),
        }

        tagged = _func(project.root, env, "--run-tag", "harness:claude", "release")
        assert tagged.returncode == 0, tagged.stderr
        records = _records(project.root, xdg_dirs.cache)
        assert [r["run_tags"] for r in records.values()] == [{"harness": "claude"}]

        blocked = _func(
            project.root, {**env, "FUNCTUALIZE_RUN_TAGS": "s:1,s:2"}, "builtin", "info"
        )
        assert blocked.returncode == 2, blocked.stderr
        assert (
            "Error: FUNCTUALIZE_RUN_TAGS gives run tag key 's' twice "
            "(items 1 and 2)." in blocked.stderr
        )

    def test_tagged_run_writes_relational_run_and_tags(
        self, project_tree, tmp_path: Path, xdg_dirs
    ) -> None:
        """The installed CLI reaches the SQLite run writer through the engine."""
        project = _release_project(project_tree, tmp_path)
        database = project.root / "state.db"
        (project.root / "config.base.toml").write_text(
            f'[runtime_store]\nurl = "sqlite://{database}"\n'
        )
        env = {
            **os.environ,
            "HOME": str(xdg_dirs.home),
            "XDG_CONFIG_HOME": str(xdg_dirs.config),
            "XDG_CACHE_HOME": str(xdg_dirs.cache),
            "XDG_DATA_HOME": str(xdg_dirs.data),
        }

        result = _func(project.root, env, "--run-tag", "harness:claude", "release")
        assert result.returncode == 0, result.stderr
        assert database.exists()
        listed = _func(project.root, env, "builtin", "run", "list", "--format", "json")
        assert listed.returncode == 0, listed.stderr
        [record] = json.loads(listed.stdout)["runs"]
        run_id = record["run_id"]
        assert record["run_tags"] == {"harness": "claude"}
        with sqlite3.connect(database) as connection:
            rows = connection.execute(
                "SELECT runs.id, runs.job, runs.status, run_tags.key, run_tags.value "
                "FROM runs JOIN run_tags ON run_tags.run_id = runs.id"
            ).fetchall()
        assert rows == [(run_id, "release", "success", "harness", "claude")]
