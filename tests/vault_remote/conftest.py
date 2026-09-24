"""Fixtures for the vault-remote suite: one in-process origin per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.vault_remote.mock_vault import MockVault


@pytest.fixture
def mock_origin() -> Iterator[MockVault]:
    vault = MockVault.start()
    try:
        yield vault
    finally:
        vault.stop()
