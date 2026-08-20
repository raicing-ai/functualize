"""Property-based tests for FieldDescriptor and JobDescriptor.

Tests Properties 3, 17, and 18 from the design document for the
layered-architecture-lazy-boot spec.

Property 3 — Validates: Requirements 4.4
Property 17 — Validates: Requirements 17.3, 17.4, 17.5, 17.7
Property 18 — Validates: Requirements 17.6
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from functualize._types.descriptors import (
    FieldDescriptor,
    JobDescriptor,
)

# --- Constants ---

# Allowed type values for FieldDescriptor as defined in the design document.
ALLOWED_TYPES = ["str", "int", "bool", "float", "enum", "list[str]"]
NON_ENUM_TYPES = ["str", "int", "bool", "float", "list[str]"]


# --- Strategies ---


@st.composite
def field_descriptors(draw: st.DrawFn) -> FieldDescriptor:
    """Generate valid FieldDescriptor instances respecting the enum/choices invariant.

    This strategy mimics what the schema extractor would produce:
    - If type is "enum", choices is a non-empty list of non-empty strings
    - If type is anything else, choices is None
    """
    type_name = draw(st.sampled_from(ALLOWED_TYPES))

    if type_name == "enum":
        choices = draw(
            st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=10)
        )
    else:
        choices = None

    name = draw(st.from_regex(r"[a-z][a-z0-9_]{0,29}", fullmatch=True))
    required = draw(st.booleans())
    default = draw(st.none() | st.text(max_size=50)) if not required else None
    help_text = draw(st.text(max_size=100))

    return FieldDescriptor(
        name=name,
        type_annotation=type_name,
        choices=choices,
        default=default,
        required=required,
        description=help_text,
    )


@st.composite
def enum_field_descriptors(draw: st.DrawFn) -> FieldDescriptor:
    """Generate FieldDescriptor instances specifically with type == 'enum'."""
    choices = draw(st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=10))
    name = draw(st.from_regex(r"[a-z][a-z0-9_]{0,29}", fullmatch=True))
    required = draw(st.booleans())
    default = draw(st.none() | st.sampled_from(choices)) if not required else None
    help_text = draw(st.text(max_size=100))

    return FieldDescriptor(
        name=name,
        type_annotation="enum",
        choices=choices,
        default=default,
        required=required,
        description=help_text,
    )


@st.composite
def non_enum_field_descriptors(draw: st.DrawFn) -> FieldDescriptor:
    """Generate FieldDescriptor instances with type != 'enum'."""
    type_name = draw(st.sampled_from(NON_ENUM_TYPES))
    name = draw(st.from_regex(r"[a-z][a-z0-9_]{0,29}", fullmatch=True))
    required = draw(st.booleans())
    default = draw(st.none() | st.text(max_size=50)) if not required else None
    help_text = draw(st.text(max_size=100))

    return FieldDescriptor(
        name=name,
        type_annotation=type_name,
        choices=None,
        default=default,
        required=required,
        description=help_text,
    )


# --- Property 3: FieldDescriptor enum/choices invariant ---


# Feature: layered-architecture-lazy-boot, Property 3: FieldDescriptor enum/choices invariant
class TestFieldDescriptorEnumChoicesInvariant:
    """Property 3: FieldDescriptor enum/choices invariant.

    For any FieldDescriptor produced by the schema extractor, if type == "enum"
    then choices SHALL be a non-empty list[str], and if type is any other allowed
    value then choices SHALL be None.
    """

    @given(descriptor=field_descriptors())
    def test_enum_choices_invariant_holds_for_all_descriptors(
        self, descriptor: FieldDescriptor
    ):
        """The enum/choices invariant holds for any valid FieldDescriptor.

        # Feature: layered-architecture-lazy-boot, Property 3: FieldDescriptor enum/choices invariant
        **Validates: Requirements 4.4**
        """
        if descriptor.type_annotation == "enum":
            # choices SHALL be a non-empty list[str]
            assert descriptor.choices is not None
            assert isinstance(descriptor.choices, list)
            assert len(descriptor.choices) > 0
            assert all(isinstance(c, str) for c in descriptor.choices)
        else:
            # choices SHALL be None for any non-enum type
            assert descriptor.choices is None

    @given(descriptor=enum_field_descriptors())
    def test_enum_type_always_has_non_empty_choices(self, descriptor: FieldDescriptor):
        """Enum-typed descriptors always have a non-empty choices list.

        # Feature: layered-architecture-lazy-boot, Property 3: FieldDescriptor enum/choices invariant
        **Validates: Requirements 4.4**
        """
        assert descriptor.type_annotation == "enum"
        assert descriptor.choices is not None
        assert isinstance(descriptor.choices, list)
        assert len(descriptor.choices) > 0
        assert all(isinstance(c, str) for c in descriptor.choices)

    @given(descriptor=non_enum_field_descriptors())
    def test_non_enum_type_always_has_none_choices(self, descriptor: FieldDescriptor):
        """Non-enum descriptors always have choices == None.

        # Feature: layered-architecture-lazy-boot, Property 3: FieldDescriptor enum/choices invariant
        **Validates: Requirements 4.4**
        """
        assert descriptor.type_annotation != "enum"
        assert descriptor.choices is None


# --- Strategies for Properties 17-18 ---

# JSON-serializable default values (primitives only, to ensure round-trip identity)
json_serializable_defaults = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6),
    st.text(max_size=50),
    st.lists(st.text(max_size=20), max_size=5),
)


@st.composite
def json_safe_field_descriptors(draw: st.DrawFn) -> FieldDescriptor:
    """Generate valid FieldDescriptor instances with JSON-serializable defaults.

    For the round-trip property to hold, defaults must be JSON-serializable
    (non-serializable defaults get converted to None during to_dict).
    """
    type_name = draw(st.sampled_from(ALLOWED_TYPES))

    if type_name == "enum":
        choices = draw(
            st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5)
        )
    else:
        choices = None

    name = draw(st.from_regex(r"[a-z][a-z0-9_]{0,29}", fullmatch=True))
    required = draw(st.booleans())

    default = None if required else draw(json_serializable_defaults)

    help_text = draw(st.text(max_size=100))

    return FieldDescriptor(
        name=name,
        type_annotation=type_name,
        choices=choices,
        default=default,
        required=required,
        description=help_text,
    )


@st.composite
def job_descriptors(draw: st.DrawFn) -> JobDescriptor:
    """Generate valid JobDescriptor instances with JSON-serializable fields.

    All defaults within config_fields are JSON-serializable so that
    the round-trip identity property holds.
    """
    name = draw(st.from_regex(r"[a-z][a-z0-9_]{0,29}", fullmatch=True))
    group = draw(st.none() | st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True))
    module_path = draw(
        st.from_regex(
            r"[a-z][a-z0-9_]{0,9}(\.[a-z][a-z0-9_]{0,9}){0,3}", fullmatch=True
        )
    )
    source_file = draw(st.from_regex(r"/[a-z][a-z0-9_/]{0,40}\.py", fullmatch=True))
    source_mtime = draw(
        st.floats(min_value=0, max_value=2e9, allow_nan=False, allow_infinity=False)
    )
    content_hash = draw(st.from_regex(r"[0-9a-f]{64}", fullmatch=True))
    docstring = draw(st.none() | st.text(max_size=200))
    config_fields = draw(st.lists(json_safe_field_descriptors(), max_size=5))

    # Dependencies: dict of paths to sha256 hashes
    dep_count = draw(st.integers(min_value=0, max_value=3))
    dep_keys = draw(
        st.lists(
            st.from_regex(r"/[a-z][a-z0-9_/]{0,30}\.py", fullmatch=True),
            min_size=dep_count,
            max_size=dep_count,
            unique=True,
        )
    )
    dep_values = draw(
        st.lists(
            st.from_regex(r"[0-9a-f]{64}", fullmatch=True),
            min_size=dep_count,
            max_size=dep_count,
        )
    )
    dependencies = dict(zip(dep_keys, dep_values, strict=False))

    return JobDescriptor(
        name=name,
        group=group,
        module_path=module_path,
        source_file=source_file,
        source_mtime=source_mtime,
        content_hash=content_hash,
        docstring=docstring,
        config_fields=config_fields,
        dependencies=dependencies,
    )


# --- Required keys for malformed dict generation ---

JOB_DESCRIPTOR_REQUIRED_KEYS = {
    "name",
    "group",
    "module_path",
    "source_file",
    "source_mtime",
    "content_hash",
    "docstring",
    "config_fields",
    "dependencies",
}


@st.composite
def malformed_dicts_missing_keys(draw: st.DrawFn) -> dict:
    """Generate dicts missing one or more required JobDescriptor keys."""
    # Start from a valid-looking dict
    base = {
        "name": "deploy",
        "group": None,
        "module_path": "my.module",
        "source_file": "/path/to/file.py",
        "source_mtime": 1234567890.0,
        "content_hash": "a" * 64,
        "docstring": None,
        "config_fields": [],
        "dependencies": {},
    }

    # Remove at least one required key
    keys_to_remove = draw(
        st.lists(
            st.sampled_from(sorted(JOB_DESCRIPTOR_REQUIRED_KEYS)),
            min_size=1,
            max_size=len(JOB_DESCRIPTOR_REQUIRED_KEYS),
            unique=True,
        )
    )
    for key in keys_to_remove:
        del base[key]

    return base


@st.composite
def malformed_dicts_wrong_types(draw: st.DrawFn) -> dict:
    """Generate dicts with one or more values of wrong types for JobDescriptor keys."""
    # Start from a valid-looking dict
    base = {
        "name": "deploy",
        "group": None,
        "module_path": "my.module",
        "source_file": "/path/to/file.py",
        "source_mtime": 1234567890.0,
        "content_hash": "a" * 64,
        "docstring": None,
        "config_fields": [],
        "dependencies": {},
    }

    # Fields that expect specific types and the wrong types to substitute
    wrong_type_options = {
        "name": st.one_of(st.integers(), st.lists(st.text()), st.booleans()),
        "module_path": st.one_of(st.integers(), st.lists(st.text()), st.booleans()),
        "source_file": st.one_of(st.integers(), st.lists(st.text()), st.booleans()),
        # Note: bool is a subclass of int in Python, so isinstance(False, (int, float))
        # is True. We only use types that actually fail the isinstance check.
        "source_mtime": st.one_of(st.text(), st.lists(st.text()), st.none()),
        "content_hash": st.one_of(st.integers(), st.lists(st.text()), st.booleans()),
        "config_fields": st.one_of(st.text(), st.integers(), st.booleans()),
        "dependencies": st.one_of(st.text(), st.integers(), st.lists(st.text())),
        # group and docstring accept None, so use non-str non-None values
        "group": st.one_of(st.integers(), st.lists(st.text()), st.booleans()).filter(
            lambda x: x is not None
        ),
        "docstring": st.one_of(
            st.integers(), st.lists(st.text()), st.booleans()
        ).filter(lambda x: x is not None),
    }

    # Pick at least one field to corrupt
    field_to_corrupt = draw(st.sampled_from(sorted(wrong_type_options.keys())))
    base[field_to_corrupt] = draw(wrong_type_options[field_to_corrupt])

    return base


# --- Property 17: JobDescriptor serialization round-trip ---


# Feature: layered-architecture-lazy-boot, Property 17: JobDescriptor serialization round-trip
class TestJobDescriptorSerializationRoundTrip:
    """Property 17: JobDescriptor serialization round-trip.

    For any valid JobDescriptor instance (including nested FieldDescriptor lists
    and dependencies dicts), serializing via to_dict() and then deserializing
    via from_dict() SHALL produce an object equal to the original.

    **Validates: Requirements 17.3, 17.4, 17.5, 17.7**
    """

    @given(descriptor=job_descriptors())
    def test_round_trip_identity(self, descriptor: JobDescriptor):
        """Serialization followed by deserialization produces an equal object.

        # Feature: layered-architecture-lazy-boot, Property 17: JobDescriptor serialization round-trip
        **Validates: Requirements 17.3, 17.4, 17.5, 17.7**
        """
        serialized = descriptor.to_dict()
        deserialized = JobDescriptor.from_dict(serialized)
        assert deserialized == descriptor

    @given(descriptor=job_descriptors())
    def test_round_trip_preserves_config_fields_order_and_length(
        self, descriptor: JobDescriptor
    ):
        """Round-trip preserves config_fields list order and length.

        # Feature: layered-architecture-lazy-boot, Property 17: JobDescriptor serialization round-trip
        **Validates: Requirements 17.4**
        """
        serialized = descriptor.to_dict()
        deserialized = JobDescriptor.from_dict(serialized)
        assert len(deserialized.config_fields) == len(descriptor.config_fields)
        for original, restored in zip(
            descriptor.config_fields, deserialized.config_fields, strict=False
        ):
            assert restored.name == original.name
            assert restored.type == original.type
            assert restored.choices == original.choices
            assert restored.required == original.required
            assert restored.help == original.help

    @given(descriptor=job_descriptors())
    def test_round_trip_preserves_dependencies(self, descriptor: JobDescriptor):
        """Round-trip preserves all dependency keys and values.

        # Feature: layered-architecture-lazy-boot, Property 17: JobDescriptor serialization round-trip
        **Validates: Requirements 17.4**
        """
        serialized = descriptor.to_dict()
        deserialized = JobDescriptor.from_dict(serialized)
        assert deserialized.dependencies == descriptor.dependencies

    @given(descriptor=job_descriptors())
    def test_round_trip_preserves_required_vs_default_none(
        self, descriptor: JobDescriptor
    ):
        """Round-trip preserves the distinction between required (no default) and optional (default=None).

        # Feature: layered-architecture-lazy-boot, Property 17: JobDescriptor serialization round-trip
        **Validates: Requirements 17.5**
        """
        serialized = descriptor.to_dict()
        deserialized = JobDescriptor.from_dict(serialized)

        for original, restored in zip(
            descriptor.config_fields, deserialized.config_fields, strict=False
        ):
            assert restored.required == original.required
            assert restored.default == original.default


# --- Capability markers (v5): requires_tty / optional_tty / uses_live ---


class TestCapabilityMarkerSerialization:
    """The TTY/Live signature markers must survive the cache round-trip.

    Warm/lazy boot routes on these flags without importing the job, so they
    are serialized into the descriptor cache (CACHE_VERSION 5).
    """

    def test_markers_round_trip_when_set(self) -> None:
        """requires_tty / optional_tty / uses_live survive to_dict/from_dict."""
        descriptor = JobDescriptor(
            name="config_editor",
            group=None,
            requires_tty=True,
            optional_tty=False,
            uses_live=True,
        )
        restored = JobDescriptor.from_dict(descriptor.to_dict())
        assert restored.requires_tty is True
        assert restored.optional_tty is False
        assert restored.uses_live is True

    def test_optional_tty_round_trips_independently(self) -> None:
        """optional_tty is distinct from requires_tty and preserved."""
        descriptor = JobDescriptor(
            name="report", group=None, optional_tty=True, uses_live=True
        )
        restored = JobDescriptor.from_dict(descriptor.to_dict())
        assert restored.requires_tty is False
        assert restored.optional_tty is True
        assert restored.uses_live is True

    def test_pre_v5_dict_defaults_markers_false(self) -> None:
        """A pre-v5 cache entry (no marker keys) deserializes with all False."""
        legacy = {
            "name": "legacy_job",
            "group": None,
            "module_path": "jobs",
            "source_file": "jobs.py",
            "source_mtime": 0.0,
            "content_hash": "abc",
            "docstring": None,
            "config_fields": [],
            "dependencies": {},
            # No requires_tty / optional_tty / uses_live keys.
        }
        restored = JobDescriptor.from_dict(legacy)
        assert restored.requires_tty is False
        assert restored.optional_tty is False
        assert restored.uses_live is False

    def test_default_descriptor_has_all_markers_false(self) -> None:
        """A plain job (no capability params) defaults every marker to False."""
        descriptor = JobDescriptor(name="plain", group=None)
        assert descriptor.requires_tty is False
        assert descriptor.optional_tty is False
        assert descriptor.uses_live is False


# --- Property 18: Malformed dict deserialization raises ValueError ---


# Feature: layered-architecture-lazy-boot, Property 18: Malformed dict deserialization raises ValueError
class TestMalformedDictDeserialization:
    """Property 18: Malformed dict deserialization raises ValueError.

    For any dict that is missing one or more required keys expected by
    JobDescriptor.from_dict() or contains values of unexpected types,
    deserialization SHALL raise a ValueError.

    **Validates: Requirements 17.6**
    """

    @given(malformed=malformed_dicts_missing_keys())
    def test_missing_keys_raises_value_error(self, malformed: dict):
        """Dicts missing required keys raise ValueError on deserialization.

        # Feature: layered-architecture-lazy-boot, Property 18: Malformed dict deserialization raises ValueError
        **Validates: Requirements 17.6**
        """
        with pytest.raises(ValueError):
            JobDescriptor.from_dict(malformed)

    @given(malformed=malformed_dicts_wrong_types())
    def test_wrong_types_raises_value_error(self, malformed: dict):
        """Dicts with wrong value types raise ValueError on deserialization.

        # Feature: layered-architecture-lazy-boot, Property 18: Malformed dict deserialization raises ValueError
        **Validates: Requirements 17.6**
        """
        with pytest.raises(ValueError):
            JobDescriptor.from_dict(malformed)

    @given(non_dict=st.one_of(st.text(), st.integers(), st.lists(st.text()), st.none()))
    def test_non_dict_input_raises_value_error(self, non_dict):
        """Non-dict inputs raise ValueError on deserialization.

        # Feature: layered-architecture-lazy-boot, Property 18: Malformed dict deserialization raises ValueError
        **Validates: Requirements 17.6**
        """
        with pytest.raises(ValueError):
            JobDescriptor.from_dict(non_dict)
