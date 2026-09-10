"""Everything a plugin registers into the app — `app.extensions`.

Extracted from :class:`~functualize.app.core.FunctualizeApp`
(engine-sealed-construction/T9). Eleven members with one caller in common: a
plugin, at wiring time. Commands, job providers, job transforms, agent-step
executors, surfaces, ambient constructs, instrumentation points, and the
per-plugin state bag they hang things off.

**Not here:** ``push_surface``, ``pop_surface``, ``live_zone`` and ``collector``,
which look like they belong. They are members of the ``EngineHost`` protocol
that T1 sealed — the engine reaches them through the port, by those names — so
grouping them would unseal exactly what this feature spent three tasks
building. The port is the floor of this class's diet, and it is a real one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from functualize._app.models import PluginCommand
    from functualize._types.protocols import (
        AgentStepExecutor,
        JobProvider,
        JobTransform,
    )
    from functualize.app.core import FunctualizeApp

__all__ = ["ExtensionsFacade"]


class ExtensionsFacade:
    """`app.extensions` — what a plugin registers: commands, providers, surfaces, constructs."""

    __slots__ = ("_app",)

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    def register_plugin_command(
        self,
        name: str,
        callback: Callable[..., Any],
        help_text: str = "",
        namespace: str | None = None,
        needs_terminal: bool = False,
    ) -> None:
        """Register a command from a plugin.

        Args:
            name: Command name (lowercase alphanumeric + hyphens).
            callback: Callable to invoke when the command is executed.
            help_text: Help text (max 256 chars).
            namespace: Optional flat CLI namespace to mount the command under
                (``namespace="mcp"`` + ``name="serve"`` → ``func mcp serve``).
                None mounts the command at the top level.
            needs_terminal: True when running the command takes over the
                controlling terminal — a server speaking a protocol on stdio, a
                spawned editor. A TUI front-end reads this to step aside rather
                than capture the command's output on a worker thread, which for
                a stdio server would corrupt the protocol it speaks.
        """
        from functualize._app.impl import register_plugin_command

        register_plugin_command(
            self._app, name, callback, help_text, namespace, needs_terminal
        )

    def get_plugin_commands(self) -> list[PluginCommand]:
        """Return all registered plugin commands."""
        return list(self._app._plugin_commands_list)

    def get_plugin(self, name: str) -> Any:
        """Look up a registered plugin instance by name."""
        from functualize._app.impl import get_plugin

        return get_plugin(self._app, name)

    def add_job_provider(
        self,
        provider: JobProvider,
        transforms: list[JobTransform] | None = None,
    ) -> None:
        """Register a job provider with optional provider-scoped transforms."""
        self._app._resolution_pipeline.add_provider(provider, transforms)
        self._app._jobs_memo = None

    def add_job_transform(self, transform: JobTransform) -> None:
        """Register an app-level transform (applies to ALL providers)."""
        self._app._resolution_pipeline.add_transform(transform)
        self._app._jobs_memo = None

    def register_agent_step_executor(self, executor: AgentStepExecutor) -> None:
        """Register an executor that services ``AgentStep`` nodes.

        Registered, never auto-discovered: a workflow that declares an agent
        step reaches an executor because a package registered one, not because
        a discovery scan found it.

        Args:
            executor: An implementation of `AgentStepExecutor` — a ``name``, a
                ``capabilities`` set, and ``execute(ctx)``.

        Raises:
            TypeError: ``executor`` does not satisfy `AgentStepExecutor`, so a
                forgotten capability declaration fails here rather than
                mid-walk.
            ValueError: Its name is empty or already registered.
        """
        from functualize._app.impl import register_agent_step_executor

        register_agent_step_executor(self._app, executor)

    @property
    def extension_state(self) -> dict[str, Any]:
        """Mutable namespace for consumer-owned state keyed by consumer name.

        A sanctioned place for long-lived consumers (MCP server, TUI
        orchestrator) to hang state that belongs to them, not to the kernel —
        instead of monkey-patching private attributes onto the app instance.

        Keys should be namespaced by consumer (e.g. ``"mcp"``,
        ``"orchestrator"``). The kernel never reads or interprets the
        contents; it only guarantees the dict exists and survives for the
        app's lifetime.

        Example:
            state = app.extensions.extension_state.setdefault("mcp", {})
            state["gate_checkpoints"] = {...}
        """
        # Lazily created: both boot paths and partially-constructed test
        # doubles get a working namespace without an __init__ contract.
        state = getattr(self._app, "_extension_state", None)
        if state is None:
            state = {}
            self._app._extension_state = state  # type: ignore[attr-defined]
        return state

    def register_surface(self, surface: Any) -> None:
        """Register something that renders a job's events, answers its prompts, or both."""
        from functualize._app.impl import register_surface

        return register_surface(self._app, surface)

    def register_ambient_construct(
        self,
        construct_factory: Any,
        *,
        name: str | None = None,
        predicate: Any = None,
    ) -> None:
        """Register a live construct that renders by default for eligible jobs."""
        from functualize._app.impl import register_ambient_construct

        return register_ambient_construct(
            self._app, construct_factory, name=name, predicate=predicate
        )

    def resolve_ambient_constructs(self, descriptor: Any = None) -> list[Any]:
        """Instantiate the ambient constructs eligible for ``descriptor``.

        The public entry point for live zones that need to pre-mount ambient
        constructs. Delivery-layer surfaces (``_cli``) must come through here
        rather than reaching into ``_engine`` directly — see the "_cli uses
        public API only" import contract.

        Args:
            descriptor: The job about to run. None resolves none.

        Returns:
            Fresh construct instances, in registration order.
        """
        from functualize._engine.ambient import resolve_ambient_constructs

        return resolve_ambient_constructs(self._app, descriptor)

    def instrument(self, operation_point: str, priority: int = 0) -> Callable[..., Any]:
        """Decorator to register a function as middleware for an operation point."""
        from functualize._app.impl import make_instrument_decorator

        return make_instrument_decorator(self._app, operation_point, priority)
