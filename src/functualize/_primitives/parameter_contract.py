"""One verdict per job parameter, decided from its declaration (spec B-1 to B-8).

- :func:`build_contracts`, :func:`build_contract` and :func:`build_field_contract`
  decide a parameter's **kind** from its declaration alone. No DI registry is read
  (F-21), so registering a provider, ``str`` included, turns no caller input into
  an injected one (UC-6). The result is what the discovery cache stores.
- :func:`admit` applies spec B-2's one availability rule: an ``INJECTED``
  parameter naming a provider (``Provide("q")`` or an unmarked class) needs one
  for exactly its ``(type, qualifier)``, else it is ``REJECTED_DISCOVERY``. The
  caller passes the question in as a predicate; nothing here imports ``di.py``.

Annotations come from :func:`resolved_hints`, so PEP 563 makes no difference (B-6);
if hints fail for the whole function, each string annotation is evaluated alone, so
one bad annotation refuses one parameter. pydantic is imported lazily.
"""

from __future__ import annotations

import collections.abc as _abc
import dataclasses
import datetime as _dt
import decimal
import enum
import inspect
import pathlib
import types
import uuid
from typing import TYPE_CHECKING, Annotated, Any, Literal, Union, cast
from typing import get_args as _args
from typing import get_origin as _origin

from functualize._primitives.capability_names import INJECTED_PARAM_TYPE_NAMES
from functualize._primitives.group_options_detection import is_group_options_subclass
from functualize._types.annotations import resolved_hints
from functualize._types.cli_markers import Arg, Option, Stdin
from functualize._types.descriptors import _REQUIRED_SENTINEL
from functualize._types.from_job import FromJob, FromStep
from functualize._types.parameter_contract import (
    CliSpelling,
    Container,
    Injection,
    ParameterContract,
    Scalar,
    ValueShape,
    Verdict,
)
from functualize._types.redaction import Secret

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic.fields import FieldInfo

__all__ = ["REQUIRED", "admit", "build_contract", "build_contracts"]
__all__ += ["build_field_contract", "shape_json_schema"]

#: ``default_json`` of a parameter with no default: the descriptor codec's own
#: sentinel, so a contract and its descriptor encode "required" alike.
REQUIRED: str = _REQUIRED_SENTINEL

#: B-3's scalars. Each one's ``__name__`` is its ``Scalar`` value.
_SCALAR_TYPES = frozenset({str, int, float, bool, uuid.UUID, decimal.Decimal})
_SCALAR_TYPES |= {_dt.date, _dt.datetime, _dt.time, _dt.timedelta}
_PYTHON: dict[Scalar, type] = {Scalar(t.__name__): t for t in _SCALAR_TYPES}
_PYTHON[Scalar.PATH] = pathlib.Path
#: Containers a command line cannot spell; supplied over MCP, HTTP, Lambda (B-5).
_INVOCATION_ONLY = frozenset({Container.SET, Container.DICT, Container.FIXED_TUPLE})
_REPEATABLE = frozenset({Container.LIST, Container.TUPLE})
_BARE = (list, tuple, set, frozenset, dict)
#: ``Annotated[Iterator[Row], Stdin()]`` streams piped rows (``stdin_reader``).
_STREAMS: tuple[Any, ...] = (_abc.Iterator, _abc.Iterable, _abc.Generator)
_STREAMS += (_abc.AsyncIterator, _abc.AsyncIterable)
_SKIPPED_KINDS = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)

#: Every refusal, in the page's §5.7 shape: ``<reason>. <remedy>``.
_REASONS = {
    "unevaluable": "The annotation {what!r} cannot be evaluated{detail}. Import every name it uses at module level",
    "positional": "Parameter {name!r} is positional-only, and no surface passes a value by position alone. Remove the '/' from the signature",
    "markers": "Parameter {name!r} declares more than one CLI marker ({what}). Keep one",
    "both": "Parameter {name!r} is marked both as a caller input and as injected. Keep one marker",
    "unconvertible": "{what}() marks '{type}', which no surface converts from text. Declare a scalar type, or drop the marker and register a provider",
    "unspellable": "{what}() marks '{type}', which a command line cannot spell. Drop the marker: the value is supplied over MCP, HTTP or Lambda",
    "union": "'{type}' is a union of {what} types. Declare one type, optionally with '| None'",
    "no_value": "'{type}' names no value a caller can supply. Declare a concrete type",
    "secret_param": "Secret[str] is supported only as a config field. Move it to the job's config model",
    "secret_type": "'{type}' cannot keep its type: Secret stores text. Declare Secret[str] and convert at the point of use",
    "dict_key": "'{type}' has non-text keys. Declare dict[str, T]",
    "element": "'{type}' {what}. Declare a container of a scalar or an Enum",
    "unsupported": "'{type}' is not a supported parameter type. Declare a scalar, an Enum, or a list, tuple, set or dict of one",
    "config": "Config field {name!r} has type '{type}', which no config source or flag can supply. Declare a scalar, an Enum, Secret[str], or list[T] or tuple[T, ...] of a scalar",
    "choice_set": "'{type}' is a choice set whose values are not all str or all int. Use an Enum whose values are all str or all int",
    "provider": "No provider is registered for {type} {what}. Register one from a plugin, or declare a type the caller supplies",
}


