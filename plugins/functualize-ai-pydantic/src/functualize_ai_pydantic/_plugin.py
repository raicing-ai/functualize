"""PydanticAI Plugin — DI registration and boot logic.

Registers both the generic AI type and the concrete PydanticAI type
with the DI registry. Reads configuration from the [ai] config section
consuming the AIConfig model fields.

Registered via entry point `functualize.ai_providers` with name "pydantic".
"""

from __future__ import annotations

import logging
from typing import Any

from functualize_ai import AI, AIConfig

from functualize_ai_pydantic._provider import PydanticAIProvider

__all__ = ["PydanticAIPlugin"]

logger = logging.getLogger(__name__)


class PydanticAIPlugin:
    """Plugin that registers PydanticAI-backed AI implementation.

    At boot time (APP_READY), reads AIConfig from the app's [ai] config
    section, creates a PydanticAIProvider instance, and registers both
    the generic AI capability and the concrete PydanticAI subclass with
    the DI registry via app.provide().

    Implements the plugin callable protocol expected by functualize's
    plugin discovery system.
    """

    name: str = "ai-pydantic"
    version: str = "0.1.0"
    description: str = "PydanticAI-backed AI provider with tool calling and streaming"
    domain: str = "ai"

    def __init__(self) -> None:
        self._provider: PydanticAIProvider | None = None
        self._pydantic_ai: Any = None
        self._app: Any = None

    @property
    def provider(self) -> PydanticAIProvider | None:
        """The PydanticAIProvider instance (available after APP_READY)."""
        return self._provider

    def __call__(self, app: Any) -> None:
        """Register the plugin with the application instance.

        Hooks into APP_READY for initialization and DI registration.
        """
        self._app = app
        hook_registry = app.hook_registry

        from functualize._events.hooks import HookEvent

        # APP_READY: initialize provider and register with DI
        hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

    def _on_app_ready(self, app: Any) -> None:
        """Initialize PydanticAI instances and register with DI registry.

        Reads AIConfig from the [ai] config section, creates a
        PydanticAIProvider instance, constructs the PydanticAI capability,
        and registers both the generic AI type and the concrete PydanticAI
        type with the app's DI registry.
        """
        try:
            # Resolve AIConfig from the [ai] config section
            config = self._resolve_ai_config(app)

            # Create the provider
            self._provider = PydanticAIProvider(config)

            # Create the concrete PydanticAI subclass instance
            from functualize_ai_pydantic._pydantic_ai import PydanticAI

            # Get event bus if available
            event_bus = getattr(app, "event_bus", None)

            # Resolve state namespace for AI budget tracking
            state_ns = self._resolve_state_namespace(app)

            # Get job registry for ToolScope resolution
            job_registry = getattr(app, "job_registry", None)

            self._pydantic_ai = PydanticAI(
                _provider=self._provider,
                _event_bus=event_bus,
                _state_ns=state_ns,
                _model=config.model,
                _job_registry=job_registry,
            )

            # Register the generic AI type with DI
            app.provide(AI, self._pydantic_ai)

            # Register the concrete PydanticAI type with DI
            app.provide(PydanticAI, self._pydantic_ai)

            logger.debug(
                "PydanticAIPlugin: Registered AI and PydanticAI (model=%s)",
                config.model,
            )
        except Exception as e:
            logger.error("PydanticAIPlugin: Failed to initialize: %s", e)

    # ─── Internal Helpers ─────────────────────────────────────────────

    def _resolve_ai_config(self, app: Any) -> AIConfig:
        """Resolve AIConfig from the app's [ai] config section.

        Falls back to default AIConfig values if no configuration is found.
        """
        try:
            config = app.resolve_model("ai", AIConfig)
            return config  # type: ignore[return-value]
        except Exception:
            # No config available — use defaults
            logger.debug(
                "PydanticAIPlugin: No [ai] config section found, using defaults."
            )
            return AIConfig()

    def _resolve_state_namespace(self, app: Any) -> Any:
        """Resolve the AI state namespace for budget tracking.

        Uses the AI SDK's resolve_ai_state_backend helper to get a
        backend suitable for budget tracking, with graceful fallback
        to ephemeral in-memory state if the State domain isn't installed.
        """
        try:
            from functualize_ai._state_fallback import resolve_ai_state_backend

            # Try to get the registered StateBackend from DI
            backend = None
            try:
                from functualize_state import StateBackend

                backend = app._di_registry.resolve(StateBackend)
            except (ImportError, Exception):
                # State domain not installed or not yet registered
                pass

            return resolve_ai_state_backend(backend)
        except ImportError:
            # functualize_ai._state_fallback not available — shouldn't happen
            logger.debug(
                "PydanticAIPlugin: state fallback module not available, "
                "budget tracking will be disabled."
            )
            return None
