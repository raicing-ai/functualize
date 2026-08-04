"""Dependency Injection Registry with type-based resolution, scoping, and freeze semantics.

This module provides:
- DIRegistry: type-to-instance registry with singleton/invocation scoping
- Provide: marker class for Annotated[T, Provide("qualifier")]
- Error types: ResolutionError, MissingProviderError, AmbiguousProviderError, RegistryFrozenError

Only imports from _types/ and stdlib — zero third-party runtime dependencies.
"""

from __future__ import annotations

import inspect
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Error Types
# ---------------------------------------------------------------------------


class ResolutionError(Exception):
    """Base for all DI resolution failures."""


class MissingProviderError(ResolutionError):
    """No provider registered for the requested type."""

    def __init__(self, type_: type, job_name: str, available: list[type]) -> None:
        self.type_ = type_
        self.job_name = job_name
        self.available = available
        available_names = [t.__name__ for t in available]
        super().__init__(
            f"No provider for {type_.__name__} "
            f"(job: {job_name!r}, available: {available_names})"
        )


class AmbiguousProviderError(ResolutionError):
    """Multiple providers for the same type without qualifier."""

    # Attached by boot-time validation once the owning job is known.
    job_name: str | None = None

    def __init__(self, type_: type, qualifiers: list[str]) -> None:
        self.type_ = type_
        self.qualifiers = qualifiers
        super().__init__(
            f"Ambiguous provider for {type_.__name__}: "
            f"multiple qualifiers available {qualifiers}. "
            f"Use Annotated[{type_.__name__}, Provide('qualifier')] to disambiguate."
        )


class RegistryFrozenError(ResolutionError):
    """Mutation attempted after registry freeze."""

    def __init__(self, method_name: str, target: str) -> None:
        self.method_name = method_name
        self.target = target
        super().__init__(
            f"Registry is frozen: cannot call {method_name}() for {target!r}"
        )


class DIValidationError(Exception):
    """Aggregate error raised when boot-time DI validation finds unresolvable bindings.

    Contains all MissingProviderError and AmbiguousProviderError instances
    collected across all discovered job functions.
    """

    def __init__(self, errors: list[ResolutionError]) -> None:
        self.errors = errors
        lines = [f"DI validation failed with {len(errors)} error(s):"]
        for i, err in enumerate(errors, 1):
            lines.append(f"  {i}. {err}")
        super().__init__("\n".join(lines))


# ---------------------------------------------------------------------------
# Provide Marker
# ---------------------------------------------------------------------------


class Provide:
    """DI qualifier marker for Annotated types.

    Usage::

        from typing import Annotated

        def my_job(cache: Annotated[Cache, Provide("redis")]) -> None:
            ...
    """

    def __init__(self, qualifier: str) -> None:
        self.qualifier = qualifier

    def __repr__(self) -> str:
        return f"Provide({self.qualifier!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Provide):
            return self.qualifier == other.qualifier
        return NotImplemented

    def __hash__(self) -> int:
        return hash(("Provide", self.qualifier))


# ---------------------------------------------------------------------------
# Internal Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RegistryEntry:
    """A single registration in the DIRegistry."""

    type_: type
    qualifier: str | None
    instance: Any | None  # For singletons with pre-built instances
    factory: Callable[..., Any] | None  # For factory-based resolution
    scope: str  # "singleton" | "invocation"


# ---------------------------------------------------------------------------
# DIRegistry
# ---------------------------------------------------------------------------


