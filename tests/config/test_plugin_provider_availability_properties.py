"""Property-based tests for plugin-registered provider availability.

Tests Property 26 from the design document: any provider registered via
explicit programmatic registration (simulating a plugin calling
app.config_registry.register_format_provider() or
app.config_registry.register_remote_provider()) is available for lookup
when config resolution is triggered.

**Validates: Requirements 9.1, 9.2**
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._config.registry import ProviderRegistry

# --- Strategies ---

# Strategy for valid file extensions (leading dot + lowercase alpha)
_extensions = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=1,
    max_size=6,
).map(lambda s: f".{s}")

# Strategy for valid remote provider identifiers (lowercase alpha + hyphens)
_identifiers = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",), whitelist_characters="-"),
    min_size=1,
    max_size=10,
).filter(lambda s: s[0].isalpha() and not s.endswith("-"))


# --- Test helpers ---


class StubFormatProvider:
    """A stub format provider simulating what a plugin would register."""

    def __init__(self, exts: list[str], label: str = "") -> None:
        self._extensions = exts
        self.label = label

    def extensions(self) -> list[str]:
        return self._extensions

    def parse(self, path: str) -> dict[str, Any]:
        return {"source": self.label}

    def serialize(self, data: dict[str, Any]) -> str:
        return f"# {self.label}"


class StubRemoteProvider:
    """A stub remote provider simulating what a plugin would register."""

    def __init__(self, ident: str, label: str = "") -> None:
        self._identifier = ident
        self.label = label

    def identifier(self) -> str:
        return self._identifier

    def is_ready(self) -> bool:
        return True

    def fetch(self, reference: str) -> str:
        return f"{self.label}:{reference}"


# --- Property 26: Plugin-registered provider availability ---


class TestProperty26PluginRegisteredProviderAvailability:
    """Any provider registered via explicit programmatic registration
    (simulating a plugin calling app.config_registry.register_format_provider()
    or app.config_registry.register_remote_provider()) is available for lookup
    when config resolution is triggered.

    **Validates: Requirements 9.1, 9.2**
    """

    @given(
        ext_list=st.lists(_extensions, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=100)
    def test_format_provider_available_after_plugin_registration(
        self, ext_list: list[str]
    ) -> None:
        """Format providers registered programmatically (as a plugin would do
        during __call__(app)) are immediately available for lookup via
        get_format_provider()."""
        registry = ProviderRegistry()

        # Simulate plugin registration: plugin registers a format provider
        provider = StubFormatProvider(ext_list, label="plugin_provider")
        registry.register_format_provider(provider)

        # Verify: every extension the plugin registered is resolvable
        for ext in ext_list:
            resolved = registry.get_format_provider(ext)
            assert resolved is provider

    @given(
        ident=_identifiers,
    )
    @settings(max_examples=100)
    def test_remote_provider_available_after_plugin_registration(
        self, ident: str
    ) -> None:
        """Remote providers registered programmatically (as a plugin would do
        during __call__(app)) are immediately available for lookup via
        get_remote_provider()."""
        registry = ProviderRegistry()

        # Simulate plugin registration: plugin registers a remote provider
        provider = StubRemoteProvider(ident, label="plugin_provider")
        registry.register_remote_provider(provider)

        # Verify: the identifier the plugin registered is resolvable
        resolved = registry.get_remote_provider(ident)
        assert resolved is provider

    @given(
        data=st.data(),
        ext_list=st.lists(_extensions, min_size=1, max_size=4, unique=True),
        ident_list=st.lists(_identifiers, min_size=1, max_size=4, unique=True),
    )
    @settings(max_examples=50)
    def test_multiple_plugin_registrations_all_available(
        self, data: st.DataObject, ext_list: list[str], ident_list: list[str]
    ) -> None:
        """When multiple plugins register different format and remote providers,
        all are available for lookup simultaneously.

        Note: Same-class re-registration for the same extension/identifier is
        idempotent (first-registered wins), per Requirement 10.1/10.3."""
        registry = ProviderRegistry()

        # Simulate multiple plugins registering different providers
        num_format_plugins = data.draw(
            st.integers(min_value=1, max_value=4), label="num_format_plugins"
        )
        format_providers: dict[str, StubFormatProvider] = {}
        for i in range(num_format_plugins):
            # Each plugin picks a unique subset of extensions
            plugin_exts = [ext_list[i % len(ext_list)]]
            fp = StubFormatProvider(plugin_exts, label=f"format_plugin_{i}")
            registry.register_format_provider(fp)
            # First-registered wins per extension (same-class re-registration
            # is a no-op per Requirement 10.1)
            for ext in plugin_exts:
                if ext not in format_providers:
                    format_providers[ext] = fp

        num_remote_plugins = data.draw(
            st.integers(min_value=1, max_value=4), label="num_remote_plugins"
        )
        remote_providers: dict[str, StubRemoteProvider] = {}
        for i in range(num_remote_plugins):
            ident = ident_list[i % len(ident_list)]
            rp = StubRemoteProvider(ident, label=f"remote_plugin_{i}")
            registry.register_remote_provider(rp)
            # First-registered wins per identifier (same-class re-registration
            # is a no-op per Requirement 10.3)
            if ident not in remote_providers:
                remote_providers[ident] = rp

        # All registered format providers should be available
        for ext, expected_fp in format_providers.items():
            resolved_fp = registry.get_format_provider(ext)
            assert resolved_fp is expected_fp

        # All registered remote providers should be available
        for ident, expected_rp in remote_providers.items():
            resolved_rp = registry.get_remote_provider(ident)
            assert resolved_rp is expected_rp

    @given(
        ext=_extensions,
        ident=_identifiers,
    )
    @settings(max_examples=100)
    def test_plugin_registration_before_resolution_is_available(
        self, ext: str, ident: str
    ) -> None:
        """Providers registered before config resolution (simulating the
        bootstrap order: plugins register providers, then resolution occurs)
        are available when resolution queries the registry."""
        registry = ProviderRegistry()

        # Phase 1: Plugin registration (happens during plugin.__call__(app))
        format_provider = StubFormatProvider([ext], label="pre_resolution_format")
        remote_provider = StubRemoteProvider(ident, label="pre_resolution_remote")
        registry.register_format_provider(format_provider)
        registry.register_remote_provider(remote_provider)

        # Phase 2: Config resolution queries the registry
        # (simulates what FileSource/RemoteSource do during resolution)
        assert registry.get_format_provider(ext) is format_provider
        assert registry.get_remote_provider(ident) is remote_provider

        # Also verify via list methods (used for introspection)
        all_format = registry.list_format_providers()
        assert ext in all_format
        assert all_format[ext] is format_provider

        all_remote = registry.list_remote_providers()
        assert ident in all_remote
        assert all_remote[ident] is remote_provider

    @given(
        builtin_ext=st.just(".toml"),
        plugin_ext=_extensions.filter(lambda e: e != ".toml" and e != ".ini"),
    )
    @settings(max_examples=50)
    def test_plugin_provider_coexists_with_builtin_providers(
        self, builtin_ext: str, plugin_ext: str
    ) -> None:
        """Plugin-registered providers coexist alongside built-in providers
        without interfering with each other."""
        registry = ProviderRegistry()

        # Register a built-in provider first (simulates step 2 in bootstrap)
        builtin_provider = StubFormatProvider([builtin_ext], label="builtin_toml")
        registry.register_format_provider(builtin_provider)

        # Then a plugin registers its own provider (simulates step 3 in bootstrap)
        plugin_provider = StubFormatProvider([plugin_ext], label="plugin_custom")
        registry.register_format_provider(plugin_provider)

        # Both should be independently available
        assert registry.get_format_provider(builtin_ext) is builtin_provider
        assert registry.get_format_provider(plugin_ext) is plugin_provider

    @given(
        ext_list=st.lists(
            _extensions.filter(lambda e: e not in (".ini", ".toml", ".cfg")),
            min_size=1,
            max_size=5,
            unique=True,
        ),
        ident_list=st.lists(_identifiers, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=50)
    def test_discover_entry_points_does_not_remove_programmatic_registrations(
        self, ext_list: list[str], ident_list: list[str]
    ) -> None:
        """Calling discover_entry_points() after programmatic registration
        does not remove or invalidate previously registered providers.
        This simulates the bootstrap order: plugins register first (step 3),
        then discover_entry_points() runs (step 4).

        Note: Extensions that collide with built-in providers (.ini, .toml)
        are excluded because a different-class entry point provider will
        correctly override a plugin's StubFormatProvider (Requirement 10.2)."""
        registry = ProviderRegistry()

        # Programmatic registration (plugin phase)
        format_providers: dict[str, StubFormatProvider] = {}
        for ext in ext_list:
            fp = StubFormatProvider([ext], label=f"plugin_{ext}")
            registry.register_format_provider(fp)
            format_providers[ext] = fp

        remote_providers: dict[str, StubRemoteProvider] = {}
        for ident in ident_list:
            rp = StubRemoteProvider(ident, label=f"plugin_{ident}")
            registry.register_remote_provider(rp)
            remote_providers[ident] = rp

        # Entry point discovery phase (runs after plugin loading)
        # This should not remove programmatic registrations
        registry.discover_entry_points()

        # All programmatically registered providers remain available
        for ext, expected_fp in format_providers.items():
            resolved_fp = registry.get_format_provider(ext)
            assert resolved_fp is expected_fp

        for ident, expected_rp in remote_providers.items():
            resolved_rp = registry.get_remote_provider(ident)
            assert resolved_rp is expected_rp
