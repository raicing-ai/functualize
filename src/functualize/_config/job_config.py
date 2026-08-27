"""JobConfigView — scoped, read-write config access for job execution.

Wraps ResolutionChain with per-instance overrides. Provides the same
get/set/get_model/set_prefix API surface that job developers use through
RunContext.config.

Also includes validation utilities for job configuration types.

Only imports from `_types/`, `_primitives/`, `_events/`, and Python stdlib.
"""

from __future__ import annotations

import enum
import types
from typing import TYPE_CHECKING, Any, TypeVar, Union, get_args, get_origin

from functualize._config.errors import MissingKeyError

if TYPE_CHECKING:
    from functualize._config.chain import ResolutionChain

T = TypeVar("T")

# Base types supported for config validation and coercion
SUPPORTED_TYPES = (str, int, float, bool)


def _env_token(section: str, key: str) -> str:
    """Build the ``SECTION_KEY`` token used for env and override lookup.

    Hyphens become underscores because environment variable names cannot
    contain them. Job names are canonical (``env-cfg``), so without this the
    token would be ``ENV-CFG_API_URL`` and the documented ``ENV_CFG_API_URL``
    would never match — the value would silently fall through to the default,
    which is the worst way for configuration to fail.
    """
    return f"{section.upper().replace('-', '_')}_{key.upper()}"


class JobConfigView:
    """Scoped, read-write config access for job execution.

    Wraps ResolutionChain (parse-once, shared) with:
    - A section prefix (scoped to job name)
    - An in-memory override layer for programmatic set()
    - Same get/set/get_model API that RunContext.config exposed
    """

    def __init__(
        self,
        resolution_chain: ResolutionChain,
        default_section_prefix: str = "general",
    ) -> None:
        """Initialize with shared resolution chain and optional prefix.

        Args:
            resolution_chain: The app's ResolutionChain (shared, read-only).
            default_section_prefix: Initial section prefix for key lookups.
        """
        self._chain = resolution_chain
        self._default_section_prefix = default_section_prefix
        self._overrides: dict[str, Any] = {}

    def get(
        self,
        key: str,
        default: Any = None,
        section: str | None = None,
    ) -> Any:
        """Retrieve a configuration value.

        Resolution priority:
        1. In-memory overrides (from set())
        2. ResolutionChain (env vars → file sources → defaults)
        3. Caller-provided default parameter

        This method never raises — it always returns a value or None.

        Args:
            key: The configuration key.
            default: Fallback value if key not found anywhere.
            section: Section override. None uses default_section_prefix.

        Returns:
            Resolved value or default.
        """
        effective_section = (
            section if section is not None else self._default_section_prefix
        )
        combined_key = _env_token(effective_section, key)

        # Step 1: Check in-memory overrides
        if combined_key in self._overrides:
            return self._overrides[combined_key]

        # Step 2-3: Delegate to ResolutionChain
        try:
            resolved = self._chain.resolve(key, effective_section)
            return resolved.value
        except MissingKeyError:
            return default

    def set(
        self,
        key: str,
        value: Any,
        section: str | None = None,
    ) -> None:
        """Store a value in the in-memory override layer.

        Does NOT write to disk. Override persists for this instance's lifetime.

        Args:
            key: The configuration key.
            value: The value to store.
            section: Section override. None uses default_section_prefix.
        """
        effective_section = (
            section if section is not None else self._default_section_prefix
        )
        combined_key = _env_token(effective_section, key)
        self._overrides[combined_key] = value

    def get_model(
        self,
        model_class: type[T],
        section: str | None = None,
    ) -> T:
        """Resolve a Pydantic model from configuration values.

        For each field in the model, resolves the value using the same
        priority as get(). Passes collected values to Pydantic for validation.

        Args:
            model_class: Pydantic BaseModel subclass.
            section: Section override. None uses default_section_prefix.

        Returns:
            Validated model instance.

        Raises:
            pydantic.ValidationError: If values don't satisfy model schema.
        """
        effective_section = (
            section if section is not None else self._default_section_prefix
        )

        data: dict[str, Any] = {}

        # Use model_fields if available (Pydantic v2), fallback for duck typing
        fields = getattr(model_class, "model_fields", {})
        for field_name in fields:
            value = self.get(field_name, default=None, section=effective_section)
            if value is not None:
                data[field_name] = value

        return model_class(**data)

    def set_prefix(self, prefix: str) -> None:
        """Update the default section prefix.

        Called by RunContext.__init__ to scope lookups to the job name.

        Args:
            prefix: New default section prefix.
        """
        self._default_section_prefix = prefix


# =============================================================================
# Type validation utilities for job configuration
# =============================================================================


