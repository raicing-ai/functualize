"""Invoke capability — job-to-job invocation interface.

Re-exports from the canonical implementation in _engine/capabilities.
"""

from functualize._engine.capabilities.invoke import Invoke, InvokeResult, WiredInvoke

__all__ = ["Invoke", "InvokeResult", "WiredInvoke"]
