"""Unit tests for the DomainMetadata dataclass and domain registry system.

Tests the centralized domain discovery system (Requirements 22.1–22.5):
- DomainMetadata dataclass construction and immutability
- DomainRegistry CRUD operations
- discover_domains() entry point scanning
- scan_domain_providers() per-domain provider scanning
- boot_domain_registry() full integration
"""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from functualize._plugins.domain_metadata import DomainMetadata
from functualize._plugins.domain_registry import (
    DomainRegistry,
    _to_canonical_metadata,
    boot_domain_registry,
    discover_domains,
    scan_domain_providers,
)

# --- Fixtures ---


def _make_metadata(
    name: str = "ai",
    display_name: str = "AI / LLM",
    description: str = "LLM interaction capabilities",
    capability_class: str = "functualize_ai.AI",
    provider_protocol: str = "functualize_ai.AIProvider",
    config_section: str = "ai",
    entry_point_group: str = "functualize.ai_providers",
    events_prefix: str = "ai.",
    **kwargs,
) -> DomainMetadata:
    return DomainMetadata(
        name=name,
        display_name=display_name,
        description=description,
        capability_class=capability_class,
        provider_protocol=provider_protocol,
        config_section=config_section,
        entry_point_group=entry_point_group,
        events_prefix=events_prefix,
        **kwargs,
    )


class _FakeEntryPoint:
    """Minimal fake for importlib.metadata.EntryPoint."""

    def __init__(self, name: str, load_result: object | None = None) -> None:
        self.name = name
        self._load_result = load_result if load_result is not None else MagicMock()

    def load(self) -> object:
        if isinstance(self._load_result, Exception):
            raise self._load_result
        return self._load_result


# --- DomainMetadata Tests ---


class TestDomainMetadata:
    """Tests for the DomainMetadata frozen dataclass."""

    def test_construction_with_required_fields(self) -> None:
        """DomainMetadata can be constructed with all required fields."""
        meta = _make_metadata()
        assert meta.name == "ai"
        assert meta.display_name == "AI / LLM"
        assert meta.description == "LLM interaction capabilities"
        assert meta.capability_class == "functualize_ai.AI"
        assert meta.provider_protocol == "functualize_ai.AIProvider"
        assert meta.config_section == "ai"
        assert meta.entry_point_group == "functualize.ai_providers"
        assert meta.events_prefix == "ai."

    def test_optional_fields_default_to_none(self) -> None:
        """Optional fields default to None when not specified."""
        meta = _make_metadata()
        assert meta.scaffold_template is None
        assert meta.documentation_url is None
        assert meta.mock_factory is None

    def test_optional_fields_can_be_set(self) -> None:
        """Optional fields can be set to non-None values."""
        meta = _make_metadata(
            scaffold_template="ai_plugin",
            documentation_url="https://docs.example.com",
            mock_factory="functualize_ai.testing:MockAI",
        )
        assert meta.scaffold_template == "ai_plugin"
        assert meta.documentation_url == "https://docs.example.com"
        assert meta.mock_factory == "functualize_ai.testing:MockAI"

    def test_frozen_immutability(self) -> None:
        """DomainMetadata is immutable (frozen dataclass)."""
        meta = _make_metadata()
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.name = "changed"  # type: ignore[misc]

    def test_equality(self) -> None:
        """Two DomainMetadata with same fields are equal."""
        meta1 = _make_metadata()
        meta2 = _make_metadata()
        assert meta1 == meta2


# --- DomainRegistry Tests ---


class TestDomainRegistry:
    """Tests for the DomainRegistry class."""

    def test_register_and_get(self) -> None:
        """Registering a domain makes it retrievable by name."""
        registry = DomainRegistry()
        meta = _make_metadata()
        registry.register(meta)

        info = registry.get("ai")
        assert info is not None
        assert info.metadata == meta
        assert info.available_providers == {}
        assert info.active_provider_name is None

    def test_register_duplicate_skipped(self) -> None:
        """Duplicate domain registration is skipped."""
        registry = DomainRegistry()
        meta = _make_metadata()
        registry.register(meta)
        registry.register(meta)  # Should be skipped
        assert len(registry) == 1

    def test_get_nonexistent_returns_none(self) -> None:
        """Getting a non-registered domain returns None."""
        registry = DomainRegistry()
        assert registry.get("nonexistent") is None

    def test_get_metadata(self) -> None:
        """get_metadata returns just the DomainMetadata."""
        registry = DomainRegistry()
        meta = _make_metadata()
        registry.register(meta)
        assert registry.get_metadata("ai") == meta
        assert registry.get_metadata("nonexistent") is None

    def test_set_available_providers(self) -> None:
        """Can set available providers for a domain."""
        registry = DomainRegistry()
        meta = _make_metadata()
        registry.register(meta)

        ep = _FakeEntryPoint("pydantic")
        registry.set_available_providers("ai", {"pydantic": ep})  # type: ignore

        info = registry.get("ai")
        assert info is not None
        assert "pydantic" in info.available_providers

    def test_set_active_provider(self) -> None:
        """Can set the active provider for a domain."""
        registry = DomainRegistry()
        meta = _make_metadata()
        registry.register(meta)
        registry.set_active_provider("ai", "pydantic")

        info = registry.get("ai")
        assert info is not None
        assert info.active_provider_name == "pydantic"

    def test_list_domains(self) -> None:
        """list_domains returns all registered metadata."""
        registry = DomainRegistry()
        meta1 = _make_metadata(name="ai")
        meta2 = _make_metadata(name="state", config_section="state")
        registry.register(meta1)
        registry.register(meta2)

        domains = registry.list_domains()
        assert len(domains) == 2
        names = {d.name for d in domains}
        assert names == {"ai", "state"}

    def test_contains(self) -> None:
        """'in' operator works on registry."""
        registry = DomainRegistry()
        meta = _make_metadata()
        registry.register(meta)
        assert "ai" in registry
        assert "nonexistent" not in registry

    def test_len(self) -> None:
        """len() returns number of registered domains."""
        registry = DomainRegistry()
        assert len(registry) == 0
        registry.register(_make_metadata(name="ai"))
        assert len(registry) == 1
        registry.register(_make_metadata(name="state", config_section="state"))
        assert len(registry) == 2


