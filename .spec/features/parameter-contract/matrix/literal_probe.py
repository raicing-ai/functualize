"""S1/S2 probe: does the published schema agree with the binder for Literal / Enum / Path config fields?

Run from the repository root:
    uv run --frozen python .spec/features/parameter-contract/matrix/literal_probe.py

For each declaration: the contract's verdict and json_schema (what info/MCP publish), then whether
the binder's TypeAdapter (built from the live annotation, as `argument_binding.py:179` does)
accepts (a) each value the schema advertises, as JSON would carry it, and (b) the typed value.
"""

from __future__ import annotations

import enum
import json
from typing import Literal

from pydantic import BaseModel, TypeAdapter

from functualize._config.job_config import SUPPORTED_TYPES
from functualize._primitives.parameter_contract import build_contracts, build_field_contract


class IntLevel(enum.Enum):
    LOW = 1
    HIGH = 2


class StrColor(enum.Enum):
    RED = "red"
    BLUE = "blue"


def s_str(p: Literal["low", "high"]) -> None: ...
def s_int(p: Literal[1, 2]) -> None: ...
def s_mixed(p: Literal["a", 1]) -> None: ...
def s_bool(p: Literal[True]) -> None: ...
def e_str(p: StrColor) -> None: ...
def e_int(p: IntLevel) -> None: ...


def probe(fn, typed) -> None:
    (c,) = build_contracts(fn)
    ann = fn.__annotations__["p"]
    ann = eval(ann) if isinstance(ann, str) else ann
    adapter = TypeAdapter(ann)
    schema = c.json_schema
    print(f"{fn.__name__:8} verdict={c.verdict.name:20} schema={json.dumps(schema)}")
    for v in (schema or {}).get("enum", []):
        try:
            adapter.validate_python(v)
            ok = "accepted"
        except Exception as e:  # noqa: BLE001
            ok = "REFUSED: " + str(e).splitlines()[1].strip()
        print(f"         advertised {v!r:8} -> binder {ok}")
    for v in typed:
        try:
            adapter.validate_python(v)
            ok = "accepted"
        except Exception as e:  # noqa: BLE001
            ok = "REFUSED"
        print(f"         typed      {v!r:8} -> binder {ok}")


probe(s_str, ["low"])
probe(s_int, [1])
probe(s_mixed, ["a", 1])
probe(s_bool, [True])
probe(e_str, ["red"])
probe(e_int, [1])

print()
print("config converter set (_config/job_config.py SUPPORTED_TYPES):", [t.__name__ for t in SUPPORTED_TYPES])
import pathlib


class Cfg(BaseModel):
    root: pathlib.Path = pathlib.Path(".")


print()
print("### S2: a Path config field today")
from functualize._config.job_config import _coerce_for_field, validate_job_config_types

coerced = _coerce_for_field("/tmp/x", pathlib.Path)
print("resolution path (_coerce_for_field then the model):", type(Cfg(root=coerced).root).__name__,
      "<- what `func` does (resolve_job_config -> config_class(**resolved))")
try:
    validate_job_config_types(Cfg)
    print("validate_job_config_types(Cfg): accepted")
except TypeError as e:
    print("validate_job_config_types(Cfg): REFUSED:", str(e).splitlines()[0])
fc = build_field_contract("root", Cfg.model_fields["root"])
print("build_field_contract(Path field) ->", fc.verdict.name, json.dumps(fc.json_schema))

print()
print("### S1: what the typed form publishes (pydantic, as shape_json_schema uses it)")
for t in (Literal["low", "high"], Literal[1, 2], list[Literal[1, 2]]):
    print(f"  {t!s:32} -> {json.dumps(TypeAdapter(t).json_schema())}")
