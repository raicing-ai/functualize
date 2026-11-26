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
from typing import TYPE_CHECKING, Any, Literal, TypeVar, Union, get_args, get_origin

from functualize._config.errors import MissingKeyError

if TYPE_CHECKING:
    from functualize._config.chain import ResolutionChain

T = TypeVar("T")


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
        *,
        scope: Literal["group", "job"] = "job",
    ) -> None:
        """Initialize with shared resolution chain and optional prefix.

        Args:
            resolution_chain: The app's ResolutionChain (shared, read-only).
            default_section_prefix: Initial section prefix for key lookups.
            scope: Whether that prefix names a group or a job. One view, one
                scope: the group path and the job name play the same role in
                a lookup, and the scope is what tells the vault which identity
                to encode and the environment which spelling to read.
        """
        self._chain = resolution_chain
        self._default_section_prefix = default_section_prefix
        self._scope = scope
        self._overrides: dict[str, Any] = {}

    def reject_inline_provider(self, key: str) -> None:
        """Check every parsed file before a stronger source can hide old syntax."""
        for source in self._chain.sources:
            reject = getattr(source, "reject_inline_provider", None)
            if reject is not None:
                reject(self._default_section_prefix, key)

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
            resolved = self._chain.resolve(key, effective_section, scope=self._scope)
            return resolved.value
        except MissingKeyError:
            return default

    def resolve_with_source(
        self,
        key: str,
        section: str | None = None,
    ) -> tuple[str, str, Any] | None:
        """``(source_type, source_id, value)`` for ``key``, or None if unset.

        The provenance-carrying sibling of :meth:`get`, for surfaces that must
        report *where* a value came from as well as what it is. It consults the
        same layers in the same order — overrides first, then the chain — which
        is the whole reason it exists here rather than in the caller: the
        display seam previously reached past this view to
        ``config_view._chain`` and so could not see the override layer at all.
        A value set through :meth:`set` was what the run used and not what any
        surface showed.

        Never raises: an unresolved key is an answer, not an error.
        """
        effective_section = (
            section if section is not None else self._default_section_prefix
        )
        combined_key = _env_token(effective_section, key)

        if combined_key in self._overrides:
            return ("override", "set() at runtime", self._overrides[combined_key])

        try:
            resolved = self._chain.resolve(key, effective_section, scope=self._scope)
        except MissingKeyError:
            return None
        except Exception:
            # Introspection must never mask the real failure a run would report.
            return None
        if resolved is None or resolved.value is None:
            return None
        return (resolved.source_type, resolved.source_id, resolved.value)

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
    """Unwrap ``Secret`` / ``Secret[str]`` to ``(str, True)``, else ``(tp, False)``.

    This helper is used only when coercing an accepted config value. Admission
    of a ``Secret[T]`` declaration is decided by its field contract.
    """
    from functualize._types.redaction import Secret

    if tp is Secret or get_origin(tp) is Secret:
        return str, True
    return tp, False


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


