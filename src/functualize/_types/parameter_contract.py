"""Immutable, cacheable declaration of a job parameter's surface contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Verdict(Enum):
    ACCEPTED_FLAG = "accepted_flag"
    ACCEPTED_POSITIONAL = "accepted_positional"
    INJECTED = "injected"
    CONFIG_FIELD = "config_field"
    INVOCATION_ONLY = "invocation_only"
    REJECTED_DISCOVERY = "rejected_discovery"


class Scalar(Enum):
    STR = "str"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    PATH = "Path"
    UUID = "UUID"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    TIMEDELTA = "timedelta"
    DECIMAL = "Decimal"
    ENUM = "enum"
    SECRET_STR = "Secret[str]"
    CLASS = "class"


class Container(Enum):
    NONE = "none"
    LIST = "list"
    TUPLE = "tuple"
    SET = "set"
    DICT = "dict"
    FIXED_TUPLE = "fixed_tuple"


@dataclass(frozen=True)
class ValueShape:
    scalar: Scalar
    container: Container = Container.NONE
    optional: bool = False
    enum_values: tuple[str, ...] = ()
    elements: tuple[ValueShape, ...] = ()


@dataclass(frozen=True)
class CliSpelling:
    long: str | None
    short: str | None = None
    negative: str | None = None
    positional: bool = False
    variadic: bool = False
    repeatable: bool = False
    hidden: bool = False
    envvar: str | None = None
    stdin: bool = False
    stdin_flag: str | None = None


@dataclass(frozen=True)
class Injection:
    capability: str | None = None
    qualifier: str | None = None
    from_job: str | None = None
    provider_type: str | None = None


@dataclass(frozen=True)
class ParameterContract:
    name: str
    verdict: Verdict
    shape: ValueShape | None
    required: bool
    default_json: Any
    cli: CliSpelling | None
    json_schema: dict[str, Any] | None
    injection: Injection | None = None
    reject_reason: str | None = None
    display: str = ""
    description: str = ""
