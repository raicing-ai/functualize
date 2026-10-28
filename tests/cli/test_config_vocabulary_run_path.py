"""The unknown-key checker stays out of a warm job invocation."""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.perf.test_startup_budget import BUDGET_WARM_COMMAND_MS


@pytest.mark.perf_budget
def test_warm_job_does_not_import_vocabulary_or_exceed_budget(tmp_path: Path) -> None:
    console_script = Path(sys.executable).parent / "func"
    if not console_script.exists():
        pytest.skip("no func console script beside the interpreter")

    project = tmp_path / "project"
    jobs = project / "jobs"
    jobs.mkdir(parents=True)
    (project / ".functualize.toml").write_text('jobs_directories = ["jobs"]\n')
    (jobs / "ping.py").write_text(
        "from functualize.job import job\n\n"
        "@job()\n"
        "def ping() -> str:\n"
        '    return "pong"\n'
    )

    # A fresh interpreter loads this before the console entry point. If the
    # job path imports the checker, the command exits nonzero at that import.
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(
        "import builtins\n"
        "_original_import = builtins.__import__\n"
        "def _guard(name, *args, **kwargs):\n"
        "    if name.startswith('functualize._cli.data.config_vocabulary'):\n"
        "        raise RuntimeError('config vocabulary reached a job run')\n"
        "    return _original_import(name, *args, **kwargs)\n"
        "builtins.__import__ = _guard\n"
    )
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "PYTHONPATH": os.pathsep.join(
            filter(None, (str(hook), os.getenv("PYTHONPATH", "")))
        ),
    }

    def invoke() -> tuple[float, subprocess.CompletedProcess[str]]:
        start = time.perf_counter()
        result = subprocess.run(
            [str(console_script), "ping"],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return (time.perf_counter() - start) * 1000, result

    _, cold = invoke()
    assert cold.returncode == 0, cold.stderr
    warm = [invoke() for _ in range(3)]
    assert all(result.returncode == 0 for _, result in warm), [
        result.stderr for _, result in warm
    ]
    median = statistics.median(elapsed for elapsed, _ in warm)
    print(f"warm func ping median: {median:.0f}ms; budget: {BUDGET_WARM_COMMAND_MS:.0f}ms")
    assert median < BUDGET_WARM_COMMAND_MS, (
        f"warm job median {median:.0f}ms exceeded {BUDGET_WARM_COMMAND_MS:.0f}ms"
    )