class _RefusalError(Exception):
    """A declaration on the reject list (B-8)."""

    def __init__(self, key: str, tp: Any = None, **fields: Any) -> None:
        super().__init__(_REASONS[key].format(type=_display(tp), **fields))


def build_contracts(func: Callable[..., Any]) -> tuple[ParameterContract, ...]:
    """Each parameter's contract, in order; skips self/cls/*args/**kwargs, as the engine does."""
    hints = resolved_hints(func)
    contracts: list[ParameterContract] = []
    for name, parameter in inspect.signature(func).parameters.items():
        if name in ("self", "cls") or parameter.kind in _SKIPPED_KINDS:
            continue
        annotation = hints.get(name, parameter.annotation)
        if isinstance(annotation, str):
            try:
                annotation = _evaluate(func, annotation)
            except Exception as exc:
                if annotation.strip() in INJECTED_PARAM_TYPE_NAMES:
                    contracts.append(build_contract(parameter, annotation))
                    continue
                why = _RefusalError("unevaluable", what=annotation, detail=f" ({exc})")
                has_default, default = _declared_default(parameter.default)
                contracts.append(_rejected(name, annotation, has_default, default, why))
                continue
        if _reads_from_step(annotation):
            continue
        contracts.append(build_contract(parameter, annotation))
    return tuple(contracts)


def _reads_from_step(annotation: Any) -> bool:
    """A step value is supplied by the walk, outside the caller contract."""
    _, metadata = _split(annotation)
    return any(isinstance(item, FromStep) for item in metadata)


def build_contract(
    parameter: inspect.Parameter, annotation: Any = inspect.Parameter.empty
) -> ParameterContract:
    """One signature parameter's contract; ``annotation`` is its resolved hint."""
    if annotation is inspect.Parameter.empty:
        annotation = parameter.annotation
    has_default, default = _declared_default(parameter.default)
    try:
        return _classify(parameter, annotation, has_default, default)
    except _RefusalError as refusal:
        return _rejected(parameter.name, annotation, has_default, default, refusal)


def build_field_contract(
    name: str, field: FieldInfo, *, group: bool = False
) -> ParameterContract:
    """A config (``CONFIG_FIELD``) or group field; ``dict``/models refused (F-29)."""
    annotation = field.annotation
    option = next((m for m in field.metadata if isinstance(m, Option)), None)
    has_default = not field.is_required()
    default = field.get_default(call_default_factory=True) if has_default else None
    try:
        shape = _value_shape(annotation, config=True)
        if shape is None or shape.container in _INVOCATION_ONLY:
            raise _RefusalError("config", annotation, name=name)
    except _RefusalError as refusal:
        return _rejected(name, annotation, has_default, default, refusal)
    verdict = Verdict.ACCEPTED_FLAG if group else Verdict.CONFIG_FIELD
    cli = _flag(name, shape, option)
    contract = _contract(name, verdict, annotation, has_default, default, shape, cli)
    description = field.description or (option.help if option else None) or ""
    return dataclasses.replace(contract, description=description)


def admit(
    contract: ParameterContract, has_provider: Callable[[str, str | None], bool]
) -> ParameterContract:
    """Apply spec B-2's availability rule; pure, the registry is the caller's.

    ``has_provider(provider_type, qualifier)`` answers for **exactly** that pair: a
    type registered only under other qualifiers answers ``False`` for ``None``,
    as resolving it is ambiguous. Only an ``INJECTED`` contract with a
    ``provider_type`` can change; capabilities and ``FromJob`` never do.
    """
    injection = contract.injection
    if (
        contract.verdict is not Verdict.INJECTED
        or injection is None
        or injection.provider_type is None
        or has_provider(injection.provider_type, injection.qualifier)
    ):
        return contract
    qualifier = injection.qualifier
    what = (
        "without a qualifier" if qualifier is None else f"with qualifier {qualifier!r}"
    )
    provider_type = injection.provider_type
    # The synchronous loader's module suffix includes a process-local id.
    # Keep that qualified key for provider lookup, but never put it in the
    # caller's refusal: cold and warm boots must name the same declaration.
    display_type = (
        provider_type.rsplit(".", 1)[-1]
        if provider_type.startswith("_functualize_sync_.")
        else provider_type
    )
    reason = _REASONS["provider"].format(type=display_type, what=what)
    return dataclasses.replace(
        contract, verdict=Verdict.REJECTED_DISCOVERY, reject_reason=reason
    )


