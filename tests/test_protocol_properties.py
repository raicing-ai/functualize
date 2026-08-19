"""Property-based tests for Protocol structural typing and StaticProvider (Properties 15, 16).

Tests:
- Property 15: Protocol structural typing correctness
- Property 16: StaticProvider round-trip from callables

# Feature: unified-architecture-redesign, Properties 15-16
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hypothesis import given, settings
from hypothesis import strategies as st

from functualize._discovery.providers import Job, StaticProvider
from functualize._primitives.pre_filter import ModulePreFilter
from functualize._types.naming import normalize_name, normalize_segment
from functualize._types.protocols import JobProvider, JobTransform

if TYPE_CHECKING:
    from functualize._types.descriptors import JobDescriptor

# =============================================================================
# Helpers: Dynamic class generation for structural typing tests
# =============================================================================


def _make_class_with_methods(
    methods: dict[str, Any], attrs: dict[str, Any] | None = None
) -> type:
    """Dynamically create a class with the given methods and attributes."""
    namespace: dict[str, Any] = {}
    if attrs:
        namespace.update(attrs)
    namespace.update(methods)
    return type("DynamicClass", (), namespace)


# =============================================================================
# Strategies
# =============================================================================

# Strategy: generate valid Python identifiers for function names
_identifier_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)

# Strategy: generate a list of function names unique *in canonical space*.
#
# Job identity is the canonical name, not the Python name: `normalize_segment`
# maps `_` to `-` and strips the result, so `a_`, `a__` and `a` all denote the
# same job and registering two of them is a collision, not two jobs. Uniqueness
# therefore has to be stated over `normalize_segment`, and names that normalize
# to empty are not addressable at all.
_unique_names_strategy = st.lists(
    _identifier_strategy.filter(lambda n: normalize_segment(n) != ""),
    min_size=1,
    max_size=20,
    unique_by=normalize_segment,
)

# Strategy: boolean for whether to use Job dataclass vs plain callable
_use_job_dataclass = st.booleans()

# Strategy: optional group name
_optional_group = st.one_of(st.none(), _identifier_strategy)

# Strategy: optional name override
_optional_name_override = st.one_of(st.none(), _identifier_strategy)


# =============================================================================
# Property 15: Protocol structural typing correctness
# =============================================================================


class TestProtocolStructuralTypingCorrectness:
    """Property 15: Protocol structural typing correctness.

    For any class that defines all required methods/attributes of a
    @runtime_checkable Protocol (JobProvider, JobTransform, ModulePreFilter)
    without inheriting from it, isinstance(instance, ProtocolClass) SHALL
    return True. For any class missing a required member, isinstance SHALL
    return False.

    **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 10.5**
    """

    # --- JobProvider Protocol ---

    @given(
        has_list_jobs=st.booleans(),
        has_get_job=st.booleans(),
    )
    @settings(max_examples=100)
    def test_job_provider_structural_typing(
        self, has_list_jobs: bool, has_get_job: bool
    ):
        """Classes with all JobProvider methods satisfy the protocol; missing methods fail.

        **Validates: Requirements 9.1, 9.2**
        """
        methods: dict[str, Any] = {}
        if has_list_jobs:
            methods["list_jobs"] = lambda self: []
        if has_get_job:
            methods["get_job"] = lambda self, name: None

        cls = _make_class_with_methods(methods)
        instance = cls()

        should_pass = has_list_jobs and has_get_job
        assert isinstance(instance, JobProvider) == should_pass

    @given(data=st.data())
    @settings(max_examples=50)
    def test_job_provider_concrete_implementations_satisfy_protocol(self, data: Any):
        """Concrete implementations with correct signatures satisfy JobProvider.

        **Validates: Requirements 9.1, 9.4**
        """

        class ConcreteProvider:
            def __init__(self, jobs: list[JobDescriptor]):
                self._jobs = jobs

            def list_jobs(self) -> Sequence[JobDescriptor]:
                return self._jobs

            def get_job(self, name: str) -> JobDescriptor | None:
                for j in self._jobs:
                    if j.name == name:
                        return j
                return None

        provider = ConcreteProvider([])
        assert isinstance(provider, JobProvider)

    # --- JobTransform Protocol ---

    @given(
        has_transform_list=st.booleans(),
        has_transform_get=st.booleans(),
    )
    @settings(max_examples=100)
    def test_job_transform_structural_typing(
        self, has_transform_list: bool, has_transform_get: bool
    ):
        """Classes with all JobTransform methods satisfy the protocol; missing methods fail.

        **Validates: Requirements 9.2, 9.3**
        """
        methods: dict[str, Any] = {}
        if has_transform_list:
            methods["transform_list"] = lambda self, jobs: jobs
        if has_transform_get:
            methods["transform_get"] = lambda self, name, descriptor: descriptor

        cls = _make_class_with_methods(methods)
        instance = cls()

        should_pass = has_transform_list and has_transform_get
        assert isinstance(instance, JobTransform) == should_pass

    @given(data=st.data())
    @settings(max_examples=50)
    def test_job_transform_concrete_implementations_satisfy_protocol(self, data: Any):
        """Concrete implementations with correct signatures satisfy JobTransform.

        **Validates: Requirements 9.2, 9.4**
        """

        class ConcreteTransform:
            def transform_list(
                self, jobs: Sequence[JobDescriptor]
            ) -> Sequence[JobDescriptor]:
                return jobs

            def transform_get(
                self, name: str, descriptor: JobDescriptor | None
            ) -> JobDescriptor | None:
                return descriptor

        transform = ConcreteTransform()
        assert isinstance(transform, JobTransform)

    # --- ModulePreFilter Protocol ---

    @given(has_should_import=st.booleans())
    @settings(max_examples=100)
    def test_module_pre_filter_structural_typing(self, has_should_import: bool):
        """Classes with should_import satisfy ModulePreFilter; missing method fails.

        **Validates: Requirements 9.3, 9.4**
        """
        methods: dict[str, Any] = {}
        if has_should_import:
            methods["should_import"] = lambda self, source_file: True

        cls = _make_class_with_methods(methods)
        instance = cls()

        assert isinstance(instance, ModulePreFilter) == has_should_import

    @given(data=st.data())
    @settings(max_examples=50)
    def test_module_pre_filter_concrete_implementation(self, data: Any):
        """Concrete ModulePreFilter implementations satisfy the protocol.

        **Validates: Requirements 9.3, 9.4**
        """

        class MyFilter:
            def should_import(self, source_file: Path) -> bool:
                return source_file.suffix == ".py"

        f = MyFilter()
        assert isinstance(f, ModulePreFilter)

    # --- Combined: multiple protocols on one class ---

    @given(
        has_list_jobs=st.booleans(),
        has_get_job=st.booleans(),
        has_should_import=st.booleans(),
    )
    @settings(max_examples=200)
    def test_class_can_satisfy_multiple_protocols(
        self, has_list_jobs: bool, has_get_job: bool, has_should_import: bool
    ):
        """A class can satisfy multiple protocols simultaneously via structural typing.

        **Validates: Requirements 9.4**
        """
        methods: dict[str, Any] = {}
        if has_list_jobs:
            methods["list_jobs"] = lambda self: []
        if has_get_job:
            methods["get_job"] = lambda self, name: None
        if has_should_import:
            methods["should_import"] = lambda self, source_file: True

        cls = _make_class_with_methods(methods)
        instance = cls()

        is_provider = has_list_jobs and has_get_job
        is_filter = has_should_import

        assert isinstance(instance, JobProvider) == is_provider
        assert isinstance(instance, ModulePreFilter) == is_filter

    # --- Extra methods don't break protocol satisfaction ---

    @given(
        extra_methods=st.lists(
            _identifier_strategy, min_size=0, max_size=5, unique=True
        )
    )
    @settings(max_examples=100)
    def test_extra_methods_do_not_break_protocol(self, extra_methods: list[str]):
        """Classes with extra methods beyond protocol requirements still satisfy protocols.

        **Validates: Requirements 9.4**
        """
        methods: dict[str, Any] = {
            "list_jobs": lambda self: [],
            "get_job": lambda self, name: None,
        }
        # Add extra methods
        for name in extra_methods:
            if name not in methods:
                methods[name] = lambda self: None

        cls = _make_class_with_methods(methods)
        instance = cls()

        assert isinstance(instance, JobProvider)


# =============================================================================
# Property 16: StaticProvider round-trip from callables
# =============================================================================


class TestStaticProviderRoundTrip:
    """Property 16: StaticProvider round-trip from callables.

    For any list of N callables (or Job dataclass instances),
    StaticProvider(functions=list) SHALL produce exactly N job descriptors
    via list_jobs(), and get_job(name) SHALL return the descriptor for any
    name derived from function.__name__ (or the explicit Job.name override).

    **Validates: Requirements 23.1, 23.2, 23.3, 23.4, 23.5**
    """

    @given(names=_unique_names_strategy)
    @settings(max_examples=200)
    def test_plain_callables_produce_exact_count(self, names: list[str]):
        """StaticProvider with N plain callables produces exactly N descriptors.

        **Validates: Requirements 23.1, 23.2**
        """
        # Create callables with distinct __name__ attributes
        functions = []
        for name in names:
            fn = lambda: None  # noqa: E731
            fn.__name__ = name
            fn.__module__ = "__test__"
            functions.append(fn)

        provider = StaticProvider(functions=functions)
        descriptors = provider.list_jobs()

        assert len(descriptors) == len(names)

    @given(names=_unique_names_strategy)
    @settings(max_examples=200)
    def test_plain_callables_get_job_round_trip(self, names: list[str]):
        """get_job(name) returns descriptor for each callable's __name__.

        **Validates: Requirements 23.1, 23.2, 23.3**
        """
        functions = []
        for name in names:
            fn = lambda: None  # noqa: E731
            fn.__name__ = name
            fn.__module__ = "__test__"
            functions.append(fn)

        provider = StaticProvider(functions=functions)

        for name in names:
            descriptor = provider.get_job(name)
            assert descriptor is not None
            assert descriptor.name == normalize_segment(name)

    @given(names=_unique_names_strategy)
    @settings(max_examples=200)
    def test_get_job_returns_none_for_unknown(self, names: list[str]):
        """get_job() returns None for names not in the provider.

        **Validates: Requirements 23.3**
        """
        functions = []
        for name in names:
            fn = lambda: None  # noqa: E731
            fn.__name__ = name
            fn.__module__ = "__test__"
            functions.append(fn)

        provider = StaticProvider(functions=functions)

        # Use a name that definitely doesn't exist
        assert provider.get_job("__nonexistent_job_xyz__") is None

    @given(
        names=_unique_names_strategy,
        overrides=st.lists(
            st.tuples(
                _identifier_strategy.filter(lambda n: normalize_segment(n) != ""),
                _optional_group,
            ),
            min_size=1,
            max_size=10,
            # Canonical name is identity, so two overrides differing only by
            # underscores are the same job, not two.
            unique_by=lambda x: normalize_segment(x[0]),
        ),
    )
    @settings(max_examples=200)
    def test_job_dataclass_name_override(
        self, names: list[str], overrides: list[tuple[str, str | None]]
    ):
        """Job dataclass name overrides are respected in descriptors.

        **Validates: Requirements 23.4, 23.5**
        """
        functions: list[Job] = []
        expected_names: list[str] = []

        for override_name, group in overrides:
            fn = lambda: None  # noqa: E731
            fn.__name__ = "original_name"
            fn.__module__ = "__test__"
            job = Job(function=fn, name=override_name, group=group)
            functions.append(job)
            expected_names.append(override_name)

        provider = StaticProvider(functions=functions)
        descriptors = provider.list_jobs()

        assert len(descriptors) == len(overrides)

        for override_name, group in overrides:
            descriptor = provider.get_job(override_name)
            assert descriptor is not None
            assert descriptor.name == normalize_segment(override_name)
            assert descriptor.group == normalize_name(group)

    @given(names=_unique_names_strategy)
    @settings(max_examples=200)
    def test_job_dataclass_uses_function_name_when_name_is_none(self, names: list[str]):
        """Job dataclass with name=None falls back to function.__name__.

        **Validates: Requirements 23.4**
        """
        functions: list[Job] = []
        for name in names:
            fn = lambda: None  # noqa: E731
            fn.__name__ = name
            fn.__module__ = "__test__"
            functions.append(Job(function=fn, name=None))

        provider = StaticProvider(functions=functions)

        for name in names:
            descriptor = provider.get_job(name)
            assert descriptor is not None
            assert descriptor.name == normalize_segment(name)

    @given(names=_unique_names_strategy)
    @settings(max_examples=100)
    def test_static_provider_satisfies_job_provider_protocol(self, names: list[str]):
        """StaticProvider satisfies the JobProvider Protocol via structural typing.

        **Validates: Requirements 23.1, 9.1**
        """
        functions = []
        for name in names:
            fn = lambda: None  # noqa: E731
            fn.__name__ = name
            fn.__module__ = "__test__"
            functions.append(fn)

        provider = StaticProvider(functions=functions)
        assert isinstance(provider, JobProvider)

    @given(
        names=_unique_names_strategy,
        use_job=st.lists(st.booleans(), min_size=1, max_size=20),
    )
    @settings(max_examples=200)
    def test_mixed_callables_and_job_dataclass(
        self, names: list[str], use_job: list[bool]
    ):
        """Mixing plain callables and Job dataclass instances produces correct descriptors.

        **Validates: Requirements 23.2, 23.4, 23.5**
        """
        # Use min of both list lengths
        count = min(len(names), len(use_job))
        functions: list[Any] = []
        expected_names: list[str] = []

        for i in range(count):
            fn = lambda: None  # noqa: E731
            fn.__name__ = names[i]
            fn.__module__ = "__test__"

            if use_job[i]:
                functions.append(Job(function=fn))
            else:
                functions.append(fn)
            expected_names.append(names[i])

        provider = StaticProvider(functions=functions)
        descriptors = provider.list_jobs()

        assert len(descriptors) == count

        for name in expected_names:
            descriptor = provider.get_job(name)
            assert descriptor is not None
            assert descriptor.name == normalize_segment(name)

    @given(names=_unique_names_strategy)
    @settings(max_examples=100)
    def test_list_jobs_and_get_job_consistency(self, names: list[str]):
        """Every descriptor from list_jobs() is retrievable via get_job(name).

        **Validates: Requirements 23.1, 23.3**
        """
        functions = []
        for name in names:
            fn = lambda: None  # noqa: E731
            fn.__name__ = name
            fn.__module__ = "__test__"
            functions.append(fn)

        provider = StaticProvider(functions=functions)
        descriptors = provider.list_jobs()

        # All list_jobs entries retrievable by get_job
        listed_names = {d.name for d in descriptors}
        for name in listed_names:
            assert provider.get_job(name) is not None

        # No phantom jobs: get_job only returns for listed names
        assert listed_names == {normalize_segment(n) for n in names}

    @given(names=_unique_names_strategy)
    @settings(max_examples=100)
    def test_static_provider_zero_io(self, names: list[str]):
        """StaticProvider produces descriptors with source='<static>' (zero I/O).

        `source` carries the sentinel; `source_file` stays empty because it is
        the filesystem path used for cache invalidation and an in-memory
        function has no file to stat.

        **Validates: Requirements 23.1**
        """
        functions = []
        for name in names:
            fn = lambda: None  # noqa: E731
            fn.__name__ = name
            fn.__module__ = "__test__"
            functions.append(fn)

        provider = StaticProvider(functions=functions)
        for desc in provider.list_jobs():
            assert desc.source == "<static>"
            assert desc.source_file == ""
            assert desc.source_mtime == 0.0
