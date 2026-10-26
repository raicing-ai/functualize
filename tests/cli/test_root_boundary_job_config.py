"""`root = true` bounds both stages of job-config resolution (G12–G18).

Job configuration (``config.<slot>.toml``) is found in two stages, and neither
read ``root = true``:

1. ``discover_config_path`` walks up from the cwd to the first directory
   holding a ``config.<slot>.*`` file;
2. ``build_resolution_chain`` layers that directory and every ancestor up to
   ``~``.

So a nested root with no job config of its own anchored on the ancestor's
``config.base.toml`` (stage 1), and one with a file missing a key still took
that key from the ancestor (stage 2). Both stages now stop at the root, for
``func`` and for a programmatic ``FunctualizeApp`` alike, on boot and on
``refresh()``. The user-global source and inheritance without a root are
unchanged.

Each gate reports the value the job printed **and** the file the value came
from, read from ``func builtin info --job greeter.greet`` (*JobConfig* table,
``Source`` column).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Use the project root so `uv run` picks up the workspace
PROJECT_ROOT = Path(__file__).parent.parent.parent

_GREETER = '''\
from pydantic import BaseModel

JOB_GROUP = "greeter"


class GreetConfig(BaseModel):
    greeting: str = "hello-default"


def greet(config: GreetConfig) -> None:
    """Print the configured greeting."""
    print(f"GREETING = {config.greeting}")
'''


def _env(tmp_path: Path) -> dict[str, str]:
    """A process environment whose home and XDG roots live under ``tmp_path``."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("FUNCTUALIZE_", "XDG_"))
    }
    home = tmp_path / "home"
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
        COLUMNS="1000",
    )
    return env


def _run_func(
    *args: str, cwd: Path, env: dict[str, str], timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    """Run `uv run func` with the given args in the specified directory."""
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        timeout=timeout,
    )


def _greeting(cwd: Path, env: dict[str, str], *flags: str) -> tuple[str, str]:
    """``(printed greeting, contributing source)`` for ``greeter.greet``."""
    run = _run_func(*flags, "greeter", "greet", cwd=cwd, env=env)
    assert run.returncode == 0, run.stderr
    printed = re.search(r"^GREETING = (\S+)$", run.stdout, re.MULTILINE)
    assert printed is not None, run.stdout

    info = _run_func(
        *flags, "builtin", "info", "--job", "greeter.greet", cwd=cwd, env=env
    )
    assert info.returncode == 0, info.stderr
    row = re.search(r"│\s*greeting\s*│\s*(\S+)\s*│\s*(.+?)\s*│", info.stdout)
    assert row is not None, info.stdout
    assert row.group(1) == printed.group(1), info.stdout
    return printed.group(1), row.group(2)


def _tree(tmp_path: Path, *, root: bool = True) -> tuple[Path, Path]:
    """N9: the ancestor's ``config.base.toml`` sets the greeting.

    Returns ``(outer, nested)``. The job lives in the nested project's
    convention directory; ``root`` decides whether the nested file declares
    the boundary.
    """
    outer = tmp_path / "work" / "outer"
    nested = outer / "nested"
    jobs = nested / ".functualize" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "greeter.py").write_text(_GREETER)
    (outer / "config.base.toml").write_text('[greeter.greet]\ngreeting = "ANCESTOR"\n')
    (nested / ".functualize.toml").write_text("root = true\n" if root else "")
    return outer, nested


class TestStageOneStopsAtTheRoot:
    """G12: discovery does not anchor on the ancestor's job config."""

    def test_g12_ancestor_base_file_does_not_apply(self, tmp_path: Path) -> None:
        outer, nested = _tree(tmp_path)

        value, source = _greeting(nested, _env(tmp_path))

        assert value == "hello-default"
        assert str(outer / "config.base.toml") not in source


