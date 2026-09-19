"""AC-10: a submitted secret appears nowhere it should not.

The claim is about *bytes on disk and bytes on a stream*, so this reads files
and captured output rather than trusting that a report type has no field for a
value. A round-trip test proves nothing here: it passes just as happily against
a store that writes plaintext.

The SQLite sidecars are scanned deliberately. The store runs in WAL mode, so a
value can sit in `vault.db-wal` for some time after the write that produced it
— a file a scan of `vault.db` alone would never look at.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from functualize._app.state import AppState
from functualize._cli.builtins import register_builtin_commands
from functualize.app import FunctualizeApp, JobSources
from functualize.app.core import request_for

#: Long, unique and structured so that an accidental match is not credible.
_SECRET = "PLAINTEXT-SWEEP-8b31f7d2-e45a-must-never-appear"  # gitleaks:allow

_JOB = '''
from pydantic import BaseModel, Field

from functualize.job import RunContext
from functualize.job.decorators import job
from functualize.types import Secret


class DeployConfig(BaseModel):
    api_token: Secret[str] = Field(description="Required credential")


@job
def deploy(config: DeployConfig, rc: RunContext) -> str:
    """Log the secret deliberately, to prove redaction is doing the work."""
    rc.log(f"token is {config.api_token}")
    return "deployed"
'''


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from functualize._config.vault_keys import ENV_VAR, generate_key

    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    (root / "jobs").mkdir()
    (root / "jobs" / "deploy.py").write_text(_JOB)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv(ENV_VAR, generate_key())
    monkeypatch.chdir(root)
    AppState.reset()
    yield root
    AppState.reset()


def _app(project: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "sweep", job_sources=JobSources(directories=[str(project / "jobs")], lazy=False)
    )


def _run(args: list[str], *, app: Any = None, stdin: str | None = None) -> Any:
    group = click.Group(name="func")
    register_builtin_commands(group)
    return CliRunner().invoke(
        group, ["builtin", "vault", *args], obj={"app": app} if app else {}, input=stdin
    )


def _store_files(tmp_path_root: Path) -> list[Path]:
    """Every file the vault could have written, sidecars included."""
    data = tmp_path_root / "data"
    return [p for p in data.rglob("*") if p.is_file()]


class TestTheSweep:
    def test_the_secret_is_absent_from_every_surface(
        self, project: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One provisioning, then every command, then the run.

        Swept together rather than per-command on purpose: a leak that only
        appears when `inspect` runs after `put` is exactly the kind a
        per-command test would miss.
        """
        outputs: list[str] = []

        with caplog.at_level(logging.DEBUG):
            outputs.append(_run(["init", "--key-source", "env"]).output)
            outputs.append(
                _run(
                    ["put", "deploy.api_token", "--stdin"],
                    app=_app(project),
                    stdin=_SECRET,
                ).output
            )
            for args in (
                ["inspect", "deploy.api_token"],
                ["inspect", "deploy.api_token", "--json"],
                ["list"],
                ["list", "--json"],
                ["status"],
                ["status", "--json"],
            ):
                outputs.append(_run(args, app=_app(project)).output)

            result = _app(project).execute(request_for("deploy"))
            assert result.return_value == "deployed"

            outputs.append(
                _run(
                    ["remove", "deploy.api_token", "--yes", "--json"],
                    app=_app(project),
                ).output
            )
            outputs.append(_run(["clear", "--yes"]).output)

        for captured in outputs:
            assert _SECRET not in captured, captured[:400]
        assert _SECRET not in caplog.text

    def test_the_secret_is_absent_from_the_database_and_its_sidecars(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Byte-level, and the sidecars are the half a naive scan forgets.

        WAL means a freshly written value can live in `vault.db-wal` rather
        than in `vault.db`, so scanning only the database would report clean
        while the plaintext sat beside it.
        """
        _run(["init", "--key-source", "env"])
        _run(["put", "deploy.api_token", "--stdin"], app=_app(project), stdin=_SECRET)

        files = _store_files(tmp_path)
        assert files, "expected the vault to have written something"

        needle = _SECRET.encode()
        for path in files:
            assert needle not in path.read_bytes(), path

    def test_the_sweep_would_notice_plaintext(
        self, project: Path, tmp_path: Path
    ) -> None:
        """The control. A scan that cannot fail proves nothing.

        Writes the same bytes into the vault directory by hand and confirms the
        assertion above would have caught them — so a green sweep means the
        encryption is working, not that the scan is looking in the wrong place.
        """
        _run(["init", "--key-source", "env"])
        _run(["put", "deploy.api_token", "--stdin"], app=_app(project), stdin=_SECRET)

        planted = next(iter(_store_files(tmp_path))).parent / "planted.txt"
        planted.write_bytes(_SECRET.encode())

        hits = [p for p in _store_files(tmp_path) if _SECRET.encode() in p.read_bytes()]

        assert planted in hits, "the sweep does not look where it claims to"

    def test_an_exception_does_not_carry_the_value(
        self, project: Path, tmp_path: Path
    ) -> None:
        """Refusals are a leak surface: they are printed, logged and often
        pasted into an issue."""
        from functualize.app.vault import VaultEntryExistsError, vault_put

        _run(["init", "--key-source", "env"])
        app = _app(project)
        _run(["put", "deploy.api_token", "--stdin"], app=app, stdin=_SECRET)

        with pytest.raises(VaultEntryExistsError) as exc:
            vault_put(app, "deploy.api_token", _SECRET)

        assert _SECRET not in str(exc.value)
        assert _SECRET not in repr(exc.value)

    def test_the_json_payloads_hold_no_value_anywhere_in_the_tree(
        self, project: Path
    ) -> None:
        """Checked structurally rather than by substring, so a value nested in
        a field nobody thought about is still caught."""
        _run(["init", "--key-source", "env"])
        app = _app(project)
        _run(["put", "deploy.api_token", "--stdin"], app=app, stdin=_SECRET)

        def _leaves(node: Any) -> list[Any]:
            if isinstance(node, dict):
                return [x for v in node.values() for x in _leaves(v)]
            if isinstance(node, list):
                return [x for v in node for x in _leaves(v)]
            return [node]

        for args in (
            ["inspect", "deploy.api_token", "--json"],
            ["list", "--json"],
            ["status", "--json"],
        ):
            payload = json.loads(_run(args, app=app).stdout)
            assert _SECRET not in _leaves(payload), args
