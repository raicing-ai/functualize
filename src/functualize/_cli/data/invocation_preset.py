"""Invocation preset reconstruction from per-field argument history.

Builds full command-line presets from per-field ``ArgumentHistory`` data,
enabling one-click replay of previous invocations in the TUI completion
list.  Each preset combines the most recent value for every recorded field
of a job into a single reconstructed invocation.

This module is in the ``_cli/`` layer — it uses only stdlib.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from functualize._cli.data.argument_history import ArgumentHistory


@dataclass(frozen=True)
class InvocationPreset:
    """A previous invocation that can be replayed.

    Attributes:
        job_name: The job that was invoked.
        kwargs: Reconstructed keyword arguments (field_name → value).
        timestamp: Approximate recency timestamp (higher = more recent).
        display_text: Human-readable CLI representation,
            e.g. ``"deploy --env staging --region us-east-1"``.
    """

    job_name: str
    kwargs: dict[str, str]
    timestamp: float
    display_text: str


def get_recent_invocations(
    history: ArgumentHistory,
    job_names: list[str],
    limit: int = 5,
    render_command: Callable[[str, dict[str, str]], str] | None = None,
) -> list[InvocationPreset]:
    """Build invocation presets from ArgumentHistory.

    Reconstructs full invocations from per-field history by combining
    the most recent value for each field of a job.

    Args:
        history: The argument history store to query.
        job_names: List of job names to consider.
        limit: Maximum number of presets to return.
        render_command: The caller's command-line emitter, supplied when a
            descriptor/trie is available. Keeps display paths and quoting in
            the same emitter as SmartBar write-back.

    Returns:
        A list of ``InvocationPreset`` items sorted by timestamp
        descending (most recent first), with at most ``limit`` entries.
    """
    presets: list[InvocationPreset] = []
    now = time.time()

    for idx, job_name in enumerate(job_names):
        if not history.has_history(job_name):
            continue

        # Reconstruct kwargs from per-field most-recent values.
        # Access the internal store to enumerate all field names for this job.
        job_fields = history._store.get(job_name, {})
        if not job_fields:
            continue

        kwargs: dict[str, str] = {}
        for field_name in job_fields:
            values = history.get_history(job_name, field_name)
            if values:
                # get_history returns most recent first
                kwargs[field_name] = values[0]

        if not kwargs:
            continue

        # Build display text: "job_name --field1 value1 --field2 value2"
        # Convert underscores in field names to hyphens for CLI display.
        parts = [job_name]
        for field_name, value in kwargs.items():
            cli_flag = field_name.replace("_", "-")
            parts.append(f"--{cli_flag}")
            parts.append(value)
        display_text = (
            render_command(job_name, kwargs)
            if render_command is not None
            else " ".join(parts)
        )

        # Use monotonically decreasing timestamp based on processing order
        # to maintain stable ordering (earlier in job_names = more recent).
        timestamp = now - idx

        presets.append(
            InvocationPreset(
                job_name=job_name,
                kwargs=kwargs,
                timestamp=timestamp,
                display_text=display_text,
            )
        )

    # Sort by timestamp descending (most recent first)
    presets.sort(key=lambda p: p.timestamp, reverse=True)

    return presets[:limit]
