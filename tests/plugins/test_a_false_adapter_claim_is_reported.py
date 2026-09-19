"""A plugin that says it is an adapter and is not gets said so. T9, AC-17.

`functualize-mcp` declared `adapter_type = "mcp"`, was named `…AdapterPlugin`,
and said *"Implements the AdapterPlugin protocol"* in its docstring — with no
`run` and no `shutdown`, two of the protocol's three methods. It shipped that way
because **`validate_adapter` had no production caller**: a re-export and five
test files, so nothing on a real boot ever asked.

`validate_adapter` cannot get one. It lives in the public `app/` package and the
`Internal never imports public` contract forbids `_plugins` from importing it.
The **protocol** is the shared thing, and `_plugins` may import `_types`, so the
check lives in `_validate_metadata` — the one function every load path reaches,
for entry-point, explicit and file-based plugins alike.

Warning rather than rejection, deliberately: `adapter_type` is declarative and
nothing dispatches on it, so refusing the plugin would have removed
`functualize-mcp` from every installation that had it over a claim that changes
no behaviour. The cost of the defect is a reader believing a docstring, so the
fix is to say so where somebody will see it.
"""

from __future__ import annotations

import logging
from typing import Any

from functualize._plugins.metadata import _validate_metadata


class _HonestPlugin:
    """Claims nothing about adapters, so nothing is checked."""

    name = "honest"
    version = "1.0.0"
    description = "makes no adapter claim"

    def __call__(self, app: Any) -> None: ...


class _RealAdapter:
    name = "real"
    version = "1.0.0"
    description = "an adapter that is one"
    adapter_type = "real"

    def __call__(self, app: Any) -> None: ...
    def run(self, *args: Any, **kwargs: Any) -> Any: ...
    def shutdown(self) -> None: ...


class _FalseClaim:
    """The exact shape `MCPAdapterPlugin` had: the label, not the methods."""

    name = "pretender"
    version = "1.0.0"
    description = "says adapter, is not"
    adapter_type = "pretend"

    def __call__(self, app: Any) -> None: ...


def test_a_false_claim_is_warned_about(caplog: Any) -> None:
    with caplog.at_level(logging.WARNING, logger="functualize._plugins.loader"):
        errors = _validate_metadata(_FalseClaim(), "pretender")

    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "adapter_type" in messages, messages
    assert "run" in messages and "shutdown" in messages, messages
    assert errors == [], "a false claim is reported, not rejected"


def test_a_real_adapter_is_silent(caplog: Any) -> None:
    with caplog.at_level(logging.WARNING, logger="functualize._plugins.loader"):
        _validate_metadata(_RealAdapter(), "real")
    assert not caplog.records


def test_a_plugin_making_no_claim_is_silent(caplog: Any) -> None:
    """Most plugins are not adapters. They must not be nagged about it."""
    with caplog.at_level(logging.WARNING, logger="functualize._plugins.loader"):
        _validate_metadata(_HonestPlugin(), "honest")
    assert not caplog.records


def test_the_shipped_mcp_plugin_no_longer_trips_it(caplog: Any) -> None:
    """The regression this was written for, against the real class."""
    import pytest

    mcp = pytest.importorskip("functualize_mcp")
    with caplog.at_level(logging.WARNING, logger="functualize._plugins.loader"):
        _validate_metadata(mcp.MCPAdapterPlugin(), "mcp")
    assert not caplog.records, [r.message for r in caplog.records]
