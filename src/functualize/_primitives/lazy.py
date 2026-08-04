"""Lazy-cached descriptor for deferred attribute computation.

Only imports from _types/ and stdlib — zero third-party runtime dependencies.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar, overload

T = TypeVar("T")


class lazy_cached:  # noqa: N801 — lowercase to match descriptor/decorator convention
    """Descriptor that computes and caches a value on first access.

    Replaces the common ``if self._X is None`` memoization pattern with a
    clean descriptor interface. The wrapped method is invoked exactly once
    per instance; subsequent accesses return the cached result.

    Usage::

        class MyClass:
            @lazy_cached
            def expensive(self) -> list[int]:
                return compute_something()

        obj = MyClass()
        obj.expensive  # computes
        obj.expensive  # returns cached value
    """

    def __init__(self, func: Callable[..., Any]) -> None:
        self._func = func
        self._attr_name = f"_lazy_{func.__name__}"
        self.__doc__ = func.__doc__

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr_name = f"_lazy_{name}"

    @overload
    def __get__(self, obj: None, objtype: type) -> lazy_cached: ...

    @overload
    def __get__(self, obj: Any, objtype: type) -> Any: ...

    def __get__(self, obj: Any, objtype: type = None) -> Any:  # type: ignore[assignment]
        if obj is None:
            return self
        try:
            return getattr(obj, self._attr_name)
        except AttributeError:
            value = self._func(obj)
            object.__setattr__(obj, self._attr_name, value)
            return value
