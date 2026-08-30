"""Click-native command construction from job signatures and config models.

Builds ``click.Parameter`` objects directly from a job's function signature
(Arg/Option/Stdin markers) and its Pydantic config class, then composes them
with the engine callback into a ``click.Command``.

The module imports ``click`` only — never the execution engine at module
scope — so it preserves the warm/lazy-boot property that
``lazy_command.py`` also depends on (see tests/test_typer_isolation.py, now an
absence test). Engine imports are deferred into the callback body.

Public API:
- ``build_click_params()`` — signature + config model → ``list[click.Parameter]``
- ``build_job_engine_callback()`` — the DI/lifecycle wrapper (shared)
- ``create_job_click_command()`` — compose params + callback into a Command
- ``invoke_command_capturing()`` — run a command, capture + emit its return value
"""

from __future__ import annotations

import contextlib
import inspect
import logging
import sys
import typing
from collections.abc import Callable, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any

import click
from click.types import convert_type
from pydantic import BaseModel

from functualize._primitives.capability_names import INJECTED_PARAM_TYPE_NAMES
from functualize._primitives.config_class_detection import detect_config_class
from functualize._types.enums import RunStatus
from functualize._types.exit_codes import ExitCode, exit_code_for_status

if TYPE_CHECKING:
    from functualize.app.core import FunctualizeApp

logger = logging.getLogger(__name__)

# DI capability type names stripped from CLI signatures — the one list, not a
# mirror of it. The mirrors drifted (see _primitives/capability_names).
_DI_TYPE_NAMES = INJECTED_PARAM_TYPE_NAMES


#: The kwarg a `--scope-id` command option binds to. A `@workflow` job command
#: carries one; every other job does not, so it stays off their `--help` and
#: cannot collide with a config field named `scope_id`.
_SCOPE_ID_PARAM = "scope_id"


def _scope_id_option() -> click.Option:
    """The per-command `--scope-id`, for a job that declares a `@workflow`.

    `func` has had a **pre-command** `--scope-id` since gates existed, and
    `app/commands.py` never threaded it — so a `@workflow` with a `Gate` on a
    `FunctualizeApp` blocked at exit 5 forever and the deposited input was never
    read. There was no surface on an embedded app that could supply the scope.

    Post-command, and on both surfaces, because that is where a reader looks:
    the audit that found this got the pre-command position wrong twice before
    reading `dispatch.py`. `func --scope-id X walk` still works.
    """
    return click.Option(
        ["--scope-id", _SCOPE_ID_PARAM],
        default=None,
        required=False,
        help="Resume the named workflow scope instead of starting a fresh one.",
    )


def _declares_workflow(function: Any) -> bool:
    """True when a live function carries a ``@workflow`` declaration."""
    return getattr(function, "__functualize_workflow__", None) is not None


def _force_requested(app_ref: Any) -> bool:
    """Did the caller ask to run anyway?

    Deposited on the app by whichever CLI parsed it — both do, at the same
    attribute — because the commands are built before the pre-command flags are
    parsed. Same route `--output` takes.
    """
    return bool(getattr(app_ref, "_force", False))


# ─── Small pure helpers (copies of the ones in adapters/cli.py) ──


def _has_from_job_marker(annotation: Any) -> bool:
    """True when ``annotation`` carries a ``FromJob`` marker."""
    from functualize._types.from_job import FromJob

    if typing.get_origin(annotation) is not Annotated:
        return False
    return any(isinstance(m, FromJob) for m in typing.get_args(annotation)[1:])


def _validate_short_flag(flag: str) -> bool:
    """A short flag is a single dash + exactly one ASCII letter (-v, -A)."""
    if len(flag) != 2 or flag[0] != "-":
        return False
    return flag[1].isascii() and flag[1].isalpha()


def _is_variadic_arg(annotation: Any) -> bool:
    """True for Annotated[list[T], Arg()] — a variadic positional."""
    from typing import get_origin

    from functualize._cli.annotation_utils import parse_annotation as _parse

    info = _parse(annotation)
    if not any(type(m).__name__ == "Arg" for m in info.cli_markers):
        return False
    base = info.base_type
    return base is list or get_origin(base) is list


def _get_list_inner_type(base_type: Any) -> Any:
    """Extract T from list[T]; str when not determinable."""
    from typing import get_args, get_origin

    if get_origin(base_type) is list:
        args = get_args(base_type)
        if args:
            return args[0]
    return str


def _click_type_for(py_type: Any) -> tuple[Any, bool, bool]:
    """Map a Python type to ``(click_type, is_flag, multiple)``.

    Mirrors Click's conversion so parsing/metavars/choices match:
    - Optional ``X | None`` is unwrapped to ``X``.
    - Enum → ``click.Choice`` of member values.
    - ``list[X]`` → inner ``X`` type with ``multiple=True``.
    - ``bool`` → ``click.BOOL`` with ``is_flag=True``.
    - everything else → ``click.types.convert_type(X)``.
    """
    from functualize._config.job_config import (
        _is_enum_subclass,
        _unwrap_list,
        _unwrap_optional,
    )

    inner, _is_opt = _unwrap_optional(py_type)

    list_inner, is_list = _unwrap_list(inner)
    if is_list:
        elem_type, _, _ = _click_type_for(list_inner)
        return elem_type, False, True

    if _is_enum_subclass(inner):
        choices = [str(member.value) for member in inner]
        return click.Choice(choices), False, False

    if inner is bool:
        return click.BOOL, True, False

    try:
        return convert_type(inner), False, False
    except Exception:
        return click.STRING, False, False


# ─── Cached type-string resolution (for the lazy descriptor path) ───────────

