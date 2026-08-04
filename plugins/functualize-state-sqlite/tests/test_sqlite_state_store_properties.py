"""Property-based tests for SQLiteStateStore.

Tests Properties 26, 27, and 28 from the Plugin Ecosystem Enablement design.

- Property 26: SQLiteStateStore round-trip — set then get returns equivalent value
- Property 27: Cross-job state isolation — get_job_state reads correct namespace
- Property 28: Non-serializable values stored as placeholder with type name
"""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path
from typing import Any

from functualize_state_sqlite.sqlite_backend import SQLiteBackend
from functualize_state_sqlite.state_store import SQLiteStateStore
from hypothesis import given, settings
from hypothesis import strategies as st

# --- Strategies ---

# Strategy for valid state keys (non-empty strings)
state_keys = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        whitelist_characters="-_. ",
    ),
    min_size=1,
    max_size=64,
)

# Strategy for job namespace names
job_names = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="-_",
    ),
    min_size=1,
    max_size=32,
)

# Strategy for JSON-serializable values (JSON round-trip equality)
json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**53), max_value=2**53),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=100),
)

# Recursive strategy for nested JSON-serializable structures
json_values = st.recursive(
    json_primitives,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(st.text(max_size=20), children, max_size=5),
    ),
    max_leaves=10,
)


def _make_backend() -> SQLiteBackend:
    """Create an initialized SQLiteBackend in a temp directory."""
    tmp = tempfile.mkdtemp()
    db = SQLiteBackend(base_dir=Path(tmp))
    db.initialize()
    return db


# --- Property 26: SQLiteStateStore round-trip ---


class TestSQLiteStateStoreRoundTrip:
    """Property 26: For any JSON-serializable key-value pair, after
    rc.state.set(key, value) is called, rc.state.get(key) SHALL return
    a value equivalent to the original (JSON round-trip equality).

    **Validates: Requirements 23.6**
    """

    @settings(max_examples=100)
    @given(key=state_keys, value=json_values)
    def test_set_then_get_returns_equivalent_value(self, key: str, value: Any):
        """**Validates: Requirements 23.6**

        For any JSON-serializable value, set then get returns an equivalent
        value (JSON round-trip equality).
        """
        backend = _make_backend()
        try:
            store = SQLiteStateStore(
                backend, scope_id="test-scope", job_namespace="job-a"
            )

            store.set(key, value)
            retrieved = store.get(key)

            # JSON round-trip: integers stay integers, strings stay strings,
            # lists stay lists, dicts stay dicts, None stays None.
            assert retrieved == value, (
                f"Round-trip failed for key={key!r}, value={value!r}, got={retrieved!r}"
            )
        finally:
            backend.close()

    @settings(max_examples=50)
    @given(key=state_keys, value=json_values)
    def test_overwrite_returns_latest_value(self, key: str, value: Any):
        """**Validates: Requirements 23.6**

        Overwriting an existing key returns the latest value on get.
        """
        backend = _make_backend()
        try:
            store = SQLiteStateStore(
                backend, scope_id="test-scope", job_namespace="job-a"
            )

            # Write an initial value
            store.set(key, "initial-sentinel")
            # Overwrite with the generated value
            store.set(key, value)
            retrieved = store.get(key)

            assert retrieved == value
        finally:
            backend.close()


# --- Property 27: Cross-job state isolation ---


