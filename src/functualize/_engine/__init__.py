"""Execution lifecycle package for functualize.

Contains the job execution engine, middleware chain, execution context,
DI resolution planning, registered job internals, and capability classes
(Invoke, WorkflowTracker).

This package imports ONLY from `_types/`, `_primitives/`, `_events/`, and stdlib.
Never from peer layers (`_discovery/`, `_config/`, `_plugins/`) or `_app/`.
"""

from functualize._engine.context import ExecutionContext
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain, MiddlewareEntry
from functualize._engine.resolution import (
    ParamBinding,
    ResolutionPlan,
    build_resolution_plan,
)
from functualize._engine.result import RegisteredJob

__all__ = [
    "ExecutionContext",
    "ExecutionMiddlewareChain",
    "JobExecutionEngine",
    "MiddlewareEntry",
    "ParamBinding",
    "RegisteredJob",
    "ResolutionPlan",
    "build_resolution_plan",
]