_SCALAR_TYPES: dict[str, Any] = {"str": str, "int": int, "bool": bool, "float": float}


def _resolve_type_string(type_str: str) -> Any:
    """Resolve a cached FieldDescriptor type string to a Python annotation.

    Unrecognized types collapse to ``str`` (never raises — a malformed cache
    must not break warm boot). Mirrors the old lazy_command resolver.
    """
    from pathlib import Path

    s = type_str.strip()
    try:
        if s.endswith(" | None"):
            return _resolve_type_string(s[: -len(" | None")]) | None
        if s.startswith("list[") and s.endswith("]"):
            inner = _resolve_type_string(s[len("list[") : -1])
            return list[inner]  # type: ignore[valid-type]
        if s == "list":
            return list[str]
        scalar = _SCALAR_TYPES.get(s)
        if scalar is not None:
            return scalar
        if s == "Path":
            return Path
    except Exception:
        return str
    return str


def _field_click_type(field: Any) -> tuple[Any, bool, bool]:
    """Resolve a FieldDescriptor to ``(click_type, is_flag, multiple)``.

    Enum fields (``type == "enum"`` or populated ``choices``) become a
    ``click.Choice``; everything else routes through the shared
    ``_click_type_for`` after resolving the cached type string.
    """
    if field.type_annotation == "enum" or field.choices:
        return click.Choice(field.choices or []), False, False
    return _click_type_for(_resolve_type_string(field.type_annotation))


def build_click_params_from_descriptor(descriptor: Any) -> list[click.Parameter]:
    """Build click parameters from a cached JobDescriptor's field metadata.

    The warm/lazy-boot counterpart to :func:`build_click_params`: it renders
    the same CLI shape from cached ``FieldDescriptor`` records without importing
    the job module.

    "The same shape" is now a property that is *asserted* rather than described.
    It used to be a prose claim next to a second copy of the rules, and the copy
    had drifted — see the comment above :func:`_config_field_option`.
    """
    return build_click_params_from_fields(descriptor.config_fields)


def build_click_params_from_fields(
    fields: Sequence[Any],
) -> list[click.Parameter]:
    """Render a sequence of cached ``FieldDescriptor`` records as click params.

    The rendering rules live here rather than in
    :func:`build_click_params_from_descriptor` because two callers need them
    (C-D1): a job's own cached fields, and a **group's** declared options
    (S6a), which are the same record type reached from a different cache
    section. A second copy of this loop is how the two would drift — a group
    flag rendering differently from the identical job flag is the bug that
    would follow.

    **Two rules, and which one applies is carried by the field.** A field
    marked ``from_config_model`` is rendered by the config rule
    (:func:`_config_field_option`: always an option, always ``default=None``,
    the ladder supplies the value). Everything else is a plain signature
    parameter, which has no ladder, so its default is passed through and a
    required one becomes a positional.

    The distinction cannot be recovered here from the list alone — a
    ``JobDescriptor`` holds one ``config_fields`` list for both kinds and does
    not serialize ``parameters`` — which is why it travels on the field.
    """
    # Preserve declaration order (cached config fields need not follow Python's
    # no-default-first rule, so a required field may legitimately trail optional
    # ones as a late positional — click parses positionals
    # by their order among Arguments in this list regardless of interleaving).
    params: list[click.Parameter] = []

    for field in fields:
        click_type, is_flag, multiple = _field_click_type(field)

        if getattr(field, "from_config_model", False):
            # A config field is rendered by the config rule, not the signature
            # rule — see `_config_field_option`. This branch is what makes the
            # warm path agree with `_config_option_params`; without it the two
            # builders of one boundary disagreed on the default *and* on the
            # parameter class, which is defect D7's shape on the pair this
            # branch's predecessor did not consolidate.
            params.append(
                _config_field_option(
                    field.name,
                    click_type=click_type,
                    is_flag=is_flag,
                    multiple=multiple,
                    help_text=_config_field_help(
                        field.description,
                        required=field.required,
                        default=field.default,
                    ),
                    short_flag=field.short_flag,
                )
            )
            continue

        if field.positional:
            if field.type_annotation.strip().startswith("list"):
                params.append(
                    _make_argument(field.name, click_type, required=True, nargs=-1)
                )
            else:
                params.append(
                    _make_argument(
                        field.name,
                        click_type,
                        required=field.required,
                        default=None if field.required else field.default,
                    )
                )
            continue

        if field.is_stdin:
            flag_name = field.stdin_flag or f"--{field.name.replace('_', '-')}"
            params.append(
                click.Option(
                    [flag_name, field.name],
                    type=click_type,
                    default=None,
                    required=False,
                    help=field.description or None,
                )
            )
            continue

        if field.short_flag:
            long_flag = f"--{field.name.replace('_', '-')}"
            short_flag = (
                field.short_flag
                if field.short_flag.startswith("-")
                else f"-{field.short_flag}"
            )
            if is_flag:
                params.append(
                    click.Option(
                        [long_flag, short_flag],
                        is_flag=True,
                        default=field.default if not field.required else False,
                        help=field.description or None,
                    )
                )
            else:
                params.append(
                    click.Option(
                        [long_flag, short_flag],
                        type=click_type,
                        default=None if field.required else field.default,
                        required=field.required,
                        multiple=multiple,
                        help=field.description or None,
                    )
                )
            continue

        # ── Plain field ────────────────────────────────────────────────────
        hyphen = field.name.replace("_", "-")
        if is_flag:
            params.append(
                click.Option(
                    [f"--{hyphen}/--no-{hyphen}"],
                    default=field.default if not field.required else False,
                    help=field.description or None,
                )
            )
        elif field.required and not multiple:
            params.append(_make_argument(field.name, click_type, required=True))
        else:
            params.append(
                click.Option(
                    [f"--{hyphen}"],
                    type=click_type,
                    default=None if field.required else field.default,
                    required=field.required,
                    multiple=multiple,
                    help=field.description or None,
                )
            )

    return params


