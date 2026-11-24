"""Rendering of a call the job's declaration does not admit (INVALID, 6.2).

Every case here runs the real ``func`` binary in a subprocess and asserts the
call's answer at the process boundary: **exit 2, no ``File "..."`` traceback**.
That is the INVALID contract — a wrong call is a usage refusal, not a crash —
and the two dispatch paths must honour it on both boots (pitfalls §23): each
call runs twice against one project, cold then warm.

The refused-job trio is stronger: a job with a ``REJECTED_DISCOVERY``
parameter refuses with its reason *whatever its arguments*, before click
parses them (contracts.md §8, DC-1 = B), so every call prints the refusal
naming the job, the parameter and the remedy — one line, exit 2.

"One line" is the call's own answer: exactly one ``Error:`` line. Beside it,
stderr may hold only B-9's boot warnings (one per refused parameter in the
project, printed on every boot whichever job is called), the boot's
plugin-timing notice, and, for a click-level refusal, click's ``Usage:``/``Try``
lines. Anything else, a frame included,
fails.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import surfaces

JOBS = {
    "needs.py": (
        "from __future__ import annotations\n"
        "\n"
        "def needs(p: str) -> str:\n"
        "    return p\n"
    ),
    "injects.py": (
        "from __future__ import annotations\n"
        "\n"
        "from typing import Annotated\n"
        "\n"
        "from functualize._primitives import Provide\n"
        "\n"
        "def injects(p: Annotated[str, Provide('state')]) -> str:\n"
        "    return p\n"
    ),
    "converts.py": (
        "from __future__ import annotations\n"
        "\n"
        "from typing import Annotated\n"
        "\n"
        "from pydantic import Field\n"
        "\n"
        "def converts(p: Annotated[int, Field(ge=1)] = 1) -> int:\n"
        "    return p\n"
    ),
    "refused.py": (
        "from __future__ import annotations\n"
        "\n"
        "class Widget:\n"
        "    def __init__(self, v: str = 'w') -> None:\n"
        "        self.v = v\n"
        "\n"
        "def refused(p: Widget) -> str:\n"
        "    return p.v\n"
    ),
}


def _run(root: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / "config"),
        XDG_DATA_HOME=str(home / "data"),
        XDG_CACHE_HOME=str(home / "cache"),
    )
    return subprocess.run(
        ["func", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _both_boots(root: Path, home: Path, *args: str):
    """One call against one project: the cold boot, then the warm cache."""
    home.mkdir(parents=True, exist_ok=True)
    cold = _run(root, home, *args)
    warm = _run(root, home, *args)
    return cold, warm


def _assert_usage_refusal(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 2, result.stderr
    assert 'File "' not in result.stderr, result.stderr


#: B-9's boot warning for a refused parameter: ``<file>: job '<j>' parameter
#: '<declaration>' is refused. <remedy>.`` Every boot prints one per refused
#: parameter in the project (DC-1 = B), whichever job is called, so it is not
#: part of the call's own answer.
_BOOT_WARNING = re.compile(r": job '[^']+' parameter '[^']+' is refused\. ")
#: click's own usage block around its ``Error:`` line (a click-level refusal).
_CLICK_USAGE = ("Usage: ", "Try '")
#: The boot's plugin-timing notice, printed when a plugin loads slower than its
#: budget; under a loaded machine it appears on any call. Boot noise, not the
#: call's answer.
_PLUGIN_TIMING = re.compile(r"^Plugin '[^']+' took \d+ms to load \(budget: ")


def _refusal_lines(stderr: str) -> list[str]:
    """The call's own answer: one ``Error:`` line, with nothing but B-9's boot
    warnings and click's usage block beside it."""
    lines = [line for line in stderr.splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("Error:")]
    others = [
        line
        for line in lines
        if not line.startswith("Error:")
        and not _BOOT_WARNING.search(line)
        and not line.startswith(_CLICK_USAGE)
        and not _PLUGIN_TIMING.search(line)
    ]
    assert others == [], stderr
    return errors


pytestmark = surfaces("func")


def test_missing_argument_refuses_cleanly(project_tree, tmp_path):
    root = project_tree(jobs=JOBS)
    for result in _both_boots(root, tmp_path / "home-missing", "needs"):
        _assert_usage_refusal(result)
        (line,) = _refusal_lines(result.stderr)
        assert "Missing" in line


def test_unknown_argument_refuses_cleanly(project_tree, tmp_path):
    root = project_tree(jobs=JOBS)
    for result in _both_boots(root, tmp_path / "home-unknown", "needs", "--nope", "1"):
        _assert_usage_refusal(result)


def test_injected_argument_refuses_cleanly(project_tree, tmp_path):
    root = project_tree(jobs=JOBS)
    for result in _both_boots(root, tmp_path / "home-injected", "injects", "--p", "x"):
        _assert_usage_refusal(result)


def test_non_converting_argument_refuses_cleanly(project_tree, tmp_path):
    root = project_tree(jobs=JOBS)
    for result in _both_boots(root, tmp_path / "home-convert", "converts", "--p", "0"):
        _assert_usage_refusal(result)


@pytest.mark.parametrize(
    "args",
    [(), ("--p", "x"), ("x",)],
    ids=["bare", "flag", "extra-positional"],
)
def test_refused_job_refuses_whatever_its_arguments(args, project_tree, tmp_path):
    root = project_tree(jobs=JOBS)
    for result in _both_boots(root, tmp_path / "home-refused", "refused", *args):
        _assert_usage_refusal(result)
        assert not any(
            line.startswith(_CLICK_USAGE) for line in result.stderr.splitlines()
        ), result.stderr
        (line,) = _refusal_lines(result.stderr)
        assert "'refused'" in line, result.stderr
        assert "'p'" in line, result.stderr
        assert "Register one from a plugin" in line, result.stderr


def test_refused_job_help_remains_available_on_both_boots(project_tree, tmp_path):
    root = project_tree(jobs=JOBS)
    for result in _both_boots(
        root, tmp_path / "home-refused-help", "refused", "--help"
    ):
        assert result.returncode == 0, result.stderr
        assert "Usage:" in result.stdout
        assert "Error:" not in result.stderr
