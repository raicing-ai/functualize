"""Async Bridge — Bridges async PydanticAI calls to functualize's sync engine.

PydanticAI's core API is async-first. This module provides utilities to
bridge those async calls into functualize's synchronous execution model
using asyncio event loop management.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

__all__ = ["run_sync"]

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async coroutine synchronously.

    Bridges async PydanticAI calls to functualize's sync engine.
    Handles the case where an event loop may or may not already be running.

    If no event loop is running, creates a new one via asyncio.run().
    If an event loop IS already running (e.g. inside Jupyter or an async framework),
    uses a background thread with its own event loop to avoid nested loop errors.

    Args:
        coro: The coroutine to execute synchronously.

    Returns:
        The result of the coroutine.

    Raises:
        Any exception raised by the coroutine is propagated.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to use asyncio.run()
        return asyncio.run(coro)

    # A loop is already running — run in a background thread
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()
