"""Functualize HTTP Plugin - HTTP delivery adapter using asyncio.

Provides HTTP serving support both as a standalone adapter (HttpAdapter)
and as a CLI command plugin (HttpServerPlugin). Both share a common
HttpServerCore class containing route building, request handling, and
async-to-sync bridging logic.

Uses Python's stdlib asyncio for a lightweight HTTP server without
heavy dependencies (no uvicorn/starlette required).

Key design:
- HttpServerCore: shared class with route building, request handling,
  async-to-sync bridging via asyncio.to_thread()
- HttpAdapter: satisfies AdapterPlugin Protocol, adapter_type="http"
- HttpServerPlugin: capability plugin registering a "serve" command

The kernel stays synchronous — the adapter owns the event loop internally
via asyncio.run().
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncio import AbstractEventLoop

    from functualize.app.core import FunctualizeApp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginMetadata:
    """Metadata for the functualize-http plugin package."""

    name: str = "functualize-http"
    version: str = "0.1.0"
    description: str = "HTTP delivery adapter plugin for functualize using asyncio"


class HttpServerCore:
    """Shared HTTP server logic for route building and request handling.

    Contains:
    - Route building: maps each job to POST /jobs/{job_name}/execute
    - Request handling: parse JSON body as kwargs, call app.execute()
    - Async-to-sync bridging: asyncio.to_thread() for kernel execution
    - Response formatting: JSON response with status and result
    - Health endpoint: GET /health returns 200
    - Job listing: GET /jobs returns available jobs

    Both HttpAdapter and HttpServerPlugin use this class internally
    to avoid code duplication.
    """

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app
        self._server: asyncio.Server | None = None

    async def start(self, host: str, port: int) -> None:
        """Start the HTTP server (async).

        Blocks until the server is shut down via stop().

        Args:
            host: Host address to bind to.
            port: Port number to listen on.
        """
        self._server = await asyncio.start_server(self._handle_connection, host, port)
        addrs = ", ".join(str(s.getsockname()) for s in self._server.sockets)
        logger.info(f"HTTP server listening on {addrs}")
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        """Stop the HTTP server gracefully."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def build_routes(self) -> dict[str, dict[str, Any]]:
        """Build route map from registered jobs.

        Returns a dict mapping (method, path) tuples conceptually:
        - GET /health
        - GET /jobs
        - POST /jobs/{job_name}/execute for each job

        This is used internally for request routing.
        """
        routes: dict[str, dict[str, Any]] = {}
        for descriptor in self._app.get_jobs():
            route_path = f"/jobs/{descriptor.name}/execute"
            routes[route_path] = {
                "method": "POST",
                "job_name": descriptor.name,
            }
        return routes

    async def handle_request(
        self, method: str, path: str, body: bytes
    ) -> tuple[int, dict[str, Any]]:
        """Route and handle a single HTTP request.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path.
            body: Request body bytes.

        Returns:
            Tuple of (status_code, response_dict).
        """
        # Health check
        if method == "GET" and path == "/health":
            return 200, {"status": "healthy"}

        # List jobs
        if method == "GET" and path == "/jobs":
            jobs = self._app.get_jobs()
            job_list = [
                {
                    "name": d.name,
                    "group": d.group,
                    "docstring": d.docstring,
                }
                for d in jobs
            ]
            return 200, {"jobs": job_list}

        # Execute job: POST /jobs/{job_name}/execute
        if method == "POST" and path.startswith("/jobs/") and path.endswith("/execute"):
            # Extract job name from path
            parts = path.split("/")
            # Expected: ["", "jobs", "<job_name>", "execute"]
            if len(parts) == 4:
                job_name = parts[2]
                return await self._execute_job(job_name, body)

        # Not found
        return 404, {"error": "Not found", "path": path}

    async def _execute_job(
        self, job_name: str, body: bytes
    ) -> tuple[int, dict[str, Any]]:
        """Execute a job with kwargs from the request body.

        Uses asyncio.to_thread() to bridge the synchronous kernel
        execution into the async server context.
        """
        # Parse body
        kwargs: dict[str, Any] = {}
        if body:
            try:
                kwargs = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                return 400, {"error": f"Invalid JSON body: {e}"}

            if not isinstance(kwargs, dict):
                return 400, {"error": "Request body must be a JSON object"}

        # Check job exists
        job = self._app.get_job(job_name)
        if job is None:
            return 404, {"error": f"Job '{job_name}' not found"}

        # Execute via asyncio.to_thread (async-to-sync bridge)
        try:
            result = await asyncio.to_thread(self._app.execute, job_name, **kwargs)
            return 200, {
                "status": result.status.value
                if hasattr(result.status, "value")
                else str(result.status),
                "duration_ms": result.duration_ms,
                "return_value": self._serialize_return_value(result.return_value),
            }
        except Exception as e:
            logger.exception(f"Error executing job '{job_name}'")
            return 500, {"error": str(e)}

    @staticmethod
    def _serialize_return_value(value: Any) -> Any:
        """Attempt to serialize a return value to JSON-compatible form."""
        if value is None:
            return None
        if isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list | tuple):
            return [HttpServerCore._serialize_return_value(v) for v in value]
        if isinstance(value, dict):
            return {
                str(k): HttpServerCore._serialize_return_value(v)
                for k, v in value.items()
            }
        # Fall back to string representation
        return str(value)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single TCP connection (HTTP/1.1 basic parsing)."""
        try:
            # Read request line
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                await writer.wait_closed()
                return

            request_str = request_line.decode("utf-8", errors="replace").strip()
            parts = request_str.split(" ")
            if len(parts) < 2:
                await self._send_response(writer, 400, {"error": "Bad request"})
                return

            method = parts[0].upper()
            path = parts[1].split("?")[0]  # Strip query params

            # Read headers
            content_length = 0
            while True:
                header_line = await reader.readline()
                if header_line in (b"\r\n", b"\n", b""):
                    break
                header_str = header_line.decode("utf-8", errors="replace").strip()
                if header_str.lower().startswith("content-length:"):
                    with contextlib.suppress(ValueError):
                        content_length = int(header_str.split(":", 1)[1].strip())

            # Read body
            body = b""
            if content_length > 0:
                body = await reader.readexactly(content_length)

            # Handle request
            status_code, response_body = await self.handle_request(method, path, body)
            await self._send_response(writer, status_code, response_body)

        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        except Exception:
            logger.exception("Error handling HTTP connection")
            with contextlib.suppress(Exception):
                await self._send_response(
                    writer, 500, {"error": "Internal server error"}
                )
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _send_response(
        writer: asyncio.StreamWriter,
        status_code: int,
        body: dict[str, Any],
    ) -> None:
        """Send an HTTP response with JSON body."""
        status_messages = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            500: "Internal Server Error",
        }
        status_text = status_messages.get(status_code, "Unknown")
        body_bytes = json.dumps(body).encode("utf-8")

        response = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode() + body_bytes

        writer.write(response)
        await writer.drain()


class HttpAdapter:
    """HTTP delivery adapter — satisfies AdapterPlugin Protocol.

    Starts an async HTTP server that blocks until shutdown, exposing
    all registered jobs as HTTP endpoints.

    The adapter owns the event loop internally via asyncio.run(),
    keeping the kernel synchronous.

    Usage:
        app = FunctualizeApp("myapp", job_sources=...)
        adapter = HttpAdapter()
        adapter(app)
        adapter.run(host="0.0.0.0", port=8000)
    """

    name: str = "functualize-http"
    version: str = "1.0.0"
    description: str = "HTTP delivery adapter plugin for functualize using asyncio"
    adapter_type: str = "http"

    def __init__(self) -> None:
        self._app: FunctualizeApp | None = None
        self._core: HttpServerCore | None = None

    def __call__(self, app: FunctualizeApp) -> None:
        """Setup phase — store app reference and create server core.

        Args:
            app: The FunctualizeApp kernel instance.
        """
        self._app = app
        self._core = HttpServerCore(app)

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Start the HTTP server (blocking).

        Accepts keyword arguments:
            host: Host address to bind to (default: "0.0.0.0").
            port: Port number to listen on (default: 8000).

        The adapter creates and runs an asyncio event loop internally.
        This method blocks until shutdown() is called or the server
        is interrupted.
        """
        if self._core is None:
            raise RuntimeError("HttpAdapter.run() called before __call__(app)")

        host = kwargs.get("host", "0.0.0.0")
        port = kwargs.get("port", 8000)

        asyncio.run(self._core.start(host, port))

    def shutdown(self) -> None:
        """Graceful shutdown — stops the HTTP server."""
        if self._core is not None and self._core._server is not None:
            # Schedule the stop coroutine on the running loop
            loop = self._get_running_loop()
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(self._core.stop())  # type: ignore[union-attr]
                )

    @staticmethod
    def _get_running_loop() -> AbstractEventLoop | None:
        """Get the currently running event loop, if any."""
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None