def _get_field_type(field_info: Any) -> Any:
    """Extract the type annotation from a Pydantic field info object.

    Handles both Pydantic v1 and v2 field info objects.
    """
    # Pydantic v2
    if hasattr(field_info, "annotation"):
        return field_info.annotation
    # Pydantic v1 fallback
    if hasattr(field_info, "outer_type_"):
        return field_info.outer_type_
    return type(None)


def _is_enum_subclass(tp: Any) -> bool:
    """Check if a type is an Enum subclass (but not Enum itself)."""
    return isinstance(tp, type) and issubclass(tp, enum.Enum) and tp is not enum.Enum


def _unwrap_optional(tp: Any) -> tuple[Any, bool]:
    """Unwrap Optional[T] to (T, True) or return (tp, False) if not Optional."""
    origin = get_origin(tp)
    args = get_args(tp)

    # Handle Union types (Optional[T] is Union[T, None])
    if origin is Union or origin is types.UnionType:
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1 and type(None) in args:
            return non_none_args[0], True

    return tp, False


def _unwrap_list(tp: Any) -> tuple[Any, bool]:
    """Unwrap list[T] to (T, True) or return (tp, False) if not a list type."""
    origin = get_origin(tp)
    if origin is list:
        args = get_args(tp)
        if args:
            return args[0], True
    return tp, False


def _unwrap_secret(tp: Any) -> tuple[Any, bool]:
    """Unwrap ``Secret[T]`` to ``(T, True)``, or ``Secret`` to ``(str, True)``.

    ``Secret`` carries a string, so the *supported-type* question is about what
    it wraps. Without this the type gate rejects the framework's own public
    secret type — a second, independent refusal sitting behind Pydantic's, so
    giving ``Secret`` a core schema alone is not enough to make it usable.
    """
    from functualize._types.redaction import Secret

    if tp is Secret:
        return str, True
    if get_origin(tp) is Secret:
        args = get_args(tp)
        return (args[0] if args else str), True
    return tp, False


def _is_supported_type(tp: Any) -> bool:
    """Check if a type is supported for configuration.

    Supported types:
    - str, int, float, bool
    - Enum subclasses
    - Optional[T] where T is a supported type
    - list[T] where T is a supported base type or Enum
    """
    if tp in SUPPORTED_TYPES:
        return True

    if _is_enum_subclass(tp):
        return True

    inner, is_secret = _unwrap_secret(tp)
    if is_secret:
        return _is_supported_type(inner)

    inner, is_optional = _unwrap_optional(tp)
    if is_optional:
        return _is_supported_type(inner)

    inner, is_list = _unwrap_list(tp)
    if is_list:
        return inner in SUPPORTED_TYPES or _is_enum_subclass(inner)

    return False


def validate_config_types(config_class: type) -> None:
    """Validate that all fields in a config model have supported types.

    Raises TypeError at registration time for unsupported field types.

    Args:
        config_class: A Pydantic model class to validate.

    Raises:
        TypeError: If any field has an unsupported type.
    """
    model_fields = getattr(config_class, "model_fields", {})
    for field_name, field_info in model_fields.items():
        field_type = getattr(field_info, "annotation", None)
        if field_type is not None and not _is_supported_type(field_type):
            raise TypeError(
                f"Unsupported type for field '{field_name}': {field_type}. "
                f"Supported types are: str, int, float, bool, Enum subclasses, "
                f"Optional[T] for supported T, and list[T] for supported T."
            )


def coerce_value(value: Any, target_type: Any) -> Any:
    """Coerce a value to the target type.

    Handles string-to-type conversion for values from env vars and config files.

    Args:
        value: The value to coerce (typically a string from external sources).
        target_type: The target Python type annotation.

    Returns:
        The coerced value.
    """
    if value is None:
        return None

    # Unwrap Secret[T]: coerce to T, then re-wrap. A caller that asked for a
    # secret must get a `Secret` back, not a bare string that happens to hold a
    # credential — the wrapper is what makes it mask in an f-string.
    inner_type, is_secret = _unwrap_secret(target_type)
    if is_secret:
        from functualize._types.redaction import Secret

        if isinstance(value, Secret):
            return value
        return Secret(coerce_value(value, inner_type))

    # Unwrap Optional
    inner_type, is_optional = _unwrap_optional(target_type)
    if is_optional:
        if value == "" or value is None:
            return None
        target_type = inner_type

    # Unwrap list
    inner_type, is_list = _unwrap_list(target_type)
    if is_list:
        if isinstance(value, list):
            return [coerce_value(v, inner_type) for v in value]
        if isinstance(value, str):
            items = [v.strip() for v in value.split(",") if v.strip()]
            return [coerce_value(v, inner_type) for v in items]
        return value

    # Handle Enum
    if _is_enum_subclass(target_type):
        if isinstance(value, target_type):
            return value
        for member in target_type:
            if str(member.value) == str(value):
                return member
        for member in target_type:
            if member.name.lower() == str(value).lower():
                return member
        return value

    # Handle bool (special case: string "true"/"false")
    if target_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)

    # Handle basic types
    if target_type in (str, int, float):
        if isinstance(value, target_type):
            return value
        return target_type(value)

    return value


