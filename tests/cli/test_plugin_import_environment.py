"""Every CLI mode gives project plugins the same resolved import libraries."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "args",
    [
        ("h1",),
        ("--help",),
        ("mcp", "schema"),
        ("builtin", "info", "schema", "--kind", "job"),
        ("builtin", "shell-init", "bash"),
    ],
)
def test_plugin_sees_convention_lib_in_every_mode(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    project = tmp_path / "project"
    jobs = project / ".functualize" / "jobs"
    plugins = project / ".functualize" / "plugins"
    libs = project / ".functualize" / "lib"
    for directory in (jobs, plugins, libs):
        directory.mkdir(parents=True)
    (jobs / "h1.py").write_text(
        "from functualize.job import job\n@job\ndef h1() -> str:\n    return 'hello'\n"
    )
    (libs / "provlib.py").write_text("class ProvWidget:\n    pass\n")
    (plugins / "import_probe.py").write_text(
        "class ImportProbe:\n"
        "    name = 'import-probe'\n"
        "    version = '1.0.0'\n"
        "    description = 'import environment probe'\n"
        "    def __call__(self, app):\n"
        "        try:\n"
        "            from provlib import ProvWidget\n"
        "            app.di.provide(ProvWidget, ProvWidget())\n"
        "            print('PROVIDER_READY')\n"
        "        except ModuleNotFoundError as exc:\n"
        "            print(f'registration failed: {exc}')\n"
        "plugin = ImportProbe()\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["HOME"] = str(tmp_path / "home")
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["XDG_DATA_HOME"] = str(tmp_path / "data")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    result = subprocess.run(
        [str(Path(sys.executable).with_name("func")), *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "PROVIDER_READY" in output, output
    assert "registration failed" not in output, output
