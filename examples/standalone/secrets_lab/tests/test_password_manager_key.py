"""`password_manager_key.py` is a key provider by shape alone, and never prompts to read."""

from __future__ import annotations

import pytest
from password_manager_key import PasswordManager, PasswordManagerKey

from functualize.plugin import (
    KeyAvailability,
    VaultKeyProbe,
    VaultKeyProvider,
    VaultKeyUnlocker,
)

_KEY_HEX = "5a" * 32
_MASTER = "correct horse battery staple"  # noqa: S105 - a test fixture


@pytest.fixture
def manager() -> PasswordManager:
    return PasswordManager(_MASTER, {"functualize vault key": _KEY_HEX})


def _provider(
    manager: PasswordManager, answers: list[str | None]
) -> tuple[PasswordManagerKey, list[str | None]]:
    """The provider, and a record of every master-password prompt it showed."""
    asked: list[str | None] = []

    def ask() -> str | None:
        answer = answers.pop(0)
        asked.append(answer)
        return answer

    return PasswordManagerKey(manager, ask_master_password=ask), asked


def test_it_is_a_key_provider_a_probe_and_an_unlocker(
    manager: PasswordManager,
) -> None:
    """No base class and no registration: having the methods is what counts."""
    provider, _ = _provider(manager, [])

    assert isinstance(provider, VaultKeyProvider)
    assert isinstance(provider, VaultKeyProbe)
    assert isinstance(provider, VaultKeyUnlocker)


def test_a_locked_manager_answers_nothing_without_a_prompt(
    manager: PasswordManager,
) -> None:
    provider, asked = _provider(manager, [])

    assert provider.probe() is KeyAvailability.LOCKED
    assert provider.get_key("any-project") is None
    assert asked == []
    assert manager.secret_reads == 0


def test_unlock_prompts_once_and_then_reads_are_silent(
    manager: PasswordManager,
) -> None:
    provider, asked = _provider(manager, [_MASTER])

    assert provider.unlock() is True
    assert provider.probe() is KeyAvailability.UNLOCKED
    assert provider.get_key("any-project") == bytes.fromhex(_KEY_HEX)
    assert provider.unlock() is True  # already unlocked: no second prompt
    assert asked == [_MASTER]


def test_a_cancelled_prompt_leaves_it_locked(manager: PasswordManager) -> None:
    provider, asked = _provider(manager, [None])

    assert provider.unlock() is False
    assert provider.probe() is KeyAvailability.LOCKED
    assert asked == [None]
