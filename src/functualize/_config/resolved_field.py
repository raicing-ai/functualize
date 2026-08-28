"""The one answer to "what value will this config field have?".

Four implementations of that question used to coexist: the executor's
``resolve_job_config``, the TUI's ``chain.resolve_section``, ``info --job``'s
``_resolve_field_with_source``, and ``builtin env``'s ``_resolve_env_vars``. They
knew different subsets of the environment conventions and disagreed about
values, so a surface could report ``service-account`` for a field the run would
receive as ``root``. A display that lies at the moment before execution is worse
than no display.

:func:`resolve_job_fields` is that single answer, and every surface reads it.
The dataclass carries three things a bare value cannot:

- ``value is None`` with ``source == "unset"`` distinguishes *genuinely
  unresolved* from ``""`` or ``0``. Every surface previously got this wrong: a
  required credential with no default rendered as ``••• model default``, which
  reads as "configured".
- ``origin`` is the name the resolver actually read (``ACME_API_TOKEN``,
  ``config.prod.toml``). An error or a template naming a variable that sets
  nothing is worse than naming none, so the tool prints what it used.
- ``secret`` travels with the value, so a sink cannot mask the right field and
  print the wrong one.

Only imports from ``_types/``, ``_primitives/``, ``_events/`` and stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from functualize._config.errors import MissingKeyError
from functualize._types.redaction import is_secret_field

if TYPE_CHECKING:
    from functualize._config.job_config import JobConfigView

__all__ = ["ResolvedField", "group_env_name_for", "resolve_job_fields"]

#: ``source`` value meaning "no source provided this, and there is no default".
UNSET = "unset"


@dataclass(frozen=True)
class ResolvedField:
    """One config field, resolved, with the provenance a surface needs."""

    name: str
    value: Any | None
    """The resolved value, or ``None`` when nothing provided one."""

    source: str
    """``cli`` | ``override`` | ``env`` | ``file`` | ``remote`` | ``default`` | ``unset``.

    ``override`` is a value deposited by ``config.set()`` at runtime. It ranks
    where the view ranks it — above every file and environment source — because
    that is where the *run* will find it.
    """

    origin: str
    """Where the value came from — a variable name, a file path, "model default"."""

    env_name: str
    """The variable that *sets* this field, whatever it currently resolves from.

    Distinct from :attr:`origin`, which answers "where did this come from?".
    ``builtin env`` needs the other question — "what do I export?" — and a field
    currently satisfied by its model default still has an env name. Conflating
    the two emitted ``export model default=...``.
    """

    secret: bool
    required: bool

    @property
    def is_set(self) -> bool:
        """Whether any source, default included, provided a value."""
        return self.source != UNSET

    @property
    def is_missing_required(self) -> bool:
        """Required by the model, and nothing supplies it.

        This is the state an operator most needs to see before a long job
        starts, and the one every surface used to render as a default.
        """
        return self.required and not self.is_set


def env_name_for(job_name: str, field_name: str) -> str:
    """The environment variable that sets ``job_name.field_name``.

    ``JOB_FIELD``, upper-cased, with hyphens and dots flattened — the single
    supported spelling, and the same one ``EnvSource._build_env_key`` and
    ``missing_value.env_var_for`` construct. Kept in step with those by
    matching their rule exactly, not by importing across a peer layer.
    """
    token = f"{job_name}_{field_name}" if job_name else field_name
    return token.upper().replace("-", "_").replace(".", "_")


def group_env_name_for(group_scope: str, field_name: str) -> str:
    """The environment variable that sets a **group option** — ``SCOPE__FIELD``.

    Group options keep a double underscore between scope and field
    (``DEPLOY__ENV``, ``DEPLOY_WEB__ENV``) because a nested group path is
    flattened with single underscores: ``DEPLOY_WEB_ENV`` cannot be told apart
    from group ``deploy`` carrying a field named ``web_env``. That ambiguity is
    real for groups and does not arise for a job, which is why job config fields
    use the single ``JOB_FIELD`` form and these do not.

    Two conventions is one more than ideal. It is deliberate: both are
    documented (``docs/guides/group-options.md``), and collapsing group options
    onto ``JOB_FIELD`` would silently change what a second, unrelated feature's
    environment variables are called.
    """
    return f"{group_scope}__{field_name}".upper().replace("-", "_").replace(".", "_")


def resolve_job_fields(
    config_class: type,
    job_name: str,
    config_view: JobConfigView,
    cli_values: dict[str, Any] | None = None,
) -> list[ResolvedField]:
    """Resolve every field of ``config_class`` with its provenance.

    Precedence is CLI, then whatever the resolution chain ranks (env, file,
    remote, default). Never raises for a missing value — an unresolved field
    comes back as ``source="unset"``, so a caller asking "what is missing?" gets
    an answer instead of a ``ValidationError``. Callers that need a validated
    model call ``resolve_job_config``, which layers Pydantic on top of this.
    """
    cli_values = cli_values or {}
    fields: list[ResolvedField] = []

    model_fields = getattr(config_class, "model_fields", {})
    for name, info in model_fields.items():
        secret = is_secret_field(info)
        required = bool(getattr(info, "is_required", lambda: False)())
        env_name = env_name_for(job_name, name)

        cli_val = cli_values.get(name)
        if cli_val is not None:
            fields.append(
                ResolvedField(
                    name=name,
                    env_name=env_name,
                    value=cli_val,
                    source="cli",
                    origin=f"--{name.replace('_', '-')}",
                    secret=secret,
                    required=required,
                )
            )
            continue

        resolved = _chain_resolve(config_view, name, job_name)
        if resolved is not None:
            source_type, source_id, value = resolved
            fields.append(
                ResolvedField(
                    name=name,
                    env_name=env_name,
                    value=_coerce(value, getattr(info, "annotation", None)),
                    source=source_type,
                    origin=_origin_for(source_type, source_id, env_name),
                    secret=secret,
                    required=required,
                )
            )
            continue

        # The resolution chain's DefaultSource knows framework settings, not a
        # job's Pydantic model, so the model's own default is the last rung and
        # has to be read here. `resolve_job_config` expressed this by simply
        # omitting the field and letting Pydantic fill it in — which works for
        # execution but leaves every display surface unable to say *what* the
        # default is or that it applied.
        default, has_default = _model_default(info)
        if has_default:
            fields.append(
                ResolvedField(
                    name=name,
                    env_name=env_name,
                    value=default,
                    source="default",
                    origin="model default",
                    secret=secret,
                    required=required,
                )
            )
            continue

        fields.append(
            ResolvedField(
                name=name,
                env_name=env_name,
                value=None,
                source=UNSET,
                # Name the variable that *would* set it: the whole point of
                # reporting a missing field is telling the operator what to do.
                origin=env_name,
                secret=secret,
                required=required,
            )
        )

    return fields


def _coerce(value: Any, target_type: Any) -> Any:
    """Coerce toward the declared type, the way execution does.

    The seam reports the value a run *will* use, so it has to apply the same
    conversion the run applies. Without this a surface printed the raw source
    string — ``true`` for a ``bool``, ``a,b,c`` for a ``list[str]`` — while the
    job received ``True`` and ``["a", "b", "c"]``. Reporting a value in a shape
    the job never sees is a smaller lie than reporting the wrong value, but it
    is the same kind, and it is the kind this module exists to end.

    Imported inside the function: ``job_config`` imports this module for the
    group-option env spelling, so a module-level import would close a cycle.
    """
    from functualize._config.job_config import _coerce_for_field

    return _coerce_for_field(value, target_type)


def _model_default(info: Any) -> tuple[Any, bool]:
    """``(default, True)`` when a field declares one, else ``(None, False)``.

    A Pydantic v2 required field's default is ``PydanticUndefined`` — neither
    ``None`` nor ``Ellipsis``. Testing for those two is what made every surface
    report a required, unset field as ``model default``; ``is_required()`` is
    the question actually being asked.
    """
    is_required = getattr(info, "is_required", None)
    if callable(is_required) and is_required():
        return None, False

    factory = getattr(info, "default_factory", None)
    if factory is not None:
        try:
            return factory(), True
        except TypeError:
            # Pydantic also allows a factory taking the already-validated
            # fields. There is no validated model here, so report no default
            # rather than crash a display path on a TypeError.
            return None, False

    default = getattr(info, "default", None)
    if default is None or default is Ellipsis:
        return None, False
    return default, True


def _chain_resolve(
    config_view: JobConfigView, key: str, section: str
) -> tuple[str, str, Any] | None:
    """``(source_type, source_id, value)`` from the view, or None if unset.

    Goes through ``JobConfigView.resolve_with_source`` rather than reaching for
    the view's private ``_chain``. Reaching past the view skipped its override
    layer, which ``get()`` consults first — so a value set through
    ``config.set()`` was what the run used and not what any surface showed.
    A seam that exists to stop displays disagreeing with the run cannot itself
    read from a different place than the run does.
    """
    resolver = getattr(config_view, "resolve_with_source", None)
    if callable(resolver):
        return resolver(key, section)  # type: ignore[no-any-return]

    # A test double predating the method. Falling back keeps introspection
    # working rather than reporting every field unset.
    chain = getattr(config_view, "_chain", None)
    if chain is None:
        return None
    try:
        result = chain.resolve(key, section)
    except MissingKeyError:
        return None
    except Exception:
        return None
    if result is None or result.value is None:
        return None
    return (result.source_type, result.source_id, result.value)


def _origin_for(source_type: str, source_id: str, env_name: str) -> str:
    """A human-facing name for where a value came from."""
    if source_type == "env":
        # `source_id` for EnvSource is "environ", which tells nobody anything.
        return env_name
    if source_type == "default":
        return "model default"
    return source_id or source_type
