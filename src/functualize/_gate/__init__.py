"""Gate resolution system.

Provides the gate strategy enum, resolver protocol, context dataclass,
and registry for managing gate resolution strategies.

Public exports:
    GateStrategy: Named strategies for resolving gate inputs.
    GateResolver: Protocol for gate strategy implementations.
    ResolveResolver: Default resolver that builds model from config chain.
    GateContext: Information provided to a gate resolver strategy.
    GateRegistry: Registry for strategies and presets.
"""

from functualize._gate._context import GateContext
from functualize._gate._registry import GateRegistry
from functualize._gate._resolver import GateResolver, ResolveResolver
from functualize._gate._strategy import GateStrategy

__all__ = [
    "GateContext",
    "GateRegistry",
    "GateResolver",
    "GateStrategy",
    "ResolveResolver",
]
