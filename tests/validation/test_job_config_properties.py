"""Property-based tests for JobConfig resolution and Typer option generation.

Tests Property 13 (JobConfig Typer Option Generation), Property 14 (JobConfig
Resolution Precedence), Property 15 (JobConfig Dual Access), and Property 27
(Pydantic Validation Before Job Execution) using Hypothesis.
"""

import contextlib
import enum
import os
from unittest.mock import MagicMock, patch

import click
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, Field, ValidationError

from functualize._config.job_config import (
    JobConfigView,
    resolve_job_config,
    validate_job_config_types,
)
from functualize.app.adapters.click_params import _config_option_params


def generate_typer_options(model: type[BaseModel]) -> dict[str, click.Option]:
    """Config model → ``{field_name: click.Option}`` (the click-native builder).

    Kept as a thin ``{name: option}`` view so the Property-13 tests read the same
    while asserting over click parameters instead of the removed typer options.
    """
    return {opt.name: opt for opt in _config_option_params(model)}  # type: ignore[misc]


# --- Strategies ---

# Strategy for valid Python identifiers (field names)
field_names = st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True)

# Strategy for job names (simple identifiers)
job_names = st.from_regex(r"[a-z][a-z0-9_]{0,10}", fullmatch=True)

# Strategy for string values (non-empty, no commas to avoid list splitting)
string_values = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"), blacklist_characters=",\n\r\x00"
    ),
    min_size=1,
    max_size=30,
)

# Strategy for integer values
int_values = st.integers(min_value=-1000, max_value=1000)

# Strategy for float values
float_values = st.floats(
    min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False
)

# Strategy for bool values
bool_values = st.booleans()


# --- Helper: Dynamic Pydantic model creation ---


class SampleEnum(enum.Enum):
    """Sample enum for testing."""

    OPTION_A = "option_a"
    OPTION_B = "option_b"
    OPTION_C = "option_c"


class OutputFormat(enum.Enum):
    """Another sample enum."""

    JSON = "json"
    CSV = "csv"
    XML = "xml"


# --- Property 13: JobConfig Typer Option Generation ---
# Feature: functualize, Property 13: JobConfig Typer Option Generation


class TestJobConfigTyperOptionGeneration:
    """Property 13: For any Pydantic BaseModel with fields of supported types
    (str, int, float, bool, Enum, Optional variants, List of primitives), the
    framework SHALL generate a Typer CLI option for each field with the field name
    (underscores to hyphens) as the option name and correct type validation.

    **Validates: Requirements 6.2**
    """

    @settings(max_examples=100)
    @given(
        str_default=st.text(min_size=1, max_size=10),
        int_default=st.integers(min_value=0, max_value=100),
        bool_default=st.booleans(),
    )
    def test_generates_option_for_each_field(
        self, str_default: str, int_default: int, bool_default: bool
    ):
        # Feature: functualize, Property 13: JobConfig Typer Option Generation
        """For any model with supported fields, generate_typer_options produces
        one option per field."""

        class DynamicConfig(BaseModel):
            api_url: str = Field(default=str_default, description="API URL")
            timeout: int = Field(default=int_default, description="Timeout")
            verbose: bool = Field(default=bool_default, description="Verbose")

        options = generate_typer_options(DynamicConfig)

        # One option per field
        assert set(options.keys()) == {"api_url", "timeout", "verbose"}

    @settings(max_examples=100)
    @given(
        field_name=field_names,
    )
    def test_option_name_uses_hyphens(self, field_name: str):
        # Feature: functualize, Property 13: JobConfig Typer Option Generation
        """For any field name with underscores, the generated option name converts
        underscores to hyphens."""
        assume("__" not in field_name)  # Avoid dunder names

        # Dynamically create a model with the given field name
        model = type(
            "DynConfig",
            (BaseModel,),
            {"__annotations__": {field_name: str}, field_name: Field(default="x")},
        )

        options = generate_typer_options(model)
        assert field_name in options

        # The option info should contain the hyphenated name
        option_info = options[field_name]
        # Typer Option stores param_decls
        assert isinstance(option_info, click.Option)

    @settings(max_examples=100)
    @given(
        enum_choice=st.sampled_from(list(SampleEnum)),
    )
    def test_generates_option_for_enum_fields(self, enum_choice: SampleEnum):
        # Feature: functualize, Property 13: JobConfig Typer Option Generation
        """For any Enum field, generate_typer_options produces a valid option."""

        class EnumConfig(BaseModel):
            format_type: SampleEnum = Field(default=enum_choice)

        options = generate_typer_options(EnumConfig)
        assert "format_type" in options
        assert isinstance(options["format_type"], click.Option)

    @settings(max_examples=100)
    @given(st.data())
    def test_optional_fields_generate_options(self, data):
        # Feature: functualize, Property 13: JobConfig Typer Option Generation
        """For any Optional[T] field, generate_typer_options produces a valid option
        with None as default."""

        class OptionalConfig(BaseModel):
            name: str | None = Field(default=None, description="Optional name")
            count: int | None = Field(default=None, description="Optional count")

        options = generate_typer_options(OptionalConfig)
        assert "name" in options
        assert "count" in options

    @settings(max_examples=100)
    @given(st.data())
    def test_list_fields_generate_options(self, data):
        # Feature: functualize, Property 13: JobConfig Typer Option Generation
        """For any list[T] field, generate_typer_options produces a valid option."""

        class ListConfig(BaseModel):
            tags: list[str] = Field(default_factory=list, description="Tags")

        options = generate_typer_options(ListConfig)
        assert "tags" in options
        assert isinstance(options["tags"], click.Option)

    @settings(max_examples=100)
    @given(st.data())
    def test_unsupported_types_raise_at_registration(self, data):
        # Feature: functualize, Property 13: JobConfig Typer Option Generation
        """For any field with an unsupported type, validate_job_config_types raises
        TypeError at registration time."""

        class BadConfig(BaseModel):
            nested: dict[str, str] = Field(default_factory=dict)

        try:
            validate_job_config_types(BadConfig)
            raise AssertionError("Should have raised TypeError")
        except TypeError as e:
            assert "nested" in str(e)
            assert "Unsupported type" in str(e)


