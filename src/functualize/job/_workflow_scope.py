"""Workflow scope module — re-exports from canonical internal location.

The implementation lives in _engine/capabilities/workflow_scope.py. This module
provides backward-compatible imports for the public API surface.
"""

from functualize._engine.capabilities.workflow_scope import WorkflowScope

__all__ = ["WorkflowScope"]
