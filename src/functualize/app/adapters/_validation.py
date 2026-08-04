"""Adapter validation utilities."""

from __future__ import annotations

from typing import Any

from functualize._types.protocols import AdapterPlugin

# Required protocol members for validation
_ADAPTER_REQUIRED_FIELDS = ("name", "version", "description", "adapter_type")
_ADAPTER_REQUIRED_METHODS = ("__call__", "run", "shutdown")


def _get_missing_adapter_members(obj: Any) -> list[str]:
    """Determine which AdapterPlugin protocol members are missing from an object."""
    missing: list[str] = []
    for field_name in _ADAPTER_REQUIRED_FIELDS:
        if not hasattr(obj, field_name):
            missing.append(field_name)
    for method_name in _ADAPTER_REQUIRED_METHODS:
        if not hasattr(obj, method_name):
            missing.append(method_name)
        elif not callable(getattr(obj, method_name)):
            missing.append(f"{method_name} (not callable)")
    return missing


def validate_adapter(obj: Any) -> None:
    """Validate that an object satisfies the AdapterPlugin protocol."""
    if not isinstance(obj, AdapterPlugin):
        missing = _get_missing_adapter_members(obj)
        raise TypeError(
            f"Expected an AdapterPlugin instance, got {type(obj).__name__}. "
            f"Missing methods/attributes: {missing}"
        )
