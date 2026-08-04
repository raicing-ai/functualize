"""Unit tests for JobExecutionEngine.get_job() fallback resolution.

Tests cover:
1. Direct qualified lookup
2. Bare-name unique match (fallback)
3. Ambiguous bare name (multiple matches)
4. Not found (no match at all)
5. Qualified name not found (dotted name, no fallback)
6. Callable ref via WiredInvoke._resolve_job_name

**Validates: Requirements 9, 10, 11, 12**
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from functualize._engine.capabilities.invoke import WiredInvoke
from functualize._engine.executor import JobExecutionEngine
from functualize._engine.middleware import ExecutionMiddlewareChain
from functualize._events.bus import EventBus
from functualize._events.hooks import HookRegistry
from functualize._primitives import DIRegistry
from functualize._types.descriptors import RegisteredJob
from functualize._types.errors import AmbiguousJobError, JobNotFoundError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> JobExecutionEngine:
    """Create a minimal JobExecutionEngine for testing get_job."""
    return JobExecutionEngine(
        di_registry=MagicMock(spec=DIRegistry),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
    )


def _make_job(name: str, group: str | None = None) -> RegisteredJob:
    """Create a RegisteredJob with a unique function."""

    def _fn():
        pass

    _fn.__name__ = name.rsplit(".", 1)[-1]
    return RegisteredJob(
        name=name,
        function=_fn,
        config_class=None,
        group=group,
        module_path="test_module",
        job_directory=Path("/tmp/test"),
    )


def _populate_engine(engine: JobExecutionEngine) -> dict[str, RegisteredJob]:
    """Register a standard set of jobs and return them for assertions.

    Registry state:
      "infra.provision"    (group="infra")
      "infra.teardown"     (group="infra")
      "monitoring.provision" (group="monitoring")
      "deploy"             (group=None, ungrouped)
    """
    jobs = {
        "infra.provision": _make_job("infra.provision", group="infra"),
        "infra.teardown": _make_job("infra.teardown", group="infra"),
        "monitoring.provision": _make_job("monitoring.provision", group="monitoring"),
        "deploy": _make_job("deploy", group=None),
    }
    for job in jobs.values():
        engine.register_job(job)
    return jobs


# ---------------------------------------------------------------------------
# Test 1: Direct qualified lookup
# ---------------------------------------------------------------------------


class TestDirectQualifiedLookup:
    """get_job with a qualified name returns the exact match."""

    def test_qualified_name_returns_registered_job(self):
        """get_job('infra.provision') returns the registered job directly.

        **Validates: Requirement 9**
        """
        engine = _make_engine()
        jobs = _populate_engine(engine)

        result = engine.get_job("infra.provision")

        assert result is jobs["infra.provision"]
        assert result.name == "infra.provision"

    def test_ungrouped_direct_lookup(self):
        """get_job('deploy') returns the ungrouped job directly.

        **Validates: Requirement 9**
        """
        engine = _make_engine()
        jobs = _populate_engine(engine)

        result = engine.get_job("deploy")

        assert result is jobs["deploy"]
        assert result.name == "deploy"


# ---------------------------------------------------------------------------
# Test 2: Bare-name unique match (fallback)
# ---------------------------------------------------------------------------


class TestBareNameUniqueMatch:
    """get_job with a bare name that uniquely matches one job's func_name."""

    def test_unique_bare_name_returns_job(self):
        """get_job('teardown') resolves to 'infra.teardown' (only match).

        **Validates: Requirement 11**
        """
        engine = _make_engine()
        jobs = _populate_engine(engine)

        result = engine.get_job("teardown")

        assert result is jobs["infra.teardown"]
        assert result.name == "infra.teardown"

    def test_bare_name_matches_ungrouped_directly_first(self):
        """get_job('deploy') matches directly (no fallback needed).

        **Validates: Requirement 11**
        """
        engine = _make_engine()
        jobs = _populate_engine(engine)

        # 'deploy' is a direct match (ungrouped), so it's found in step 1
        result = engine.get_job("deploy")

        assert result is jobs["deploy"]


# ---------------------------------------------------------------------------
# Test 3: Ambiguous bare name
# ---------------------------------------------------------------------------


