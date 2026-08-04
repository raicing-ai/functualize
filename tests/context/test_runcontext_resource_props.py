"""Property-based tests for RunContext resource injection and typed access.

Property 16: Resource Injection and Typed Access
**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6**
"""

from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from functualize._config.job_config import JobConfigView
from functualize.job.context import RunContext, inject_resource

# --- Strategies ---

# Strategy for valid resource names (non-empty identifiers)
resource_names = st.text(
    alphabet=st.characters(categories=("L", "N", "Pd", "Pc")),
    min_size=1,
    max_size=50,
)


# --- Custom resource classes for type checking tests ---


class DatabaseClient:
    """Fake database client resource."""

    def __init__(self, url: str) -> None:
        self.url = url


class HttpSession:
    """Fake HTTP session resource."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


class QueueHandle:
    """Fake queue handle resource."""

    def __init__(self, queue_name: str) -> None:
        self.queue_name = queue_name


class CacheClient:
    """Fake cache client resource."""

    def __init__(self, ttl: int) -> None:
        self.ttl = ttl


# Strategy for generating typed resource instances
resource_instances = st.one_of(
    st.builds(DatabaseClient, url=st.text(min_size=1, max_size=30)),
    st.builds(HttpSession, base_url=st.text(min_size=1, max_size=30)),
    st.builds(QueueHandle, queue_name=st.text(min_size=1, max_size=30)),
    st.builds(CacheClient, ttl=st.integers(min_value=1, max_value=3600)),
)

# Types available for mismatch testing
resource_types: list[type[object]] = [
    DatabaseClient,
    HttpSession,
    QueueHandle,
    CacheClient,
]


# --- Helpers ---


def make_run_context(
    name: str = "test-job",
    resources: dict[str, object] | None = None,
) -> RunContext:
    """Create a RunContext with mocked dependencies."""
    mock_config = MagicMock(spec=JobConfigView)
    mock_logger = MagicMock()
    return RunContext(
        name=name,
        config=mock_config,
        logger=mock_logger,
        resources=resources,
    )


# Feature: enriched-runcontext, Property 16: Resource Injection and Typed Access
# inject_resource makes a resource accessible via get_resource.
# get_resource with correct type returns the resource.
# get_resource with wrong type raises TypeError with resource name, expected and actual types.
# get_resource with unknown name raises KeyError with available resources listed.
# resources property returns read-only mapping (immutable from outside).
# Multiple resources can be injected and accessed independently.
# **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6**
class TestResourceInjectionAndTypedAccess:
    """Property 16: Resource Injection and Typed Access."""

    @given(name=resource_names, resource=resource_instances)
    @settings(max_examples=200)
    def test_inject_resource_makes_accessible_via_get_resource(
        self, name: str, resource: object
    ) -> None:
        """inject_resource makes a resource accessible via get_resource.

        **Validates: Requirements 9.5**
        """
        rc = make_run_context()
        inject_resource(rc, name, resource)
        result = rc.get_resource(name, type(resource))
        assert result is resource

    @given(name=resource_names, resource=resource_instances)
    @settings(max_examples=200)
    def test_get_resource_correct_type_returns_resource(
        self, name: str, resource: object
    ) -> None:
        """get_resource with correct type returns the resource.

        **Validates: Requirements 9.2**
        """
        rc = make_run_context(resources={name: resource})
        result = rc.get_resource(name, type(resource))
        assert result is resource

    @given(
        name=resource_names,
        resource=resource_instances,
        wrong_type=st.sampled_from(resource_types),
    )
    @settings(max_examples=200)
    def test_get_resource_wrong_type_raises_typeerror(
        self, name: str, resource: object, wrong_type: type[object]
    ) -> None:
        """get_resource with wrong type raises TypeError with resource name,
        expected and actual types.

        **Validates: Requirements 9.4**
        """
        assume(not isinstance(resource, wrong_type))

        rc = make_run_context(resources={name: resource})

        with pytest.raises(TypeError) as exc_info:
            rc.get_resource(name, wrong_type)

        error_msg = str(exc_info.value)
        # Error message should contain the resource name
        assert name in error_msg
        # Error message should contain the expected type name
        assert wrong_type.__name__ in error_msg
        # Error message should contain the actual type name
        assert type(resource).__name__ in error_msg

    @given(
        name=resource_names,
        existing_names=st.lists(resource_names, min_size=0, max_size=5, unique=True),
    )
    @settings(max_examples=200)
    def test_get_resource_unknown_name_raises_keyerror(
        self, name: str, existing_names: list[str]
    ) -> None:
        """get_resource with unknown name raises KeyError with available resources listed.

        **Validates: Requirements 9.3**
        """
        assume(name not in existing_names)

        resources: dict[str, object] = {
            n: DatabaseClient(url=f"db://{n}") for n in existing_names
        }
        rc = make_run_context(resources=resources)

        with pytest.raises(KeyError) as exc_info:
            rc.get_resource(name, DatabaseClient)

        error_msg = str(exc_info.value)
        # Error message should list available resource names
        for existing_name in existing_names:
            assert existing_name in error_msg

    @given(
        items=st.dictionaries(
            keys=resource_names,
            values=resource_instances,
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=200)
    def test_resources_property_returns_readonly_mapping(
        self, items: dict[str, object]
    ) -> None:
        """resources property returns read-only mapping (immutable from outside).

        **Validates: Requirements 9.1, 9.6**
        """
        rc = make_run_context(resources=dict(items) if items else None)
        mapping = rc.resources

        # Should be a MappingProxyType (read-only)
        assert isinstance(mapping, MappingProxyType)

        # Should not be directly mutable
        with pytest.raises(TypeError):
            mapping["new_key"] = "new_value"  # type: ignore[index]

    @given(
        items=st.dictionaries(
            keys=resource_names,
            values=resource_instances,
            min_size=2,
            max_size=10,
        )
    )
    @settings(max_examples=200)
    def test_multiple_resources_injected_and_accessed_independently(
        self, items: dict[str, object]
    ) -> None:
        """Multiple resources can be injected and accessed independently.

        **Validates: Requirements 9.1, 9.2, 9.5**
        """
        rc = make_run_context()
        for name, resource in items.items():
            inject_resource(rc, name, resource)

        # Each resource should be independently accessible
        for name, resource in items.items():
            result = rc.get_resource(name, type(resource))
            assert result is resource

    @given(
        name=resource_names,
        resource=resource_instances,
    )
    @settings(max_examples=200)
    def test_resources_mapping_reflects_injected_resources(
        self, name: str, resource: object
    ) -> None:
        """resources property reflects resources after injection.

        **Validates: Requirements 9.1, 9.5**
        """
        rc = make_run_context()
        inject_resource(rc, name, resource)

        mapping = rc.resources
        assert name in mapping
        assert mapping[name] is resource

    @given(
        name=resource_names,
        first_resource=st.builds(DatabaseClient, url=st.text(min_size=1, max_size=20)),
        second_resource=st.builds(
            HttpSession, base_url=st.text(min_size=1, max_size=20)
        ),
    )
    @settings(max_examples=200)
    def test_inject_resource_overwrites_existing_name(
        self, name: str, first_resource: object, second_resource: object
    ) -> None:
        """inject_resource with same name overwrites the previous resource.

        **Validates: Requirements 9.5**
        """
        rc = make_run_context()
        inject_resource(rc, name, first_resource)
        inject_resource(rc, name, second_resource)

        result = rc.get_resource(name, type(second_resource))
        assert result is second_resource

    def test_resources_property_empty_when_no_resources(self) -> None:
        """resources returns empty mapping when no resources injected.

        **Validates: Requirements 9.1**
        """
        rc = make_run_context()
        mapping = rc.resources
        assert isinstance(mapping, MappingProxyType)
        assert len(mapping) == 0

    @given(
        name=resource_names,
        resource=resource_instances,
    )
    @settings(max_examples=200)
    def test_get_resource_with_object_type_always_succeeds(
        self, name: str, resource: object
    ) -> None:
        """get_resource with type_=object always succeeds (all resources are objects).

        **Validates: Requirements 9.2**
        """
        rc = make_run_context(resources={name: resource})
        result = rc.get_resource(name, object)
        assert result is resource