def validate_job_config_types(job_config_class: type) -> None:
    """Validate that all fields in a JobConfig model have supported types.

    Raises TypeError at registration time for unsupported field types.

    Args:
        job_config_class: The Pydantic model class to validate.

    Raises:
        TypeError: If any field has an unsupported type.
    """
    from pydantic import BaseModel

    if not (
        isinstance(job_config_class, type) and issubclass(job_config_class, BaseModel)
    ):
        return

    import enum
    import types as _types
    from typing import Union, get_args, get_origin

    def _is_enum(tp: Any) -> bool:
        return (
            isinstance(tp, type) and issubclass(tp, enum.Enum) and tp is not enum.Enum
        )

    def _unwrap_optional(tp: Any) -> tuple[Any, bool]:
        origin = get_origin(tp)
        args = get_args(tp)
        if origin is Union or origin is _types.UnionType:
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1 and type(None) in args:
                return non_none[0], True
        return tp, False

    def _unwrap_list(tp: Any) -> tuple[Any, bool]:
        if get_origin(tp) is list:
            args = get_args(tp)
            if args:
                return args[0], True
        return tp, False

    def _is_supported(tp: Any) -> bool:
        if tp in SUPPORTED_TYPES:
            return True
        if _is_enum(tp):
            return True
        inner, is_secret = _unwrap_secret(tp)
        if is_secret:
            return _is_supported(inner)
        inner, is_opt = _unwrap_optional(tp)
        if is_opt:
            return _is_supported(inner)
        inner, is_list = _unwrap_list(tp)
        if is_list:
            return inner in SUPPORTED_TYPES or _is_enum(inner)
        return False

    for field_name, field_info in job_config_class.model_fields.items():
        field_type = field_info.annotation
        if not _is_supported(field_type):
            raise TypeError(
                f"Unsupported type for field '{field_name}': {field_type}. "
                f"Supported types are: str, int, float, bool, Enum subclasses, "
                f"Optional[T] for supported T, and list[T] for supported T."
            )


def resolve_job_config(
    config_class: type,
    job_name: str,
    config_view: JobConfigView,
    cli_values: dict[str, Any],
) -> Any:
    """Resolve a Pydantic job config model from CLI, env, config, and defaults.

    Resolution precedence (highest to lowest):
    1. CLI values (non-None values from cli_values dict)
    2. Environment variables — ``JOB_FIELD``, the one supported spelling
    3. Config file values (via config_view)
    4. Model field defaults

    2-4 are all resolved by the chain behind ``config_view``; this function only
    layers CLI on top. There is deliberately no second env lookup here.

    Args:
        config_class: Pydantic model class to instantiate.
        job_name: The job name (used as config section prefix).
        config_view: JobConfigView providing env/file resolution.
        cli_values: Dict of CLI-provided values (None means not provided).

    Returns:
        An instance of config_class populated with resolved values.

    Raises:
        ValidationError: If resolved values don't satisfy model constraints.
    """
    from pydantic import BaseModel

    if not (isinstance(config_class, type) and issubclass(config_class, BaseModel)):
        raise TypeError(f"Expected a Pydantic BaseModel subclass, got {config_class}")

    resolved: dict[str, Any] = {}

    for field_name, _field_info in config_class.model_fields.items():
        # 1. CLI value (if provided and not None)
        cli_val = cli_values.get(field_name)
        if cli_val is not None:
            resolved[field_name] = cli_val
            continue

        # 2-4. Environment (JOB_FIELD), config file, then the model default —
        # all through the resolution chain, which is the only thing that knows
        # the ranking. Two extra env forms used to be read directly from
        # os.environ here, ahead of the chain:
        #
        #   JOB__FIELD  — undocumented, and named only by an error message
        #   FIELD       — undocumented, unprefixed, and therefore captured by
        #                 any ambient shell variable of the same name. A field
        #                 called `user` resolved to $USER and its declared
        #                 default was unreachable; on a field called `token` or
        #                 `password` that is credential substitution.
        #
        # Both outranked the documented JOB_FIELD, so the convention the guide
        # teaches was the last of three to be consulted. Removed outright rather
        # than deprecated: pre-1.0, and `.spec/CONSTITUTION.md` forbids compat
        # shims. See ADR-008 and the 2026-08-27 config/secrets scrutiny (D5/D6).
        config_val = config_view.get(field_name)
        if config_val is not None:
            resolved[field_name] = config_val
            continue

    return config_class(**resolved)
