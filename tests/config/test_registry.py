"""Unit tests for the ProviderRegistry."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

import pytest

from functualize._config.errors import (
    UnregisteredProviderError,
    UnsupportedFormatError,
)
from functualize._config.registry import ProviderRegistry

# --- Test helpers ---


class FakeTomlProvider:
    """A fake format provider for testing."""

    def extensions(self) -> list[str]:
        return [".toml"]

    def parse(self, path: str) -> dict[str, Any]:
        return {}

    def serialize(self, data: dict[str, Any]) -> str:
        return ""


class FakeYamlProvider:
    """A fake YAML format provider for testing."""

    def extensions(self) -> list[str]:
        return [".yaml", ".yml"]

    def parse(self, path: str) -> dict[str, Any]:
        return {}

    def serialize(self, data: dict[str, Any]) -> str:
        return ""


class FakeAlternateTomlProvider:
    """Another fake TOML provider to test override behavior."""

    def extensions(self) -> list[str]:
        return [".toml"]

    def parse(self, path: str) -> dict[str, Any]:
        return {"alternate": True}

    def serialize(self, data: dict[str, Any]) -> str:
        return "alternate"


class FakeVaultProvider:
    """A fake remote provider for testing."""

    def identifier(self) -> str:
        return "vault"

    def is_ready(self) -> bool:
        return True

    def fetch(self, reference: str) -> str:
        return f"secret:{reference}"


class FakeAwsProvider:
    """A fake AWS Secrets Manager remote provider for testing."""

    def identifier(self) -> str:
        return "aws-sm"

    def is_ready(self) -> bool:
        return True

    def fetch(self, reference: str) -> str:
        return f"aws:{reference}"


class FakeAlternateVaultProvider:
    """Another fake vault provider to test override behavior."""

    def identifier(self) -> str:
        return "vault"

    def is_ready(self) -> bool:
        return False

    def fetch(self, reference: str) -> str:
        return f"alt-vault:{reference}"


class NotAProvider:
    """Something that doesn't implement any provider protocol."""

    def do_something(self) -> None:
        pass


# --- Tests ---


