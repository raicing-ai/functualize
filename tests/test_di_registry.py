"""Unit tests for DIRegistry, Provide marker, and DI error types.

Tests cover:
- provide/resolve round-trip
- provide_factory with singleton and invocation scope
- provide_named / resolve_named
- Qualifier-based resolution
- Namespace resolution priority
- Freeze mechanism
- Error types: MissingProviderError, AmbiguousProviderError, RegistryFrozenError
- Provide marker class

# Feature: unified-architecture-redesign, Tasks 3.1 & 3.2
"""

from __future__ import annotations

import pytest

from functualize._primitives.di import (
    AmbiguousProviderError,
    DIRegistry,
    MissingProviderError,
    Provide,
    RegistryFrozenError,
    ResolutionError,
)

# =============================================================================
# Helpers
# =============================================================================


class ServiceA:
    pass


class ServiceB:
    pass


class Cache:
    pass


# =============================================================================
# Tests: provide / resolve
# =============================================================================


class TestProvideResolve:
    def test_provide_and_resolve_singleton(self) -> None:
        reg = DIRegistry()
        svc = ServiceA()
        reg.provide(ServiceA, svc)
        assert reg.resolve(ServiceA) is svc

    def test_provide_replaces_silently(self) -> None:
        reg = DIRegistry()
        svc1 = ServiceA()
        svc2 = ServiceA()
        reg.provide(ServiceA, svc1)
        reg.provide(ServiceA, svc2)
        assert reg.resolve(ServiceA) is svc2

    def test_provide_with_qualifier(self) -> None:
        reg = DIRegistry()
        redis = Cache()
        memcache = Cache()
        reg.provide(Cache, redis, qualifier="redis")
        reg.provide(Cache, memcache, qualifier="memcache")
        assert reg.resolve(Cache, qualifier="redis") is redis
        assert reg.resolve(Cache, qualifier="memcache") is memcache

    def test_provide_same_qualifier_replaces(self) -> None:
        reg = DIRegistry()
        old = Cache()
        new = Cache()
        reg.provide(Cache, old, qualifier="redis")
        reg.provide(Cache, new, qualifier="redis")
        assert reg.resolve(Cache, qualifier="redis") is new

    def test_resolve_unqualified_with_no_unqualified_entry_raises_ambiguous(
        self,
    ) -> None:
        reg = DIRegistry()
        reg.provide(Cache, Cache(), qualifier="redis")
        reg.provide(Cache, Cache(), qualifier="memcache")
        with pytest.raises(AmbiguousProviderError) as exc_info:
            reg.resolve(Cache)
        assert (
            "redis" in exc_info.value.qualifiers
            or "memcache" in exc_info.value.qualifiers
        )

    def test_resolve_missing_type_raises(self) -> None:
        reg = DIRegistry()
        reg.provide(ServiceA, ServiceA())
        with pytest.raises(MissingProviderError) as exc_info:
            reg.resolve(ServiceB)
        assert exc_info.value.type_ is ServiceB
        assert ServiceA in exc_info.value.available


# =============================================================================
# Tests: provide_factory
# =============================================================================


class TestProvideFactory:
    def test_singleton_factory_invoked_once(self) -> None:
        reg = DIRegistry()
        call_count = 0

        def make_service():
            nonlocal call_count
            call_count += 1
            return ServiceA()

        reg.provide_factory(ServiceA, make_service, "singleton")
        result1 = reg.resolve(ServiceA)
        result2 = reg.resolve(ServiceA)
        assert result1 is result2
        assert call_count == 1

    def test_invocation_factory_fresh_each_call(self) -> None:
        reg = DIRegistry()

        def make_service(caps: dict):
            return ServiceA()

        reg.provide_factory(ServiceA, make_service, "invocation")
        result1 = reg.resolve(ServiceA, caps={})
        result2 = reg.resolve(ServiceA, caps={})
        assert result1 is not result2

    def test_invocation_factory_receives_caps(self) -> None:
        reg = DIRegistry()
        received_caps = None

        def make_service(caps: dict):
            nonlocal received_caps
            received_caps = caps
            return ServiceA()

        reg.provide_factory(ServiceA, make_service, "invocation")
        my_caps = {ServiceB: ServiceB()}
        reg.resolve(ServiceA, caps=my_caps)
        assert received_caps is my_caps

    def test_invalid_scope_raises_value_error(self) -> None:
        reg = DIRegistry()
        with pytest.raises(ValueError, match="scope must be"):
            reg.provide_factory(ServiceA, lambda: None, "request")

    def test_factory_with_qualifier(self) -> None:
        reg = DIRegistry()
        reg.provide_factory(Cache, lambda: Cache(), "singleton", qualifier="redis")
        reg.provide_factory(Cache, lambda: Cache(), "singleton", qualifier="memcache")
        redis = reg.resolve(Cache, qualifier="redis")
        memcache = reg.resolve(Cache, qualifier="memcache")
        assert redis is not memcache
        # Singleton: same on subsequent calls
        assert reg.resolve(Cache, qualifier="redis") is redis