# ─── Config model → click options ─────────
#
# One rule, two builders. `_config_option_params` reads a live pydantic model
# (cold boot); `build_click_params_from_fields` reads cached `FieldDescriptor`
# records (warm boot). They read different inputs and cannot be one function
# without unifying those two representations — but what they *emit* is one
# decision, and it lives here so it cannot be made twice.
#
# It was made twice, and the two copies disagreed. The warm copy passed the
# model's default explicitly, which `_resolve_config_model` pops into
# `cli_values` — the top tier of the ladder — so the pydantic default outranked
# the config file, the environment, and everything else from the second run
# onward. And it rendered a *required* field as a positional argument where the
# cold copy renders a non-required option, so an app whose job took a required
# config field from `config.base.toml` became uninvocable warm:
# `Error: Missing argument 'TOKEN'`.
#
# `tests/config/test_click_builder_agreement.py` asserts they agree, which is
# the same "prove the registry" discipline `contributor/reference/pitfalls.md`
# #6 demands and that `app/adapters/surface_gate.py` already applies to one
# attribute.


def _config_field_option(
    name: str,
    *,
    click_type: Any,
    is_flag: bool,
    multiple: bool,
    help_text: str,
    short_flag: str | None = None,
) -> click.Option:
    """The one rule for rendering a config-model field as a click parameter.

    Always an ``Option``, never an ``Argument``, and always ``default=None``.

    A config field is never a positional, because the config file, the
    environment, a `.env`, a prompt and the CLI can each supply it — click
    cannot know which, so it must report only what the *user typed*. ``None``
    is how it says "not provided"; the resolution ladder supplies the rest.
    Passing the model's default here would mean click reporting a value nobody
    entered, at the highest precedence there is.

    The rule covers the *decision* — parameter class, ``required``, ``default``
    — not the spelling. ``short_flag`` stays a per-builder input because only
    the cached descriptor records it: a ``GroupOptions`` field declared
    ``Option("-e")`` reaches the CLI through this builder alone, and dropping
    its short form here removed ``-e`` from completion.
    """
    decls = [f"--{name.replace('_', '-')}"]
    if short_flag:
        decls.append(short_flag if short_flag.startswith("-") else f"-{short_flag}")
    return click.Option(
        decls,
        type=click_type,
        default=None,
        required=False,
        is_flag=is_flag,
        multiple=multiple,
        help=help_text or None,
        show_default=False,
    )


def _config_field_help(description: str, *, required: bool, default: Any) -> str:
    """Annotate a config field's help with ``[required]`` / ``[default: X]``.

    Click's own ``show_default`` cannot do this: the option carries
    ``default=None`` on purpose, so the real default has to be rendered as
    text or the user never sees it.
    """
    if required:
        return f"{description} \\[required]" if description else "\\[required]"
    if default is None or default is False:
        return description
    rendered = default.value if isinstance(default, Enum) else default
    return (
        f"{description} \\[default: {rendered}]"
        if description
        else f"\\[default: {rendered}]"
    )


def _config_option_params(job_config_class: type[BaseModel]) -> list[click.Parameter]:
    """Build a ``click.Option`` for every field of a Pydantic config model.

    The cold-boot half of the pair described above. Emits through
    :func:`_config_field_option`, so the rule is stated once.
    """
    from pydantic_core import PydanticUndefined

    from functualize._config.job_config import _get_field_type, _is_enum_subclass

    params: list[click.Parameter] = []
    for field_name, field_info in job_config_class.model_fields.items():
        help_text = field_info.description or ""

        has_default = field_info.default is not PydanticUndefined or (
            field_info.default_factory is not None
        )
        if not has_default:
            help_text = f"{help_text} \\[required]" if help_text else "\\[required]"
        elif field_info.default_factory is not None:
            pass  # factory default, don't annotate
        elif field_info.default is None:
            pass  # Optional with None default
        elif _is_enum_subclass(type(field_info.default)):
            default_repr = field_info.default.value
            help_text = (
                f"{help_text} \\[default: {default_repr}]"
                if help_text
                else f"\\[default: {default_repr}]"
            )
        elif field_info.default is not False:
            default_repr = field_info.default
            help_text = (
                f"{help_text} \\[default: {default_repr}]"
                if help_text
                else f"\\[default: {default_repr}]"
            )

        click_type, is_flag, multiple = _click_type_for(_get_field_type(field_info))
        params.append(
            _config_field_option(
                field_name,
                click_type=click_type,
                is_flag=is_flag,
                multiple=multiple,
                help_text=help_text,
            )
        )
    return params


# ─── Signature → click params (replaces the create_job_command builder) ─────


def _make_argument(
    name: str,
    click_type: Any,
    *,
    required: bool,
    default: Any = None,
    nargs: int = 1,
    metavar: str | None = None,
) -> click.Argument:
    """Build a ``click.Argument``, omitting ``default`` when required.

    click has a sharp edge: a required argument constructed with an
    explicit ``default=None`` is silently *not* enforced (the callback runs with
    ``None``). Required arguments must therefore be built with no ``default`` at
    all so click's missing-argument check fires.
    """
    kwargs: dict[str, Any] = {"type": click_type, "nargs": nargs}
    if metavar is not None:
        kwargs["metavar"] = metavar
    if required:
        kwargs["required"] = True
    else:
        kwargs["required"] = False
        kwargs["default"] = default
    return click.Argument([name], **kwargs)


