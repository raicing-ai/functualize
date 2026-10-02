"""E2E: the vault key comes from an unlocked keyring whether or not stdout is a pipe.

Real ``func`` processes, stdout captured (so never a terminal), and a keyring
backend the test controls (``_fake_keyring``). This is the capability test for
the feature: every component test can pass while the run path still gates the
keyring on a TTY — which is exactly the defect the field report was.

Spec A1 (pipe works), A2 (an unrelated job, and ``--help``, never touch the
keyring), A3 (the env key short-circuits), A4 (a keyring that never answers
costs the configured wait, then an honest refusal), A5 (no keyring: refused at
once) and A6 (many lookups, one keyring call).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from functualize.app.utils import ExitCode

_REPO = Path(__file__).resolve().parents[2]
_KEY_HEX = "5c" * 32
_SECRET = "E2E-UNLOCK-PLAINTEXT-7d2e-never-printed"  # gitleaks:allow
_FIELDS = [f"s{i}" for i in range(10)]

_JOBS = f"""
from pydantic import BaseModel, Field

from functualize.job.decorators import job
from functualize.types import Secret


class DeployConfig(BaseModel):
    api_token: Secret[str] = Field(description="Required credential")


@job
def deploy(config: DeployConfig) -> None:
    print("token:" + config.api_token.get_secret_value())


class ManyConfig(BaseModel):
{"".join(f"    {name}: Secret[str] = Field(description='x')" + chr(10) for name in _FIELDS)}

@job
def many(config: ManyConfig) -> None:
    print("fields:" + ",".join(
        getattr(config, name).get_secret_value() for name in {_FIELDS!r}
    ))


@job
def hello() -> None:
    print("hello")
"""


def _func() -> Path:
    func = Path(sys.executable).parent / "func"
    if not func.exists():  # pragma: no cover - editable installs have it
        pytest.skip("no `func` console script in this environment")
    return func


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    (root / "jobs").mkdir()
    (root / "jobs" / "vaultjobs.py").write_text(_JOBS)
    (root / "pyproject.toml").write_text(
        '[tool.functualize]\njobs_directories = ["jobs"]\n'
    )
    return root


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """A child environment with its own HOME and XDG roots, and no vault key."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("FUNCTUALIZE_", "XDG_", "FAKE_KEYRING_"))
    }
    env.update(
        HOME=str(tmp_path / "home"),
        XDG_DATA_HOME=str(tmp_path / "data"),
        XDG_CACHE_HOME=str(tmp_path / "cache"),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        PYTHONPATH=os.pathsep.join(
            p for p in (str(_REPO), env.get("PYTHONPATH", "")) if p
        ),
        PYTHON_KEYRING_BACKEND="tests.integration._fake_keyring.FakeKeyring",
        FAKE_KEYRING_CALLS=str(tmp_path / "keyring-calls.log"),
        FAKE_KEYRING_KEY=_KEY_HEX,
        COLUMNS="100",
    )
    env.update(extra)
    return env


def _run(
    project: Path,
    tmp_path: Path,
    args: list[str],
    *,
    stdin: str | None = None,
    **env: str,
) -> Any:
    return subprocess.run(  # noqa: S603
        [str(_func()), *args],
        cwd=project,
        input=stdin,
        capture_output=True,
        text=True,
        env=_env(tmp_path, **env),
        timeout=120,
    )


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "keyring-calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _provision(project: Path, tmp_path: Path, *paths: str) -> None:
    """Store direct entries through a real `func`, with the env key, so the
    store and the later runs agree about which vault they mean."""
    for path in paths:
        stored = _run(
            project,
            tmp_path,
            ["builtin", "vault", "put", path, "--stdin"],
            stdin=f"{_SECRET}-{path.rsplit('.', 1)[-1]}",
            FUNCTUALIZE_VAULT_KEY=_KEY_HEX,
            FAKE_KEYRING_MODE="raises",
        )
        assert stored.returncode == ExitCode.OK, stored.stderr
    (tmp_path / "keyring-calls.log").unlink(missing_ok=True)