# --- discover_domains Tests ---


class TestDiscoverDomains:
    """Tests for discover_domains() entry point scanning.

    Validates: Requirement 22.1
    """

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_discovers_valid_domains(self, mock_eps) -> None:
        """Discovers domain SDKs from functualize.domains entry points."""
        meta = _make_metadata()
        mock_eps.return_value = [_FakeEntryPoint("ai", load_result=meta)]

        result = discover_domains()

        assert len(result) == 1
        assert result[0].name == "ai"
        mock_eps.assert_called_once_with(group="functualize.domains")

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_skips_entry_points_that_fail_to_load(self, mock_eps) -> None:
        """Entry points that raise on load are skipped."""
        failing_ep = _FakeEntryPoint("bad", load_result=ImportError("missing"))
        meta = _make_metadata()
        mock_eps.return_value = [failing_ep, _FakeEntryPoint("ai", load_result=meta)]

        result = discover_domains()

        assert len(result) == 1
        assert result[0].name == "ai"

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_skips_entry_points_without_required_fields(self, mock_eps) -> None:
        """Entry points that don't have required fields are skipped."""
        incomplete = MagicMock(spec=[])  # No attributes
        mock_eps.return_value = [_FakeEntryPoint("bad", load_result=incomplete)]

        result = discover_domains()

        assert len(result) == 0

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_converts_duck_typed_metadata(self, mock_eps) -> None:
        """Objects with compatible fields are converted to canonical DomainMetadata."""

        class _OtherDomainMetadata:
            """Different class with same fields (from a domain SDK package)."""

            def __init__(self):
                self.name = "tasks"
                self.display_name = "Tasks"
                self.description = "Task management"
                self.capability_class = "functualize_tasks.Tasks"
                self.provider_protocol = "functualize_tasks.TaskProvider"
                self.config_section = "tasks"
                self.entry_point_group = "functualize.tasks_providers"
                self.events_prefix = "tasks."
                self.scaffold_template = None
                self.documentation_url = None
                self.mock_factory = None

        other_meta = _OtherDomainMetadata()
        mock_eps.return_value = [_FakeEntryPoint("tasks", load_result=other_meta)]

        result = discover_domains()

        assert len(result) == 1
        assert isinstance(result[0], DomainMetadata)
        assert result[0].name == "tasks"


# --- scan_domain_providers Tests ---


class TestScanDomainProviders:
    """Tests for scan_domain_providers().

    Validates: Requirement 22.3
    """

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_scans_domain_entry_point_group(self, mock_eps) -> None:
        """Scans the domain's entry_point_group for implementations."""
        ep1 = _FakeEntryPoint("pydantic")
        ep2 = _FakeEntryPoint("instructor")
        mock_eps.return_value = [ep1, ep2]

        meta = _make_metadata()
        result = scan_domain_providers(meta)

        assert len(result) == 2
        assert "pydantic" in result
        assert "instructor" in result
        mock_eps.assert_called_once_with(group="functualize.ai_providers")

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_returns_empty_when_no_providers(self, mock_eps) -> None:
        """Returns empty dict when no providers are installed."""
        mock_eps.return_value = []

        meta = _make_metadata()
        result = scan_domain_providers(meta)

        assert result == {}


# --- _to_canonical_metadata Tests ---