def _option_from_marker(
    param: inspect.Parameter, marker: Any, base_type: Any
) -> click.Option:
    """Build a ``click.Option`` from an ``Option()`` marker (short/long flags)."""
    short_flag: str | None = marker.short
    long_flag: str | None = marker.long

    if short_flag is not None and not _validate_short_flag(short_flag):
        raise ValueError(
            f"Invalid short flag '{short_flag}' for parameter '{param.name}'. "
            f"Short flags must be a single dash followed by exactly one ASCII letter "
            f"(e.g., '-v', '-t', '-n')."
        )
    if short_flag is not None and long_flag is None:
        long_flag = f"--{param.name.replace('_', '-')}"
    if long_flag is None:
        long_flag = f"--{param.name.replace('_', '-')}"

    decls = [long_flag]
    if short_flag is not None:
        decls.append(short_flag)
    # Bind the click param name to the function parameter name — a malformed or
    # custom flag ("-tt") must not let click infer a different name, or the
    # engine callback would receive the wrong keyword.
    decls.append(param.name)

    click_type, is_flag, multiple = _click_type_for(base_type)
    has_default = param.default is not inspect.Parameter.empty
    default = param.default if has_default else None

    return click.Option(
        decls,
        type=click_type,
        default=default,
        required=not has_default and not is_flag,
        is_flag=is_flag,
        multiple=multiple,
        help=marker.help,
        hidden=marker.hidden,
        envvar=marker.envvar,
    )


def build_click_params(
    function: Callable[..., Any],
    job_config_class: type[BaseModel] | None,
    *,
    apply_job_filter: bool = True,
) -> tuple[list[click.Parameter], type[BaseModel] | None, dict[str, Any]]:
    """Build click parameters for a job function's CLI signature.

    Returns ``(params, resolved_config_class, stdin_markers)``. With
    ``apply_job_filter`` (the default, for jobs), the DI/config/FromJob/non-CLI
    stripping matches ``create_job_command`` exactly. With it False (for raw
    plugin callbacks, which are processed unfiltered) only DI params are
    dropped, so plain ``X | None`` params survive as options.
    """
    from functualize._cli.annotation_utils import parse_annotation as _parse
    from functualize.job.markers import Arg
    from functualize.job.markers import Option as _OptionMarker
    from functualize.job.markers import Stdin as _StdinMarker

    sig = inspect.signature(function)
    params = list(sig.parameters.values())

    try:
        resolved_hints = typing.get_type_hints(function, include_extras=True)
    except Exception:
        resolved_hints = {}
    if resolved_hints:
        params = [
            p.replace(annotation=resolved_hints[p.name])
            if p.name in resolved_hints
            else p
            for p in params
        ]

    # Auto-detect config class from signature if not provided — through the
    # one shared rule, not a local copy of it.
    #
    # The local copy this replaced used `_parse(...).base_type`, which
    # deliberately unwraps `Annotated[...]` so that `Annotated[int, Option()]`
    # yields `int`. Applied to the detection question that unwrapping is wrong:
    # `Annotated[Findings, FromJob("audit.check")]` yielded `Findings`, a
    # BaseModel subclass, so an upstream envelope became the job's config class
    # and the job died in config resolution before its body ran. The filter
    # loop 30 lines below already skipped `FromJob` params; the detection loop
    # above it did not.
    if job_config_class is None and apply_job_filter:
        job_config_class = detect_config_class(function)

    # ── Filter to CLI-facing params (identical policy to create_job_command) ─
    kept: list[inspect.Parameter] = []
    for param in params:
        annotation = param.annotation
        if isinstance(annotation, str) and annotation in _DI_TYPE_NAMES:
            continue
        if isinstance(annotation, str):
            kept.append(param)
            continue
        if _has_from_job_marker(annotation):
            continue
        info = _parse(annotation)
        if info.is_di_param:
            continue
        if not apply_job_filter:
            # Raw plugin callback: applies no config/CLI-compat filter.
            kept.append(param)
            continue
        if (
            info.base_type is not None
            and isinstance(info.base_type, type)
            and issubclass(info.base_type, BaseModel)
            and info.base_type is not BaseModel
        ):
            continue
        if not info.is_cli_compatible and not info.cli_markers:
            continue
        kept.append(param)

    # ── Emit click params (Arg → Argument, Option/Stdin/plain → Option) ─────
    arguments: list[click.Parameter] = []
    options: list[click.Parameter] = []
    stdin_markers: dict[str, _StdinMarker] = {}

    for param in kept:
        annotation = param.annotation
        if isinstance(annotation, str) or annotation is inspect.Parameter.empty:
            # Untyped/forward-ref param. Rule: no default → positional
            # argument, otherwise a string option.
            has_default = param.default is not inspect.Parameter.empty
            if not has_default:
                arguments.append(
                    _make_argument(param.name, click.STRING, required=True)
                )
            else:
                options.append(
                    click.Option(
                        [f"--{param.name.replace('_', '-')}"],
                        type=click.STRING,
                        default=param.default,
                        required=False,
                    )
                )
            continue

        info = _parse(annotation)
        base_type = info.base_type if info.base_type is not None else str
        arg_marker = next((m for m in info.cli_markers if isinstance(m, Arg)), None)

        if arg_marker is not None:
            if _is_variadic_arg(annotation):
                inner = _get_list_inner_type(info.base_type)
                elem_type, _, _ = _click_type_for(inner)
                arguments.append(
                    _make_argument(
                        param.name,
                        elem_type,
                        required=True,
                        nargs=-1,
                        metavar=arg_marker.metavar,
                    )
                )
            else:
                has_default = param.default is not inspect.Parameter.empty
                click_type, _, _ = _click_type_for(base_type)
                arguments.append(
                    _make_argument(
                        param.name,
                        click_type,
                        required=not has_default,
                        default=param.default if has_default else None,
                        metavar=arg_marker.metavar,
                    )
                )
            continue

        stdin_marker = next(
            (m for m in info.cli_markers if isinstance(m, _StdinMarker)), None
        )
        if stdin_marker is not None:
            flag_name = stdin_marker.flag or f"--{param.name.replace('_', '-')}"
            click_type, _, _ = _click_type_for(base_type)
            # Bind the param name explicitly: a custom Stdin(flag="--data") on a
            # param named "payload" must still bind the "payload" keyword.
            options.append(
                click.Option(
                    [flag_name, param.name],
                    type=click_type,
                    default=None,
                    required=False,
                    help=stdin_marker.help,
                )
            )
            stdin_markers[param.name] = stdin_marker
            continue

        option_marker = next(
            (m for m in info.cli_markers if isinstance(m, _OptionMarker)), None
        )
        if option_marker is not None:
            options.append(_option_from_marker(param, option_marker, base_type))
            continue

        # ── Plain CLI param (no marker): default rules ──────────────
        hyphen = param.name.replace("_", "-")
        click_type, is_flag, multiple = _click_type_for(base_type)
        has_default = param.default is not inspect.Parameter.empty
        if is_flag:
            # A plain bool param renders as a --flag/--no-flag pair.
            options.append(
                click.Option(
                    [f"--{hyphen}/--no-{hyphen}"],
                    default=param.default if has_default else False,
                )
            )
        elif not has_default and not multiple:
            # No default → positional argument (standard rule for plain params).
            arguments.append(_make_argument(param.name, click_type, required=True))
        else:
            options.append(
                click.Option(
                    [f"--{hyphen}"],
                    type=click_type,
                    default=param.default if has_default else None,
                    required=not has_default,
                    multiple=multiple,
                )
            )

    if job_config_class is not None:
        options.extend(_config_option_params(job_config_class))

    return arguments + options, job_config_class, stdin_markers


