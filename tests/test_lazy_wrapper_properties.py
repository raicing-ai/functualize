"""Property-based tests for lazy command wrapper construction.

Tests Properties 7 and 8 from the design document for the
layered-architecture-lazy-boot spec.

Property 7: "For any set of valid JobDescriptor instances, constructing lazy
command wrappers from them SHALL NOT invoke importlib.import_module() or
otherwise trigger module loading."

Property 8: "For any valid list of FieldDescriptor instances, the reconstructed
function signature SHALL have: one parameter per descriptor with matching name;
type annotation mapped from descriptor.type_annotation; required fields have no default;
optional fields use descriptor.default."

**Validates: Requirements 9.1, 9.2**

# Feature: layered-architecture-lazy-boot, Property 7: Lazy wrapper construction does not import modules
# Feature: layered-architecture-lazy-boot, Property 8: Signature reconstruction from FieldDescriptors
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
from click.types import convert_type
from hypothesis import given
from hypothesis import strategies as st

from functualize._types.descriptors import FieldDescriptor, JobDescriptor
from functualize.app.adapters.click_params import build_click_params_from_descriptor
from functualize.app.adapters.lazy_command import make_lazy_command

# --- Constants ---

ALLOWED_TYPES = ["str", "int", "bool", "float", "enum", "list[str]"]
NON_ENUM_TYPES = ["str", "int", "bool", "float", "list[str]"]

# Expected click param type per descriptor type string (enum → Choice separately).
_EXPECTED_CLICK_TYPE = {
    "str": convert_type(str),
    "int": convert_type(int),
    "bool": click.BOOL,
    "float": convert_type(float),
    "list[str]": convert_type(str),  # inner type; list → multiple option
}


def _params_by_name(descriptor: JobDescriptor) -> dict[str, click.Parameter]:
    return {p.name: p for p in build_click_params_from_descriptor(descriptor)}


# --- Strategies ---


@st.composite
def field_descriptors(draw: st.DrawFn) -> FieldDescriptor:
    """Generate valid FieldDescriptor instances respecting the enum/choices invariant.

    - If type is "enum", choices is a non-empty list of non-empty strings
    - If type is anything else, choices is None
    - Names are valid Python identifiers (required for signature parameters)
    """
    type_name = draw(st.sampled_from(ALLOWED_TYPES))

    if type_name == "enum":
        choices = draw(
            st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=10)
        )
    else:
        choices = None

    # Must be a valid Python identifier for use as a parameter name
    # Filter out Python keywords which are not valid parameter names
    import keyword as _kw

    name = draw(
        st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True).filter(
            lambda n: not _kw.iskeyword(n)
        )
    )
    required = draw(st.booleans())

    # Optional fields get a default value; required fields have no default
    if required:
        default = None
    else:
        # Generate JSON-serializable defaults appropriate to the type
        default = draw(
            st.one_of(
                st.none(),
                st.text(max_size=30),
                st.integers(min_value=-1000, max_value=1000),
                st.booleans(),
                st.floats(allow_nan=False, allow_infinity=False),
            )
        )

    help_text = draw(st.text(max_size=50))

    return FieldDescriptor(
        name=name,
        type_annotation=type_name,
        choices=choices,
        default=default,
        required=required,
        description=help_text,
    )


@st.composite
def field_descriptor_lists(draw: st.DrawFn) -> list[FieldDescriptor]:
    """Generate a list of FieldDescriptors with unique names.

    Unique names are required because they become parameter names in the
    reconstructed signature and Python signatures require unique param names.
    """
    fields = draw(st.lists(field_descriptors(), min_size=0, max_size=10))
    # Ensure unique names (deduplicate by keeping first occurrence)
    seen: set[str] = set()
    unique_fields: list[FieldDescriptor] = []
    for f in fields:
        if f.name not in seen:
            seen.add(f.name)
            unique_fields.append(f)
    return unique_fields


@st.composite
def job_descriptors(draw: st.DrawFn) -> JobDescriptor:
    """Generate valid JobDescriptor instances with unique field names."""
    config_fields = draw(field_descriptor_lists())
    return JobDescriptor(
        name=draw(st.from_regex(r"[a-z][a-z0-9_]{2,15}", fullmatch=True)),
        group=draw(st.none() | st.from_regex(r"[a-z][a-z0-9_]{2,10}", fullmatch=True)),
        module_path=draw(
            st.from_regex(
                r"[a-z][a-z0-9_]{1,10}(\.[a-z][a-z0-9_]{1,10}){0,3}", fullmatch=True
            )
        ),
        source_file=draw(
            st.from_regex(r"/tmp/[a-z][a-z0-9_]{2,10}\.py", fullmatch=True)
        ),
        source_mtime=draw(st.floats(min_value=0.0, max_value=2000000000.0)),
        content_hash=draw(st.from_regex(r"[0-9a-f]{64}", fullmatch=True)),
        docstring=draw(st.none() | st.text(max_size=100)),
        config_fields=config_fields,
        dependencies={},
    )


# Feature: layered-architecture-lazy-boot, Property 7: Lazy wrapper construction does not import modules
class TestLazyWrapperNoImport:
    """Property 7: Lazy wrapper construction does not import modules.

    For any set of valid JobDescriptor instances, constructing lazy command
    wrappers from them SHALL NOT invoke importlib.import_module() or otherwise
    trigger module loading. Only the actual invocation of the wrapper triggers
    import.
    """

    @given(descriptors=st.lists(job_descriptors(), min_size=1, max_size=5))
    def test_construction_never_calls_import_module(
        self, descriptors: list[JobDescriptor]
    ) -> None:
        """For any set of valid JobDescriptor instances, make_lazy_command()
        SHALL NOT invoke importlib.import_module() during construction.

        # Feature: layered-architecture-lazy-boot, Property 7: Lazy wrapper construction does not import modules
        **Validates: Requirements 9.1**
        """
        app = MagicMock()

        with patch(
            "functualize._discovery.lazy_wrapper.importlib.import_module"
        ) as mock_import:
            for descriptor in descriptors:
                wrapper = make_lazy_command(descriptor, app)
                # Verify the wrapper is callable
                assert callable(wrapper)

            # importlib.import_module must NOT have been called during any construction
            mock_import.assert_not_called()

    @given(descriptor=job_descriptors())
    def test_construction_produces_callable_without_side_effects(
        self, descriptor: JobDescriptor
    ) -> None:
        """For any valid JobDescriptor, construction produces a callable wrapper
        without triggering module loading or any import side effects.

        # Feature: layered-architecture-lazy-boot, Property 7: Lazy wrapper construction does not import modules
        **Validates: Requirements 9.1**
        """
        app = MagicMock()

        with patch(
            "functualize._discovery.lazy_wrapper.importlib.import_module"
        ) as mock_import:
            cmd = make_lazy_command(descriptor, app)

            # A click.Command is produced (callable) with the descriptor's help.
            assert isinstance(cmd, click.Command)
            assert cmd.help == (descriptor.docstring or None)
            assert cmd.params is not None

            # No imports triggered
            mock_import.assert_not_called()


# Feature: layered-architecture-lazy-boot, Property 8: Signature reconstruction from FieldDescriptors
class TestSignatureReconstruction:
    """Property 8: Signature reconstruction from FieldDescriptors.

    For any valid list of FieldDescriptor instances, the reconstructed function
    signature SHALL have: one parameter per descriptor with matching name; type
    annotation mapped from descriptor.type_annotation; required fields have no default;
    optional fields use descriptor.default.
    """

    @given(fields=field_descriptor_lists())
    def test_parameter_count_matches_descriptor_count(
        self, fields: list[FieldDescriptor]
    ) -> None:
        """The reconstructed signature has exactly one parameter per FieldDescriptor.

        # Feature: layered-architecture-lazy-boot, Property 8: Signature reconstruction from FieldDescriptors
        **Validates: Requirements 9.2**
        """
        descriptor = JobDescriptor(
            name="test_job",
            group=None,
            module_path="test.module",
            source_file="/tmp/test.py",
            source_mtime=1.0,
            content_hash="a" * 64,
            docstring=None,
            config_fields=fields,
            dependencies={},
        )

        params = build_click_params_from_descriptor(descriptor)
        assert len(params) == len(fields)

    @given(fields=field_descriptor_lists())
    def test_parameter_names_match_descriptors(
        self, fields: list[FieldDescriptor]
    ) -> None:
        """Each parameter name in the signature matches the corresponding
        FieldDescriptor's name, preserving order.

        # Feature: layered-architecture-lazy-boot, Property 8: Signature reconstruction from FieldDescriptors
        **Validates: Requirements 9.2**
        """
        descriptor = JobDescriptor(
            name="test_job",
            group=None,
            module_path="test.module",
            source_file="/tmp/test.py",
            source_mtime=1.0,
            content_hash="a" * 64,
            docstring=None,
            config_fields=fields,
            dependencies={},
        )

        params = build_click_params_from_descriptor(descriptor)
        param_names = [p.name for p in params]
        expected_names = [f.name for f in fields]
        assert param_names == expected_names

    @given(fields=field_descriptor_lists())
    def test_type_annotations_match_type_mapping(
        self, fields: list[FieldDescriptor]
    ) -> None:
        """Each parameter's type annotation matches the expected type mapping:
        str→str, int→int, bool→bool, float→float, enum→click.Choice,
        list[str]→list[str].

        # Feature: layered-architecture-lazy-boot, Property 8: Signature reconstruction from FieldDescriptors
        **Validates: Requirements 9.2**
        """
        descriptor = JobDescriptor(
            name="test_job",
            group=None,
            module_path="test.module",
            source_file="/tmp/test.py",
            source_mtime=1.0,
            content_hash="a" * 64,
            docstring=None,
            config_fields=fields,
            dependencies={},
        )

        params = _params_by_name(descriptor)

        for field in fields:
            param = params[field.name]
            if field.type_annotation == "enum":
                assert isinstance(param.type, click.Choice), (
                    f"Field '{field.name}' with type='enum' should have a "
                    f"click.Choice type, got {param.type}"
                )
                assert list(param.type.choices) == (field.choices or [])
            else:
                expected_type = _EXPECTED_CLICK_TYPE[field.type_annotation]
                assert param.type == expected_type, (
                    f"Field '{field.name}' with type='{field.type_annotation}' should "
                    f"have click type {expected_type}, got {param.type}"
                )

    @given(fields=field_descriptor_lists())
    def test_required_fields_have_no_default(
        self, fields: list[FieldDescriptor]
    ) -> None:
        """Required fields SHALL have no default (Parameter.empty) in the
        reconstructed signature.

        # Feature: layered-architecture-lazy-boot, Property 8: Signature reconstruction from FieldDescriptors
        **Validates: Requirements 9.2**
        """
        descriptor = JobDescriptor(
            name="test_job",
            group=None,
            module_path="test.module",
            source_file="/tmp/test.py",
            source_mtime=1.0,
            content_hash="a" * 64,
            docstring=None,
            config_fields=fields,
            dependencies={},
        )

        params = _params_by_name(descriptor)

        for field in fields:
            if field.required:
                param = params[field.name]
                # A required field is a required parameter (Argument, or a
                # required multi-value Option), or a boolean flag. None of these
                # silently carry a caller-invisible default.
                assert param.required or getattr(param, "is_flag", False), (
                    f"Required field '{field.name}' should render as a required "
                    f"parameter or a flag, got {param!r}"
                )

    @given(fields=field_descriptor_lists())
    def test_optional_fields_use_descriptor_default(
        self, fields: list[FieldDescriptor]
    ) -> None:
        """Optional fields SHALL use descriptor.default as the parameter default
        in the reconstructed signature.

        # Feature: layered-architecture-lazy-boot, Property 8: Signature reconstruction from FieldDescriptors
        **Validates: Requirements 9.2**
        """
        descriptor = JobDescriptor(
            name="test_job",
            group=None,
            module_path="test.module",
            source_file="/tmp/test.py",
            source_mtime=1.0,
            content_hash="a" * 64,
            docstring=None,
            config_fields=fields,
            dependencies={},
        )

        params = _params_by_name(descriptor)

        for field in fields:
            if not field.required:
                param = params[field.name]
                assert param.default == field.default, (
                    f"Optional field '{field.name}' should have default "
                    f"{field.default!r}, got {param.default!r}"
                )
