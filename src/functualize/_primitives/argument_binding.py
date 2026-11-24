"""The one binding step between a surface's raw values and a job's arguments.

Spec B-23 to B-26: every surface hands its raw values here before the job
runs, and binding is the only place a value a surface supplies becomes a job
argument. It reads the job's parameter contracts, which decide what a caller may
supply at all, and converts each value with a pydantic ``TypeAdapter`` built from
the live annotation, so ``Field(...)`` constraints hold on every surface.

It refuses, before the job is called, a call that supplies an unknown key, a
value for an ``INJECTED`` parameter, or a value that does not convert; that
omits a required argument; or that reaches a parameter discovery refused
(DC-1 = B: the job stays listed and refuses when called). Each refusal is a
:class:`BindRefusal` naming the argument and the reason, never a ``TypeError``
or a ``ValidationError``; the surface renders it.

The result holds only supplied and defaulted values. DI then fills the
``INJECTED`` names and nothing else (B-29).

pydantic is imported lazily, as in the other ``_primitives`` modules that use it.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from functualize._primitives.parameter_contract import REQUIRED
from functualize._types.annotations import resolved_hints
from functualize._types.parameter_contract import (
    Container,
    ParameterContract,
    Scalar,
    ValueShape,
    Verdict,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = ["COMMAND_LINE_SURFACES", "ArgumentBinder", "BindRefusal"]

#: Surfaces that parse a command line: an ``INVOCATION_ONLY`` parameter has no
#: spelling on them (B-15), so a required one makes the call a usage error
#: naming the surfaces that do accept it.
COMMAND_LINE_SURFACES: frozenset[str] = frozenset(
    {"func.job", "func.group", "func.single-file", "app.cli", "tui.inline", "tui.shell"}
)

#: Verdicts whose value a caller supplies, so binding accepts and converts them.
_CALLER_VERDICTS = frozenset(
    {Verdict.ACCEPTED_FLAG, Verdict.ACCEPTED_POSITIONAL, Verdict.INVOCATION_ONLY}
)


class BindRefusal(Exception):  # noqa: N818 - the name the schema fixes
    """A call the job's declaration does not admit; nothing ran.

    Attributes:
        argument: The argument the refusal is about, or None for the call.
        reason: What is wrong and how to fix it, ready to render.
    """

    def __init__(self, argument: str | None, reason: str) -> None:
        self.argument = argument
        self.reason = reason
        super().__init__(reason)


class ArgumentBinder:
    """Binds raw surface values to one job's arguments.

    Holds one ``TypeAdapter`` per ``(function, parameter)``, built on first
    use and kept on this instance, not in module state: the engine owns one
    binder, and an adapter outlives no app that built it. Keyed by the callable
    itself, never by ``id()`` (schema invariant 8); an unhashable callable
    cannot be a key, so its values are converted uncached rather than refused.
    """

    def __init__(self) -> None:
        self._adapters: dict[tuple[Callable[..., Any], str], Any] = {}

    def bind(
        self,
        function: Callable[..., Any],
        contracts: Sequence[ParameterContract],
        raw: Mapping[str, Any],
        *,
        surface: str,
    ) -> dict[str, Any]:
        """The job's caller-supplied and defaulted arguments, converted.

        Args:
            function: The live job function, whose annotations convert values.
            contracts: Its parameters' contracts, after availability (``admit``).
            raw: What the surface supplied, by parameter name.
            surface: The ``RunSurface`` the call arrived on.

        Raises:
            BindRefusal: The call is not admitted; the job must not run.
        """
        by_name = {contract.name: contract for contract in contracts}
        for name in raw:
            contract = by_name.get(name)
            if contract is None:
                accepted = sorted(
                    c.name for c in contracts if c.verdict in _CALLER_VERDICTS
                )
                listing = ", ".join(accepted) if accepted else "no arguments"
                raise BindRefusal(
                    name, f"Unknown argument {name!r}. This job accepts: {listing}"
                )
            if contract.verdict is Verdict.INJECTED:
                raise BindRefusal(
                    name,
                    f"Argument {name!r} is supplied by the framework, not the "
                    "caller. Remove it from the call",
                )
            if contract.verdict is Verdict.CONFIG_FIELD:
                raise BindRefusal(
                    name,
                    f"{name!r} is a config field, resolved from configuration. Set "
                    "it in a config file, the environment, or its flag",
                )
        for contract in contracts:
            if contract.verdict is Verdict.REJECTED_DISCOVERY:
                raise BindRefusal(
                    contract.name,
                    f"Parameter {contract.name!r} was refused at discovery: "
                    f"{contract.reject_reason}",
                )

        bound: dict[str, Any] = {}
        for contract in contracts:
            if contract.verdict not in _CALLER_VERDICTS:
                continue
            name = contract.name
            if name in raw:
                bound[name] = self._convert(function, contract, raw[name])
            elif contract.required:
                raise BindRefusal(name, _missing(contract, surface))
            else:
                bound[name] = self._default(function, contract)
        return bound

    def _convert(
        self, function: Callable[..., Any], contract: ParameterContract, value: Any
    ) -> Any:
        from pydantic import ValidationError

        adapter = self._adapter(function, contract.name)
        try:
            return adapter.validate_python(_choice_tokens(contract.shape, value))
        except ValidationError as exc:
            detail = exc.errors()[0].get("msg", str(exc)) if exc.errors() else str(exc)
            label = contract.display or "the declared type"
            raise BindRefusal(
                contract.name,
                f"Invalid value for {contract.name!r}: {value!r} is not a valid "
                f"{label} ({detail})",
            ) from None

    def _default(
        self, function: Callable[..., Any], contract: ParameterContract
    ) -> Any:
        """The declared default, decoded from ``default_json`` to the declared type.

        ``None`` stays ``None`` (B-12: ``p: list[str] = None`` is ``None``, not a
        validation error). A default the adapter cannot decode — an object JSON
        could not carry — falls back to the signature's own default.
        """
        encoded = contract.default_json
        if encoded is None or encoded == REQUIRED:
            return None if encoded is None else _signature_default(function, contract)
        try:
            return self._adapter(function, contract.name).validate_python(encoded)
        except Exception:
            return _signature_default(function, contract)

    def _adapter(self, function: Callable[..., Any], name: str) -> Any:
        from pydantic import TypeAdapter

        key = (function, name)
        try:
            adapter = self._adapters.get(key)
        except TypeError:  # an unhashable callable: convert, but cannot cache
            return TypeAdapter(_annotation(function, name))
        if adapter is None:
            adapter = self._adapters[key] = TypeAdapter(_annotation(function, name))
        return adapter


def _annotation(function: Callable[..., Any], name: str) -> Any:
    """The live annotation, ``Annotated`` metadata (``Field(...)``) included."""
    hint = resolved_hints(function).get(name)
    if hint is not None:
        return hint
    parameter = inspect.signature(function).parameters[name]
    annotation = parameter.annotation
    if annotation is inspect.Parameter.empty:
        # No declared type: one door, one rule — the value is text (C090, C091),
        # so an unannotated parameter is `str` whatever the caller sent.
        return str
    if isinstance(annotation, str):  # PEP 563, and the whole-function hints failed
        namespace = getattr(inspect.unwrap(function), "__globals__", {})
        return eval(annotation, dict(namespace))
    return annotation


def _signature_default(
    function: Callable[..., Any], contract: ParameterContract
) -> Any:
    default = inspect.signature(function).parameters[contract.name].default
    return None if default is inspect.Parameter.empty else default


def _choice_tokens(shape: ValueShape | None, value: Any) -> Any:
    """Map a text token to the ``int`` choice it spells, before conversion (B-3).

    A text surface spells a choice as ``str(value)``. For an ``int`` choice set
    the adapter would refuse ``"1"``, so the token becomes the choice whose
    ``str()`` it equals. A ``str`` set needs no mapping; anything else is left
    for the adapter to accept or refuse.
    """
    if shape is None:
        return value
    if shape.container is Container.DICT and isinstance(value, dict):
        element = shape.elements[0]
        return {key: _choice_tokens(element, item) for key, item in value.items()}
    if shape.container is Container.FIXED_TUPLE and isinstance(value, list | tuple):
        if len(value) != len(shape.elements):
            return value  # the adapter refuses the wrong arity; never truncate
        pairs = zip(shape.elements, value, strict=True)
        return [_choice_tokens(element, item) for element, item in pairs]
    if shape.scalar is not Scalar.ENUM or not all(
        type(choice) is int for choice in shape.enum_values
    ):
        return value
    by_text = {str(choice): choice for choice in shape.enum_values}

    def one(item: Any) -> Any:
        return by_text.get(item, item) if isinstance(item, str) else item

    if shape.container is Container.NONE:
        return one(value)
    if isinstance(value, list | tuple | set | frozenset):
        return type(value)(one(item) for item in value)
    return value


def _missing(contract: ParameterContract, surface: str) -> str:
    if contract.verdict is Verdict.INVOCATION_ONLY and surface in COMMAND_LINE_SURFACES:
        return (
            f"Parameter {contract.name!r} can only be supplied over MCP, HTTP or Lambda"
        )
    return f"Missing required argument {contract.name!r}"
