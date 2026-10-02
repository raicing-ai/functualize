"""E2E: an unlocked keyring answers a piped run; a locked one refuses it at once.

Real ``func`` processes, stdout captured (so never a terminal), ``keyring``'s
real Secret Service backend, functualize's real Linux keyring adapter — and a
fake ``secretstorage`` underneath (``_fake_keyring``), so the keyring is one the
test controls and nothing reaches a real session bus.

Spec A1 (pipe works), A2 (an unrelated job, and ``--help``, never touch the
keyring), A3 (the env key short-circuits), A4' (a locked keyring refuses a
piped run at once, with no unlock prompt requested), A5 (no keyring), A6 (many
lookups, one read), and the unlock-elsewhere story: ``vault unlock`` in a
terminal, then the piped run works; cancelled, it does not.
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

#: The two-line `secretstorage` package that stands in for the real one.
_SHIM = (
    "import tests.integration._fake_keyring as _fake\n"
    "globals().update({k: getattr(_fake, k) for k in dir(_fake) "
    "if not k.startswith('__') or k == '__version_tuple__'})\n"
    "from . import exceptions\n"
)
_SHIM_EXCEPTIONS = (
    "from tests.integration._fake_keyring import (\n"
    "    ItemNotFoundException, LockedException,\n"
    "    SecretServiceNotAvailableException, SecretStorageException,\n"
    ")\n"
)


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
    shim = tmp_path / "fakesite" / "secretstorage"
    shim.mkdir(parents=True)
    (shim / "__init__.py").write_text(_SHIM)
    (shim / "exceptions.py").write_text(_SHIM_EXCEPTIONS)
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
            p
            for p in (str(tmp_path / "fakesite"), str(_REPO), env.get("PYTHONPATH", ""))
            if p
        ),
        PYTHON_KEYRING_BACKEND="keyring.backends.SecretService.Keyring",
        FAKE_KEYRING_CALLS=str(tmp_path / "keyring-calls.log"),
        FAKE_KEYRING_STATE=str(tmp_path / "keyring-state.json"),
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
        assert _calls(tmp_path).count("get_secret") == 1
        assert "unlock" not in _calls(tmp_path)


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


class TestALockedKeyringRefusesAtOnce:
    def test_a4_a_locked_keyring_refuses_a_piped_run_without_a_prompt(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        started = time.monotonic()
        result = _run(
            project,
            tmp_path,
            ["deploy"],
            FAKE_KEYRING_MODE="locked",
            FUNCTUALIZE_VAULT_KEYRING_TIMEOUT="30s",
        )
        elapsed = time.monotonic() - started

        assert result.returncode == ExitCode.REFUSED, result.stderr[-1500:]
        # Refused at once: nowhere near the 30 s keyring_timeout. What is left
        # is process start-up and boot.
        assert elapsed < 10.0, elapsed
        assert "unlock" not in _calls(tmp_path)
        message = result.stderr
        assert "keyring is locked" in message
        assert "vault unlock" in message
        assert "FUNCTUALIZE_VAULT_KEY" in message
        assert "vault remove" not in message
        assert "vault clear" not in message
        # A direct entry: sync cannot restore it, so it is never offered.
        assert "vault sync" not in message
        lowered = message.lower()
        for product in ("gnome", "kwallet", "credential manager", "secret service"):
            assert product not in lowered
        assert _SECRET not in result.stdout + result.stderr

    def test_a5_no_keyring_is_refused_without_waiting(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        started = time.monotonic()
        result = _run(project, tmp_path, ["deploy"], FAKE_KEYRING_MODE="absent")
        elapsed = time.monotonic() - started

        assert result.returncode == ExitCode.REFUSED, result.stderr[-1500:]
        assert elapsed < 10.0, elapsed
        assert "no OS keyring is reachable" in result.stderr
        assert "vault remove" not in result.stderr


class TestOneReadPerProcess:
    def test_a6_many_lookups_one_keyring_read(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, *(f"many.{name}" for name in _FIELDS))

        result = _run(project, tmp_path, ["many"], FAKE_KEYRING_MODE="unlocked")

        assert result.returncode == ExitCode.OK, result.stderr[-1500:]
        assert result.stdout.count(_SECRET) == len(_FIELDS)
        assert _calls(tmp_path).count("get_secret") == 1


class TestUnlockElsewhereThenRun:
    """The story the feature exists for: unlock once, then runs read silently."""

    def test_vault_unlock_then_a_piped_run_works(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        unlocked = _run(
            project,
            tmp_path,
            ["builtin", "vault", "unlock"],
            FAKE_KEYRING_MODE="locked",
            FAKE_KEYRING_UNLOCK="accept",
        )
        assert unlocked.returncode == ExitCode.OK, unlocked.stderr[-1500:]
        assert "Unlocked." in unlocked.stdout
        assert _KEY_HEX not in unlocked.stdout + unlocked.stderr
        assert _calls(tmp_path).count("unlock") == 1

        run = _run(project, tmp_path, ["deploy"], FAKE_KEYRING_MODE="locked")
        assert run.returncode == ExitCode.OK, run.stderr[-1500:]
        assert f"token:{_SECRET}-api_token" in run.stdout

    def test_a_cancelled_unlock_leaves_the_run_refused(
        self, project: Path, tmp_path: Path
    ) -> None:
        _provision(project, tmp_path, "deploy.api_token")

        cancelled = _run(
            project,
            tmp_path,
            ["builtin", "vault", "unlock"],
            FAKE_KEYRING_MODE="locked",
            FAKE_KEYRING_UNLOCK="cancel",
        )
        assert cancelled.returncode == ExitCode.REFUSED, cancelled.stderr[-1500:]
        assert "cancelled" in cancelled.stderr

        run = _run(project, tmp_path, ["deploy"], FAKE_KEYRING_MODE="locked")
        assert run.returncode == ExitCode.REFUSED
        assert "keyring is locked" in run.stderr