def resolve_job_config(
    config_class: type,
    job_name: str,
    config_view: JobConfigView,
    cli_values: dict[str, Any],
) -> Any:
    """Resolve a Pydantic job config model from CLI, env, config, and defaults.

    Resolution precedence (highest to lowest):
    1. CLI values (non-None values from cli_values dict)
    2. Environment variables — ``JOB_FIELD`` for a job, ``SCOPE__FIELD`` for a
       group option, the spelling ``EnvSource`` builds from the view's scope
    3. Config file values (via config_view)
    4. Model field defaults

    2-4 are all resolved by the chain behind ``config_view``; this function only
    layers CLI on top. There is deliberately no env lookup here at all — not
    for a job, and not for a group option either. The group's ``SCOPE__FIELD``
    used to be read directly from ``os.environ`` before the chain, which put
    the environment *above* the vault for groups and made the two scopes obey
    two different ladders. The view's scope is what tells ``EnvSource`` which
    spelling to build now, so one ladder serves both.

    Args:
        config_class: Pydantic model class to instantiate.
        job_name: The job name (used as config section prefix).
        config_view: JobConfigView providing env/file resolution. A view built
            with ``scope="group"`` resolves a ``GroupOptions`` model.
        cli_values: Dict of CLI-provided values (None means not provided).

    Returns:
        An instance of config_class populated with resolved values.

    Raises:
        ValidationError: If resolved values don't satisfy model constraints.
    """
    from pydantic import BaseModel

    from functualize._types.redaction import is_secret_field

    if not (isinstance(config_class, type) and issubclass(config_class, BaseModel)):
        raise TypeError(f"Expected a Pydantic BaseModel subclass, got {config_class}")

    resolved: dict[str, Any] = {}

    for field_name, field_info in config_class.model_fields.items():
        target_type = getattr(field_info, "annotation", None)
        if is_secret_field(field_info):
            config_view.reject_inline_provider(field_name)

        # 1. CLI value (if provided and not None)
        cli_val = cli_values.get(field_name)
        if not _is_absent_cli_value(cli_val):
            resolved[field_name] = _coerce_for_field(cli_val, target_type)
            continue

        # 2-4. Environment, config file, then the model default — all through
        # the resolution chain, which is the only thing that knows the
        # ranking. Extra env forms used to be read directly from os.environ
        # here, ahead of the chain:
        #
        #   JOB__FIELD  — undocumented, and named only by an error message
        #   FIELD       — undocumented, unprefixed, and therefore captured by
        #                 any ambient shell variable of the same name. A field
        #                 called `user` resolved to $USER and its declared
        #                 default was unreachable; on a field called `token` or
        #                 `password` that is credential substitution.
        #   SCOPE__FIELD (groups) — documented, but reading it here put the
        #                 environment above the vault for group options.
        #
        # All three moved into the chain. Removed outright rather than
        # deprecated: pre-1.0, and `.spec/CONSTITUTION.md` forbids compat
        # shims. See ADR-008.
        config_val = config_view.get(field_name)
        if config_val is not None:
            resolved[field_name] = _coerce_for_field(config_val, target_type)
            continue

    return config_class(**resolved)


def _is_absent_cli_value(value: Any) -> bool:
    """Whether a CLI value means "the user did not pass this".

    ``None`` is the usual answer. The empty tuple is the other one, and it is
    not obvious: a ``list[T]`` field becomes a click option with
    ``multiple=True``, and click hands those ``()`` when the flag is absent —
    ``default=None`` does not apply to a multiple option. ``() is not None``,
    so an unpassed list flag counted as a CLI value and won the whole ladder.
    A ``list[str]`` field therefore resolved to ``[]`` no matter what the
    environment, the config file, or the model default said, and its
    documented comma-separated form could never take effect.

    Nothing is lost by treating it as absent: click cannot express "passed,
    with zero values" for a multiple option, so ``()`` has no other meaning.
    """
    if value is None:
        return True
    return isinstance(value, tuple) and not value


def _coerce_for_field(value: Any, target_type: Any) -> Any:
    """Coerce a resolved value toward its declared type, best-effort.

    Pydantic does the real validation a line later; this runs first for the
    conversions Pydantic will not do, which is what config sources actually
    produce:

    - ``"a,b,c"`` from an environment variable into ``list[str]`` — the form
      ``docs/guides/job-config.md`` documents, which did not work because
      ``coerce_value`` had no production caller at all.
    - a plain string into ``Secret[str]``, so the wrapper is what the job gets.

    Any failure falls back to the raw value. Coercion must not be where a bad
    config value is reported: ``int("banana")`` raises a bare ``ValueError``
    naming nothing, while letting Pydantic see the string produces a
    ``ValidationError`` naming the field, the type and the input.
    """
    if target_type is None:
        return value
    try:
        return coerce_value(value, target_type)
    except Exception:
        return value
