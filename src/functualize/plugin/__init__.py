"""Public plugin author API for functualize.

This module re-exports symbols that plugin authors need to build
functualize plugins: event infrastructure, job provider protocols,
adapter protocols, plugin metadata, and TUI extension protocols.

Usage:
    from functualize.plugin import EventBus, JobProvider, AdapterPlugin, PluginMetadata
    from functualize.plugin import DisplayProvider, PanelProvider, ThemeProvider
"""

from functualize._discovery.providers import Job
from functualize._events.bus import EventBus, StructuredEvent
from functualize._events.hooks import HookEvent
from functualize._plugins.domain_registry import discover_domains, scan_domain_providers
from functualize._plugins.loader import PluginMetadata
from functualize._types.commands import CommandNode, CommandProvider
from functualize._types.input_modes import DEFAULT_SIGIL, InputMode, InputModeRegistry
from functualize._types.interactivity import (
    LiveConstruct,
    PromptCollector,
    PromptRequest,
    Surface,
)
from functualize._types.protocols import (
    AdapterPlugin,
    FormatProvider,
    JobProvider,
    JobTransform,
    PluginWithShutdown,
    Source,
)
from functualize._types.settings import (
    AppSettingsSchema,
    Setting,
    SettingsSources,
)
from functualize.plugin.protocols import (
    BarRenderer,
    DisplayProvider,
    HeaderItemProvider,
    InteractiveContent,
    PanelProvider,
    PostRunStampProvider,
    SessionState,
    SignatureProvider,
    StatusBarItemProvider,
    ThemeProvider,
    validate_extension_id,
)

__all__ = [
    # Event infrastructure
    "EventBus",
    "HookEvent",
    "StructuredEvent",
    # Job provider protocols
    "JobProvider",
    "JobTransform",
    "Job",
    # Adapter and plugin protocols
    "AdapterPlugin",
    "AppSettingsSchema",
    "CommandNode",
    "CommandProvider",
    "DEFAULT_SIGIL",
    "InputMode",
    "InputModeRegistry",
    "Setting",
    "SettingsSources",
    "PromptCollector",
    "Surface",
    "LiveConstruct",
    "PromptRequest",
    "PluginMetadata",
    "PluginWithShutdown",
    "Source",
    "FormatProvider",
    # Domain discovery
    "discover_domains",
    "scan_domain_providers",
    # TUI extension protocols (Phase 5-6)
    "BarRenderer",
    "DisplayProvider",
    "HeaderItemProvider",
    "InteractiveContent",
    "PanelProvider",
    "PostRunStampProvider",
    "SessionState",
    "SignatureProvider",
    "StatusBarItemProvider",
    "ThemeProvider",
    "validate_extension_id",
]