class TestStageTwoStopsAtTheRoot:
    """G13: layering does not reach above the root for a missing key."""

    def test_g13_missing_key_is_not_taken_from_the_ancestor(
        self, tmp_path: Path
    ) -> None:
        outer, nested = _tree(tmp_path)
        (nested / "config.base.toml").write_text("[other]\nx = 1\n")

        value, source = _greeting(nested, _env(tmp_path))

        assert value == "hello-default"
        assert str(outer / "config.base.toml") not in source


class TestInsideTheRootNothingChanges:
    """G14–G16: order inside the root, no-root inheritance, the global source."""

    def test_g14_environment_overlay_still_wins_over_base(self, tmp_path: Path) -> None:
        _outer, nested = _tree(tmp_path)
        (nested / "config.base.toml").write_text(
            '[greeter.greet]\ngreeting = "NESTED-BASE"\n'
        )
        (nested / "config.dev.toml").write_text(
            '[greeter.greet]\ngreeting = "NESTED-DEV"\n'
        )

        value, source = _greeting(nested, _env(tmp_path))

        assert value == "NESTED-DEV"
        assert str(nested / "config.dev.toml") in source

    def test_g15_without_a_root_the_ancestor_still_applies(
        self, tmp_path: Path
    ) -> None:
        outer, nested = _tree(tmp_path, root=False)

        value, source = _greeting(nested, _env(tmp_path))

        assert value == "ANCESTOR"
        assert str(outer / "config.base.toml") in source

    def test_g16_user_global_job_config_still_applies_under_a_root(
        self, tmp_path: Path
    ) -> None:
        """The user-global job-config source is the platform data directory.

        ``search_platform_user`` reads ``$XDG_DATA_HOME/<app>/``; that is the
        file a user puts machine-wide job defaults in.
        """
        outer, nested = _tree(tmp_path)
        (outer / "config.base.toml").unlink()
        env = _env(tmp_path)
        user_dir = Path(env["XDG_DATA_HOME"]) / "functualize"
        user_dir.mkdir(parents=True)
        (user_dir / "config.base.toml").write_text(
            '[greeter.greet]\ngreeting = "USER-GLOBAL"\n'
        )

        value, source = _greeting(nested, env)

        assert value == "USER-GLOBAL"
        assert str(user_dir / "config.base.toml") in source


class TestAnExplicitConfigDirectoryStopsAtItsRoot:
    """G17 — D4 (a): an explicit directory layers up to *its* root, no further."""

    def test_g17_explicit_directory_under_a_root(self, tmp_path: Path) -> None:
        outer, nested = _tree(tmp_path)
        cfg = nested / "cfg"
        cfg.mkdir()
        (cfg / "config.base.toml").write_text("[other]\nx = 1\n")

        value, source = _greeting(
            nested, _env(tmp_path), "--config-directory", str(cfg)
        )

        assert value == "hello-default"
        assert str(outer / "config.base.toml") not in source


_PROGRAMMATIC = """\
from functualize import FunctualizeApp
from functualize.app import JobSources
from functualize._types.run_request import RunRequest

app = FunctualizeApp(
    name="greeter-app", job_sources=JobSources(directories=[".functualize/jobs"])
)
app.execute(RunRequest(job_name="greeter.greet", surface="app.execute"))
app.refresh()
app.execute(RunRequest(job_name="greeter.greet", surface="app.execute"))
"""


class TestAProgrammaticAppStopsAtTheRoot:
    """G18: the rule is the program's, not `func`'s — boot and refresh agree."""

    @pytest.mark.parametrize("root", [True, False], ids=["root", "no-root"])
    def test_g18_boot_and_refresh(self, tmp_path: Path, root: bool) -> None:
        _outer, nested = _tree(tmp_path, root=root)
        script = tmp_path / "programmatic.py"
        script.write_text(_PROGRAMMATIC)

        run = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=str(nested),
            env=_env(tmp_path),
            timeout=60,
        )

        assert run.returncode == 0, run.stderr
        printed = re.findall(r"^GREETING = (\S+)$", run.stdout, re.MULTILINE)
        expected = "hello-default" if root else "ANCESTOR"
        assert printed == [expected, expected]
