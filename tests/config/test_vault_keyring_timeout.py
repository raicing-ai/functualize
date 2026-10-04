"""The keyring wait: precedence, spelling, and honest refusals.

The OS keyring is read regardless of terminal, behind a deadline. This file
pins how that deadline is chosen — ``$FUNCTUALIZE_VAULT_KEYRING_TIMEOUT``
beats a configured file value beats the 30-second default — and that an
unusable value warns once and falls back rather than breaking the run. The
wait governs a refusal message; a typo in it must not be more disruptive
than the message it governs.
"""

from __future__ import annotations

import logging

import pytest

from functualize._config.vault import (
    DEFAULT_KEYRING_TIMEOUT,
    ENV_KEYRING_TIMEOUT,
    app_keyring_timeout,
    resolve_keyring_timeout,
)
from functualize.app.config import ConfigSources


@pytest.fixture(autouse=True)
def _no_env_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_KEYRING_TIMEOUT, raising=False)


class TestPrecedence:
    def test_unconfigured_resolves_to_the_default(self) -> None:
        assert resolve_keyring_timeout(None) == 30.0

    def test_the_env_var_outranks_a_configured_value(self) -> None:
        import os

        os.environ[ENV_KEYRING_TIMEOUT] = "7s"
        try:
            assert resolve_keyring_timeout("2m") == 7.0
        finally:
            del os.environ[ENV_KEYRING_TIMEOUT]

    def test_a_configured_value_outranks_the_default(self) -> None:
        assert resolve_keyring_timeout("2m") == 120.0

    def test_an_empty_configured_value_falls_to_the_default(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Empty is "unconfigured", as for max_age: skipped, not warned about.
        with caplog.at_level(logging.WARNING):
            assert resolve_keyring_timeout("") == 30.0
        assert not [r for r in caplog.records if "keyring timeout" in r.getMessage()]


class TestTheSpelling:
    def test_seconds_and_minutes_parse(self) -> None:
        assert resolve_keyring_timeout("30s") == 30.0
        assert resolve_keyring_timeout("2m") == 120.0

    def test_a_bare_number_is_refused_with_one_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert resolve_keyring_timeout("30") == 30.0
        warnings = [r for r in caplog.records if "keyring timeout" in r.getMessage()]
        assert len(warnings) == 1
        assert "30" in warnings[0].getMessage()

    def test_zero_is_refused_not_obeyed(self, caplog: pytest.LogCaptureFixture) -> None:
        # "Do not wait at all" cannot be written by accident: a parsed zero
        # falls back to the default rather than making every run refuse
        # instantly.
        with caplog.at_level(logging.WARNING):
            assert resolve_keyring_timeout("0s") == 30.0
        assert (
            len([r for r in caplog.records if "keyring timeout" in r.getMessage()]) == 1
        )

    def test_garbage_warns_once_and_falls_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            assert resolve_keyring_timeout("soon") == 30.0
        assert (
            len([r for r in caplog.records if "keyring timeout" in r.getMessage()]) == 1
        )


class TestAppKeyringTimeout:
    def test_no_app_is_the_default(self) -> None:
        assert app_keyring_timeout(None) == 30.0

    def test_an_app_without_sources_is_the_default(self) -> None:
        assert app_keyring_timeout(object()) == 30.0

    def test_it_reads_the_field_off_the_app(self) -> None:
        class _App:
            def __init__(self) -> None:
                self._config_sources = ConfigSources(vault_keyring_timeout="5s")

        assert app_keyring_timeout(_App()) == 5.0

    def test_an_app_with_unconfigured_sources_is_the_default(self) -> None:
        class _App:
            def __init__(self) -> None:
                self._config_sources = ConfigSources()

        assert app_keyring_timeout(_App()) == 30.0


class TestTheDefaultHasOneSpelling:
    """`app/config.py` cannot import `_config.vault` (cold-boot rule), so the
    default is "unconfigured" there and a literal here. These tests stop the
    two from drifting, exactly as the max_age pair does.
    """

    def test_the_field_defaults_to_unconfigured(self) -> None:
        assert ConfigSources().vault_keyring_timeout is None

    def test_unconfigured_resolves_to_the_documented_default(self) -> None:
        assert DEFAULT_KEYRING_TIMEOUT.total_seconds() == 30.0
        assert resolve_keyring_timeout(ConfigSources().vault_keyring_timeout) == 30.0

    def test_the_duration_spelling_matches_max_age(self) -> None:
        # "2m" means two minutes here exactly as it does for max_age; the
        # shared parser guarantees it, this pins that it is *the* shared one.
        assert resolve_keyring_timeout("1h") == 3600.0
