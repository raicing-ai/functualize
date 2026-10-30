"""The callable a class job registers (plan.md §4.4).

A class job registers its bound ``run`` method, but that method's own
``__functualize_job__`` is the method's *unmerged* ``@job`` and its signature
still carries ``self`` — the run's config instance, supplied by the engine.
:class:`ClassJobMethod` is the receiver-less, declaration-correct callable that
registration, the click parameter build and the engine's bind all consume.

Proxy rules (schema §6): the signature is the method's with the first parameter
removed and its annotations resolved to live types; the introspection dunders
are copied from the underlying function; ``__functualize_job__`` is an **own**
attribute holding the effective merged declaration, never delegated through
``__getattr__`` (which would answer with the method's unmerged ``@job``);
``__functualize_lazy__`` is never reachable — a cache stand-in would make
``executor._execute_lifecycle`` treat the proxy as a lazy wrapper instead of a
job; everything else delegates to the function. Calling it raises: the receiver
is the run's config instance, and a call without one would build a second
instance.

``_types`` imports stdlib only, plus ``_types.annotations.resolved_hints`` —
the declaration's type is annotation-only, under ``TYPE_CHECKING``.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from functualize._types.annotations import resolved_hints

if TYPE_CHECKING:
    from functualize._types.job_declaration import JobDeclaration

#: Dunder names a caller must never see through delegation: the declaration is
#: the proxy's own, and lazy would be a cache stand-in (schema §6).
_NEVER_DELEGATED = ("__functualize_job__", "__functualize_lazy__")


class ClassJobMethod:
    """A class job's ``run`` method as a receiver-less registered callable.

    Args:
        job_class: The decorated class — registration's ``config_class``.
        method_name: The method's ``python_name``, used for the engine's bind.
        declaration: The descriptor's effective merged declaration, stored as
            the proxy's own ``__functualize_job__``.

    Attributes:
        job_class: The decorated class.
        method_name: The bound method's name.
    """

    def __init__(
        self,
        job_class: type,
        method_name: str,
        declaration: JobDeclaration,
    ) -> None:
        self.job_class = job_class
        self.method_name = method_name
        self.__functualize_job__ = declaration

        method = getattr(job_class, method_name)
        # Introspection copies are own attributes: type-level dunders like
        # __doc__ shadow __getattr__, so delegation cannot serve them.
        self.__name__ = method.__name__
        self.__qualname__ = method.__qualname__
        self.__doc__ = method.__doc__
        self.__module__ = method.__module__
        self.__annotations__ = method.__annotations__
        self.__wrapped__ = method

        hints = resolved_hints(method)
        signature = inspect.signature(method)
        # The first parameter is the receiver — removed by position, never by
        # name. Remaining annotations resolve to live types where they can.
        params = [
            param.replace(annotation=hints.get(name, param.annotation))
            for name, param in list(signature.parameters.items())[1:]
        ]
        self.__signature__ = signature.replace(
            parameters=params,
            return_annotation=hints.get("return", signature.return_annotation),
        )

    def __getattr__(self, name: str) -> Any:
        """Delegate to the underlying function, except the two forbidden dunders."""
        if name in _NEVER_DELEGATED:
            raise AttributeError(name)
        return getattr(self.__wrapped__, name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Refuse a call: the receiver is the run's config instance."""
        raise RuntimeError(
            f"{self.__qualname__} is a class job method; it runs against the "
            "run's config instance and cannot be called directly"
        )