class TestAmbiguousBareName:
    """get_job with a bare name matching multiple jobs raises AmbiguousJobError."""

    def test_ambiguous_bare_name_raises(self):
        """get_job('provision') raises AmbiguousJobError when multiple match.

        'provision' is the func_name of both 'infra.provision' and
        'monitoring.provision'.

        **Validates: Requirement 12**
        """
        engine = _make_engine()
        _populate_engine(engine)

        with pytest.raises(AmbiguousJobError) as exc_info:
            engine.get_job("provision")

        err = exc_info.value
        assert err.name == "provision"
        assert set(err.candidates) == {"infra.provision", "monitoring.provision"}

    def test_ambiguous_error_message_suggests_qualified_form(self):
        """AmbiguousJobError message includes candidate qualified names.

        **Validates: Requirement 12**
        """
        engine = _make_engine()
        _populate_engine(engine)

        with pytest.raises(AmbiguousJobError) as exc_info:
            engine.get_job("provision")

        msg = str(exc_info.value)
        assert "provision" in msg
        assert "infra.provision" in msg or "monitoring.provision" in msg


# ---------------------------------------------------------------------------
# Test 4: Not found
# ---------------------------------------------------------------------------


class TestNotFound:
    """get_job with a name that doesn't match anything raises KeyError."""

    def test_bare_name_not_found_raises_key_error(self):
        """get_job('nonexistent') raises KeyError.

        **Validates: Requirement 11**
        """
        engine = _make_engine()
        _populate_engine(engine)

        with pytest.raises(KeyError):
            engine.get_job("nonexistent")


# ---------------------------------------------------------------------------
# Test 5: Qualified name not found (no fallback for dotted names)
# ---------------------------------------------------------------------------


class TestQualifiedNameNotFound:
    """get_job with a dotted name not in registry raises KeyError (no fallback)."""

    def test_dotted_name_not_found_raises_key_error(self):
        """get_job('infra.nonexistent') raises KeyError without fallback.

        **Validates: Requirement 9**
        """
        engine = _make_engine()
        _populate_engine(engine)

        with pytest.raises(KeyError):
            engine.get_job("infra.nonexistent")

    def test_completely_unknown_group_raises_key_error(self):
        """get_job('unknown.provision') raises KeyError.

        **Validates: Requirement 9**
        """
        engine = _make_engine()
        _populate_engine(engine)

        with pytest.raises(KeyError):
            engine.get_job("unknown.provision")


# ---------------------------------------------------------------------------
# Test 6: Callable ref via WiredInvoke._resolve_job_name
# ---------------------------------------------------------------------------


class TestCallableRefResolution:
    """WiredInvoke._resolve_job_name resolves callables to qualified names."""

    def test_string_passes_through(self):
        """A string name is returned as-is by _resolve_job_name.

        **Validates: Requirement 9**
        """
        engine = _make_engine()
        _populate_engine(engine)

        invoke = WiredInvoke(
            execution_engine=engine,
            run_context=MagicMock(),
            invoke_depth=0,
            max_invoke_depth=10,
        )

        result = invoke._resolve_job_name("infra.provision")
        assert result == "infra.provision"

    def test_callable_resolves_to_qualified_name(self):
        """A registered callable resolves to its qualified name.

        **Validates: Requirement 10**
        """
        engine = _make_engine()

        def provision():
            pass

        job = RegisteredJob(
            name="infra.provision",
            function=provision,
            config_class=None,
            group="infra",
            module_path="test_module",
            job_directory=Path("/tmp/test"),
        )
        engine.register_job(job)

        invoke = WiredInvoke(
            execution_engine=engine,
            run_context=MagicMock(),
            invoke_depth=0,
            max_invoke_depth=10,
        )

        result = invoke._resolve_job_name(provision)
        assert result == "infra.provision"

    def test_unregistered_callable_raises_job_not_found(self):
        """An unregistered callable raises JobNotFoundError.

        **Validates: Requirement 10**
        """
        engine = _make_engine()
        _populate_engine(engine)

        def unknown_func():
            pass

        invoke = WiredInvoke(
            execution_engine=engine,
            run_context=MagicMock(),
            invoke_depth=0,
            max_invoke_depth=10,
        )

        with pytest.raises(JobNotFoundError):
            invoke._resolve_job_name(unknown_func)
