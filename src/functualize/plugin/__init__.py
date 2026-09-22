"""Public plugin author API for functualize.

This module re-exports symbols that plugin authors need to build
functualize plugins: event infrastructure, job provider protocols,
adapter protocols, plugin metadata, and TUI extension protocols.

Usage:
    from functualize.plugin import EventBus, JobProvider, AdapterPlugin, PluginMetadata
    from functualize.plugin import DisplayProvider, PanelProvider, ThemeProvider
"""

from functualize._discovery.providers import Job, StaticProvider
from functualize._events.bus import EventBus, StructuredEvent
from functualize._events.hooks import HookEvent
from functualize._plugins.domain_registry import discover_domains, scan_domain_providers
from functualize._plugins.loader import PluginMetadata
from functualize._types.commands import CommandNode, CommandProvider
from functualize._types.errors import SubstrateInstallError
from functualize._types.host import PluginHost
from functualize._types.input_modes import DEFAULT_SIGIL, InputMode, InputModeRegistry
from functualize._types.interactivity import (
    LiveConstruct,
    PromptChoice,
    PromptCollector,
    PromptIntent,
    PromptRequest,
    PromptResponse,
    PromptSeverity,
    Surface,
)
from functualize._types.protocols import (
    AdapterPlugin,
    AgentCapability,
    AgentStepContext,
    AgentStepExecutor,
    AgentStepResult,
    FormatProvider,
    JobProvider,
    JobTransform,
    ModulePreFilter,
    PluginWithShutdown,
    Source,
    VaultKeyInitializer,
    VaultKeyProvider,
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
    # The provider that turns `Job`s (or plain callables) into a working
    # source. `Job` was public and `StaticProvider` was not, so the only
    # consumer of a published type lived behind a private import — and a
    # hand-rolled substitute had to reimplement parameter extraction, which is
    # also private, or publish jobs that take no arguments.
    "StaticProvider",
    # Discovery: decide what to import, without importing it
    "ModulePreFilter",
    # Adapter and plugin protocols
    "AdapterPlugin",
    "SubstrateInstallError",
    # The host port: what a plugin may ask of the application that loaded it.
    # Annotate `app` with this instead of `Any` or the concrete
    # `FunctualizeApp` — eleven members, each one earned by a measured client
    # count, and `AdapterPlugin.__call__` names it too.
    #
    # `PluginHost` alone, deliberately: its five view protocols
    # (`DependencyView` and the rest) are reached *through* it — `app.di` is
    # already typed — so importing them separately is never necessary to
    # write a plugin. They stay internal until something needs to name one.
    "PluginHost",
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
    # The full prompt vocabulary: PromptCollector.collect takes a PromptRequest
    # and returns a PromptResponse, dispatching on PromptIntent — so a plugin
    # author needs all of them to implement the protocol at all.
    "PromptRequest",
    "PromptResponse",
    "PromptIntent",
    "PromptSeverity",
    "PromptChoice",
    "PluginMetadata",
    "PluginWithShutdown",
    "Source",
    "FormatProvider",
    "VaultKeyInitializer",
    "VaultKeyProvider",
    # The agent step port. A step performed by an agent is an executor behind
    # this Protocol; what an executor can enforce is declared, and a step that
    # requires what the executor lacks is refused at validation rather than run
    # with the constraint silently unenforced. Registration is an app method —
    # nothing here is auto-discovered.
    "AgentStepExecutor",
    "AgentCapability",
    "AgentStepContext",
    "AgentStepResult",
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