class DIRegistry:
    """Type-to-instance registry with singleton/invocation scoping and freeze semantics.

    Supports:
    - Singleton instances via provide()
    - Factory-based resolution with singleton or invocation scope via provide_factory()
    - String-keyed named values via provide_named()
    - Namespace-aware resolution via resolve()
    - Permanent freeze via freeze()
    """

    def __init__(self) -> None:
        # Key: (type, qualifier) -> _RegistryEntry
        self._entries: dict[tuple[type, str | None], _RegistryEntry] = {}
        # Named string-keyed values
        self._named: dict[str, Any] = {}
        # Singleton factory cache: (type, qualifier) -> constructed instance
        self._singleton_cache: dict[tuple[type, str | None], Any] = {}
        # Frozen state
        self._frozen: bool = False

    # ------------------------------------------------------------------
    # Mutation methods
    # ------------------------------------------------------------------

    def provide(self, type_: type, instance: Any, qualifier: str | None = None) -> None:
        """Register a singleton instance with type validation and duplicate detection.

        Args:
            type_: The type to register the instance under.
            instance: The instance to register; must pass isinstance(instance, type_).
            qualifier: Optional qualifier for multiple instances of the same type.

        Raises:
            TypeError: If instance does not pass isinstance check against type_.
            RegistryFrozenError: If registry is frozen.
        """
        self._check_frozen(
            "provide", type_.__name__ + (f"[{qualifier}]" if qualifier else "")
        )

        # Type validation
        if not isinstance(instance, type_):
            raise TypeError(
                f"Cannot register instance of {type(instance).__name__} "
                f"as {type_.__name__}: isinstance check failed."
            )

        # Duplicate detection (warn on unqualified duplicates, don't error)
        key = (type_, qualifier)
        if key in self._entries and qualifier is None:
            caller = inspect.stack()[1]
            warnings.warn(
                f"Duplicate registration for {type_.__name__} "
                f"(called from {caller.filename}:{caller.lineno}). "
                f"Replacing previous instance.",
                UserWarning,
                stacklevel=2,
            )

        self._entries[key] = _RegistryEntry(
            type_=type_,
            qualifier=qualifier,
            instance=instance,
            factory=None,
            scope="singleton",
        )
        # Clear any cached singleton factory result for this key
        self._singleton_cache.pop(key, None)

    def provide_factory(
        self,
        type_: type,
        factory: Callable[..., Any],
        scope: str,
        qualifier: str | None = None,
    ) -> None:
        """Register a factory.

        Args:
            type_: The type this factory produces.
            factory: The callable to invoke.
            scope: "singleton" (zero-arg, cached on first resolve) or
                   "invocation" (accepts caps: dict[type, Any], fresh each call).
            qualifier: Optional qualifier string.
        """
        if scope not in ("singleton", "invocation"):
            raise ValueError(
                f"scope must be 'singleton' or 'invocation', got {scope!r}"
            )
        self._check_frozen(
            "provide_factory", type_.__name__ + (f"[{qualifier}]" if qualifier else "")
        )
        key = (type_, qualifier)
        self._entries[key] = _RegistryEntry(
            type_=type_,
            qualifier=qualifier,
            instance=None,
            factory=factory,
            scope=scope,
        )
        # Clear any cached singleton factory result for this key
        self._singleton_cache.pop(key, None)

    def provide_named(self, name: str, instance: Any) -> None:
        """Register a string-keyed value."""
        self._check_frozen("provide_named", name)
        self._named[name] = instance

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        type_: type,
        qualifier: str | None = None,
        namespace: str | None = None,
        *,
        caps: dict[type, Any] | None = None,
    ) -> Any:
        """Resolve a type from the registry.

        Resolution priority when namespace is provided:
        1. Explicit qualifier match (type_, qualifier)
        2. Namespace-scoped registration (type_, namespace)
        3. App-level unqualified registration (type_, None) — only if unambiguous

        Args:
            type_: The type to resolve.
            qualifier: Explicit qualifier to match.
            namespace: Optional namespace for scoped resolution.
            caps: Per-invocation capabilities dict passed to invocation-scoped factories.

        Returns:
            The resolved instance.

        Raises:
            MissingProviderError: No provider for the type (or qualified lookup not found).
            AmbiguousProviderError: Multiple providers without qualifier.
        """
        # 1. Try explicit qualifier
        if qualifier is not None:
            entry = self._entries.get((type_, qualifier))
            if entry is not None:
                return self._construct(entry, caps)
            # Explicit qualifier not found — raise MissingProviderError
            available_types = list({t for (t, _) in self._entries})
            raise MissingProviderError(type_, qualifier, available_types)

        # 2. Try namespace-scoped (namespace acts as qualifier)
        if namespace is not None and qualifier is None:
            entry = self._entries.get((type_, namespace))
            if entry is not None:
                return self._construct(entry, caps)

        # 3. Try unqualified (app-level)
        if qualifier is None:
            entry = self._entries.get((type_, None))
            if entry is not None:
                return self._construct(entry, caps)

        # 4. Check if type exists with qualifiers but none was specified
        matching_qualifiers = [
            q for (t, q) in self._entries if t is type_ and q is not None
        ]
        if matching_qualifiers:
            raise AmbiguousProviderError(type_, matching_qualifiers)

        # 5. No match at all
        available_types = list({t for (t, _) in self._entries})
        raise MissingProviderError(type_, "<unknown>", available_types)

    def resolve_named(self, name: str) -> Any:
        """Resolve a string-keyed named value.

        Args:
            name: The string key.

        Returns:
            The registered value.

        Raises:
            MissingProviderError: No named provider for the key.
        """
        if name in self._named:
            return self._named[name]
        available_types = list({t for (t, _) in self._entries})
        raise MissingProviderError(type(name), name, available_types)

    def has(self, type_: type, qualifier: str | None = None) -> bool:
        """Check if a type (optionally qualified) is registered."""
        if qualifier is not None:
            return (type_, qualifier) in self._entries
        # Check unqualified or any qualifier
        return any(t is type_ for (t, _) in self._entries)

    def has_named(self, name: str) -> bool:
        """Check if a named value is registered."""
        return name in self._named

    def available_types(self) -> list[type]:
        """Return all registered types (deduplicated)."""
        return list({t for (t, _) in self._entries})

    def available_qualifiers(self, type_: type) -> list[str | None]:
        """Return all qualifiers registered for a given type."""
        return [q for (t, q) in self._entries if t is type_]

    # ------------------------------------------------------------------
    # Freeze mechanism
    # ------------------------------------------------------------------

    def freeze(self) -> None:
        """Permanently disable all mutation methods.

        Called after APP_READY hooks. After this, provide(), provide_factory(),
        and provide_named() will raise RegistryFrozenError.
        resolve() continues to work normally.
        """
        self._frozen = True

    @property
    def is_frozen(self) -> bool:
        """Whether the registry is frozen."""
        return self._frozen

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_frozen(self, method_name: str, target: str) -> None:
        """Raise RegistryFrozenError if the registry is frozen."""
        if self._frozen:
            raise RegistryFrozenError(method_name, target)

    def _construct(self, entry: _RegistryEntry, caps: dict[type, Any] | None) -> Any:
        """Construct or return an instance from a registry entry."""
        # Pre-built singleton instance
        if entry.instance is not None:
            return entry.instance

        # Factory-based
        assert entry.factory is not None
        key = (entry.type_, entry.qualifier)

        if entry.scope == "singleton":
            # Check cache first
            if key in self._singleton_cache:
                return self._singleton_cache[key]
            # Construct with zero arguments
            instance = entry.factory()
            self._singleton_cache[key] = instance
            return instance

        # scope == "invocation"
        # Construct with caps argument
        return entry.factory(caps=caps or {})