def shape_json_schema(shape: ValueShape) -> dict[str, Any]:
    """The one shape-to-JSON-Schema function (D4, B-20); absence is ``required``."""
    from pydantic import TypeAdapter

    return TypeAdapter(_python_type(shape)).json_schema()


def _classify(
    parameter: inspect.Parameter, annotation: Any, has_default: bool, default: Any
) -> ParameterContract:
    name = parameter.name
    if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
        raise _RefusalError("positional", name=name)
    if annotation is inspect.Parameter.empty:
        annotation = str  # an unannotated parameter is text (C090, C091)
    if isinstance(annotation, str):
        capability = annotation.strip()
        if capability in INJECTED_PARAM_TYPE_NAMES:
            return dataclasses.replace(
                _contract(name, Verdict.INJECTED, annotation, has_default, default),
                injection=Injection(capability=capability),
            )
        raise _RefusalError("unevaluable", what=annotation, detail="")
    base, meta = _split(annotation)
    markers = [m for m in meta if isinstance(m, (Arg, Option, Stdin))]
    from_job = next((m for m in meta if isinstance(m, FromJob)), None)
    # Matched by name: this module may not import `di.py` (schema invariant 1).
    provide = next((m for m in meta if type(m).__name__ == "Provide"), None)
    if len(markers) > 1:
        spelled = ", ".join(f"{type(m).__name__}()" for m in markers)
        raise _RefusalError("markers", name=name, what=spelled)
    marker = markers[0] if markers else None
    if marker is not None and (from_job is not None or provide is not None):
        raise _RefusalError("both", name=name)
    texts = (getattr(m, "help", None) or getattr(m, "description", None) for m in meta)
    description = next((t for t in texts if isinstance(t, str) and t), "")

    def done(contract: ParameterContract, **extra: Any) -> ParameterContract:
        return dataclasses.replace(contract, description=description, **extra)

    def injected(injection: Injection) -> ParameterContract:
        contract = _contract(name, Verdict.INJECTED, annotation, has_default, default)
        return done(contract, injection=injection)

    if from_job is not None:
        return injected(Injection(from_job=from_job.name))
    inner, optional = _unwrap_optional(base)
    if provide is not None:
        qualifier = getattr(provide, "qualifier", None)
        return injected(Injection(qualifier=qualifier, provider_type=_qualname(inner)))
    if marker is None and isinstance(inner, type):
        if inner.__name__ in INJECTED_PARAM_TYPE_NAMES:
            return injected(Injection(capability=inner.__name__))
        if inner is base and _is_model_parameter(inner):
            return injected(Injection())  # config model or GroupOptions: engine-filled
    if isinstance(marker, Stdin) and _origin(inner) in _STREAMS:
        shape = ValueShape(Scalar.STR, Container.LIST, optional=optional)
    else:
        found = _value_shape(base, config=False)
        if found is None and marker is not None:
            raise _RefusalError("unconvertible", inner, what=type(marker).__name__)
        if found is None:  # an unmarked class that is not a value type
            return injected(Injection(provider_type=_qualname(inner)))
        shape = found
    if shape.container in _INVOCATION_ONLY:
        if marker is not None:
            raise _RefusalError("unspellable", base, what=type(marker).__name__)
        verdict, cli = Verdict.INVOCATION_ONLY, None
    else:
        repeatable = shape.container in _REPEATABLE
        if shape.scalar is Scalar.BOOL and not repeatable and not has_default:
            has_default, default = True, False  # a bare bool: off-by-default flag
        positional = marker is None and not repeatable and not has_default
        if isinstance(marker, Arg) or positional:
            verdict = Verdict.ACCEPTED_POSITIONAL
            cli = CliSpelling(long=None, positional=True, variadic=repeatable)
        else:
            verdict, cli = Verdict.ACCEPTED_FLAG, _flag(name, shape, marker)
    return done(_contract(name, verdict, annotation, has_default, default, shape, cli))