def _streaming_stdin_params(
    function: Callable[..., Any], stdin_markers: dict[str, Any]
) -> frozenset[str]:
    """Which ``Stdin``-marked params are typed as a stream (§C.2).

    A parameter annotated ``Iterator[Row]`` / ``Iterable[Row]`` /
    ``Generator[...]`` wants the lazy NDJSON stream; anything else keeps the
    eager whole-of-stdin string. ``str``/``bytes`` are iterable but are emphatically
    *not* streams, and are excluded by construction: this tests the annotation's
    generic **origin**, which is ``None`` for a bare ``str``.

    Annotations are read through ``resolved_hints`` rather than raw, so a module
    compiled under ``from __future__ import annotations`` (PEP 563) does not
    silently report every type as the string ``"Iterator[Row]"``.
    """
    import collections.abc as _abc
    import typing as _typing

    if not stdin_markers:
        return frozenset()
    try:
        from functualize._types.annotations import resolved_hints

        hints = resolved_hints(function)
    except Exception:
        return frozenset()

    stream_origins = {
        _abc.Iterator,
        _abc.Iterable,
        _abc.Generator,
        _abc.AsyncIterator,
        _abc.AsyncIterable,
    }
    streaming: set[str] = set()
    for pname in stdin_markers:
        hint = hints.get(pname)
        if hint is None:
            continue
        # Unwrap Annotated[...] so `Annotated[Iterator[Row], Stdin()]` is seen.
        if _typing.get_origin(hint) is _typing.Annotated:
            hint = _typing.get_args(hint)[0]
        if _typing.get_origin(hint) in stream_origins:
            streaming.add(pname)
    return frozenset(streaming)


def _exit_quietly_on_broken_pipe() -> None:
    """Redirect stdout to ``/dev/null`` and exit 0 after a broken pipe.

    The redirect matters as much as the code: without it the interpreter's
    shutdown flush of ``sys.stdout`` prints "Exception ignored in: …" to
    stderr, which is exactly the noise the quiet exit exists to avoid.
    """
    import os

    with contextlib.suppress(OSError, ValueError):
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    raise SystemExit(0)


def _report_blocked(result: Any) -> None:
    """Explain a gate pause on stderr, tiered by log level (S5 T39).

    A blocked run is the one outcome a *script* most needs to act on, so the
    scope id and gate name stay at INFO: an agent greps them and drives ``func
    builtin workflow resume``. That is the machine-capture contract, and moving
    the token to DEBUG would defeat the reason it is on stderr at all.

    A human, though, does not want the full resume incantation every time a
    pipeline pauses — so the copy-paste command and the gate's input schema are
    DEBUG-only, and INFO points at them.
    """
    metadata = dict(getattr(result, "metadata", None) or {})
    gate = str(metadata.get("blocked_on") or metadata.get("blocked_reason") or "")
    scope = str(metadata.get("workflow_scope") or "")
    job_name = str(metadata.get("job_name") or getattr(result, "job_name", "") or "")

    where = f"gate {gate!r}" if gate else "a gate"
    in_scope = f" in scope {scope!r}" if scope else ""
    print(f"Blocked: {where}{in_scope} awaits input.", file=sys.stderr)

    # The resume commands are printed at **default** level, not behind
    # `--log-level DEBUG`. A blocked run is the one outcome a script most needs
    # to act on, and "re-run with a different flag to find out what to do" is
    # one indirection too many for the line a CI log carries.
    #
    # `argv[0]` rather than a literal `func`: on a `FunctualizeApp` entry point
    # the command is `./main.py`, and printing `func` sent readers to a CLI that
    # does not know about their project. The flag is spelled post-command for
    # the same reason — that is where a reader looks, and the pre-command form
    # is what the audit that found this got wrong twice.
    program = _program_name()
    resume = f"{program} builtin workflow resume"
    if scope and gate:
        print(f"  {resume} {scope} {gate} --input '{{…}}'", file=sys.stderr)
    else:
        print(
            f"  {resume} <scope> <gate> --input '{{…}}'  "
            f"(run `{program} builtin workflow list` to find the scope)",
            file=sys.stderr,
        )
    if scope and job_name:
        print(f"  {program} {job_name} --scope-id {scope}", file=sys.stderr)

    if not logger.isEnabledFor(logging.DEBUG):
        return
    schema = metadata.get("gate_input_schema")
    if schema:
        print(f"  input schema: {schema}", file=sys.stderr)


