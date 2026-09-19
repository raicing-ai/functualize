"""`[plugins] disabled` means disabled for `func builtin`, not only for jobs.

`plugin-taxonomy`/T5. Three job handlers (`_handle_bare`, `_handle_group`,
`_handle_job`) read `[plugins] disabled` from the merged config and pass it to
`PluginSources`. **`cli_app` did not** — and `cli_app` is the path every
`func builtin …` command boots through.

The omission was invisible until a plugin that changes a *default* actually
loaded. With `disabled = ["substrate-sqlite"]` in config, `func <job>` honoured
it and wrote to files, while `func builtin why` and `func builtin data show`
ignored it and read a database the run had never written to. Three of the four
doors agreeing is worse than none, because the disagreement only shows up in the
answers.

**This file exists because the fix shipped with nothing defending it.** Unwiring
`PluginSources(disabled=…)` from `cli_app` left `tests/plugins`, `tests/_cli` and
`tests/cli/test_state_mode_report.py` at **1,865 passed, 0 failed**. Found by the
Verify phase's sabotage step.

Asserted through a **subprocess**, not an in-process app, for two reasons. The
defect is in the CLI's own boot path, so anything that constructs a
`FunctualizeApp` directly tests a different function. And the root suite hides
the substrate plugin from discovery so the ambient environment cannot decide a
test's storage backend (`tests/conftest.py::_hide_default_changing_plugins`) —
an in-process monkeypatch a child process does not inherit, which is precisely
what makes a subprocess the honest instrument here.

What is asserted is the rendered output, because that is what a user sees:
`data show` names the file behind every store, and the two backends disagree
about the name.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "functualize_substrate_sqlite.substrate",
    reason="workspace plugins not installed; run `uv sync --all-packages --all-extras`",
)

pytestmark = pytest.mark.installed_plugins

_REPO = Path(__file__).resolve().parents[2]


def _project(tmp_path: Path, config: str) -> Path:
    """A declared project — `.functualize/` is what makes it one."""
    (tmp_path / ".functualize").mkdir()
    (tmp_path / ".functualize.toml").write_text(config, encoding="utf-8")
    return tmp_path


def _data_show(cwd: Path) -> str:
    """Run `func builtin data show` in `cwd`, in its own home.

    **The child gets an isolated HOME, and that is not hygiene — it is
    required.** `tests/conftest.py::_isolate_home` is autouse and points HOME at
    a *fixed* path (`/tmp/functualize_test_fakehome_nonexistent`), shared by
    every worktree on the machine, and a subprocess inherits it through
    `os.environ`. Meanwhile `func` registers itself in
    `<config>/functualize/install.json` on every run, and that registry is
    **append-only by design** — `self doctor` reports a record whose binary no
    longer exists as a WARNING and never removes it.

    So a child launched as `python -c ...` registers `<venv>/bin/-c`, which
    never exists, and `test_self_doctor.py::test_a_recognised_installation_
    reports_ok` fails **for every future run in every checkout**. Measured: it
    did, and the record had to be deleted by hand.
    """
    env = dict(os.environ)
    home = cwd / "_home"
    home.mkdir()
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CACHE_HOME"] = str(home / ".cache")

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from functualize._cli.main import main; main()",
            "builtin",
            "data",
            "show",
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_the_substrate_plugin_decides_where_builtin_commands_look(
    tmp_path: Path,
) -> None:
    """Enabled: every store names the database. This is the T5 storage fix."""
    output = _data_show(_project(tmp_path, 'name = "probe"\n'))

    assert "state.db#runs" in output, output
    assert "runs.json" not in output, output


def test_disabling_the_plugin_sends_them_back_to_the_files(tmp_path: Path) -> None:
    """Disabled: the same command names the JSON files.

    Fails if `cli_app` stops reading `[plugins] disabled` — the output reverts
    to `state.db#…` because the plugin loads anyway.
    """
    output = _data_show(
        _project(
            tmp_path,
            'name = "probe"\n\n[plugins]\ndisabled = ["substrate-sqlite"]\n',
        )
    )

    assert "runs.json" in output, output
    assert "state.db" not in output, output


def test_disabled_matches_the_entry_point_name(tmp_path: Path) -> None:
    """A name that is not the entry point's disables nothing.

    Recorded during T5 and worth pinning rather than leaving as a note:
    `disabled` matches the **entry-point** name, which the rename moved from
    `sqlite` to `substrate-sqlite`. Someone carrying the old spelling forward
    gets no error and no effect.
    """
    output = _data_show(
        _project(tmp_path, 'name = "probe"\n\n[plugins]\ndisabled = ["sqlite"]\n')
    )

    assert "state.db#runs" in output, output