# =============================================================================
# Tests: provide_named / resolve_named
# =============================================================================


class TestProvideNamed:
    def test_provide_and_resolve_named(self) -> None:
        reg = DIRegistry()
        reg.provide_named("app_name", "functualize")
        assert reg.resolve_named("app_name") == "functualize"

    def test_provide_named_replaces(self) -> None:
        reg = DIRegistry()
        reg.provide_named("key", "old")
        reg.provide_named("key", "new")
        assert reg.resolve_named("key") == "new"

    def test_resolve_named_missing_raises(self) -> None:
        reg = DIRegistry()
        with pytest.raises(MissingProviderError):
            reg.resolve_named("nonexistent")

    def test_has_named(self) -> None:
        reg = DIRegistry()
        assert not reg.has_named("key")
        reg.provide_named("key", "value")
        assert reg.has_named("key")


# =============================================================================
# Tests: namespace resolution
# =============================================================================


class TestNamespaceResolution:
    def test_namespace_as_qualifier_priority(self) -> None:
        """Namespace-scoped registration takes priority over app-level unqualified."""
        reg = DIRegistry()
        app_level = ServiceA()
        ns_level = ServiceA()
        reg.provide(ServiceA, app_level)
        reg.provide(ServiceA, ns_level, qualifier="analytics")
        # With namespace, should resolve to namespace-scoped
        assert reg.resolve(ServiceA, namespace="analytics") is ns_level
        # Without namespace, should resolve to app-level
        assert reg.resolve(ServiceA) is app_level

    def test_explicit_qualifier_beats_namespace(self) -> None:
        """Explicit qualifier takes priority over namespace-scoped."""
        reg = DIRegistry()
        app_level = ServiceA()
        ns_level = ServiceA()
        explicit = ServiceA()
        reg.provide(ServiceA, app_level)
        reg.provide(ServiceA, ns_level, qualifier="analytics")
        reg.provide(ServiceA, explicit, qualifier="special")
        # Explicit qualifier always wins regardless of namespace
        assert (
            reg.resolve(ServiceA, qualifier="special", namespace="analytics")
            is explicit
        )

    def test_namespace_falls_through_to_unqualified(self) -> None:
        """When namespace has no match, falls through to unqualified."""
        reg = DIRegistry()
        app_level = ServiceA()
        reg.provide(ServiceA, app_level)
        # Namespace "other" not registered, should fall through to unqualified
        assert reg.resolve(ServiceA, namespace="other") is app_level


# =============================================================================
# Tests: freeze mechanism
# =============================================================================


class TestFreeze:
    def test_freeze_disables_provide(self) -> None:
        reg = DIRegistry()
        reg.provide(ServiceA, ServiceA())
        reg.freeze()
        with pytest.raises(RegistryFrozenError) as exc_info:
            reg.provide(ServiceA, ServiceA())
        assert exc_info.value.method_name == "provide"

    def test_freeze_disables_provide_factory(self) -> None:
        reg = DIRegistry()
        reg.freeze()
        with pytest.raises(RegistryFrozenError) as exc_info:
            reg.provide_factory(ServiceA, lambda: None, "singleton")
        assert exc_info.value.method_name == "provide_factory"

    def test_freeze_disables_provide_named(self) -> None:
        reg = DIRegistry()
        reg.freeze()
        with pytest.raises(RegistryFrozenError) as exc_info:
            reg.provide_named("key", "value")
        assert exc_info.value.method_name == "provide_named"

    def test_resolve_works_after_freeze(self) -> None:
        reg = DIRegistry()
        svc = ServiceA()
        reg.provide(ServiceA, svc)
        reg.provide_named("key", "value")
        reg.freeze()
        assert reg.resolve(ServiceA) is svc
        assert reg.resolve_named("key") == "value"

    def test_is_frozen_flag(self) -> None:
        reg = DIRegistry()
        assert not reg.is_frozen
        reg.freeze()
        assert reg.is_frozen

    def test_freeze_is_permanent(self) -> None:
        """Once frozen, there's no unfreezing."""
        reg = DIRegistry()
        reg.freeze()
        # No unfreeze method exists; frozen state is permanent
        assert reg.is_frozen
        with pytest.raises(RegistryFrozenError):
            reg.provide(ServiceA, ServiceA())