def _program_name() -> str:
    """How the user actually invoked this process.

    A `FunctualizeApp` entry point is `./main.py`, not `func`, and telling its
    operator to run `func …` sends them to a CLI that does not know about their
    project at all.
    """
    import os

    argv0 = sys.argv[0] if sys.argv else ""
    if not argv0:
        return "func"
    base = os.path.basename(argv0)
    return base or "func"


# ─── Engine callback (shared with adapters/cli.py's create_job_command) ─────


def build_job_engine_callback(
    name: str,
    function: Callable[..., Any],
    job_config_class: type[BaseModel] | None,
    app: FunctualizeApp | None,
    stdin_markers: dict[str, Any],
    *,
    uses_live: bool,
    requires_tty: bool,
    group_option_values: dict[str, Any] | None = None,
    workflow_scope_id: str | None = None,
) -> Callable[..., Any]:
    """Build the DI/config/lifecycle callback a click command invokes.

    This is the ``wrapper``/``_engine_path`` closure lifted out of
    ``create_job_command`` so the lazy and eager construction paths share one
    execution body. click invokes it with every parameter as a keyword.

    ``group_option_values`` carries the group flags the dispatcher consumed
    *before* the job name (S6a). They are not click params of this command —
    position is what scopes them (D-d) — so they ride the closure rather than
    ``kwargs``, and the engine resolves them against the group, not the job.
    """
    app_ref = app

    def wrapper(**kwargs: Any) -> Any:
        from functualize._engine.executor import (
            JobExecutionEngine as _JobExecutionEngine,
        )

        if requires_tty:
            from functualize._engine.capabilities.tty import terminal_available

            if not terminal_available():
                print(
                    f"Error: '{name}' needs an interactive terminal "
                    f"(it declares `tty: TTY`). Run it from `func` at a real "
                    f"TTY — it cannot run over a pipe, in CI, or under MCP.",
                    file=sys.stderr,
                )
                # A pre-flight refusal, not a job failure (T39 exit table).
                raise SystemExit(ExitCode.REFUSED)

        engine = getattr(app_ref, "_execution_engine", None)
        if not isinstance(engine, _JobExecutionEngine):
            raise RuntimeError(
                f"Cannot execute job '{name}': no execution engine available. "
                "Ensure the app has been booted with an execution engine."
            )

        # `--scope-id` is a command option on a `@workflow` job (see
        # `_scope_id_option`), so it arrives as a kwarg and must not reach the
        # job body. A per-command value wins over the pre-command global.
        scope_id = kwargs.pop(_SCOPE_ID_PARAM, None) or workflow_scope_id
        if scope_id is None:
            scope_id = getattr(app_ref, "_workflow_scope_id", None)

        cli_values: dict[str, Any] = {}
        if job_config_class is not None:
            config_field_names = set(job_config_class.model_fields.keys())
            for field_name in list(kwargs.keys()):
                if field_name in config_field_names:
                    cli_values[field_name] = kwargs.pop(field_name)

        direct_kwargs = dict(kwargs)

        if stdin_markers:
            from functualize._cli.stdin_reader import resolve_stdin_params

            stdin_cli_values = {
                pname: direct_kwargs.get(pname) for pname in stdin_markers
            }
            resolved = resolve_stdin_params(
                stdin_markers,
                stdin_cli_values,
                _streaming_stdin_params(function, stdin_markers),
            )
            direct_kwargs.update(resolved)
            for pname in stdin_markers:
                if pname in resolved:
                    pass
                elif direct_kwargs.get(pname) is None:
                    direct_kwargs.pop(pname, None)

        from functualize.app.adapters.surface_gate import wants_stdout_surface

        _descriptor = (
            app_ref.get_job(name)
            if app_ref is not None and getattr(app_ref, "get_job", None)
            else None
        )
        live_ctx: Any = contextlib.nullcontext()
        if wants_stdout_surface(app_ref, _descriptor, uses_live=uses_live):
            with contextlib.suppress(ImportError):
                from functualize.ui import stdout_live_session

                live_ctx = stdout_live_session(app_ref, _descriptor)

        with live_ctx:
            result = app_ref.execution_engine.execute(  # type: ignore[union-attr]
                job_name=name,
                function=function,
                config_class=job_config_class,
                kwargs={**direct_kwargs, **cli_values},
                group_option_values=group_option_values,
                workflow_scope_id=scope_id,
                force=_force_requested(app_ref),
            )

        return deliver_job_result(result, name, app_ref)

    return wrapper