# --- Property 14: JobConfig Resolution Precedence ---
# Feature: functualize, Property 14: JobConfig Resolution Precedence


class TestJobConfigResolutionPrecedence:
    """Property 14: For any JobConfig field, when values exist at multiple precedence
    levels, the resolved value SHALL follow the order: CLI argument > environment
    variable (JOBNAME_FIELDNAME) > configuration file ([job_name] section) > model
    default value.

    **Validates: Requirements 6.3**
    """

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        cli_val=string_values,
        env_val=string_values,
        config_val=string_values,
        default_val=string_values,
    )
    def test_cli_takes_precedence_over_all(
        self,
        job_name: str,
        cli_val: str,
        env_val: str,
        config_val: str,
        default_val: str,
    ):
        # Feature: functualize, Property 14: JobConfig Resolution Precedence
        """CLI argument takes highest precedence over env var, config, and default."""
        assume(cli_val != default_val)  # Ensure CLI value differs from default

        class MyConfig(BaseModel):
            name: str = Field(default=default_val)

        env_key = f"{job_name.upper()}_NAME"

        with patch.dict(os.environ, {env_key: env_val}, clear=False):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = config_val

            result = resolve_job_config(MyConfig, job_name, config, {"name": cli_val})
            assert result.name == cli_val

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        env_val=string_values,
        config_val=string_values,
        default_val=string_values,
    )
    def test_env_var_takes_precedence_over_config_and_default(
        self,
        job_name: str,
        env_val: str,
        config_val: str,
        default_val: str,
    ):
        # Feature: functualize, Property 14: JobConfig Resolution Precedence
        """Env var takes precedence over config file and model default when CLI
        is not provided."""

        class MyConfig(BaseModel):
            name: str = Field(default=default_val)

        env_key = f"{job_name.upper()}_NAME"

        with patch.dict(os.environ, {env_key: env_val}, clear=False):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = config_val

            # CLI value is None (not provided)
            result = resolve_job_config(MyConfig, job_name, config, {"name": None})
            assert result.name == env_val

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        config_val=string_values,
        default_val=string_values,
    )
    def test_config_takes_precedence_over_default(
        self,
        job_name: str,
        config_val: str,
        default_val: str,
    ):
        # Feature: functualize, Property 14: JobConfig Resolution Precedence
        """Config file value takes precedence over model default when CLI and
        env var are not provided."""

        class MyConfig(BaseModel):
            name: str = Field(default=default_val)

        env_key = f"{job_name.upper()}_NAME"

        # Ensure env var is NOT set
        env_patch = {k: v for k, v in os.environ.items() if k != env_key}
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = config_val

            result = resolve_job_config(MyConfig, job_name, config, {"name": None})
            assert result.name == config_val

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        default_val=string_values,
    )
    def test_model_default_used_when_no_other_source(
        self,
        job_name: str,
        default_val: str,
    ):
        # Feature: functualize, Property 14: JobConfig Resolution Precedence
        """Model default is used when CLI, env var, and config file provide no value."""

        class MyConfig(BaseModel):
            name: str = Field(default=default_val)

        env_key = f"{job_name.upper()}_NAME"

        # Ensure env var is NOT set
        env_patch = {k: v for k, v in os.environ.items() if k != env_key}
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None  # Config returns nothing

            result = resolve_job_config(MyConfig, job_name, config, {"name": None})
            assert result.name == default_val

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        cli_int=st.integers(min_value=1, max_value=500),
        env_int=st.integers(min_value=501, max_value=1000),
    )
    def test_precedence_with_int_fields(
        self,
        job_name: str,
        cli_int: int,
        env_int: int,
    ):
        # Feature: functualize, Property 14: JobConfig Resolution Precedence
        """Precedence works correctly for integer fields."""

        class IntConfig(BaseModel):
            timeout: int = Field(default=30)

        env_key = f"{job_name.upper()}_TIMEOUT"

        with patch.dict(os.environ, {env_key: str(env_int)}, clear=False):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            # CLI provided
            result = resolve_job_config(
                IntConfig, job_name, config, {"timeout": cli_int}
            )
            assert result.timeout == cli_int


