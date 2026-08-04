"""Tests for config-file slot parsing and role classification."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._config.roles import classify, parse_slot
from functualize._types.enums import ConfigFileRole


class TestParseSlot:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("config.base.toml", "base"),
            ("config.dev.toml", "dev"),
            ("config.prod.ini", "prod"),
            ("config.PROD.toml", "PROD"),
            ("/abs/path/to/config.staging.toml", "staging"),
            # No slot segment.
            ("config.toml", None),
            # Not a config file at all.
            ("settings.dev.toml", None),
            ("pyproject.toml", None),
        ],
    )
    def test_parses(self, filename: str, expected: str | None) -> None:
        assert parse_slot(filename) == expected


class TestClassify:
    @pytest.mark.parametrize(
        ("filename", "environment", "expected"),
        [
            ("config.base.toml", "dev", ConfigFileRole.BASE),
            ("config.dev.toml", "dev", ConfigFileRole.OVERLAY),
            ("config.prod.toml", "dev", ConfigFileRole.INERT),
            # Case-insensitive both ways.
            ("config.PROD.toml", "prod", ConfigFileRole.OVERLAY),
            ("config.prod.toml", "PROD", ConfigFileRole.OVERLAY),
            # An unslotted file can never be selected by an environment, so
            # BASE is the only reading where it does anything.
            ("config.toml", "dev", ConfigFileRole.BASE),
            # environment=None disables banding entirely.
            ("config.prod.toml", None, ConfigFileRole.BASE),
        ],
    )
    def test_classifies(
        self, filename: str, environment: str | None, expected: ConfigFileRole
    ) -> None:
        assert classify(filename, environment) is expected

    def test_environment_named_base_degrades_sanely(self) -> None:
        """ENVIRONMENT=base must not promote base to an overlay of itself."""
        assert classify("config.base.toml", "base") is ConfigFileRole.BASE


class TestClassifyProperties:
    slots = st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True)

    @given(slot=slots, environment=slots)
    def test_inert_iff_slot_is_neither_base_nor_the_environment(
        self, slot: str, environment: str
    ) -> None:
        role = classify(f"config.{slot}.toml", environment)
        is_inert = slot != "base" and slot.casefold() != environment.casefold()
        assert (role is ConfigFileRole.INERT) == is_inert

    @given(slot=slots)
    def test_never_inert_without_an_environment(self, slot: str) -> None:
        assert classify(f"config.{slot}.toml", None) is not ConfigFileRole.INERT