def deliver_job_result(result: Any, name: str, app_ref: Any = None) -> Any:
    """Turn a ``JobResult`` into stdout, an exit code, or a return value.

    **The single place a run reaches the process boundary.** Both command
    constructors route here — the eager one built from a live signature and
    the lazy one built from a cached descriptor.

    That is not tidiness. The lazy (warm-boot) wrapper used to return its
    ``JobResult`` and inspect nothing, so on any second invocation of any job:

    - a job that raised exited **0**, silently, with the traceback swallowed;
    - a workflow blocked at a gate exited 0 instead of 5;
    - a refusal exited 0 instead of 3.

    Cold boot exited 1, warm boot exited 0, for the same job and the same
    failure. Every guarantee in the exit-code table — which exists to be
    scripted against — was true only on a project's first run.

    Args:
        result: The JobResult the engine returned.
        name: Job name, for the validation-error panel.
        app_ref: The app, for the same panel's config-source hints.

    Returns:
        ``result.return_value`` when the run finished normally.
    """
    if result.exception is not None:
        # A downstream reader closing the pipe is not a job failure: the
        # engine catches *every* exception into JobResult, so a
        # BrokenPipeError raised inside the job would otherwise surface as
        # exit 1 rather than the quiet 0 a `| head -5` deserves (T39).
        if isinstance(result.exception, BrokenPipeError):
            _exit_quietly_on_broken_pipe()

        from pydantic import ValidationError as PydanticValidationError

        from functualize._engine.missing_value import MissingValueError

        if isinstance(result.exception, PydanticValidationError):
            from functualize.app.adapters.cli import _print_validation_error

            _print_validation_error(name, result.exception, app_ref)
            # A config/usage error, not the job raising (T39 exit table).
            raise SystemExit(ExitCode.USAGE) from result.exception

        # A value was missing and nothing could be asked (T45 / T-S6b-4).
        # Same class of failure as the ValidationError above — config, not
        # the job raising — so it takes the same code. Its message already
        # names the field and the environment variable that sets it, which
        # is the whole point of the typed error; printing it plainly beats a
        # traceback for the CI reader who has to act on it.
        if isinstance(result.exception, MissingValueError):
            click.echo(f"Error: {result.exception}", err=True)
            raise SystemExit(ExitCode.USAGE) from result.exception

        raise result.exception

    # Every terminal status takes its code from the one table (D-6). Two of
    # them also have something to say first:
    #
    #  - a gate pause ran *successfully* and is resumable, so it gets its own
    #    code rather than sharing one with a refusal (D-a); without the message
    #    the run would look like a plain success to any caller;
    #  - a refusal must reach the boundary or the whole point is lost — a stage
    #    that declined to run because its declared inputs are not there would
    #    exit 0, and the pipeline after it would read that as "verified,
    #    nothing wrong". Silence plus exit 0 is precisely the false clean.
    #
    # The codes used to be hand-written next to those two messages, and every
    # other status fell through to `return result.return_value` — exit 0.
    # Nothing reaches that fall-through today (TIMEOUT and CANCELLED come only
    # from `Invoke.parallel`, never from a top-level run), so this changes no
    # observable exit code. What it removes is the trap: `_types/exit_codes.py`
    # describes itself as "the single RunStatus -> process exit-code mapping"
    # and warns that scattering SystemExit "is how that contract silently
    # drifts", and this was the scattering. It is the same shape as D7 — a rule
    # stated in two places, one of which quietly answered 0.
    if result.status is RunStatus.BLOCKED:
        _report_blocked(result)
    elif result.status is RunStatus.REFUSED:
        _report_refused(result)

    code = exit_code_for_status(result.status)
    if code == ExitCode.OK:
        return result.return_value
    raise SystemExit(code)


def _report_refused(result: Any) -> None:
    """Explain a pre-flight refusal on stderr.

    Split from its exit code so the message and the number are separable, the
    way :func:`_report_blocked` already is — the code now comes from the table.
    """
    reason = str((getattr(result, "metadata", None) or {}).get("skip_reason") or "")
    message = (
        f"Refused: {reason}"
        if reason
        else "Refused: a declared precondition for running this job was not met."
    )
    print(message, file=sys.stderr)


def create_job_click_command(
    name: str,
    function: Callable[..., Any],
    job_config_class: type[BaseModel] | None = None,
    app: FunctualizeApp | None = None,
    *,
    command_name: str | None = None,
    group_option_values: dict[str, Any] | None = None,
    workflow_scope_id: str | None = None,
) -> click.Command:
    """Build a ``click.Command`` for a job — the click-native replacement.

    Args:
        name: The job name (config/env prefix; the identity the engine runs).
        function: The live job function.
        job_config_class: Optional Pydantic config model.
        app: The FunctualizeApp for engine access.
        command_name: CLI command name if it differs from ``name`` (e.g. the
            bare function name for a grouped job). Defaults to ``name``.
        group_option_values: Group flags consumed mid-path by the dispatcher
            (S6a), passed through to the engine as the group-CLI layer.
    """
    from functualize._discovery.providers import extract_capability_markers

    params, resolved_config, stdin_markers = build_click_params(
        function, job_config_class
    )
    if _declares_workflow(function):
        # A `@workflow` job can be resumed; every other job has nothing
        # to resume, so the flag stays off its --help.
        params = [*params, _scope_id_option()]
    markers = extract_capability_markers(function)
    callback = build_job_engine_callback(
        name,
        function,
        resolved_config,
        app,
        stdin_markers,
        uses_live=markers["uses_live"],
        requires_tty=markers["requires_tty"],
        group_option_values=group_option_values,
        workflow_scope_id=workflow_scope_id,
    )
    return click.Command(
        name=command_name or name,
        params=params,
        callback=callback,
        help=inspect.getdoc(function) or None,
    )


