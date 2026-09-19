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
        job_tools: Which jobs get a **tool of their own**, over and above the
            generic door. ``"all"`` (default, today's behaviour), ``"tagged"``
            (only jobs carrying ``job_tools_tag``), or ``"none"``.
        job_tools_tag: The tag ``job_tools="tagged"`` selects on.
        enable_management: When True, expose multi-server management meta-tools.

    **``job_tools`` decides the candidate set; the filters above narrow it.**
    They answer different questions — ``job_tools`` is "should this project
    publish per-job tools at all", ``include_tags``/``exclude_tags``/
    ``exclude_jobs`` are "which of the published ones". Collapsing them would
    make ``include_tags=[]`` ambiguous between *no filter* and *nothing*.

    **Why ``"none"`` is now expressible.** A per-job tool duplicates
    ``run_job(name, config)`` completely — both funnel to the same
    ``_execute_job`` — and buys one thing: typed parameters at the call site,
    paid for with a full JSON Schema per job in the connect-time tool list, for
    every session, whether or not the agent ever calls that job. Turning them
    off used to cost information, because every door was equally lossy about
    ``JobResult.metadata``. It no longer does: the generic door returns
    ``metadata``, so an agent that blocks a workflow through it learns its own
    scope id. That fix is what makes this switch safe, and it is why the two
    landed together.
    """

    transport: Literal["stdio", "http"] = "stdio"
    port: int = Field(default=8080, ge=1024, le=65535)
    host: str = "127.0.0.1"
    include_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    exclude_jobs: list[str] = Field(default_factory=list)
    job_tools: Literal["all", "tagged", "none"] = "all"
    job_tools_tag: str = "mcp"
    enable_management: bool = False
