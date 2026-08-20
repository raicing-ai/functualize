"""Property-based tests for JobDescriptor retention and dynamic job registration.

Tests Properties 18 and 19 from the design document using Hypothesis.

Property 18: JobDescriptor retention — all descriptors queryable after registration
Property 19: Dynamic job registration — name uniqueness enforced

Validates: Requirements 12.2, 12.3, 12.4, 13.4
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from functualize._app.state import AppState
from functualize._types.naming import normalize_segment
from functualize.app.core import FunctualizeApp


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


# --- Strategies ---

# Valid job names: non-empty strings suitable for dynamic job registration.
# Using a pattern that matches typical job names (lowercase, hyphens, alphanumeric).
# Names are mapped through `normalize_segment` so every generated name is
# already canonical. A job is addressed by its canonical name, so a raw `t-`
# registers as `t` and any assertion comparing against the raw spelling fails
# on the trailing hyphen. Mapping (rather than filtering) keeps the full
# generation range while making each value a fixed point.
job_names = (
    st.from_regex(r"[a-z][a-z0-9\-]{0,30}", fullmatch=True)
    .map(normalize_segment)
    .filter(bool)
)

# Strategy for optional group names
group_names = st.one_of(
    st.none(),
    st.from_regex(r"[a-z][a-z0-9\-]{0,15}", fullmatch=True)
    .map(normalize_segment)
    .filter(bool),
)

# Strategy for optional docstrings
docstrings = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=100),
)


def _make_job_fn(docstring: str | None = None):
    """Create a simple job function with an optional docstring."""

    def job_fn() -> None:
        pass

    if docstring is not None:
        job_fn.__doc__ = docstring
    else:
        job_fn.__doc__ = None
    return job_fn


# --- Property 18: JobDescriptor retention — all descriptors queryable after registration ---


class TestJobDescriptorRetentionProperty:
    """Property 18: JobDescriptor retention — all descriptors queryable after registration.

    For any set of N dynamically registered jobs, get_descriptors() returns N
    descriptors, and get_descriptor(name) returns the correct one for each
    registered name. For unregistered names, KeyError.

    **Validates: Requirements 12.2, 12.3, 12.4**
    """

    @given(
        names=st.lists(job_names, min_size=1, max_size=10, unique=True),
    )
    def test_get_descriptors_returns_all_registered(self, names: list[str]) -> None:
        """For any set of N registered jobs, get_descriptors() returns N descriptors."""
        # **Validates: Requirements 12.2**
        app = FunctualizeApp(name="testapp")

        for name in names:
            app.register_dynamic_job(name, _make_job_fn())

        descriptors = app.job_registry.get_descriptors()
        assert len(descriptors) == len(names)

        descriptor_names = {d.name for d in descriptors}
        assert descriptor_names == set(names)

    @given(
        names=st.lists(job_names, min_size=1, max_size=10, unique=True),
        groups=st.lists(group_names, min_size=1, max_size=10),
        docs=st.lists(docstrings, min_size=1, max_size=10),
    )
    def test_get_descriptor_returns_correct_for_each_name(
        self, names: list[str], groups: list[str | None], docs: list[str | None]
    ) -> None:
        """For each registered name, get_descriptor(name) returns the correct descriptor."""
        # **Validates: Requirements 12.3**
        app = FunctualizeApp(name="testapp")

        # Pair names with groups and docs (cycle if lists differ in length)
        for i, name in enumerate(names):
            group = groups[i % len(groups)]
            doc = docs[i % len(docs)]
            fn = _make_job_fn(doc)
            app.register_dynamic_job(name, fn, group=group)

        # Verify each descriptor is individually retrievable and correct
        for i, name in enumerate(names):
            descriptor = app.job_registry.get_descriptor(name)
            assert descriptor.name == name
            expected_group = groups[i % len(groups)]
            assert descriptor.group == expected_group
            expected_doc = docs[i % len(docs)]
            assert descriptor.docstring == expected_doc

    @given(
        registered_names=st.lists(job_names, min_size=1, max_size=5, unique=True),
        unregistered_name=job_names,
    )
    def test_get_descriptor_raises_key_error_for_unregistered(
        self, registered_names: list[str], unregistered_name: str
    ) -> None:
        """For unregistered names, get_descriptor() raises KeyError."""
        # **Validates: Requirements 12.4**
        assume(unregistered_name not in registered_names)

        app = FunctualizeApp(name="testapp")

        for name in registered_names:
            app.register_dynamic_job(name, _make_job_fn())

        with pytest.raises(KeyError):
            app.job_registry.get_descriptor(unregistered_name)

    @given(
        names=st.lists(job_names, min_size=0, max_size=8, unique=True),
    )
    @settings(deadline=5000)
    def test_get_descriptors_empty_when_no_jobs(self, names: list[str]) -> None:
        """get_descriptors() returns empty list when no jobs registered, and
        returns a list of length N after N registrations."""
        # **Validates: Requirements 12.2**
        app = FunctualizeApp(name="testapp")

        # Initially empty
        assert app.job_registry.get_descriptors() == []

        # After registering N jobs, should have N descriptors
        for name in names:
            app.register_dynamic_job(name, _make_job_fn())

        assert len(app.job_registry.get_descriptors()) == len(names)


# --- Property 19: Dynamic job registration — name uniqueness enforced ---


class TestDynamicJobNameUniquenessProperty:
    """Property 19: Dynamic job registration — name uniqueness enforced.

    For any job name already present in the registry, register_dynamic_job()
    with the same name raises ValueError.

    **Validates: Requirements 13.4**
    """

    @given(
        name=job_names,
    )
    def test_duplicate_name_raises_value_error(self, name: str) -> None:
        """Registering a job with a name that already exists raises ValueError."""
        # **Validates: Requirements 13.4**
        app = FunctualizeApp(name="testapp")

        # Register first time succeeds
        app.register_dynamic_job(name, _make_job_fn("first"))

        # Register same name again raises ValueError
        with pytest.raises(ValueError, match="already exists"):
            app.register_dynamic_job(name, _make_job_fn("second"))

    @given(
        names=st.lists(job_names, min_size=2, max_size=8, unique=True),
        duplicate_index=st.integers(min_value=0),
    )
    def test_duplicate_after_multiple_registrations(
        self, names: list[str], duplicate_index: int
    ) -> None:
        """After registering N unique names, re-registering any of them raises ValueError."""
        # **Validates: Requirements 13.4**
        app = FunctualizeApp(name="testapp")

        # Register all unique names
        for name in names:
            app.register_dynamic_job(name, _make_job_fn())

        # Pick one to re-register (wrap index)
        target = names[duplicate_index % len(names)]

        with pytest.raises(ValueError, match="already exists"):
            app.register_dynamic_job(target, _make_job_fn("duplicate"))

    @given(
        names=st.lists(job_names, min_size=2, max_size=10, unique=True),
    )
    @settings(deadline=5000)
    def test_unique_names_all_succeed(self, names: list[str]) -> None:
        """Registering jobs with all unique names does not raise."""
        # **Validates: Requirements 13.4** (inverse: unique names succeed)
        app = FunctualizeApp(name="testapp")

        # All unique registrations should succeed without exception
        for name in names:
            app.register_dynamic_job(name, _make_job_fn())

        # Verify all are queryable
        descriptors = app.job_registry.get_descriptors()
        assert len(descriptors) == len(names)
