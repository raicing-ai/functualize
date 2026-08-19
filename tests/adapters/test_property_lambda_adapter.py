"""Property-based tests for LambdaAdapter event routing (Property 25).

Tests that for any valid event dict containing {"job": job_name, "kwargs": {...}}
where job_name corresponds to a registered job, LambdaAdapter.run(event, context)
executes the named job with the provided kwargs and returns a dict with statusCode
and body fields.

Also verifies error handling: missing "job" field returns 400, unknown job names
return 500, and the adapter routes to the correct job.

# Feature: unified-architecture-redesign, Property 25: Lambda adapter event routing

**Validates: Requirements 27.2, 27.3**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from functualize_lambda import LambdaAdapter
from hypothesis import given
from hypothesis import strategies as st

# =============================================================================
# Test Doubles
# =============================================================================


@dataclass(frozen=True)
class FakeJobResult:
    """Minimal stand-in for JobResult to track execution."""

    status: str = "success"
    duration_ms: float = 1.0
    return_value: Any = None
    exception: BaseException | None = None
    job_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class TrackingApp:
    """Fake FunctualizeApp that tracks which job was called with which kwargs.

    Records all calls for later assertion and returns predictable results.
    """

    def __init__(self, registered_jobs: set[str]) -> None:
        self._registered_jobs = registered_jobs
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, job_name: str, **kwargs: Any) -> FakeJobResult:
        if job_name not in self._registered_jobs:
            raise KeyError(f"Job '{job_name}' not found")
        self.calls.append((job_name, kwargs))
        return FakeJobResult(
            return_value={"job_name": job_name, "kwargs": kwargs},
            job_name=job_name,
        )


# =============================================================================
# Strategies
# =============================================================================

# Strategy: generate valid job names (non-empty ASCII strings, no whitespace)
_job_name_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=30,
)

# Strategy: generate sets of registered job names (at least 1)
_registered_jobs_strategy = st.frozensets(
    _job_name_strategy,
    min_size=1,
    max_size=10,
)

# Strategy: generate JSON-compatible kwargs values
_json_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    st.text(min_size=0, max_size=50),
)

_json_value = st.recursive(
    _json_leaf,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(
            st.text(min_size=1, max_size=10),
            children,
            max_size=5,
        ),
    ),
    max_leaves=20,
)

# Strategy: generate kwargs dicts (string keys, JSON-compatible values)
_kwargs_strategy = st.dictionaries(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
            whitelist_characters="_",
        ),
        min_size=1,
        max_size=15,
    ),
    _json_leaf,
    min_size=0,
    max_size=5,
)


# =============================================================================
# Property 25: Lambda adapter event routing
# =============================================================================


class TestLambdaAdapterEventRouting:
    """Property 25: Lambda adapter event routing.

    For any valid event dict containing {"job": job_name, "kwargs": {...}}
    where job_name corresponds to a registered job, LambdaAdapter.run(event, context)
    SHALL execute the named job with the provided kwargs and return a dict with
    statusCode and body fields.

    **Validates: Requirements 27.2, 27.3**
    """

    @given(
        registered_jobs=_registered_jobs_strategy,
        kwargs=_kwargs_strategy,
    )
    def test_valid_event_returns_200_with_statuscode_and_body(
        self,
        registered_jobs: frozenset[str],
        kwargs: dict[str, Any],
    ):
        """For any valid event with a registered job name, run() returns a dict
        with statusCode=200 and body containing the job's return value.

        **Validates: Requirements 27.2, 27.3**
        """
        # Pick a job name from the registered set
        job_name = sorted(registered_jobs)[0]

        app = TrackingApp(registered_jobs=set(registered_jobs))
        adapter = LambdaAdapter()
        adapter(app)

        event = {"job": job_name, "kwargs": kwargs}
        result = adapter.run(event, None)

        # Must return a dict with statusCode and body
        assert isinstance(result, dict)
        assert "statusCode" in result
        assert "body" in result
        assert result["statusCode"] == 200
        assert isinstance(result["statusCode"], int)

    @given(
        registered_jobs=_registered_jobs_strategy,
        kwargs=_kwargs_strategy,
    )
    def test_adapter_routes_to_correct_job(
        self,
        registered_jobs: frozenset[str],
        kwargs: dict[str, Any],
    ):
        """The adapter SHALL route to the exact job name specified in the event,
        passing the kwargs to it.

        **Validates: Requirements 27.2, 27.3**
        """
        job_name = sorted(registered_jobs)[0]

        app = TrackingApp(registered_jobs=set(registered_jobs))
        adapter = LambdaAdapter()
        adapter(app)

        event = {"job": job_name, "kwargs": kwargs}
        adapter.run(event, None)

        # Verify the correct job was called with the correct kwargs
        assert len(app.calls) == 1
        called_job, called_kwargs = app.calls[0]
        assert called_job == job_name
        assert called_kwargs == kwargs

    @given(
        registered_jobs=_registered_jobs_strategy,
        data=st.data(),
    )
    def test_any_registered_job_is_routable(
        self,
        registered_jobs: frozenset[str],
        data: st.DataObject,
    ):
        """For any job name drawn from the set of registered jobs,
        run() successfully routes to it and returns 200.

        **Validates: Requirements 27.2, 27.3**
        """
        job_name = data.draw(st.sampled_from(sorted(registered_jobs)))

        app = TrackingApp(registered_jobs=set(registered_jobs))
        adapter = LambdaAdapter()
        adapter(app)

        event = {"job": job_name}
        result = adapter.run(event, None)

        assert result["statusCode"] == 200
        assert len(app.calls) == 1
        assert app.calls[0][0] == job_name

    @given(
        event=st.dictionaries(
            st.text(min_size=1, max_size=10).filter(lambda k: k != "job"),
            _json_leaf,
            min_size=0,
            max_size=5,
        )
    )
    def test_missing_job_field_returns_400(
        self,
        event: dict[str, Any],
    ):
        """Events without a 'job' field SHALL always return statusCode 400.

        **Validates: Requirements 27.2, 27.3**
        """
        # Ensure event does NOT contain "job" key
        assert "job" not in event

        app = TrackingApp(registered_jobs={"some_job"})
        adapter = LambdaAdapter()
        adapter(app)

        result = adapter.run(event, None)

        assert isinstance(result, dict)
        assert "statusCode" in result
        assert "body" in result
        assert result["statusCode"] == 400

    @given(
        registered_jobs=_registered_jobs_strategy,
        unknown_suffix=st.text(min_size=1, max_size=10),
    )
    def test_unknown_job_name_returns_500(
        self,
        registered_jobs: frozenset[str],
        unknown_suffix: str,
    ):
        """Events with job names not in the registered set SHALL return statusCode 500.

        **Validates: Requirements 27.2, 27.3**
        """
        # Construct a job name guaranteed to not be in the registered set
        unknown_job = "___unknown___" + unknown_suffix

        app = TrackingApp(registered_jobs=set(registered_jobs))
        adapter = LambdaAdapter()
        adapter(app)

        event = {"job": unknown_job}
        result = adapter.run(event, None)

        assert isinstance(result, dict)
        assert "statusCode" in result
        assert "body" in result
        assert result["statusCode"] == 500

    @given(
        registered_jobs=_registered_jobs_strategy,
        kwargs=_kwargs_strategy,
    )
    def test_result_body_contains_return_value(
        self,
        registered_jobs: frozenset[str],
        kwargs: dict[str, Any],
    ):
        """The body field SHALL contain the job's return value on success.

        **Validates: Requirements 27.2, 27.3**
        """
        job_name = sorted(registered_jobs)[0]

        app = TrackingApp(registered_jobs=set(registered_jobs))
        adapter = LambdaAdapter()
        adapter(app)

        event = {"job": job_name, "kwargs": kwargs}
        result = adapter.run(event, None)

        assert result["statusCode"] == 200
        # The body is the return_value from FakeJobResult
        # TrackingApp returns {"job_name": ..., "kwargs": ...}
        assert result["body"] == {"job_name": job_name, "kwargs": kwargs}