class TestToCanonicalMetadata:
    """Tests for the structural conversion function."""

    def test_returns_canonical_instance_directly(self) -> None:
        """If already canonical DomainMetadata, returns as-is."""
        meta = _make_metadata()
        result = _to_canonical_metadata(meta, "test")
        assert result is meta

    def test_converts_duck_typed_object(self) -> None:
        """Converts objects with compatible fields."""
        obj = MagicMock()
        obj.name = "ai"
        obj.display_name = "AI"
        obj.description = "AI capabilities"
        obj.capability_class = "pkg.AI"
        obj.provider_protocol = "pkg.AIProvider"
        obj.config_section = "ai"
        obj.entry_point_group = "functualize.ai_providers"
        obj.events_prefix = "ai."
        obj.scaffold_template = None
        obj.documentation_url = None
        obj.mock_factory = None

        result = _to_canonical_metadata(obj, "test")

        assert result is not None
        assert isinstance(result, DomainMetadata)
        assert result.name == "ai"

    def test_returns_none_for_missing_fields(self) -> None:
        """Returns None when required fields are missing."""
        obj = MagicMock(spec=["name"])  # Missing most fields
        obj.name = "ai"

        result = _to_canonical_metadata(obj, "test")

        assert result is None


# --- boot_domain_registry Integration Tests ---


class TestBootDomainRegistry:
    """Tests for boot_domain_registry() integration.

    Validates: Requirements 22.1, 22.2, 22.3, 22.4
    """

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_full_boot_discovery_and_registration(self, mock_eps) -> None:
        """Full boot discovers domains and scans for providers.

        Validates: Requirements 22.1, 22.2, 22.3
        """
        meta = _make_metadata()
        provider_ep = _FakeEntryPoint("pydantic")

        # First call: functualize.domains group
        # Second call: functualize.ai_providers group
        def side_effect(group: str):
            if group == "functualize.domains":
                return [_FakeEntryPoint("ai", load_result=meta)]
            elif group == "functualize.ai_providers":
                return [provider_ep]
            return []

        mock_eps.side_effect = side_effect

        app = MagicMock()
        app._resolution_chain = None

        registry = boot_domain_registry(app)

        assert len(registry) == 1
        assert "ai" in registry
        info = registry.get("ai")
        assert info is not None
        assert "pydantic" in info.available_providers

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_auto_selects_single_provider(self, mock_eps) -> None:
        """Auto-selects the single installed provider at boot.

        Validates: Requirement 22.4
        """
        meta = _make_metadata()
        provider_ep = _FakeEntryPoint("pydantic")

        def side_effect(group: str):
            if group == "functualize.domains":
                return [_FakeEntryPoint("ai", load_result=meta)]
            elif group == "functualize.ai_providers":
                return [provider_ep]
            return []

        mock_eps.side_effect = side_effect

        app = MagicMock()
        app._resolution_chain = None

        registry = boot_domain_registry(app)

        info = registry.get("ai")
        assert info is not None
        assert info.active_provider_name == "pydantic"

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_no_auto_select_when_multiple_providers(self, mock_eps) -> None:
        """Does not auto-select when multiple providers are installed."""
        meta = _make_metadata()

        def side_effect(group: str):
            if group == "functualize.domains":
                return [_FakeEntryPoint("ai", load_result=meta)]
            elif group == "functualize.ai_providers":
                return [
                    _FakeEntryPoint("pydantic"),
                    _FakeEntryPoint("instructor"),
                ]
            return []

        mock_eps.side_effect = side_effect

        app = MagicMock()
        app._resolution_chain = None

        registry = boot_domain_registry(app)

        info = registry.get("ai")
        assert info is not None
        assert info.active_provider_name is None

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_respects_configured_provider(self, mock_eps) -> None:
        """Uses the configured provider when resolution chain has one."""
        meta = _make_metadata()

        def side_effect(group: str):
            if group == "functualize.domains":
                return [_FakeEntryPoint("ai", load_result=meta)]
            elif group == "functualize.ai_providers":
                return [
                    _FakeEntryPoint("pydantic"),
                    _FakeEntryPoint("instructor"),
                ]
            return []

        mock_eps.side_effect = side_effect

        # Mock app with resolution chain returning "pydantic" for [ai] provider
        app = MagicMock()
        resolved = MagicMock()
        resolved.value = "pydantic"
        app._resolution_chain.resolve.return_value = resolved

        registry = boot_domain_registry(app)

        info = registry.get("ai")
        assert info is not None
        assert info.active_provider_name == "pydantic"

    @patch("functualize._plugins.domain_registry.importlib.metadata.entry_points")
    def test_handles_no_providers_gracefully(self, mock_eps) -> None:
        """Handles domains with no providers without crashing."""
        meta = _make_metadata()

        def side_effect(group: str):
            if group == "functualize.domains":
                return [_FakeEntryPoint("ai", load_result=meta)]
            elif group == "functualize.ai_providers":
                return []
            return []

        mock_eps.side_effect = side_effect

        app = MagicMock()
        app._resolution_chain = None

        registry = boot_domain_registry(app)

        info = registry.get("ai")
        assert info is not None
        assert info.available_providers == {}
        assert info.active_provider_name is None
