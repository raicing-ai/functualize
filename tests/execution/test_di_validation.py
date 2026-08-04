"""Unit tests for boot-time DI validation and error aggregation.

Tests the validate_di_bindings() method on JobExecutionEngine, covering:
- Missing provider detection across all registered jobs
- Ambiguous provider detection
- Aggregate error collection (doesn't fail-fast)
- Optional[T] parameters handled gracefully (resolve to None, no error)
- Factory construction errors wrapped in ResolutionError with __cause__
- Per-invocation capability types are not flagged as missing

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from unittest.mock import MagicMock

import pytest

from functualize._engine.executor import JobExecutionEngine
from functualize._engine.result import RegisteredJob
from functualize._primitives.di import (
    AmbiguousProviderError,
    DIRegistry,
    DIValidationError,
    MissingProviderError,
    Provide,
    ResolutionError,
)

if TYPE_CHECKING:
    from functualize.job.capabilities import Log

# ---------------------------------------------------------------------------
# Test service types
# ---------------------------------------------------------------------------


class DatabaseService:
    """A user-defined service for DI tests."""

    pass


class CacheService:
    """Another user-defined service."""

    pass


class EmailService:
    """A third user-defined service."""

    pass


# ---------------------------------------------------------------------------
# Helper to create a minimal engine with a mock app
# ---------------------------------------------------------------------------


def _make_engine(di_registry: DIRegistry | None = None) -> JobExecutionEngine:
    """Create a minimal JobExecutionEngine with a mock app."""
    registry = di_registry or DIRegistry()

    hook_registry = MagicMock()
    middleware_chain = MagicMock()
    middleware_chain.has_middleware = False
    event_bus = MagicMock()

    engine = JobExecutionEngine(
        di_registry=registry,
        hook_registry=hook_registry,
        middleware_chain=middleware_chain,
        event_bus=event_bus,
    )
    return engine


def _register_job(
    engine: JobExecutionEngine,
    name: str,
    function: object,
    group: str | None = None,
) -> None:
    """Register a job function in the engine."""
    entry = RegisteredJob(
        name=name,
        function=function,
        config_class=None,
        group=group,
        module_path="test_module",
        job_directory=Path("."),
    )
    engine.register_job(entry)


# ---------------------------------------------------------------------------
# Tests: Requirement 18.3 — boot-time validation raises errors early
# ---------------------------------------------------------------------------


class TestValidateDIBindings:
    """Tests for validate_di_bindings() method."""

    def test_no_jobs_passes_validation(self) -> None:
        """Empty engine with no registered jobs should pass validation."""
        engine = _make_engine()
        # Should not raise
        engine.validate_di_bindings()

    def test_all_bindings_satisfied_passes(self) -> None:
        """If all DI bindings are satisfied, validation passes."""
        registry = DIRegistry()
        registry.provide(DatabaseService, DatabaseService())

        engine = _make_engine(registry)

        def my_job(db: DatabaseService) -> None:
            pass

        _register_job(engine, "my_job", my_job)
        # Should not raise
        engine.validate_di_bindings()

    def test_missing_provider_raises_error(self) -> None:
        """A job with a missing DI type raises DIValidationError."""
        engine = _make_engine()

        def my_job(db: DatabaseService) -> None:
            pass

        _register_job(engine, "my_job", my_job)

        with pytest.raises(DIValidationError) as exc_info:
            engine.validate_di_bindings()

        err = exc_info.value
        assert len(err.errors) == 1
        assert isinstance(err.errors[0], MissingProviderError)
        assert err.errors[0].type_ is DatabaseService
        assert err.errors[0].job_name == "my_job"

    def test_ambiguous_provider_raises_error(self) -> None:
        """A job with ambiguous providers raises DIValidationError."""
        registry = DIRegistry()
        registry.provide(CacheService, CacheService(), qualifier="redis")
        registry.provide(CacheService, CacheService(), qualifier="memcached")

        engine = _make_engine(registry)

        def my_job(cache: CacheService) -> None:
            pass

        _register_job(engine, "my_job", my_job)

        with pytest.raises(DIValidationError) as exc_info:
            engine.validate_di_bindings()

        err = exc_info.value
        assert len(err.errors) == 1
        assert isinstance(err.errors[0], AmbiguousProviderError)
        assert err.errors[0].type_ is CacheService

    # -----------------------------------------------------------------------
    # Requirement 18.5 — aggregate all errors, don't fail-fast
    # -----------------------------------------------------------------------

    def test_collects_all_errors_across_jobs(self) -> None:
        """Validation collects ALL errors across multiple jobs."""
        engine = _make_engine()

        def job_a(db: DatabaseService) -> None:
            pass

        def job_b(cache: CacheService) -> None:
            pass

        def job_c(email: EmailService) -> None:
            pass

        _register_job(engine, "job_a", job_a)
        _register_job(engine, "job_b", job_b)
        _register_job(engine, "job_c", job_c)

        with pytest.raises(DIValidationError) as exc_info:
            engine.validate_di_bindings()

        err = exc_info.value
        assert len(err.errors) == 3
        # All should be MissingProviderError
        for e in err.errors:
            assert isinstance(e, MissingProviderError)

    def test_collects_errors_from_multiple_params_in_one_job(self) -> None:
        """Errors from multiple params within the same job are collected."""
        engine = _make_engine()

        def my_job(db: DatabaseService, cache: CacheService) -> None:
            pass

        _register_job(engine, "my_job", my_job)

        with pytest.raises(DIValidationError) as exc_info:
            engine.validate_di_bindings()

        err = exc_info.value
        assert len(err.errors) == 2

    # -----------------------------------------------------------------------
    # Requirement 18.6 — Optional[T] parameters gracefully resolve to None
    # -----------------------------------------------------------------------

    def test_optional_param_does_not_raise(self) -> None:
        """Optional[T] params with no provider do NOT trigger errors."""
        engine = _make_engine()

        def my_job(db: DatabaseService | None) -> None:
            pass

        _register_job(engine, "my_job", my_job)
        # Should not raise
        engine.validate_di_bindings()

    def test_optional_and_required_mixed(self) -> None:
        """Only required params with missing providers trigger errors."""
        engine = _make_engine()

        def my_job(
            db: DatabaseService | None,
            cache: CacheService,
        ) -> None:
            pass

        _register_job(engine, "my_job", my_job)

        with pytest.raises(DIValidationError) as exc_info:
            engine.validate_di_bindings()

        err = exc_info.value
        assert len(err.errors) == 1
        assert isinstance(err.errors[0], MissingProviderError)
        assert err.errors[0].type_ is CacheService

    # -----------------------------------------------------------------------
    # Requirement 18.4 — factory construction errors wrapped in ResolutionError
    # -----------------------------------------------------------------------

    def test_factory_construction_error_wrapped(self) -> None:
        """Factory errors during validation are wrapped in ResolutionError with __cause__."""
        registry = DIRegistry()

        def bad_factory():
            raise RuntimeError("Connection failed")

        registry.provide_factory(DatabaseService, bad_factory, scope="singleton")

        engine = _make_engine(registry)

        def my_job(db: DatabaseService) -> None:
            pass

        _register_job(engine, "my_job", my_job)

        with pytest.raises(DIValidationError) as exc_info:
            engine.validate_di_bindings()

        err = exc_info.value
        assert len(err.errors) == 1
        assert isinstance(err.errors[0], ResolutionError)
        assert err.errors[0].__cause__ is not None
        assert isinstance(err.errors[0].__cause__, RuntimeError)
        assert "Connection failed" in str(err.errors[0].__cause__)

    # -----------------------------------------------------------------------
    # Per-invocation capability types should not require registration
    # -----------------------------------------------------------------------

    def test_per_invocation_capability_types_not_flagged(self) -> None:
        """Per-invocation capability types (Log, etc.) don't require explicit registration."""
        engine = _make_engine()

        def my_job(logger: Log) -> None:
            pass

        _register_job(engine, "my_job", my_job)
        # Should not raise - Log is a per-invocation type
        engine.validate_di_bindings()

    # -----------------------------------------------------------------------
    # Qualified bindings
    # -----------------------------------------------------------------------

    def test_qualified_binding_satisfied(self) -> None:
        """A qualified binding that is registered passes validation."""
        registry = DIRegistry()
        registry.provide(CacheService, CacheService(), qualifier="redis")

        engine = _make_engine(registry)

        def my_job(cache: Annotated[CacheService, Provide("redis")]) -> None:
            pass

        _register_job(engine, "my_job", my_job)
        # Should not raise
        engine.validate_di_bindings()

    def test_qualified_binding_missing(self) -> None:
        """A qualified binding that isn't registered raises an error."""
        registry = DIRegistry()
        registry.provide(CacheService, CacheService(), qualifier="redis")

        engine = _make_engine(registry)

        def my_job(cache: Annotated[CacheService, Provide("memcached")]) -> None:
            pass

        _register_job(engine, "my_job", my_job)

        with pytest.raises(DIValidationError) as exc_info:
            engine.validate_di_bindings()

        err = exc_info.value
        assert len(err.errors) == 1

    # -----------------------------------------------------------------------
    # Skip params (no annotation, unregistered without DI)
    # -----------------------------------------------------------------------

    def test_skip_params_not_validated(self) -> None:
        """Params with source='skip' are not validated."""
        engine = _make_engine()

        def my_job(name, count=5) -> None:
            pass

        _register_job(engine, "my_job", my_job)
        # Should not raise - unannotated params are skipped
        engine.validate_di_bindings()

    # -----------------------------------------------------------------------
    # DIValidationError message quality
    # -----------------------------------------------------------------------

    def test_aggregate_error_message_contains_all_diagnostics(self) -> None:
        """The aggregate error message lists all individual errors."""
        engine = _make_engine()

        def job_a(db: DatabaseService) -> None:
            pass

        def job_b(cache: CacheService) -> None:
            pass

        _register_job(engine, "job_a", job_a)
        _register_job(engine, "job_b", job_b)

        with pytest.raises(DIValidationError) as exc_info:
            engine.validate_di_bindings()

        msg = str(exc_info.value)
        assert "2 error(s)" in msg
        assert "DatabaseService" in msg
        assert "CacheService" in msg


class TestDIValidationErrorClass:
    """Tests for the DIValidationError class itself."""

    def test_errors_attribute(self) -> None:
        """DIValidationError stores the list of errors."""
        errors = [
            MissingProviderError(DatabaseService, "test_job", []),
            MissingProviderError(CacheService, "test_job", []),
        ]
        err = DIValidationError(errors)
        assert err.errors == errors

    def test_message_format(self) -> None:
        """DIValidationError formats a readable message."""
        errors = [
            MissingProviderError(DatabaseService, "my_job", [CacheService]),
        ]
        err = DIValidationError(errors)
        msg = str(err)
        assert "1 error(s)" in msg
        assert "DatabaseService" in msg
