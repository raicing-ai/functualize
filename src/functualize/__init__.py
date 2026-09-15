"""Functualize - A reusable Python CLI framework."""

__version__ = "0.3.0"

from functualize._config.job_config import JobConfigView
from functualize._gate import GateContext, GateResolver, GateStrategy
from functualize.app.core import FunctualizeApp
from functualize.job.context import RunContext
from functualize.workflow import (
    END,
    AgentStep,
    ConditionalEdge,
    Edge,
    Gate,
    Step,
    workflow,
)

__all__ = [
    "FunctualizeApp",
    "JobConfigView",
    "RunContext",
    "__version__",
    # Workflow types and decorator
    "workflow",
    "Step",
    "Gate",
    # The third node kind. It reached `functualize.workflow` and stopped there,
    # so `from functualize import Gate` worked and `from functualize import
    # AgentStep` did not — a facade that lists two of three node kinds teaches
    # the wrong vocabulary (asp M-5). `tests/test_public_api_surface.py` now
    # asserts the three travel together.
    "AgentStep",
    "Edge",
    "ConditionalEdge",
    "END",
    # Gate resolution types
    "GateStrategy",
    "GateResolver",
    "GateContext",
]
