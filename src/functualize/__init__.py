"""Functualize - A reusable Python CLI framework."""

__version__ = "0.2.0"

from functualize._config.job_config import JobConfigView
from functualize._gate import GateContext, GateResolver, GateStrategy
from functualize.app.core import FunctualizeApp
from functualize.job.context import RunContext
from functualize.workflow import END, ConditionalEdge, Edge, Gate, Step, workflow

__all__ = [
    "FunctualizeApp",
    "JobConfigView",
    "RunContext",
    "__version__",
    # Workflow types and decorator
    "workflow",
    "Step",
    "Gate",
    "Edge",
    "ConditionalEdge",
    "END",
    # Gate resolution types
    "GateStrategy",
    "GateResolver",
    "GateContext",
]
