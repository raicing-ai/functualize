"""Before a long run: will it get its stored secrets? Unlock only if a person is here.

A deploy script, a CI step or an agent wrapper wants to know *before* it starts
a twenty-minute run whether that run can open the vault — not to find out at
minute nineteen. `vault_key_state` answers that without ever showing a dialog,
reading the key or waiting on a keyring, so it is safe to call from anywhere.

Unlocking is a different matter. A run never asks the keyring to unlock: a
dialog nobody answers, or one the caller walks away from, can take the keyring
service down with every keyring the user has. `vault_unlock` is the one call
that may show the dialog, so this script calls it only when a person is at the
terminal — and otherwise says what to do instead.
"""

from __future__ import annotations

import sys
from typing import Any

from functualize.app.vault import (
    UnlockAbandonedError,
    VaultKeySourceError,
    VaultKeyState,
    VaultKeyStatus,
    vault_key_state,
    vault_unlock,
)


def preflight(app: Any, *, person_present: bool | None = None) -> str:
    """One line saying whether a run of ``app`` would get its stored secrets.

    Args:
        app: The application about to run.
        person_present: Whether someone can answer the keyring's dialog.
            Defaults to "stdin is a terminal".

    Returns:
        A message for the operator. It never contains the key.
    """
    state: VaultKeyState = vault_key_state(app)

    if state.status is VaultKeyStatus.UNLOCKED:
        return f"ready: the vault key comes from {state.source}"
    if state.status is VaultKeyStatus.NOT_APPLICABLE:
        return "ready: this project keeps nothing in its vault"
    if state.status is not VaultKeyStatus.LOCKED:
        return (
            f"cannot tell ({state.status.value}): set FUNCTUALIZE_VAULT_KEY "
            "to run without a keyring"
        )

    if person_present is None:
        person_present = sys.stdin.isatty()
    if not person_present:
        return "locked: run `func builtin vault unlock` in a terminal, then retry"

    try:
        unlocked = vault_unlock(app)
    except UnlockAbandonedError:
        return "stopped waiting for the keyring's dialog; nothing was unlocked"
    except VaultKeySourceError as refusal:
        return f"still locked ({refusal.reason}): {refusal}"
    return f"unlocked: the vault key comes from {unlocked.provider_id}"
