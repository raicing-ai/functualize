"""Tests for active-environment detection from the process environment."""

from __future__ import annotations

import pytest

from functualize._app.environment import DEFAULT_ENVIRONMENT, detect_environment
from functualize._types.enums import EnvironmentSource


class TestPrecedence:
    def test_functualize_env_wins(self) -> None:
        name, source = detect_environment(
            {"FUNCTUALIZE_ENV": "a", "ENVIRONMENT": "b", "ENV": "c"}
        )
        assert (name, source) == ("a", EnvironmentSource.FUNCTUALIZE_ENV)

    def test_environment_beats_env(self) -> None:
        name, source = detect_environment({"ENVIRONMENT": "b", "ENV": "c"})
        assert (name, source) == ("b", EnvironmentSource.ENVIRONMENT)

    def test_env_is_last_resort(self) -> None:
        name, source = detect_environment({"ENV": "c"})
        assert (name, source) == ("c", EnvironmentSource.ENV)

    def test_defaults_when_nothing_is_set(self) -> None:
        name, source = detect_environment({})
        assert (name, source) == (DEFAULT_ENVIRONMENT, EnvironmentSource.DEFAULT)


class TestValidation:
    @pytest.mark.parametrize("value", ["", "   ", "\n"])
    def test_blank_is_skipped(self, value: str) -> None:
        name, source = detect_environment({"ENVIRONMENT": value, "ENV": "real"})
        assert (name, source) == ("real", EnvironmentSource.ENV)

    def test_env_as_a_startup_file_path_is_rejected(self) -> None:
        """POSIX sh/ksh use $ENV as the path to a startup file.

        Unguarded, that path would be taken as the environment name and
        silently make every overlay inert — so it must be skipped, and the
        result must fall back rather than fail.
        """
        name, source = detect_environment({"ENV": "/home/user/.kshrc"})
        assert (name, source) == (DEFAULT_ENVIRONMENT, EnvironmentSource.DEFAULT)

    @pytest.mark.parametrize(
        "value", ["prod/../etc", "a b", "pro:d", "$(x)", "a.b", "*"]
    )
    def test_invalid_filename_segments_are_skipped(self, value: str) -> None:
        # The name becomes part of config.<name>.toml, so it must look like
        # a filename segment.
        name, _ = detect_environment({"ENVIRONMENT": value})
        assert name == DEFAULT_ENVIRONMENT

    @pytest.mark.parametrize("value", ["prod", "PROD", "staging_2", "us-east-1"])
    def test_valid_names_are_accepted(self, value: str) -> None:
        name, source = detect_environment({"ENVIRONMENT": value})
        assert (name, source) == (value, EnvironmentSource.ENVIRONMENT)

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        name, _ = detect_environment({"ENVIRONMENT": "  prod  "})
        assert name == "prod"

    def test_an_invalid_higher_precedence_var_falls_through(self) -> None:
        """A bad FUNCTUALIZE_ENV must not mask a good ENVIRONMENT."""
        name, source = detect_environment(
            {"FUNCTUALIZE_ENV": "not a name", "ENVIRONMENT": "prod"}
        )
        assert (name, source) == ("prod", EnvironmentSource.ENVIRONMENT)


class TestProcessEnvironment:
    def test_reads_os_environ_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FUNCTUALIZE_ENV", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "staging")

        assert detect_environment() == ("staging", EnvironmentSource.ENVIRONMENT)