class HttpServerPlugin:
    """Capability plugin that registers a 'serve' CLI command.

    This plugin registers a `serve` command via
    `app.register_plugin_command()`. When invoked, the serve command
    starts an HTTP server using the shared HttpServerCore.

    Usage:
        app = FunctualizeApp("myapp", ...)
        plugin = HttpServerPlugin()
        plugin(app)
        # The 'serve' command is now available in the CLI

    The plugin is NOT an adapter — it augments the CLI adapter with
    an HTTP serving command.
    """

    name: str = "functualize-http-server"
    version: str = "1.0.0"
    description: str = "Registers a 'serve' command for HTTP serving"

    def __init__(self) -> None:
        self._app: FunctualizeApp | None = None
        self._core: HttpServerCore | None = None

    def __call__(self, app: FunctualizeApp) -> None:
        """Register the 'serve' command on the app.

        Args:
            app: The FunctualizeApp kernel instance.
        """
        self._app = app
        self._core = HttpServerCore(app)

        app.register_plugin_command(
            name="serve",
            callback=self._serve_command,
            help_text="Start an HTTP server exposing all jobs as endpoints",
        )

    def _serve_command(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
    ) -> None:
        """Start the HTTP server (CLI command handler).

        Args:
            host: Host address to bind to.
            port: Port number to listen on.
        """
        if self._core is None:
            raise RuntimeError("HttpServerPlugin not initialized")
        asyncio.run(self._core.start(host, port))


__all__ = [
    "HttpAdapter",
    "HttpServerCore",
    "HttpServerPlugin",
    "PluginMetadata",
]
