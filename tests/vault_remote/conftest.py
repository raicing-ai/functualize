"""Fixtures for the vault-remote suite: one in-process origin per test."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from functualize.app.vault import vault_put
from tests.vault_remote.mock_vault import MockVault

if TYPE_CHECKING:
    from functualize.app import FunctualizeApp

from tests.vault_remote.projects import (
    _ALL_JOBS,
    _APP_KEY,
    _MY_KEY,
    _REGION,
    _SECRET,
    _TOKEN,
    _app,
    _project,
)


@pytest.fixture
def mock_origin() -> Iterator[MockVault]:
    vault = MockVault.start()
    try:
        yield vault
    finally:
        vault.stop()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from functualize._config.vault_keys import ENV_VAR, generate_key

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv(ENV_VAR, generate_key())
    monkeypatch.setenv("FUNCTUALIZE_ENV", "prod")


@pytest.fixture
def sender(tmp_path: Path, env: None) -> tuple[FunctualizeApp, Path]:
    root = _project(tmp_path / "sender", *_ALL_JOBS)
    app = _app(root)
    for identity in (_TOKEN, _APP_KEY, _REGION, _MY_KEY):
        vault_put(app, identity, f"{_SECRET}-{identity.field}", cwd=root)
    return app, root


@pytest.fixture
def receiver(tmp_path: Path, env: None) -> tuple[FunctualizeApp, Path]:
    root = _project(tmp_path / "receiver", *_ALL_JOBS)
    return _app(root), root
