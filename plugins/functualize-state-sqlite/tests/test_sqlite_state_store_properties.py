"""Property-based tests for SQLiteStateStore.

Tests Properties 26, 27, and 28 from the Plugin Ecosystem Enablement design.

- Property 26: SQLiteStateStore round-trip — set then get returns equivalent value
- Property 27: Cross-job state isolation — one job's write does not touch another's
- Property 28: Non-serializable values stored as placeholder with type name
"""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path
from typing import Any

from functualize_state_sqlite.sqlite_backend import SQLiteBackend
from functualize_state_sqlite.state_store import SQLiteStateStore
from hypothesis import given
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
    """Property 27: two jobs writing the same key in one scope do not collide.

    **The cross-*read* half of this property is gone** (`capability-duality`
    /T12). It asserted `store_b.get_job_state("A", key)` returning A's value —
    a framework namespace API, which ADR-021 §B records the maintainer deciding
    not to have, on the grounds that a namespace is something a string prefix
    already does. Deleting it from `StateStoreProtocol` cost this plugin a
    genuine capability: its rows are scoped by a real `(scope_id,
    job_namespace)` pair, so it could answer a cross-namespace read that the
    default dotted-key store only simulates.

    What survives is the half that matters for correctness, and it is asserted
    below: each job's own `get()` is unaffected by the other's write.

    **Validates: Requirements 23.7**
    """

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
