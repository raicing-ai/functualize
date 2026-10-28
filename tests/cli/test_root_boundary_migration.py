"""The `root = true` migration, replayed with real data (AC10).

Before the fix a nested ``root = true`` project with no ``.functualize/`` of its
own adopted its ancestor's folder: its runs and workflow scopes were written to
``<ancestor>/.functualize/``, and its vault was the ancestor's (keyed by the
ancestor's directory). After the fix the nested root is its own standalone
project, so none of that is selected any more — and none of it is moved.

This test produces that data the way a user did, with the **pre-fix build**:
the tree of ``f30285c`` (the authoring baseline), exported from the object DB
and run with this checkout's interpreter. Then, on this checkout:

1. the nested root sees none of the ancestor's runs, scopes or vault entries,
   and the ancestor's files hash the same (G10);
2. the documented migration (``docs/guides/configuration.md`` § *Project
   boundaries and `root = true`*) — ``mkdir .functualize``, copy ``runs.json``
   and ``scopes.json``, ``func builtin data clear``, ``func builtin vault put``
   again — gives the nested root the copied records and its own vault entry,
   and *not* the ancestor's other entries.

Skipped, with the reason, when ``f30285c`` is not in the object DB (a shallow
clone, or after the branch it lives on is gone).

Marked ``real_state_root``: the subject is the state path itself. Every ``func``
runs in a subprocess with ``HOME`` and the ``XDG_*`` roots under ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from functualize._primitives.locator import compute_project_id

pytestmark = pytest.mark.real_state_root

PROJECT_ROOT = Path(__file__).parent.parent.parent

#: The authoring baseline: the last build before the boundary fix.
PRE_FIX = "f30285c"

_PIPELINE = '''
from functualize.job.decorators import job
from functualize.workflow import END, Edge, Step, workflow


@job
def fetch() -> str:
    """Fetch."""
    return "fetched"


@job
def store() -> str:
    """Store."""
    return "stored"


@workflow(
    steps=[Step(fetch), Step(store)],
    edges=[Edge("fetch", "store"), Edge("store", END)],
)
def pipeline() -> None:
    """Fetch, then store."""
'''

_SECRET_JOB = '''
from pydantic import BaseModel, Field

from functualize.job.decorators import job
from functualize.types import Secret


class {cls}(BaseModel):
    api_token: Secret[str] = Field(description="Required credential")


@job
def {name}(config: {cls}) -> None:
    """Print the token, so the test can tell which value arrived."""
    print("TOKEN", config.api_token.get_secret_value())
'''


@pytest.fixture(scope="module")
def pre_fix_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``src/`` and ``plugins/`` of the pre-fix commit, exported from git."""
    found = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "cat-file", "-e", f"{PRE_FIX}^{{commit}}"],
        capture_output=True,
    )
    if found.returncode != 0:
        pytest.skip(f"pre-fix commit {PRE_FIX} is not in this clone's object DB")
    tree = tmp_path_factory.mktemp("pre_fix")
    archive = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "archive", PRE_FIX, "src", "plugins"],
        capture_output=True,
        check=True,
    )
    subprocess.run(["tar", "-x", "-C", str(tree)], input=archive.stdout, check=True)
    return tree