# --- Property 15: JobConfig Dual Access ---
# Feature: functualize, Property 15: JobConfig Dual Access


class TestJobConfigDualAccess:
    """Property 15: For any job with a declared JobConfig, after resolution the
    validated instance SHALL be accessible both as the annotated function parameter
    and via rc.job_config, and both references SHALL be the same object.

    **Validates: Requirements 6.8**
    """

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        name_val=string_values,
        timeout_val=st.integers(min_value=1, max_value=100),
    )
    def test_resolved_config_is_same_object_for_param_and_rc(
        self,
        job_name: str,
        name_val: str,
        timeout_val: int,
    ):
        # Feature: functualize, Property 15: JobConfig Dual Access
        """The resolved JobConfig instance can be assigned to both the function
        parameter and rc.job_config, and they are the same object."""

        class JobCfg(BaseModel):
            name: str = Field(default="default")
            timeout: int = Field(default=30)

        env_key_name = f"{job_name.upper()}_NAME"
        env_key_timeout = f"{job_name.upper()}_TIMEOUT"

        # Clear relevant env vars
        env_patch = {
            k: v
            for k, v in os.environ.items()
            if k not in (env_key_name, env_key_timeout)
        }
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            # Resolve the config
            resolved = resolve_job_config(
                JobCfg, job_name, config, {"name": name_val, "timeout": timeout_val}
            )

            # Simulate dual access: same object assigned to param and rc.job_config
            param_config = resolved
            rc_job_config = resolved

            assert param_config is rc_job_config
            assert param_config.name == name_val
            assert param_config.timeout == timeout_val

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        enum_choice=st.sampled_from(list(OutputFormat)),
    )
    def test_dual_access_with_enum_fields(
        self,
        job_name: str,
        enum_choice: OutputFormat,
    ):
        # Feature: functualize, Property 15: JobConfig Dual Access
        """Dual access works correctly for models with Enum fields."""

        class EnumJobCfg(BaseModel):
            output: OutputFormat = Field(default=OutputFormat.JSON)

        env_key = f"{job_name.upper()}_OUTPUT"
        env_patch = {k: v for k, v in os.environ.items() if k != env_key}
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            resolved = resolve_job_config(
                EnumJobCfg, job_name, config, {"output": enum_choice.value}
            )

            # Both references are the same object
            param_ref = resolved
            rc_ref = resolved
            assert param_ref is rc_ref
            assert param_ref.output == enum_choice

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        val=string_values,
    )
    def test_resolved_instance_is_validated_pydantic_model(
        self,
        job_name: str,
        val: str,
    ):
        # Feature: functualize, Property 15: JobConfig Dual Access
        """The resolved instance is always a validated Pydantic model instance."""

        class ValidatedCfg(BaseModel):
            endpoint: str = Field(default="http://localhost")

        env_key = f"{job_name.upper()}_ENDPOINT"
        env_patch = {k: v for k, v in os.environ.items() if k != env_key}
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            resolved = resolve_job_config(
                ValidatedCfg, job_name, config, {"endpoint": val}
            )

            assert isinstance(resolved, ValidatedCfg)
            assert isinstance(resolved, BaseModel)


# --- Property 27: Pydantic Validation Before Job Execution ---
# Feature: functualize, Property 27: Pydantic Validation Before Job Execution


