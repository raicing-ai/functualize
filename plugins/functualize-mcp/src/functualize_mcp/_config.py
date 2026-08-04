"""MCP adapter configuration model.

Defines MCPConfig pydantic model with transport, networking, filtering,
and management settings for the MCP server.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["MCPConfig"]


class MCPConfig(BaseModel):
    """Configuration for the MCP delivery adapter.

    Read from the ``[mcp]`` config section. Controls transport mode,
    network binding, job visibility filtering, and management features.

    Attributes:
        transport: Server transport mode — "stdio" (default) or "http".
        port: HTTP port when using HTTP+SSE transport.
        host: Bind address for HTTP transport.
        include_tags: Only expose jobs tagged with at least one of these tags.
            Empty list means no tag filtering (expose all visible jobs).
        exclude_tags: Hide jobs tagged with any of these tags.
        exclude_jobs: Hide specific jobs by name from MCP tool listings.
        enable_management: When True, expose multi-server management meta-tools.
    """

    transport: Literal["stdio", "http"] = "stdio"
    port: int = Field(default=8080, ge=1024, le=65535)
    host: str = "127.0.0.1"
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    exclude_jobs: list[str] = Field(default_factory=list)
    enable_management: bool = False
