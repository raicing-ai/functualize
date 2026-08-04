"""Signature introspection utilities for adaptive hook dispatch.

Provides reusable helpers to inspect callable signatures and determine
which keyword arguments they accept. This enables signature-adaptive
dispatch: pass new kwargs only to hooks whose signatures declare them.

Only imports from stdlib.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def accepts_keyword(func: Callable[..., Any], keyword: str) -> bool:
    """Check if a callable accepts a specific keyword argument.

    Returns True if the function signature includes:
    - An explicit parameter named `keyword` (POSITIONAL_OR_KEYWORD or KEYWORD_ONLY)
    - A **kwargs catch-all (VAR_KEYWORD)

    Returns False if the function signature does not accept the keyword.
    """
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        return False

    for param in sig.parameters.values():
        if param.name == keyword and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            return True
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True

    return False


def filter_kwargs_for_callable(
    func: Callable[..., Any], kwargs: dict[str, Any]
) -> dict[str, Any]:
    """Filter a kwargs dict to only include keys the callable accepts.

    Returns a new dict containing only keys the callable accepts.
    """
    return {k: v for k, v in kwargs.items() if accepts_keyword(func, k)}
