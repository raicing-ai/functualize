"""Tests for boot-time dotenv loading via ConfigSources.dotenv/dotenv_path.

Boot (both standard and static paths) loads a .env file before the
resolution chain is built, so EnvSource sees the variables. override=False
keeps already-set environment values winning.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from functualize.app.config import ConfigSources, JobSources, PluginSources
from functualize.app.core import FunctualizeApp
from functualize.app.presets import env_only, twelve_factor

if TYPE_CHECKING:
    import pytest


def _job() -> None:
    """Minimal job for static wiring."""


def _static_app(config_sources: ConfigSources) -> FunctualizeApp:
    """Build a fully-explicit app that takes the boot_static path."""
    return FunctualizeApp(
        name="dotenv-test",
        job_sources=JobSources(functions=[_job]),
        config_sources=config_sources,
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )


class TestBootDotenv:
    """ConfigSources.dotenv/dotenv_path are consumed during boot."""

    def test_static_boot_loads_explicit_dotenv_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / ".env.explicit"
        env_file.write_text("BOOT_DOTENV_EXPLICIT=loaded\n")
        monkeypatch.delenv("BOOT_DOTENV_EXPLICIT", raising=False)

        try:
            _static_app(env_only(dotenv_path=str(env_file)))
            assert os.environ.get("BOOT_DOTENV_EXPLICIT") == "loaded"
        finally:
            os.environ.pop("BOOT_DOTENV_EXPLICIT", None)

    def test_static_boot_auto_discovers_cwd_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text("BOOT_DOTENV_CWD=loaded\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("BOOT_DOTENV_CWD", raising=False)

        try:
            _static_app(env_only())
            assert os.environ.get("BOOT_DOTENV_CWD") == "loaded"
        finally:
            os.environ.pop("BOOT_DOTENV_CWD", None)

    def test_dotenv_disabled_loads_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text("BOOT_DOTENV_DISABLED=loaded\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("BOOT_DOTENV_DISABLED", raising=False)

        try:
            _static_app(twelve_factor())
            assert os.environ.get("BOOT_DOTENV_DISABLED") is None
        finally:
            os.environ.pop("BOOT_DOTENV_DISABLED", None)

    def test_existing_environ_wins_over_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text("BOOT_DOTENV_PRESET=from_dotenv\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BOOT_DOTENV_PRESET", "from_environ")

        _static_app(env_only())
        assert os.environ.get("BOOT_DOTENV_PRESET") == "from_environ"

    def test_standard_boot_loads_cwd_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".env").write_text("BOOT_DOTENV_STANDARD=loaded\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("BOOT_DOTENV_STANDARD", raising=False)

        try:
            # Default ConfigSources has dotenv=True; directories force the
            # standard boot path.
            FunctualizeApp(
                name="dotenv-test-standard",
                job_sources=JobSources(directories=[str(tmp_path)]),
            )
            assert os.environ.get("BOOT_DOTENV_STANDARD") == "loaded"
        finally:
            os.environ.pop("BOOT_DOTENV_STANDARD", None)

    def test_env_var_resolves_through_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A .env variable is visible to EnvSource in the resolution chain."""
        (tmp_path / ".env").write_text("MYSECTION_MYKEY=from_dotenv\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("MYSECTION_MYKEY", raising=False)

        try:
            app = _static_app(env_only())
            chain = app._config_sources.config_resolution_chain
            assert chain is not None
            resolved = chain.resolve("mykey", section="mysection")
            assert resolved.value == "from_dotenv"
            assert resolved.source_type == "env"
        finally:
            os.environ.pop("MYSECTION_MYKEY", None)