def _value_shape(tp: Any, *, config: bool) -> ValueShape | None:
    """The caller-supplied shape of ``tp``; None for a class that is not a value."""
    inner, optional = _unwrap_optional(tp)
    if inner is object or inner is Any:
        raise _RefusalError("no_value", inner)
    if _is_secret(inner):
        if not config:
            raise _RefusalError("secret_param")
        if _args(inner) not in ((), (str,)):
            raise _RefusalError("secret_type", inner)
        shape: ValueShape | None = ValueShape(Scalar.SECRET_STR)
    else:
        shape = _scalar(inner) or _container(inner)
    if shape is not None and optional:
        shape = dataclasses.replace(shape, optional=True)
    return shape


def _container(tp: Any) -> ValueShape | None:
    origin = tp if tp in _BARE else _origin(tp)
    args = _args(tp)
    if origin is list:
        return _repeated(tp, Container.LIST, args)
    if origin in (set, frozenset):
        return _repeated(tp, Container.SET, args)
    if origin is tuple:
        if not args or (len(args) == 2 and args[1] is Ellipsis):
            return _repeated(tp, Container.TUPLE, args)
        members = tuple(_element(tp, a) for a in args)
        return ValueShape(members[0].scalar, Container.FIXED_TUPLE, elements=members)
    if origin is dict:
        key, value = args or (str, str)
        if key is not str:
            raise _RefusalError("dict_key", tp)
        element = _element(tp, value)
        return ValueShape(element.scalar, Container.DICT, elements=(element,))
    if isinstance(tp, type) and origin is None:
        return None  # a class: injected, if a provider exists (B-2)
    raise _RefusalError("unsupported", tp)


def _repeated(tp: Any, container: Container, args: tuple[Any, ...]) -> ValueShape:
    element = _element(tp, args[0] if args else str)
    return dataclasses.replace(element, container=container)


def _element(outer: Any, tp: Any) -> ValueShape:
    shape = _scalar(tp)
    if shape is not None:
        return shape
    if _is_secret(tp):
        what = "holds Secret values, which only a config field may declare"
    elif _origin(tp) is not None or tp in _BARE:
        what = "nests a container"
    else:
        what = f"holds '{_display(tp)}', which is not a supported scalar"
    raise _RefusalError("element", outer, what=what)


def _scalar(tp: Any) -> ValueShape | None:
    if _origin(tp) is Literal:
        return _choices(tp, _args(tp))
    if not isinstance(tp, type):
        return None
    if issubclass(tp, enum.Enum):
        values = tuple(member.value for member in tp)
        return _choices(tp, values) if values else None
    if issubclass(tp, pathlib.PurePath):
        return ValueShape(Scalar.PATH)
    return ValueShape(Scalar(tp.__name__)) if tp in _SCALAR_TYPES else None


def _choices(tp: Any, values: tuple[Any, ...]) -> ValueShape:
    """A choice set keeps its values' type; any but all-str or all-int (bool, float,
    None, mixed) is refused (B-3)."""
    if {type(value) for value in values} not in ({str}, {int}):
        raise _RefusalError("choice_set", tp)
    return ValueShape(Scalar.ENUM, enum_values=values)


def _contract(
    name: str,
    verdict: Verdict,
    annotation: Any,
    has_default: bool,
    default: Any,
    shape: ValueShape | None = None,
    cli: CliSpelling | None = None,
) -> ParameterContract:
    """A contract; ``shape`` and ``json_schema`` only for a value verdict."""
    return ParameterContract(
        name=name,
        verdict=verdict,
        shape=shape,
        required=not has_default,
        default_json=_default_json(has_default, default, shape),
        cli=cli,
        json_schema=shape_json_schema(shape) if shape is not None else None,
        display=_display(annotation),
    )


def _rejected(
    name: str, annotation: Any, has_default: bool, default: Any, why: Exception
) -> ParameterContract:
    rejected = Verdict.REJECTED_DISCOVERY
    contract = _contract(name, rejected, annotation, has_default, default)
    return dataclasses.replace(contract, reject_reason=str(why))


