"""Shared field-list lookup for job descriptors.

Job descriptors expose their fields via either ``config_fields`` (layered
resolution, preferred) or ``parameters`` (plain pass-through fallback).
This is the single place that encodes that precedence.
"""

from __future__ import annotations

from typing import Any


def get_descriptor_fields(descriptor: Any) -> list[Any] | None:
    """Return a descriptor's field list, preferring config_fields over parameters.

    Returns None if the descriptor has neither a non-empty config_fields nor
    parameters list — callers should treat this the same as an empty list.
    """
    return getattr(descriptor, "config_fields", None) or getattr(
        descriptor, "parameters", None
    )
