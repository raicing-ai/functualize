"""Give a hand-built ``FieldDescriptor`` the contract discovery would decide.

Discovery has attached a parameter contract to every field since task 3.2, and
the click renderer reads only the contract: a field without one has no
rendering (``build_click_params_from_fields`` refuses it). Tests that build
field records by hand describe a declaration in the record's terms — a type
string, a default, ``positional``, ``short_flag``, ``from_config_model``.
:func:`with_contract` writes that declaration as Python, classifies it with the
real classifier, and attaches the result, so a fake renders exactly as the
declaration it stands for would after discovery.

- A signature parameter is classified by ``build_contracts`` over a generated
  function: ``Arg()`` for ``positional``, ``Option("-x")`` for
  ``short_flag``, ``Stdin(flag=...)`` for ``is_stdin``, ``Literal[...]`` for
  ``choices``.
- A config-model field (``from_config_model``) and a group option
  (``group=True``) are classified by ``build_field_contract`` over a generated
  pydantic model, as discovery classifies them.
"""

from __future__ import annotations

import dataclasses
import datetime
import decimal
import keyword
import pathlib
import types
import typing
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from functualize._types.descriptors import FieldDescriptor

__all__ = ["declared", "with_contract", "with_contracts"]


def declared(
    name: str,
    annotation: str = "str",
    *,
    default: Any = None,
    required: bool = False,
    positional: bool = False,
    short_flag: str | None = None,
    is_stdin: bool = False,
    stdin_flag: str | None = None,
    choices: list[str] | None = None,
    description: str = "",
    from_config_model: bool = False,
    group: bool = False,
    secret: bool = False,
) -> FieldDescriptor:
    """Build a field with the contract discovery assigns to its declaration.

    The annotation is an input to the declaration, not a second type label on
    the resulting descriptor. It remains explicit when the descriptor's old
    string field is deleted.
    """
    from functualize.types import FieldDescriptor

    source = types.SimpleNamespace(
        name=name,
        annotation=annotation,
        default=default,
        required=required,
        positional=positional,
        short_flag=short_flag,
        is_stdin=is_stdin,
        stdin_flag=stdin_flag,
        choices=choices,
        description=description,
        from_config_model=from_config_model,
    )
    contract = (
        _model_contract(source, group=group)
        if group or from_config_model
        else _signature_contract(source)
    )
    return FieldDescriptor(
        name=name,
        default=default,
        description=description,
        required=required,
        choices=choices,
        positional=positional,
        short_flag=short_flag,
        is_stdin=is_stdin,
        stdin_flag=stdin_flag,
        secret=secret,
        from_config_model=from_config_model,
        contract=contract,
    )


def _namespace() -> dict[str, Any]:
    from functualize.job.markers import Arg, Option, Stdin

    return {
        **{name: getattr(typing, name) for name in typing.__all__},
        "Path": pathlib.Path,
        "UUID": uuid.UUID,
        "Decimal": decimal.Decimal,
        "date": datetime.date,
        "datetime": datetime.datetime,
        "time": datetime.time,
        "timedelta": datetime.timedelta,
        "Arg": Arg,
        "Option": Option,
        "Stdin": Stdin,
    }


def _annotation(field: FieldDescriptor, *, marked: bool) -> str:
    """The declaration's annotation, as source."""
    choices = getattr(field, "choices", None)
    if choices:
        values = ", ".join(repr(choice) for choice in choices)
        base = f"Literal[{values}]"
    else:
        base = getattr(field, "annotation", None) or "str"
    markers: list[str] = []
    if marked and getattr(field, "positional", False):
        markers.append("Arg()")
    if short := getattr(field, "short_flag", None):
        markers.append(f"Option({short if short.startswith('-') else '-' + short!r})")
    if marked and getattr(field, "is_stdin", False):
        markers.append(f"Stdin(flag={getattr(field, 'stdin_flag', None)!r})")
    return f"Annotated[{base}, {', '.join(markers)}]" if markers else base


def _signature_contract(field: FieldDescriptor) -> Any:
    from functualize._primitives.parameter_contract import build_contracts

    declared_name = (
        field.name
        if field.name.isidentifier()
        and not keyword.iskeyword(field.name)
        and field.name not in ("self", "cls")
        else "_field"
    )
    default = "" if field.required else f" = {field.default!r}"
    source = (
        f"def _declared({declared_name}: {_annotation(field, marked=True)}{default}):\n"
        "    pass\n"
    )
    namespace = _namespace()
    exec(source, namespace)  # noqa: S102 - a test's own declaration
    (contract,) = build_contracts(namespace["_declared"])
    if declared_name != field.name:
        cli = contract.cli
        if cli is not None:
            long = f"--{field.name.replace('_', '-')}"
            cli = dataclasses.replace(
                cli,
                long=long if cli.long is not None else None,
                negative=f"--no-{field.name.replace('_', '-')}"
                if cli.negative is not None
                else None,
            )
        contract = dataclasses.replace(contract, name=field.name, cli=cli)
    return contract


def _model_contract(field: FieldDescriptor, *, group: bool) -> Any:
    from pydantic import Field, create_model

    from functualize._primitives.parameter_contract import build_field_contract

    namespace = _namespace()
    annotation = eval(_annotation(field, marked=False), namespace)  # noqa: S307
    default = ... if field.required else field.default
    model = create_model(
        "_Declared",
        **{
            field.name: (
                annotation,
                Field(default, description=getattr(field, "description", "") or None),
            )
        },
    )
    return build_field_contract(field.name, model.model_fields[field.name], group=group)


def with_contract(field: FieldDescriptor, *, group: bool = False) -> FieldDescriptor:
    """``field``, carrying the contract discovery decides for its declaration.

    Args:
        field: A hand-built record — a ``FieldDescriptor`` or a row with its
            attributes, such as a ``SimpleNamespace``. A record that already
            carries a contract is returned unchanged.
        group: The field is a group option (a ``GroupOptions`` model field).
    """
    if getattr(field, "contract", None) is not None or not field.name.isidentifier():
        # A name no declaration can spell (``db.host``) has no contract to give.
        return field
    if group or getattr(field, "from_config_model", False):
        contract = _model_contract(field, group=group)
    else:
        contract = _signature_contract(field)
    if dataclasses.is_dataclass(field):
        return dataclasses.replace(field, contract=contract)  # type: ignore[type-var]
    return types.SimpleNamespace(**{**vars(field), "contract": contract})  # type: ignore[return-value]


def with_contracts(
    fields: typing.Iterable[FieldDescriptor], *, group: bool = False
) -> list[FieldDescriptor]:
    """:func:`with_contract` over a field list."""
    return [with_contract(field, group=group) for field in fields]
