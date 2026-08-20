"""Property-based tests for Auto-Scope creation in FunctualizeApp.execute().

Tests Properties 23–24 from the Phase 1 design document.

**Validates: Requirements 9.2, 9.3, 9.6**
"""

from __future__ import annotations

import re
from collections.abc import Generator
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._app.state import AppState
from functualize.app.core import FunctualizeApp
from functualize.job._workflow_scope import WorkflowScope

# --- Fixtures ---


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


@pytest.fixture
def app() -> FunctualizeApp:
    """Create a minimal FunctualizeApp for testing."""
    return FunctualizeApp(name="testapp")


# --- Hypothesis Strategies ---

# Valid job names: non-empty strings with typical identifier-like characters
# (letters, digits, hyphens, underscores)
job_names = st.from_regex(r"[a-z][a-z0-9_\-]{0,29}", fullmatch=True)

# Scope IDs for explicit reuse testing
scope_ids = st.from_regex(r"[a-z][a-z0-9_\-]{0,29}", fullmatch=True)


# --- Property 23: Auto-scope ID format ---
# For any job name string, when app.execute(job_name) auto-creates a scope,
# the scope_id SHALL match the regex pattern ^{re.escape(job_name)}-[0-9a-f]{8}$.
# **Validates: Requirements 9.2**


@pytest.mark.slow
class TestAutoScopeIdFormat:
    """Property 23: Auto-scope ID format."""

    @given(job_name=job_names)
    @settings(deadline=None)
    def test_auto_scope_id_matches_format(self, job_name: str) -> None:
        """Auto-generated scope_id matches ^{job_name}-[0-9a-f]{8}$.

        **Validates: Requirements 9.2**
        """
        app = FunctualizeApp(name="testapp")

        # Register a simple job that does nothing
        def dummy_job(**kwargs: Any) -> str:
            return "ok"

        app.register_dynamic_job(job_name, dummy_job)

        # Execute the job (auto-creates scope)
        app.execute(job_name)

        # The scope registry should have exactly one scope with matching format
        assert len(app._scope_registry) == 1
        scope_id = next(iter(app._scope_registry.keys()))

        # Verify the scope_id matches the expected pattern
        pattern = rf"^{re.escape(job_name)}-[0-9a-f]{{8}}$"
        assert re.match(pattern, scope_id), (
            f"scope_id '{scope_id}' does not match pattern '{pattern}'"
        )

    @given(job_name=job_names)
    @settings(deadline=None)
    def test_auto_scope_suffix_is_exactly_8_hex_chars(self, job_name: str) -> None:
        """The auto-generated suffix after the job name is exactly 8 hex characters.

        **Validates: Requirements 9.2**
        """
        app = FunctualizeApp(name="testapp")

        def dummy_job(**kwargs: Any) -> str:
            return "ok"

        app.register_dynamic_job(job_name, dummy_job)
        app.execute(job_name)

        scope_id = next(iter(app._scope_registry.keys()))

        # The suffix should be after "{job_name}-"
        prefix = f"{job_name}-"
        assert scope_id.startswith(prefix), (
            f"scope_id '{scope_id}' does not start with '{prefix}'"
        )

        suffix = scope_id[len(prefix) :]
        assert len(suffix) == 8, f"suffix '{suffix}' is not 8 characters"
        assert all(c in "0123456789abcdef" for c in suffix), (
            f"suffix '{suffix}' contains non-hex characters"
        )

    @given(job_name=job_names)
    @settings(deadline=None)
    def test_auto_scope_creates_workflow_scope_instance(self, job_name: str) -> None:
        """Auto-scope creates a WorkflowScope instance stored in registry.

        **Validates: Requirements 9.2**
        """
        app = FunctualizeApp(name="testapp")

        def dummy_job(**kwargs: Any) -> str:
            return "ok"

        app.register_dynamic_job(job_name, dummy_job)
        app.execute(job_name)

        # There should be one scope in the registry
        assert len(app._scope_registry) == 1
        scope = next(iter(app._scope_registry.values()))
        assert isinstance(scope, WorkflowScope)


# --- Property 24: Explicit scope_id reuse ---
# For any scope_id that already exists in the scope registry, calling
# app.execute(job_name, scope_id=existing_id) SHALL reuse the existing
# WorkflowScope rather than creating a new one.
# **Validates: Requirements 9.3, 9.6**


@pytest.mark.slow
class TestExplicitScopeIdReuse:
    """Property 24: Explicit scope_id reuse."""

    @given(job_name=job_names, scope_id=scope_ids)
    @settings(deadline=None)
    def test_explicit_scope_id_reuses_existing_scope(
        self, job_name: str, scope_id: str
    ) -> None:
        """Existing scope_id reuses WorkflowScope rather than creating new one.

        **Validates: Requirements 9.3, 9.6**
        """
        app = FunctualizeApp(name="testapp")

        def dummy_job(**kwargs: Any) -> str:
            return "ok"

        app.register_dynamic_job(job_name, dummy_job)

        # Pre-create a scope with the explicit ID
        original_scope = app.create_workflow_scope(scope_id)

        # Execute with that explicit scope_id
        app.execute(job_name, scope_id=scope_id)

        # The scope in the registry should be the same instance
        assert app._scope_registry[scope_id] is original_scope

    @given(job_name=job_names, scope_id=scope_ids)
    @settings(deadline=None)
    def test_explicit_scope_id_does_not_create_new_scope(
        self, job_name: str, scope_id: str
    ) -> None:
        """Using an existing scope_id does not add additional scopes.

        **Validates: Requirements 9.3, 9.6**
        """
        app = FunctualizeApp(name="testapp")

        def dummy_job(**kwargs: Any) -> str:
            return "ok"

        app.register_dynamic_job(job_name, dummy_job)

        # Pre-create a scope
        app.create_workflow_scope(scope_id)
        assert len(app._scope_registry) == 1

        # Execute with same scope_id — should not create another scope
        app.execute(job_name, scope_id=scope_id)
        assert len(app._scope_registry) == 1

    @given(job_name=job_names, scope_id=scope_ids)
    @settings(deadline=None)
    def test_explicit_new_scope_id_creates_scope(
        self, job_name: str, scope_id: str
    ) -> None:
        """An explicit scope_id not in registry creates a new WorkflowScope.

        **Validates: Requirements 9.3**
        """
        app = FunctualizeApp(name="testapp")

        def dummy_job(**kwargs: Any) -> str:
            return "ok"

        app.register_dynamic_job(job_name, dummy_job)

        # Execute with an explicit scope_id that doesn't exist yet
        app.execute(job_name, scope_id=scope_id)

        # A scope should have been created with that exact ID
        assert scope_id in app._scope_registry
        assert app._scope_registry[scope_id].scope_id == scope_id
