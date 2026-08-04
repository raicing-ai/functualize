"""MCP Adapter Plugin — DI registration and boot.

Registers the MCP delivery adapter with the application, setting up
gate strategies, tools, and server configuration.

Registered via entry point ``functualize.plugins`` with name "mcp".
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["MCPAdapterPlugin"]

logger = logging.getLogger(__name__)


class MCPAdapterPlugin:
    """Plugin that exposes functualize jobs as MCP tools via FastMCP.

    Implements the AdapterPlugin protocol with adapter_type "mcp".
    At boot time, reads MCPConfig from the application's config section,
    registers gate strategies (ai_outbound), and prepares the MCP server
    for serving when invoked via the CLI.
    """

    name: str = "mcp"
    version: str = "0.1.0"
    description: str = "MCP delivery adapter — exposes jobs as MCP tools"
    adapter_type: str = "mcp"

    def __init__(self) -> None:
        self._config: Any = None
        self._server: Any = None
        self._app: Any = None

    @property
    def config(self) -> Any:
        """The MCPConfig instance (resolved lazily on first access)."""
        self._ensure_initialized()
        return self._config

    @property
    def server(self) -> Any:
        """The MCPServer instance (created lazily on first access).

        Importing MCPServer triggers heavy dependencies (pydantic-ai, httpx,
        anyio). By deferring until first access, non-MCP commands avoid the
        ~800ms import cost entirely.
        """
        self._ensure_initialized()
        if self._server is None and self._app is not None and self._config is not None:
            from functualize_mcp._server import MCPServer

            self._server = MCPServer(self._app, config=self._config)
        return self._server

    def __call__(self, app: Any) -> None:
        """Register the MCP adapter plugin with the application.

        Hooks into APP_READY for initialization and server setup.

        Args:
            app: The FunctualizeApp instance.
        """
        from functualize._events.hooks import HookEvent

        self._app = app
        app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)

    def _on_app_ready(self, app: Any) -> None:
        """Register MCP plugin with DI and defer heavy initialization.

        Config resolution, gate strategy registration, and CLI commands
        are all deferred to avoid triggering pydantic model compilation
        during boot (~200ms penalty for the first BaseModel subclass).

        The actual initialization happens lazily on first property access
        or CLI command invocation.

        Args:
            app: The FunctualizeApp instance.
        """
        try:
            # Register the plugin instance with DI (lightweight, no pydantic)
            app.provide_named("mcp_plugin", self)
            app.provide(MCPAdapterPlugin, self)

            # Register CLI commands (closures that resolve config lazily)
            self._register_cli_commands(app)
        except Exception as e:
            logger.error("MCPAdapterPlugin: Failed to initialize: %s", e)

    def _ensure_initialized(self) -> None:
        """Lazily initialize config and gate strategy on first use."""
        if self._config is not None:
            return
        app = self._app
        if app is None:
            return
        self._config = self._resolve_mcp_config(app)
        self._register_ai_outbound_strategy(app)
        logger.debug(
            "MCPAdapterPlugin: Initialized with transport=%s, host=%s, port=%d",
            self._config.transport,
            self._config.host,
            self._config.port,
        )

    # ─── Internal Helpers ─────────────────────────────────────────────

    def _resolve_mcp_config(self, app: Any) -> Any:
        """Resolve MCPConfig from the app's [mcp] config section.

        Falls back to default MCPConfig values if no configuration is found.

        Args:
            app: The FunctualizeApp instance.

        Returns:
            An MCPConfig instance with resolved or default values.
        """
        from functualize_mcp._config import MCPConfig

        try:
            config = app.resolve_model("mcp", MCPConfig)
            return config
        except Exception:
            logger.debug(
                "MCPAdapterPlugin: No [mcp] config section found, using defaults."
            )
            return MCPConfig()

    def _register_ai_outbound_strategy(self, app: Any) -> None:
        """Register the AI_OUTBOUND gate strategy and preset.

        Registers the ai_outbound strategy unconditionally when the MCP
        plugin boots. This strategy serializes workflow checkpoint and
        pauses execution, allowing an external AI agent to provide input
        via MCP.

        Also registers the "ai_outbound" preset mapping to the strategy
        fallback chain: ["ai_outbound", "prompt", "resolve"].

        Args:
            app: The FunctualizeApp instance.
        """
        try:
            from functualize_mcp._gate_strategy import (
                register_ai_outbound_gate_strategy,
            )

            register_ai_outbound_gate_strategy(app)

            logger.debug(
                "MCPAdapterPlugin: Registered 'ai_outbound' gate strategy and preset.",
            )
        except Exception as e:
            logger.warning(
                "MCPAdapterPlugin: Failed to register ai_outbound strategy: %s", e
            )

    def _register_cli_commands(self, app: Any) -> None:
        """Register MCP CLI commands with the application.

        Registers the following commands under the 'mcp' group:
        - ``func mcp serve``: Start an MCP server (foreground)
        - ``func mcp start``: Start a background MCP HTTP server
        - ``func mcp list``: List running managed servers
        - ``func mcp stop``: Stop a managed server by name or all servers
        - ``func mcp schema``: Export job schemas in multiple formats
        - ``func mcp tools``: List exposed MCP tools without starting a server

        Args:
            app: The FunctualizeApp instance.
        """
        try:
            self._register_serve_command(app)
            self._register_start_command(app)
            self._register_list_command(app)
            self._register_stop_command(app)
            self._register_schema_command(app)
            self._register_tools_command(app)
        except Exception as e:
            logger.warning("MCPAdapterPlugin: Failed to register CLI commands: %s", e)

    def _register_serve_command(self, app: Any) -> None:
        """Register the 'func mcp serve' command."""
        plugin = self

        def serve_command(
            http: bool = False,
            port: int | None = None,
            host: str | None = None,
        ) -> None:
            """Start an MCP server (foreground)."""
            server = plugin.server
            config = plugin.config
            if http or (config and config.transport == "http"):
                effective_port = port or (config.port if config else 8080)
                effective_host = host or (config.host if config else "127.0.0.1")
                server.start_http(effective_host, effective_port)
            else:
                server.start_stdio()

        app.register_plugin_command(
            "serve", serve_command, help_text="Start MCP server", namespace="mcp"
        )

    def _register_start_command(self, app: Any) -> None:
        """Register the 'func mcp start' command."""

        def start_command(
            directory: str,
            name: str | None = None,
            port: int = 8080,
        ) -> None:
            """Start a background MCP HTTP server for a project directory."""
            import sys
            from pathlib import Path

            from functualize_mcp._server_manager import ServerManager

            manager = ServerManager()
            effective_name = name or Path(directory).resolve().name

            try:
                info = manager.start(directory, effective_name, port)
                print(
                    f"Started server '{info.name}' "
                    f"(PID={info.pid}) on port {info.port} "
                    f"for {info.directory}"
                )
            except (ValueError, RuntimeError) as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

        app.register_plugin_command(
            "start",
            start_command,
            help_text="Start a background MCP HTTP server",
            namespace="mcp",
        )

    def _register_list_command(self, app: Any) -> None:
        """Register the 'func mcp list' command."""

        def list_command() -> None:
            """Display all running managed MCP servers."""
            from functualize_mcp._server_manager import ServerManager

            manager = ServerManager()
            servers = manager.list()

            if not servers:
                print("No managed MCP servers.")
                return

            # Header
            print(
                f"{'NAME':<20} {'DIRECTORY':<40} {'PORT':<8} {'PID':<10} {'STATUS':<10}"
            )
            print("-" * 88)

            for server in servers:
                # Truncate long directory paths
                directory = server.directory
                if len(directory) > 38:
                    directory = "..." + directory[-35:]

                print(
                    f"{server.name:<20} {directory:<40} "
                    f"{server.port:<8} {server.pid:<10} {server.status:<10}"
                )

        app.register_plugin_command(
            "list",
            list_command,
            help_text="List running MCP servers",
            namespace="mcp",
        )

    def _register_stop_command(self, app: Any) -> None:
        """Register the 'func mcp stop' command."""

        def stop_command(
            name: str | None = None,
            all: bool = False,
        ) -> None:
            """Stop a managed MCP server by name, or all servers with --all."""
            import sys

            from functualize_mcp._server_manager import ServerManager

            manager = ServerManager()

            if all:
                servers = manager.list()
                if not servers:
                    print("No managed MCP servers to stop.")
                    return
                manager.stop_all()
                print(f"Stopped {len(servers)} server(s).")
                return

            if name is None:
                print(
                    "Error: Provide a server name or use --all to stop all servers.",
                    file=sys.stderr,
                )
                sys.exit(1)

            try:
                manager.stop(name)
                print(f"Stopped server '{name}'.")
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

        app.register_plugin_command(
            "stop",
            stop_command,
            help_text="Stop a managed MCP server",
            namespace="mcp",
        )

    def _register_schema_command(self, app: Any) -> None:
        """Register the 'func mcp schema' command."""

        def schema_command(
            format: str = "json",
        ) -> None:
            """Export job schemas in the specified format."""
            from functualize_mcp._schema_export import SchemaExporter

            descriptors = app.get_jobs()
            exporter = SchemaExporter()

            if format == "json":
                print(exporter.export_json(descriptors))
            elif format == "markdown":
                results = exporter.export_markdown(descriptors)
                for _name, md in results:
                    print(md)
                    print()
            elif format == "openai":
                print(exporter.export_openai(descriptors))
            elif format == "typescript":
                print(exporter.export_typescript(descriptors))
            else:
                import sys

                print(
                    f"Error: Unknown format '{format}'. "
                    "Use: json, markdown, openai, typescript",
                    file=sys.stderr,
                )
                sys.exit(1)

        app.register_plugin_command(
            "schema",
            schema_command,
            help_text="Export job schemas in multiple formats",
            namespace="mcp",
        )

    def _register_tools_command(self, app: Any) -> None:
        """Register the 'func mcp tools' command."""

        def tools_command() -> None:
            """List all jobs that would be exposed as MCP tools."""
            from functualize_mcp._translator import (
                JobToolTranslator,
                read_cached_group_options,
            )

            descriptors = app.get_jobs()
            translator = JobToolTranslator(read_cached_group_options())
            config = self.config

            tool_defs = translator.translate_all(descriptors, config)

            if not tool_defs:
                print("No jobs would be exposed as MCP tools.")
                return

            print(f"MCP Tools ({len(tool_defs)} total):")
            print()
            for tool_def in tool_defs:
                desc = (tool_def.description or "").split("\n")[0][:60]
                print(f"  {tool_def.name}")
                if desc:
                    print(f"    {desc}")

        app.register_plugin_command(
            "tools",
            tools_command,
            help_text="List exposed MCP tools",
            namespace="mcp",
        )