def _env(tmp_path: Path, vault_key: str) -> dict[str, str]:
    """Home and XDG roots under ``tmp_path``; one vault key for every run."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("FUNCTUALIZE_", "XDG_")) and k != "PYTHONPATH"
    }
    home = tmp_path / "home"
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_CACHE_HOME=str(home / ".cache"),
        FUNCTUALIZE_VAULT_KEY=vault_key,
        COLUMNS="1000",
    )
    return env


def _run_head(
    *args: str, cwd: Path, env: dict[str, str], stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """`func` from this checkout."""
    return subprocess.run(
        ["uv", "run", "--project", str(PROJECT_ROOT), "func", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
        input=stdin if stdin is not None else "",
        timeout=60,
    )


def _run_pre_fix(
    tree: Path,
    *args: str,
    cwd: Path,
    env: dict[str, str],
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """`func` from the pre-fix tree: its own `src/` and plugins shadow ours."""
    paths = [tree / "src", *sorted(tree.glob("plugins/*/*/src"))]
    return subprocess.run(
        [sys.executable, "-m", "functualize", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={**env, "PYTHONPATH": os.pathsep.join(str(p) for p in paths)},
        input=stdin if stdin is not None else "",
        timeout=60,
    )


def _ok(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _data(stdout: str) -> dict[str, str]:
    """``Mode``, run and scope counts and their files from `builtin data show`."""
    found = {
        "mode": re.search(r"^Mode:\s+(.*)$", stdout, re.MULTILINE),
        "runs": re.search(r"^Runs:\s+(\d+) — (\S+)", stdout, re.MULTILINE),
        "scopes": re.search(r"^Scopes:\s+(\d+) of \d+ — (\S+)", stdout, re.MULTILINE),
    }
    assert all(m is not None for m in found.values()), stdout
    mode, runs, scopes = found["mode"], found["runs"], found["scopes"]
    assert mode is not None and runs is not None and scopes is not None
    return {
        "mode": mode.group(1),
        "runs": runs.group(1),
        "runs_file": runs.group(2),
        "scopes": scopes.group(1),
        "scopes_file": scopes.group(2),
    }


def _vault(cwd: Path, env: dict[str, str]) -> tuple[Path, list[tuple[str, str]]]:
    """``(vault file, sorted (target, field))`` from `builtin vault list --json`."""
    listed = json.loads(
        _ok(_run_head("builtin", "vault", "list", "--json", cwd=cwd, env=env))
    )
    entries = sorted((e["target"], e["field"]) for e in listed["entries"])
    return Path(listed["path"]), entries


def _hashes(*roots: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digests[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _n4_tree(tmp_path: Path) -> tuple[Path, Path]:
    """N4 with real jobs: ``(outer, nested)``.

    The ancestor is a project with its own ``.functualize/`` and a secret job
    of its own (``release``); the nested root declares ``root = true`` and its
    jobs, and has no ``.functualize/``.
    """
    outer = tmp_path / "work" / "outer"
    nested = outer / "nested"
    (outer / ".functualize" / "jobs").mkdir(parents=True)
    (outer / ".functualize" / "jobs" / "release.py").write_text(
        _SECRET_JOB.format(cls="ReleaseConfig", name="release")
    )
    (outer / ".functualize.toml").write_text("")
    (nested / "jobs").mkdir(parents=True)
    (nested / "jobs" / "pipeline.py").write_text(_PIPELINE)
    (nested / "jobs" / "deploy.py").write_text(
        _SECRET_JOB.format(cls="DeployConfig", name="deploy")
    )
    (nested / ".functualize.toml").write_text(
        'root = true\njobs_directories = ["jobs"]\n'
    )
    return outer, nested


def test_migration_from_an_adopted_ancestor_folder(
    tmp_path: Path, pre_fix_tree: Path
) -> None:
    from functualize._config.vault_keys import generate_key

    outer, nested = _n4_tree(tmp_path)
    env = _env(tmp_path, generate_key())
    ancestor_folder = outer / ".functualize"
    ancestor_vault = (
        tmp_path
        / "home"
        / ".local"
        / "share"
        / "functualize"
        / "vaults"
        / compute_project_id(outer)
    )

    # --- The pre-fix build: the nested root writes into its ancestor. -------
    probe = _run_pre_fix(pre_fix_tree, "builtin", "data", "show", cwd=nested, env=env)
    assert (
        _data(_ok(probe))["mode"]
        == f"project (.functualize/ found at {ancestor_folder})"
    )
    _ok(_run_pre_fix(pre_fix_tree, "fetch", cwd=nested, env=env))
    _ok(_run_pre_fix(pre_fix_tree, "pipeline", cwd=nested, env=env))
    _ok(
        _run_pre_fix(
            pre_fix_tree,
            *("builtin", "vault", "put", "--job", "deploy", "--field", "api_token"),
            "--stdin",
            cwd=nested,
            env=env,
            stdin="ANCESTOR-DEPLOY",
        )
    )
    _ok(
        _run_pre_fix(
            pre_fix_tree,
            *("builtin", "vault", "put", "--job", "release", "--field", "api_token"),
            "--stdin",
            cwd=outer,
            env=env,
            stdin="ANCESTOR-RELEASE",
        )
    )
    assert "TOKEN ANCESTOR-DEPLOY" in _ok(
        _run_pre_fix(pre_fix_tree, "deploy", cwd=nested, env=env)
    )
    adopted = _data(
        _ok(_run_pre_fix(pre_fix_tree, "builtin", "data", "show", cwd=nested, env=env))
    )
    assert adopted["runs_file"] == str(ancestor_folder / "runs.json")
    assert adopted["scopes_file"] == str(ancestor_folder / "scopes.json")
    assert int(adopted["runs"]) > 0
    assert int(adopted["scopes"]) == 1
    assert _vault(outer, env) == (
        ancestor_vault / "vault.db",
        [("deploy", "api_token"), ("release", "api_token")],
    )
    before = _hashes(ancestor_folder, ancestor_vault)
    assert str(ancestor_folder / "runs.json") in before
    assert str(ancestor_vault / "vault.db") in before

    # --- (1) This build: the nested root sees none of it (G10). -------------
    fresh = _data(_ok(_run_head("builtin", "data", "show", cwd=nested, env=env)))
    assert fresh["mode"].startswith("standalone"), fresh["mode"]
    assert (fresh["runs"], fresh["scopes"]) == ("0", "0")
    own_vault = ancestor_vault.parent / compute_project_id(nested) / "vault.db"
    assert _vault(nested, env) == (own_vault, [])
    assert _vault(nested / "jobs", env) == (own_vault, [])
    assert "TOKEN" not in _run_head("deploy", cwd=nested, env=env).stdout
    _ok(_run_head("fetch", cwd=nested, env=env))
    assert _hashes(ancestor_folder, ancestor_vault) == before

    # --- (2) The documented migration, step by step. ------------------------
    own_folder = nested / ".functualize"
    own_folder.mkdir()
    for name in ("runs.json", "scopes.json"):
        (own_folder / name).write_bytes((ancestor_folder / name).read_bytes())
    _ok(_run_head("builtin", "data", "clear", cwd=nested, env=env))
    _ok(
        _run_head(
            *("builtin", "vault", "put", "--job", "deploy", "--field", "api_token"),
            "--stdin",
            cwd=nested,
            env=env,
            stdin="NESTED-DEPLOY",
        )
    )

    migrated = _data(_ok(_run_head("builtin", "data", "show", cwd=nested, env=env)))
    assert migrated["mode"] == f"project (.functualize/ found at {own_folder})"
    assert (migrated["runs"], migrated["scopes"]) == (
        adopted["runs"],
        adopted["scopes"],
    )
    assert migrated["runs_file"] == str(own_folder / "runs.json")
    from_sub = nested / "jobs"
    assert (
        _data(_ok(_run_head("builtin", "data", "show", cwd=from_sub, env=env)))
        == migrated
    )
    assert _vault(nested, env) == (own_vault, [("deploy", "api_token")])
    assert "TOKEN NESTED-DEPLOY" in _ok(_run_head("deploy", cwd=nested, env=env))
    assert _hashes(ancestor_folder, ancestor_vault) == before