# =============================================================================
# Tests: has / available_types / available_qualifiers
# =============================================================================


class TestIntrospection:
    def test_has_type(self) -> None:
        reg = DIRegistry()
        assert not reg.has(ServiceA)
        reg.provide(ServiceA, ServiceA())
        assert reg.has(ServiceA)

    def test_has_type_with_qualifier(self) -> None:
        reg = DIRegistry()
        reg.provide(Cache, Cache(), qualifier="redis")
        assert reg.has(Cache, qualifier="redis")
        assert not reg.has(Cache, qualifier="memcache")
        # has() without qualifier checks any qualifier
        assert reg.has(Cache)

    def test_available_types(self) -> None:
        reg = DIRegistry()
        reg.provide(ServiceA, ServiceA())
        reg.provide(ServiceB, ServiceB())
        types = reg.available_types()
        assert ServiceA in types
        assert ServiceB in types

    def test_available_qualifiers(self) -> None:
        reg = DIRegistry()
        reg.provide(Cache, Cache(), qualifier="redis")
        reg.provide(Cache, Cache(), qualifier="memcache")
        qualifiers = reg.available_qualifiers(Cache)
        assert "redis" in qualifiers
        assert "memcache" in qualifiers


# =============================================================================
# Tests: Error types
# =============================================================================


class TestErrorTypes:
    def test_resolution_error_is_exception(self) -> None:
        assert issubclass(ResolutionError, Exception)

    def test_missing_provider_error_inherits(self) -> None:
        assert issubclass(MissingProviderError, ResolutionError)

    def test_ambiguous_provider_error_inherits(self) -> None:
        assert issubclass(AmbiguousProviderError, ResolutionError)

    def test_registry_frozen_error_inherits(self) -> None:
        assert issubclass(RegistryFrozenError, ResolutionError)

    def test_missing_provider_error_attributes(self) -> None:
        err = MissingProviderError(ServiceA, "deploy", [ServiceB, Cache])
        assert err.type_ is ServiceA
        assert err.job_name == "deploy"
        assert ServiceB in err.available
        assert Cache in err.available
        assert "ServiceA" in str(err)
        assert "deploy" in str(err)

    def test_ambiguous_provider_error_attributes(self) -> None:
        err = AmbiguousProviderError(Cache, ["redis", "memcache"])
        assert err.type_ is Cache
        assert err.qualifiers == ["redis", "memcache"]
        assert "Cache" in str(err)
        assert "redis" in str(err)

    def test_registry_frozen_error_attributes(self) -> None:
        err = RegistryFrozenError("provide", "ServiceA")
        assert err.method_name == "provide"
        assert err.target == "ServiceA"
        assert "provide" in str(err)
        assert "ServiceA" in str(err)


# =============================================================================
# Tests: Provide marker
# =============================================================================


class TestProvideMarker:
    def test_qualifier_attribute(self) -> None:
        p = Provide("redis")
        assert p.qualifier == "redis"

    def test_repr(self) -> None:
        p = Provide("redis")
        assert repr(p) == "Provide('redis')"

    def test_equality(self) -> None:
        assert Provide("redis") == Provide("redis")
        assert Provide("redis") != Provide("memcache")

    def test_hash(self) -> None:
        assert hash(Provide("redis")) == hash(Provide("redis"))
        # Can be used as dict key
        d = {Provide("redis"): "value"}
        assert d[Provide("redis")] == "value"

    def test_inequality_with_other_types(self) -> None:
        assert Provide("redis") != "redis"
        assert Provide("redis") != 42