def make_duality_group(
    job_command: click.Command,
    *,
    name: str,
    panel: str | None = None,
) -> click.Group:
    """Wrap a job ``click.Command`` in a Group that is *both* runnable and navigable.

    The duality case (spec §2.A(5)): a ``deploy`` job that also has
    ``deploy web`` beneath it. click cannot natively merge a Command's params
    into a Group, so this builds an ``invoke_without_command=True`` Group that
    carries the job command's ``params`` and, when no sub-command is invoked,
    runs the job command's callback. Its help is the job's help, so
    ``func deploy --help`` renders the job's options followed by the child
    listing on one page.

    Laziness (Q-F): the caller passes the ``make_lazy_command`` result; this
    helper only *reads* ``job_command.params``/``.callback``/``.help`` — it never
    calls the callback or introspects the underlying function, so group
    construction stays import-free.

    Caveat: because the Group's own params are parsed before sub-command
    resolution, a job with a **required positional argument** would consume the
    sub-command token as that argument. Duality therefore composes cleanly for
    option-only jobs (``func deploy --env prod`` runs the job; ``func deploy web
    run`` runs the child); a positional-bearing duality job shadows its subtree,
    which matches click's parsing model.
    """
    from functualize.app.adapters.cli import _PANEL_ATTR, NormalizingGroup

    job_callback = job_command.callback

    def _callback(*args: Any, **kwargs: Any) -> Any:
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None and job_callback is not None:
            return job_callback(*args, **kwargs)
        return None

    group = NormalizingGroup(
        name=name,
        params=list(job_command.params),
        callback=_callback,
        invoke_without_command=True,
        help=job_command.help,
    )
    if panel is not None:
        setattr(group, _PANEL_ATTR, panel)
    return group


def create_job_command(
    name: str,
    function: Callable[..., Any],
    job_config_class: type[BaseModel] | None = None,
    app: FunctualizeApp | None = None,
) -> Callable[..., Any]:
    """Wrap a job function for direct invocation, DI/config-aware.

    Returns the engine callback (invoked with keyword arguments, or none to
    resolve everything from config sources) carrying a synthesized
    ``__signature__`` that exposes exactly the CLI-facing parameters — the DI
    capability params are excluded. This is the callable form of
    :func:`create_job_click_command` for embedders and the ``_discovery``
    CLI-wiring seam, which must not import ``click`` machinery directly.
    """
    from functualize._discovery.providers import extract_capability_markers

    params, resolved_config, stdin_markers = build_click_params(
        function, job_config_class
    )
    markers = extract_capability_markers(function)
    callback = build_job_engine_callback(
        name,
        function,
        resolved_config,
        app,
        stdin_markers,
        uses_live=markers["uses_live"],
        requires_tty=markers["requires_tty"],
    )

    # Synthesize a signature exposing the CLI param names (DI already stripped),
    # so callers that introspect the wrapper see the user-facing parameters.
    sig_params = [
        inspect.Parameter(
            p.name,
            inspect.Parameter.KEYWORD_ONLY,
            default=None if p.required else getattr(p, "default", None),
        )
        for p in params
    ]
    callback.__signature__ = inspect.Signature(sig_params)  # type: ignore[attr-defined]
    callback.__name__ = getattr(function, "__name__", name)
    callback.__doc__ = function.__doc__
    return callback


def create_callback_click_command(
    name: str,
    callback: Callable[..., Any],
    help_text: str | None = None,
) -> click.Command:
    """Build a ``click.Command`` from a raw plugin callback's signature.

    Plugin callbacks are authored as plain functions (no config
    model, no DI/CLI-compat filtering). The command's callback is the raw
    function itself.
    """
    params, _, _ = build_click_params(callback, None, apply_job_filter=False)
    return click.Command(
        name=name,
        params=params,
        callback=callback,
        help=help_text or inspect.getdoc(callback) or None,
    )


# ─── Fast-path invocation with return-value capture ─────────────────────────


def invoke_command_capturing(
    command: click.Command,
    args: list[str],
    output_format: str,
    *,
    prog_name: str | None = None,
    on_start: Callable[[], None] | None = None,
    on_end: Callable[[], None] | None = None,
    obj: Any | None = None,
    emit_return: bool = False,
) -> int:
    """Run ``command`` over ``args`` and return its exit code.

    For **jobs** (the default) the callback's return value is *not* written to
    stdout: a job's return value is programmatic only — it feeds ``rc.invoke()``
    and ``FromJob``/``FromStep``. Job data reaches stdout solely through the
    explicit ``Stdout`` capability (``out.emit()`` / ``out.write()``), which the
    engine injects and which honors ``--output``. See
    ``functualize._types.stdout`` for the ratified design.

    ``emit_return=True`` restores return-value emission for **plugin/ad-hoc
    commands**, which are plain click callbacks rather than engine-executed
    jobs: they get no ``Stdout`` injection and carry no ``FromJob`` semantics,
    so serializing their return under ``--output`` remains the right behavior.
    Emission still requires an *explicit* format — ``auto`` and ``none`` stay
    silent, preserving "no ``--output``, no stdout dump".

    ``obj`` seeds ``ctx.obj`` for callers invoking a command out of its group,
    where no root callback runs to populate it.
    """
    captured: list[Any] = []
    original = command.callback
    if emit_return and original is not None:

        def _capturing(*a: Any, **kw: Any) -> Any:
            result = original(*a, **kw)
            captured.append(result)
            return result

        command.callback = _capturing

    if on_start is not None:
        on_start()
    try:
        command.main(
            args=list(args),
            standalone_mode=True,
            prog_name=prog_name or command.name,
            **({"obj": obj} if obj is not None else {}),
        )
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else 0
    else:
        exit_code = 0
    finally:
        if emit_return:
            command.callback = original
        if on_end is not None:
            on_end()

    if emit_return and exit_code == 0 and captured:
        from functualize._primitives.stdout_emitter import StdoutEmitter

        if output_format not in ("auto", "none"):
            StdoutEmitter(format=output_format).emit(captured[0])
    return exit_code
