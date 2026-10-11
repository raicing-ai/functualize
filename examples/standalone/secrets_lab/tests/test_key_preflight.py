"""The pre-run check in `key_preflight.py`, through the published API only.

The ready cases run the real `vault_key_state` and `vault_unlock` against a
project whose key is in `FUNCTUALIZE_VAULT_KEY`, so no keyring is touched. The
locked cases stand in for the keyring's answer by replacing the two calls the
script makes — with the public `VaultKeyState` and the public errors, exactly
as the real ones would come back.
"""

from __future__ import annotations

from pathlib import Path

import key_preflight
import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.app.vault import (
    UnlockAbandonedError,
    VaultIdentity,
    VaultKeySourceError,
    VaultKeyState,
    VaultKeyStatus,
    vault_key_state,
    vault_put,
    vault_unlock,
)

_ROOT = Path(__file__).parent.parent
_KEY_HEX = "ab" * 32


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """This lab's jobs in a throwaway project, keyed by the environment."""
    work = tmp_path / "lab"
    (work / ".functualize").mkdir(parents=True)
    (work / "jobs").mkdir()
    for name in ("sync.py", "report.py"):
        (work / "jobs" / name).write_text((_ROOT / "jobs" / name).read_text())
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("FUNCTUALIZE_VAULT_KEY", _KEY_HEX)
    monkeypatch.chdir(work)
    return work


def _app(project: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "secrets-lab",
        job_sources=JobSources(directories=[str(project / "jobs")], lazy=False),
    )


def _locked(monkeypatch: pytest.MonkeyPatch) -> None:
    """What `vault_key_state` answers while the keyring is locked."""
    monkeypatch.setattr(
        key_preflight,
        "vault_key_state",
        lambda app: VaultKeyState(VaultKeyStatus.LOCKED, source="linux"),
    )


def test_a_project_without_a_vault_is_ready(project: Path) -> None:
    app = _app(project)

    assert vault_key_state(app).status is VaultKeyStatus.NOT_APPLICABLE
    assert key_preflight.preflight(app) == (
        "ready: this project keeps nothing in its vault"
    )


def test_a_key_in_the_environment_is_ready_and_never_printed(project: Path) -> None:
    app = _app(project)
    vault_put(app, VaultIdentity("job", "report", "token"), "lab-token-preflight")

    state = vault_key_state(app)

    assert state == VaultKeyState(VaultKeyStatus.UNLOCKED, source="env")
    message = key_preflight.preflight(app)
    assert message == "ready: the vault key comes from env"
    assert _KEY_HEX not in message


def test_vault_unlock_reports_where_the_key_came_from(project: Path) -> None:
    """With the key in the environment there is nothing to unlock and no dialog."""
    assert vault_unlock(_app(project)).provider_id == "env"


def test_locked_with_nobody_at_the_terminal_does_not_unlock(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _locked(monkeypatch)

    def no_dialog(app: object) -> object:
        raise AssertionError("an unattended run must never ask to unlock")

    monkeypatch.setattr(key_preflight, "vault_unlock", no_dialog)

    message = key_preflight.preflight(_app(project), person_present=False)

    assert message == (
        "locked: run `func builtin vault unlock` in a terminal, then retry"
    )


def test_a_cancelled_dialog_is_reported_by_its_reason(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _locked(monkeypatch)

    def cancelled(app: object) -> object:
        raise VaultKeySourceError("cancelled", "The unlock was cancelled.")

    monkeypatch.setattr(key_preflight, "vault_unlock", cancelled)

    message = key_preflight.preflight(_app(project), person_present=True)

    assert message.startswith("still locked (cancelled)")


def test_giving_up_on_the_dialog_is_not_an_unlock(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second Ctrl-C while the dialog is open: `vault_unlock` stops waiting."""
    _locked(monkeypatch)

    def abandoned(app: object) -> object:
        raise UnlockAbandonedError("unlock_abandoned", "Stopped waiting.")

    monkeypatch.setattr(key_preflight, "vault_unlock", abandoned)

    message = key_preflight.preflight(_app(project), person_present=True)

    assert message == "stopped waiting for the keyring's dialog; nothing was unlocked"
