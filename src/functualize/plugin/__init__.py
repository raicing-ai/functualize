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
from functualize._gate.decision_strategy import DecisionGateResolver
from functualize._plugins.domain_registry import discover_domains, scan_domain_providers
from functualize._plugins.loader import PluginMetadata
from functualize._types.commands import CommandNode, CommandProvider
from functualize._types.decision import (
    ChoiceRequest,
    DecisionProvenance,
    DecisionProvider,
    DecisionResult,
)
from functualize._types.errors import (
    DecisionFailure,
    DecisionUnavailableError,
    IllegalTransition,
    RuntimeStoreCapabilityError,
    RuntimeStoreSelectionError,
    SubstrateInstallError,
)
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
from functualize._types.persistence import (
    Attempt,
    CancelResult,
    CancelWorkflow,
    Claimed,
    ClaimWorkflow,
    CompleteStep,
    Conflict,
    ConsumeInput,
    EffectWriter,
    EventView,
    EventWriter,
    FinishAttempt,
    InputReader,
    InputRequest,
    InputWriter,
    PreparedStore,
    Resumed,
    ResumeWorkflow,
    RunQuery,
    RunReader,
    RuntimeStore,
    RuntimeStoreConfig,
    RuntimeStoreFactory,
    RuntimeTransaction,
    RunTree,
    RunView,
    RunWriter,
    StartAttempt,
    StateBatch,
    StoreProfile,
    SuspendAtGate,
    WorkflowQuery,
    WorkflowReader,
    WorkflowView,
    WorkflowWriter,
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
    KeyAvailability,
    ModulePreFilter,
    PluginWithShutdown,
    Source,
    VaultKeyInitializer,
    VaultKeyProbe,
    VaultKeyProvider,
    VaultKeyUnlocker,
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
    # The optional probe half of the key seam: can this provider answer
    # without prompting? Separate for the same reason VaultKeyInitializer is
    # — widening VaultKeyProvider would invalidate every read-only
    # structural implementation that exists today.
    "VaultKeyProbe",
    "KeyAvailability",
    # The unlock half: the one capability that may prompt, used only by
    # `func builtin vault unlock`. A provider's `get_key` never prompts.
    "VaultKeyUnlocker",
    # The agent step port. A step performed by an agent is an executor behind
    # this Protocol; what an executor can enforce is declared, and a step that
    # requires what the executor lacks is refused at validation rather than run
    # with the constraint silently unenforced. Registration is an app method —
    # nothing here is auto-discovered.
    "AgentStepExecutor",
    "AgentCapability",
    "AgentStepContext",
    "AgentStepResult",
    # The decision provider port. PROVISIONAL: outside the list of names 1.0
    # promises to keep, and this comment is the marker until the mechanism that
    # marks provisional names exists. A provider proposes a candidate for a
    # closed choice; whether it is acted on is the gate's declared rule, never
    # the provider's.
    "DecisionProvider",
    "ChoiceRequest",
    "DecisionResult",
    "DecisionProvenance",
    "DecisionFailure",
    "DecisionUnavailableError",
    # The provider-neutral resolver a provider plugin registers as the
    # `decision` gate strategy, wrapped around its own DecisionProvider.
    "DecisionGateResolver",
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
    # Runtime persistence: what a storage backend implements and how boot
    # selects it by `runtime_store.url` — the factory contract, the store and
    # its transaction, the writer and reader protocols, and the command,
    # outcome, view and query values they speak.
    "StoreProfile",
    "ClaimWorkflow",
    "CompleteStep",
    "SuspendAtGate",
    "ResumeWorkflow",
    "ConsumeInput",
    "CancelWorkflow",
    "StateBatch",
    "StartAttempt",
    "FinishAttempt",
    "Claimed",
    "Conflict",
    "Resumed",
    "CancelResult",
    "Attempt",
    "InputRequest",
    "RunView",
    "WorkflowView",
    "EventView",
    "RunTree",
    "RunQuery",
    "WorkflowQuery",
    "RunWriter",
    "WorkflowWriter",
    "InputWriter",
    "EventWriter",
    "EffectWriter",
    "RunReader",
    "WorkflowReader",
    "InputReader",
    "RuntimeStore",
    "RuntimeTransaction",
    "RuntimeStoreConfig",
    "PreparedStore",
    "RuntimeStoreFactory",
    "IllegalTransition",
    "RuntimeStoreCapabilityError",
    "RuntimeStoreSelectionError",
]