class TestRegisterFormatProvider:
    """Tests for register_format_provider."""

    def test_register_and_retrieve_format_provider(self) -> None:
        registry = ProviderRegistry()
        provider = FakeTomlProvider()
        registry.register_format_provider(provider)

        assert registry.get_format_provider(".toml") is provider

    def test_register_multi_extension_provider(self) -> None:
        registry = ProviderRegistry()
        provider = FakeYamlProvider()
        registry.register_format_provider(provider)

        assert registry.get_format_provider(".yaml") is provider
        assert registry.get_format_provider(".yml") is provider

    def test_last_registered_provider_wins(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry = ProviderRegistry()
        first = FakeTomlProvider()
        second = FakeAlternateTomlProvider()

        registry.register_format_provider(first)
        with caplog.at_level(logging.WARNING):
            registry.register_format_provider(second)

        assert registry.get_format_provider(".toml") is second
        assert "overridden" in caplog.text
        assert "FakeTomlProvider" in caplog.text
        assert "FakeAlternateTomlProvider" in caplog.text

    def test_register_non_format_provider_raises_type_error(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(TypeError, match="Expected a FormatProvider"):
            registry.register_format_provider(NotAProvider())  # type: ignore[arg-type]


class TestRegisterRemoteProvider:
    """Tests for register_remote_provider."""

    def test_register_and_retrieve_remote_provider(self) -> None:
        registry = ProviderRegistry()
        provider = FakeVaultProvider()
        registry.register_remote_provider(provider)

        assert registry.get_remote_provider("vault") is provider

    def test_last_registered_remote_provider_wins(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        registry = ProviderRegistry()
        first = FakeVaultProvider()
        second = FakeAlternateVaultProvider()

        registry.register_remote_provider(first)
        with caplog.at_level(logging.WARNING):
            registry.register_remote_provider(second)

        assert registry.get_remote_provider("vault") is second
        assert "overridden" in caplog.text
        assert "FakeVaultProvider" in caplog.text
        assert "FakeAlternateVaultProvider" in caplog.text

    def test_register_non_remote_provider_raises_type_error(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(TypeError, match="Expected a RemoteProvider"):
            registry.register_remote_provider(NotAProvider())  # type: ignore[arg-type]


class TestGetFormatProvider:
    """Tests for get_format_provider."""

    def test_raises_unsupported_format_for_unknown_extension(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(UnsupportedFormatError) as exc_info:
            registry.get_format_provider(".unknown")

        assert exc_info.value.extension == ".unknown"

    def test_retrieves_correct_provider_among_multiple(self) -> None:
        registry = ProviderRegistry()
        toml = FakeTomlProvider()
        yaml = FakeYamlProvider()
        registry.register_format_provider(toml)
        registry.register_format_provider(yaml)

        assert registry.get_format_provider(".toml") is toml
        assert registry.get_format_provider(".yaml") is yaml


class TestGetRemoteProvider:
    """Tests for get_remote_provider."""

    def test_raises_unregistered_provider_for_unknown_identifier(self) -> None:
        registry = ProviderRegistry()
        with pytest.raises(UnregisteredProviderError) as exc_info:
            registry.get_remote_provider("nonexistent")

        assert exc_info.value.provider_name == "nonexistent"

    def test_retrieves_correct_provider_among_multiple(self) -> None:
        registry = ProviderRegistry()
        vault = FakeVaultProvider()
        aws = FakeAwsProvider()
        registry.register_remote_provider(vault)
        registry.register_remote_provider(aws)

        assert registry.get_remote_provider("vault") is vault
        assert registry.get_remote_provider("aws-sm") is aws


class TestListProviders:
    """Tests for list_format_providers and list_remote_providers."""

    def test_list_format_providers_empty(self) -> None:
        registry = ProviderRegistry()
        assert registry.list_format_providers() == {}

    def test_list_format_providers_returns_copy(self) -> None:
        registry = ProviderRegistry()
        provider = FakeTomlProvider()
        registry.register_format_provider(provider)

        result = registry.list_format_providers()
        assert result == {".toml": provider}
        # Mutating the result doesn't affect the registry
        result[".fake"] = provider
        assert ".fake" not in registry.list_format_providers()

    def test_list_remote_providers_empty(self) -> None:
        registry = ProviderRegistry()
        assert registry.list_remote_providers() == {}

    def test_list_remote_providers_returns_copy(self) -> None:
        registry = ProviderRegistry()
        provider = FakeVaultProvider()
        registry.register_remote_provider(provider)

        result = registry.list_remote_providers()
        assert result == {"vault": provider}
        # Mutating the result doesn't affect the registry
        result["fake"] = provider
        assert "fake" not in registry.list_remote_providers()

    def test_list_format_providers_shows_all_extensions(self) -> None:
        registry = ProviderRegistry()
        yaml = FakeYamlProvider()
        registry.register_format_provider(yaml)

        result = registry.list_format_providers()
        assert ".yaml" in result
        assert ".yml" in result
        assert result[".yaml"] is yaml
        assert result[".yml"] is yaml


class TestDiscoverEntryPoints:
    """Tests for discover_entry_points."""

    def test_discover_format_entry_points_loads_providers(self) -> None:
        """Entry points that return valid FormatProvider instances are loaded."""
        registry = ProviderRegistry()

        fake_ep = _make_fake_entry_point("toml", FakeTomlProvider)
        with patch(
            "functualize._config.registry.entry_points",
            side_effect=lambda group: (
                [fake_ep] if group == "functualize.format_providers" else []
            ),
        ):
            registry.discover_entry_points()

        assert ".toml" in registry.list_format_providers()

    def test_discover_remote_entry_points_loads_providers(self) -> None:
        """Entry points that return valid RemoteProvider instances are loaded."""
        registry = ProviderRegistry()

        fake_ep = _make_fake_entry_point("vault", FakeVaultProvider)
        with patch(
            "functualize._config.registry.entry_points",
            side_effect=lambda group: (
                [fake_ep] if group == "functualize.remote_providers" else []
            ),
        ):
            registry.discover_entry_points()

        assert "vault" in registry.list_remote_providers()

    def test_discover_skips_failed_entry_points_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Entry points that fail to load are skipped with a warning."""
        registry = ProviderRegistry()

        fake_ep = _make_failing_entry_point("broken-plugin", ImportError("no module"))
        with (
            patch(
                "functualize._config.registry.entry_points",
                side_effect=lambda group: (
                    [fake_ep] if group == "functualize.format_providers" else []
                ),
            ),
            caplog.at_level(logging.WARNING),
        ):
            registry.discover_entry_points()

        assert registry.list_format_providers() == {}
        assert (
            "Failed to load format provider entry point 'broken-plugin'" in caplog.text
        )

    def test_discover_skips_non_protocol_entry_points_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Entry points that don't implement the protocol are skipped."""
        registry = ProviderRegistry()

        fake_ep = _make_fake_entry_point("bad", NotAProvider)
        with (
            patch(
                "functualize._config.registry.entry_points",
                side_effect=lambda group: (
                    [fake_ep] if group == "functualize.format_providers" else []
                ),
            ),
            caplog.at_level(logging.WARNING),
        ):
            registry.discover_entry_points()

        assert registry.list_format_providers() == {}
        assert "does not implement FormatProvider protocol" in caplog.text

    def test_discover_entry_point_returning_instance(self) -> None:
        """Entry points that return an already-instantiated provider work."""
        registry = ProviderRegistry()
        instance = FakeTomlProvider()

        fake_ep = _make_fake_entry_point("toml", instance)
        with patch(
            "functualize._config.registry.entry_points",
            side_effect=lambda group: (
                [fake_ep] if group == "functualize.format_providers" else []
            ),
        ):
            registry.discover_entry_points()

        assert registry.get_format_provider(".toml") is instance


# --- Helpers for mocking entry points ---


class _FakeEntryPoint:
    """Mimics importlib.metadata.EntryPoint for testing."""

    def __init__(self, name: str, load_result: Any) -> None:
        self.name = name
        self._load_result = load_result

    def load(self) -> Any:
        return self._load_result


class _FailingEntryPoint:
    """Mimics an entry point that raises on load."""

    def __init__(self, name: str, error: Exception) -> None:
        self.name = name
        self._error = error

    def load(self) -> Any:
        raise self._error


def _make_fake_entry_point(name: str, load_result: Any) -> _FakeEntryPoint:
    return _FakeEntryPoint(name, load_result)


def _make_failing_entry_point(name: str, error: Exception) -> _FailingEntryPoint:
    return _FailingEntryPoint(name, error)