def _flag(name: str, shape: ValueShape, marker: Any) -> CliSpelling:
    long = "--" + name.replace("_", "-")
    short = envvar = stdin_flag = None
    hidden = stdin = False
    if isinstance(marker, Option):
        long, short = marker.long or long, marker.short
        hidden, envvar = marker.hidden, marker.envvar
    elif isinstance(marker, Stdin):
        stdin, stdin_flag = True, marker.flag
        long = marker.flag or long
    single_bool = shape.scalar is Scalar.BOOL and shape.container is Container.NONE
    return CliSpelling(
        long=long,
        short=short,
        negative=f"--no-{long.removeprefix('--')}" if single_bool else None,
        repeatable=shape.container in _REPEATABLE,
        hidden=hidden,
        envvar=envvar,
        stdin=stdin,
        stdin_flag=stdin_flag,
    )


def _default_json(has_default: bool, default: Any, shape: ValueShape | None) -> Any:
    """JSON-native default; never a secret, and None for an unencodable object."""
    if not has_default:
        return REQUIRED
    if isinstance(default, Secret) or (shape and shape.scalar is Scalar.SECRET_STR):
        return None
    from pydantic_core import to_jsonable_python

    try:
        return to_jsonable_python(default)
    except Exception:
        return None


def _python_type(shape: ValueShape) -> Any:
    """The Python type a shape stands for, for pydantic's schema generator."""
    if shape.container is Container.FIXED_TUPLE:
        members = tuple(_python_type(e) for e in shape.elements)
        return types.GenericAlias(tuple, members)
    if shape.container is Container.DICT:
        return types.GenericAlias(dict, (str, _python_type(shape.elements[0])))
    element: Any = _PYTHON.get(shape.scalar)
    if shape.scalar is Scalar.ENUM:
        element = cast("Any", Literal)[shape.enum_values]
    elif shape.scalar is Scalar.SECRET_STR:
        from pydantic import SecretStr

        element = SecretStr
    if shape.container is Container.TUPLE:
        return types.GenericAlias(tuple, (element, ...))
    generic = {Container.LIST: list, Container.SET: set}.get(shape.container)
    return types.GenericAlias(generic, (element,)) if generic else element


def _evaluate(func: Callable[..., Any], annotation: str) -> Any:
    """``get_type_hints``' per-parameter fallback: same eval, same globals."""
    namespace = getattr(inspect.unwrap(func), "__globals__", {})
    return eval(annotation, dict(namespace))


def _declared_default(default: Any) -> tuple[bool, Any]:
    """``(has_default, value)``, unwrapping a pydantic ``Field(...)`` default."""
    if default is inspect.Parameter.empty:
        return False, None
    if type(default).__name__ == "FieldInfo" and hasattr(default, "is_required"):
        if default.is_required():
            return False, None
        return True, default.get_default(call_default_factory=True)
    return True, default


def _split(annotation: Any) -> tuple[Any, tuple[Any, ...]]:
    if _origin(annotation) is Annotated:
        args = _args(annotation)
        return args[0], tuple(args[1:])
    return annotation, ()


def _unwrap_optional(tp: Any) -> tuple[Any, bool]:
    """``(T, True)`` for ``Optional[T]`` / ``T | None``; refuses a wider union."""
    if _origin(tp) not in (Union, types.UnionType):
        return tp, False
    rest = [a for a in _args(tp) if a is not type(None)]
    if len(rest) == 1:
        return rest[0], True
    raise _RefusalError("union", tp, what=len(rest))


def _is_secret(tp: Any) -> bool:
    return tp is Secret or _origin(tp) is Secret


def _is_model_parameter(tp: type) -> bool:
    """A job's config model or a ``GroupOptions`` model: filled by the engine."""
    if is_group_options_subclass(tp):
        return True
    from pydantic import BaseModel

    return issubclass(tp, BaseModel) and tp is not BaseModel


def _qualname(tp: Any) -> str:
    return (
        f"{tp.__module__}.{tp.__qualname__}" if isinstance(tp, type) else _display(tp)
    )


def _display(tp: Any) -> str:
    """The human type label (``contract.display``), without module prefixes."""
    if isinstance(tp, str):
        return tp
    if tp is inspect.Parameter.empty or tp is None:
        return ""
    if tp is type(None) or tp is Ellipsis:
        return "None" if tp is type(None) else "..."
    origin, args = _origin(tp), _args(tp)
    if origin is Annotated:
        return _display(args[0])
    if origin in (Union, types.UnionType):
        return " | ".join(_display(a) for a in args)
    if origin is Literal:
        return f"Literal[{', '.join(repr(a) for a in args)}]"
    if origin is not None:
        head = getattr(origin, "__name__", str(origin))
        return f"{head}[{', '.join(_display(a) for a in args)}]" if args else head
    return tp.__name__ if isinstance(tp, type) else str(tp).replace("typing.", "")