class TestCrossJobStateIsolation:
    """Property 27: For two jobs A and B each writing state under their own
    namespace, rc.state.get_job_state("A", key) from job B's context SHALL
    return the value written by job A, not job B's value for the same key.

    **Validates: Requirements 23.7**
    """

    @settings(max_examples=100)
    @given(
        key=state_keys,
        value_a=json_values,
        value_b=json_values,
        job_a_name=job_names,
        job_b_name=job_names,
    )
    def test_get_job_state_reads_correct_namespace(
        self,
        key: str,
        value_a: Any,
        value_b: Any,
        job_a_name: str,
        job_b_name: str,
    ):
        """**Validates: Requirements 23.7**

        For two jobs A and B writing to their own namespace,
        get_job_state("A", key) from B's context returns A's value.
        """
        # Ensure distinct job names to test isolation
        if job_a_name == job_b_name:
            job_b_name = job_b_name + "_other"

        backend = _make_backend()
        try:
            scope_id = "shared-scope"

            # Create stores for both jobs in the same scope
            store_a = SQLiteStateStore(
                backend, scope_id=scope_id, job_namespace=job_a_name
            )
            store_b = SQLiteStateStore(
                backend, scope_id=scope_id, job_namespace=job_b_name
            )

            # Job A writes its value
            store_a.set(key, value_a)
            # Job B writes a different value for the same key
            store_b.set(key, value_b)

            # From B's context, reading A's namespace returns A's value
            result_from_b = store_b.get_job_state(job_a_name, key)
            assert result_from_b == value_a, (
                f"Expected value from job A ({value_a!r}), got {result_from_b!r}"
            )

            # From A's context, reading B's namespace returns B's value
            result_from_a = store_a.get_job_state(job_b_name, key)
            assert result_from_a == value_b, (
                f"Expected value from job B ({value_b!r}), got {result_from_a!r}"
            )
        finally:
            backend.close()

    @settings(max_examples=50)
    @given(
        key=state_keys,
        value_a=json_values,
        value_b=json_values,
        job_a_name=job_names,
        job_b_name=job_names,
    )
    def test_own_namespace_not_affected_by_other_job(
        self,
        key: str,
        value_a: Any,
        value_b: Any,
        job_a_name: str,
        job_b_name: str,
    ):
        """**Validates: Requirements 23.7**

        Writing in one job's namespace does not affect the other's get().
        """
        if job_a_name == job_b_name:
            job_b_name = job_b_name + "_other"

        backend = _make_backend()
        try:
            scope_id = "shared-scope"

            store_a = SQLiteStateStore(
                backend, scope_id=scope_id, job_namespace=job_a_name
            )
            store_b = SQLiteStateStore(
                backend, scope_id=scope_id, job_namespace=job_b_name
            )

            # Both jobs write the same key with different values
            store_a.set(key, value_a)
            store_b.set(key, value_b)

            # Each job's own get() returns its own value
            assert store_a.get(key) == value_a
            assert store_b.get(key) == value_b
        finally:
            backend.close()


# --- Property 28: Non-serializable values stored as placeholder ---


class TestNonSerializableValuesPlaceholder:
    """Property 28: For non-serializable values (lambda, generator, socket),
    the ExecutionState plugin SHALL store a placeholder string containing
    the value's type name, and retrieval SHALL return that placeholder.

    **Validates: Requirements 23.10**
    """

    @settings(max_examples=50)
    @given(key=state_keys)
    def test_lambda_stored_as_placeholder(self, key: str):
        """**Validates: Requirements 23.10**

        Lambda functions are stored as a placeholder with the type name 'function'.
        """
        backend = _make_backend()
        try:
            store = SQLiteStateStore(
                backend, scope_id="test-scope", job_namespace="job-a"
            )
            non_serializable = lambda x: x  # noqa: E731

            store.set(key, non_serializable)
            retrieved = store.get(key)

            assert isinstance(retrieved, str)
            assert "function" in retrieved
            assert "<non-serializable:" in retrieved
        finally:
            backend.close()

    @settings(max_examples=50)
    @given(key=state_keys)
    def test_generator_stored_as_placeholder(self, key: str):
        """**Validates: Requirements 23.10**

        Generators are stored as a placeholder with the type name 'generator'.
        """
        backend = _make_backend()
        try:
            store = SQLiteStateStore(
                backend, scope_id="test-scope", job_namespace="job-a"
            )

            def gen():
                yield 1

            non_serializable = gen()

            store.set(key, non_serializable)
            retrieved = store.get(key)

            assert isinstance(retrieved, str)
            assert "generator" in retrieved
            assert "<non-serializable:" in retrieved
        finally:
            backend.close()

    @settings(max_examples=50)
    @given(key=state_keys)
    def test_socket_stored_as_placeholder(self, key: str):
        """**Validates: Requirements 23.10**

        Socket objects are stored as a placeholder with the type name 'socket'.
        """
        backend = _make_backend()
        try:
            store = SQLiteStateStore(
                backend, scope_id="test-scope", job_namespace="job-a"
            )
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            try:
                store.set(key, sock)
                retrieved = store.get(key)

                assert isinstance(retrieved, str)
                assert "socket" in retrieved
                assert "<non-serializable:" in retrieved
            finally:
                sock.close()
        finally:
            backend.close()

    @settings(max_examples=50)
    @given(
        key=state_keys,
        type_choice=st.sampled_from(["lambda", "generator", "module"]),
    )
    def test_non_serializable_placeholder_contains_type_name(
        self, key: str, type_choice: str
    ):
        """**Validates: Requirements 23.10**

        For any non-serializable value, the placeholder contains the type name.
        """
        backend = _make_backend()
        try:
            store = SQLiteStateStore(
                backend, scope_id="test-scope", job_namespace="job-a"
            )

            if type_choice == "lambda":
                value = lambda: None  # noqa: E731
                expected_type = "function"
            elif type_choice == "generator":

                def gen():
                    yield 1

                value = gen()
                expected_type = "generator"
            else:
                # Module objects are not JSON-serializable
                import os

                value = os
                expected_type = "module"

            store.set(key, value)
            retrieved = store.get(key)

            assert isinstance(retrieved, str)
            assert expected_type in retrieved
            assert "<non-serializable:" in retrieved
        finally:
            backend.close()