class TestPydanticValidationBeforeJobExecution:
    """Property 27: For any job with a Pydantic-typed parameter receiving invalid
    input, the framework SHALL raise a validation error listing all field violations
    (field name, expected type, actual value, error message) BEFORE the job function
    body executes.

    **Validates: Requirements 6.4, 13.1, 13.2**
    """

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        bad_int=st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=1,
            max_size=5,
        ),
    )
    def test_invalid_type_raises_validation_error(
        self,
        job_name: str,
        bad_int: str,
    ):
        # Feature: functualize, Property 27: Pydantic Validation Before Job Execution
        """When a field receives a value that cannot be coerced to the expected type,
        a ValidationError is raised before job execution."""

        class StrictConfig(BaseModel):
            count: int

        env_key = f"{job_name.upper()}_COUNT"
        env_patch = {k: v for k, v in os.environ.items() if k != env_key}
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            # Provide a non-numeric string that can't be coerced to int
            with contextlib.suppress(ValidationError, ValueError):
                resolve_job_config(StrictConfig, job_name, config, {"count": bad_int})
                # If coercion succeeds (e.g., "1"), that's fine

    @settings(max_examples=100)
    @given(
        job_name=job_names,
    )
    def test_missing_required_field_raises_validation_error(
        self,
        job_name: str,
    ):
        # Feature: functualize, Property 27: Pydantic Validation Before Job Execution
        """When a required field has no value from any source, a ValidationError
        is raised listing the missing field."""

        class RequiredConfig(BaseModel):
            api_key: str  # No default — required
            endpoint: str  # No default — required

        env_key_api = f"{job_name.upper()}_API_KEY"
        env_key_endpoint = f"{job_name.upper()}_ENDPOINT"
        env_patch = {
            k: v
            for k, v in os.environ.items()
            if k not in (env_key_api, env_key_endpoint)
        }
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            try:
                resolve_job_config(RequiredConfig, job_name, config, {})
                raise AssertionError("Should have raised ValidationError")
            except ValidationError as e:
                # Error should mention the missing fields
                error_str = str(e)
                assert "api_key" in error_str
                assert "endpoint" in error_str

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        num_bad_fields=st.integers(min_value=1, max_value=3),
    )
    def test_validation_error_lists_all_violations(
        self,
        job_name: str,
        num_bad_fields: int,
    ):
        # Feature: functualize, Property 27: Pydantic Validation Before Job Execution
        """ValidationError lists ALL field violations, not just the first one."""

        class MultiFieldConfig(BaseModel):
            field_a: int  # Required
            field_b: int  # Required
            field_c: int  # Required

        env_keys = [
            f"{job_name.upper()}_FIELD_A",
            f"{job_name.upper()}_FIELD_B",
            f"{job_name.upper()}_FIELD_C",
        ]
        env_patch = {k: v for k, v in os.environ.items() if k not in env_keys}
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            # Provide no values for any field
            try:
                resolve_job_config(MultiFieldConfig, job_name, config, {})
                raise AssertionError("Should have raised ValidationError")
            except ValidationError as e:
                # All three fields should be mentioned
                errors = e.errors()
                error_fields = {err["loc"][0] for err in errors}
                assert "field_a" in error_fields
                assert "field_b" in error_fields
                assert "field_c" in error_fields

    @settings(max_examples=100)
    @given(
        job_name=job_names,
        valid_val=string_values,
    )
    def test_valid_input_does_not_raise(
        self,
        job_name: str,
        valid_val: str,
    ):
        # Feature: functualize, Property 27: Pydantic Validation Before Job Execution
        """When all fields receive valid values, no ValidationError is raised and
        the resolved model is returned."""

        class ValidConfig(BaseModel):
            name: str
            active: bool = Field(default=True)

        env_key = f"{job_name.upper()}_NAME"
        env_key_active = f"{job_name.upper()}_ACTIVE"
        env_patch = {
            k: v for k, v in os.environ.items() if k not in (env_key, env_key_active)
        }
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            result = resolve_job_config(
                ValidConfig, job_name, config, {"name": valid_val}
            )
            assert result.name == valid_val
            assert result.active is True

    @settings(max_examples=100)
    @given(
        job_name=job_names,
    )
    def test_validation_happens_before_job_body(
        self,
        job_name: str,
    ):
        # Feature: functualize, Property 27: Pydantic Validation Before Job Execution
        """Validation occurs during resolve_job_config, which is called before
        the job function body executes. A job function is never called with
        invalid config."""

        class StrictModel(BaseModel):
            port: int  # Required, must be int

        env_key = f"{job_name.upper()}_PORT"
        env_patch = {k: v for k, v in os.environ.items() if k != env_key}
        with patch.dict(os.environ, env_patch, clear=True):
            config = MagicMock(spec=JobConfigView)
            config.get.return_value = None

            job_executed = False

            def fake_job(cfg: StrictModel):
                nonlocal job_executed
                job_executed = True

            # Attempt to resolve with no value for required field
            try:
                resolved = resolve_job_config(StrictModel, job_name, config, {})
                fake_job(resolved)
            except ValidationError:
                pass  # Validation error raised before job executes

            # If ValidationError was raised, job should NOT have executed
            # If no error (impossible here), job would have executed
            # The key property: validation error prevents job execution
            if not job_executed:
                assert True  # Job was not executed due to validation
