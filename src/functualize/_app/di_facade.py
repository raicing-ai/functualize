"""Dependency injection registration — `app.di`.

Extracted from :class:`~functualize.app.core.FunctualizeApp`
(engine-sealed-construction/T9). Three registration doors onto one registry: an
instance, a factory, and a name. The registry itself is `app.di_registry`; these
are the sanctioned ways to put something in it before boot freezes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from functualize.app.core import FunctualizeApp

__all__ = ["DependencyFacade"]


class DependencyFacade:
    """`app.di` — register what jobs can ask for by type or name."""

    __slots__ = ("_app",)

    def __init__(self, app: FunctualizeApp) -> None:
        self._app = app

    def provide(self, type_: type, instance: Any, qualifier: str | None = None) -> None:
        """Register a singleton instance in the DI registry."""
        self._app._di_registry.provide(type_, instance, qualifier)

    def provide_factory(
        self,
        type_: type,
        factory: Callable[..., Any],
        scope: str,
        qualifier: str | None = None,
    ) -> None:
        """Register a factory in the DI registry."""
        self._app._di_registry.provide_factory(type_, factory, scope, qualifier)

    def provide_named(self, name: str, instance: Any) -> None:
        """Register a string-keyed value in the DI registry."""
        self._app._di_registry.provide_named(name, instance)