class TestAPipedRunReadsAnUnlockedKeyring:
    def test_a1_the_stored_value_arrives_with_stdout_piped(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        result = _run(project, tmp_path, ["deploy"], FAKE_KEYRING_MODE="unlocked")

        assert result.returncode == ExitCode.OK, result.stderr[-1500:]
        assert f"token:{_SECRET}-api_token" in result.stdout
        assert _calls(tmp_path).count("get_password") == 1


class TestARunThatNeedsNoKeyNeverAsks:
    def test_a2_an_unrelated_job_never_touches_the_keyring(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        result = _run(project, tmp_path, ["hello"], FAKE_KEYRING_MODE="raises")

        assert result.returncode == ExitCode.OK, result.stderr[-1500:]
        assert "hello" in result.stdout
        assert _calls(tmp_path) == []

    def test_a2_help_never_touches_the_keyring(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        result = _run(project, tmp_path, ["--help"], FAKE_KEYRING_MODE="raises")

        assert result.returncode == ExitCode.OK, result.stderr[-1500:]
        assert _calls(tmp_path) == []

    def test_a3_an_env_key_short_circuits_the_keyring(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        result = _run(
            project,
            tmp_path,
            ["deploy"],
            FAKE_KEYRING_MODE="raises",
            FUNCTUALIZE_VAULT_KEY=_KEY_HEX,
        )

        assert result.returncode == ExitCode.OK, result.stderr[-1500:]
        assert f"token:{_SECRET}-api_token" in result.stdout
        assert _calls(tmp_path) == []


class TestAKeyringThatCannotAnswer:
    def test_a4_a_blocking_keyring_costs_the_configured_wait(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        started = time.monotonic()
        result = _run(
            project,
            tmp_path,
            ["deploy"],
            FAKE_KEYRING_MODE="locked-blocks",
            FUNCTUALIZE_VAULT_KEYRING_TIMEOUT="1s",
        )
        elapsed = time.monotonic() - started

        assert result.returncode == ExitCode.REFUSED, result.stderr[-1500:]
        # The wait itself is 1 s; the rest is process start-up and boot.
        assert 1.0 <= elapsed < 8.0, elapsed
        message = result.stderr
        assert "locked or did not answer" in message
        assert "vault unlock" in message
        assert "FUNCTUALIZE_VAULT_KEY" in message
        assert "vault remove" not in message
        assert "vault clear" not in message
        # A direct entry: sync cannot restore it, so it is never offered.
        assert "vault sync" not in message
        assert _SECRET not in result.stdout + result.stderr

    def test_a5_no_keyring_is_refused_without_waiting(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        started = time.monotonic()
        result = _run(
            project,
            tmp_path,
            ["deploy"],
            PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring",
        )
        elapsed = time.monotonic() - started

        assert result.returncode == ExitCode.REFUSED, result.stderr[-1500:]
        # Well under the 30 s default the run would otherwise wait.
        assert elapsed < 15.0, elapsed
        assert "no OS keyring is reachable" in result.stderr
        assert "vault remove" not in result.stderr


class TestOneWaitPerProcess:
    def test_a6_many_lookups_one_keyring_call(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, *(f"many.{name}" for name in _FIELDS))

        result = _run(project, tmp_path, ["many"], FAKE_KEYRING_MODE="unlocked")

        assert result.returncode == ExitCode.OK, result.stderr[-1500:]
        assert result.stdout.count(_SECRET) == len(_FIELDS)
        assert _calls(tmp_path).count("get_password") == 1

    def test_a6_many_lookups_against_a_blocking_keyring_wait_once(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, *(f"many.{name}" for name in _FIELDS))

        started = time.monotonic()
        result = _run(
            project,
            tmp_path,
            ["many"],
            FAKE_KEYRING_MODE="locked-blocks",
            FUNCTUALIZE_VAULT_KEYRING_TIMEOUT="1s",
        )
        elapsed = time.monotonic() - started

        assert result.returncode == ExitCode.REFUSED, result.stderr[-1500:]
        assert elapsed < 8.0, elapsed
        assert _calls(tmp_path).count("get_password") == 1
