# Internal types — the parameter contract

Names are provisional (page `SD/28901379` §7). The shape is what `plan.md` relies on. All types are
frozen, stdlib-only dataclasses and enums in `src/functualize/_types/parameter_contract.py`, because
`FieldDescriptor` (`_types/descriptors.py`) carries them and `_types` may import nothing internal.

```python
class Verdict(Enum):
    ACCEPTED_FLAG = "accepted_flag"
    ACCEPTED_POSITIONAL = "accepted_positional"
    INJECTED = "injected"
    CONFIG_FIELD = "config_field"
    INVOCATION_ONLY = "invocation_only"
    REJECTED_DISCOVERY = "rejected_discovery"


class Scalar(Enum):        # the caller-supplied element types (spec B-3)
    STR = "str"; INT = "int"; FLOAT = "float"; BOOL = "bool"; PATH = "Path"; UUID = "UUID"
    DATE = "date"; DATETIME = "datetime"; TIME = "time"; TIMEDELTA = "timedelta"
    DECIMAL = "Decimal"; ENUM = "enum"; SECRET_STR = "Secret[str]"; CLASS = "class"   # CLASS: a marked convertible class


class Container(Enum):
    NONE = "none"; LIST = "list"; TUPLE = "tuple"; SET = "set"; DICT = "dict"; FIXED_TUPLE = "fixed_tuple"


@dataclass(frozen=True)
class ValueShape:
    scalar: Scalar
    container: Container = Container.NONE
    optional: bool = False                 # `T | None` / `Optional[T]`
    enum_values: tuple[str, ...] | tuple[int, ...] = ()   # typed as declared (B-3 choice sets; task 4.4)      # Scalar.ENUM only, in declaration order
    elements: tuple["ValueShape", ...] = ()  # FIXED_TUPLE members; DICT value shape


@dataclass(frozen=True)
class CliSpelling:                         # data only — no click import (constitution, Forbidden Patterns)
    long: str | None                       # "--targets"; None for a positional
    short: str | None = None               # "-t"
    negative: str | None = None            # "--no-dry-run" when the bool pair owns it (negative_flag_for)
    positional: bool = False
    variadic: bool = False                 # Annotated[list[T], Arg()]
    repeatable: bool = False
    hidden: bool = False
    envvar: str | None = None
    stdin: bool = False
    stdin_flag: str | None = None


@dataclass(frozen=True)
class Injection:                           # verdict INJECTED only
    capability: str | None = None          # one of INJECTED_PARAM_TYPE_NAMES
    qualifier: str | None = None           # Provide("q")
    from_job: str | None = None            # FromJob target name
    provider_type: str | None = None       # the declared type's qualified name, for Provide("q") AND an unmarked class;
                                           # with `qualifier`, the one dependency B-2's availability rule checks


@dataclass(frozen=True)
class ParameterContract:
    name: str
    verdict: Verdict
    shape: ValueShape | None               # None for INJECTED / REJECTED_DISCOVERY
    required: bool
    default_json: Any                      # JSON-native encoding of the declared default, or a REQUIRED sentinel
    cli: CliSpelling | None                # None unless ACCEPTED_FLAG / ACCEPTED_POSITIONAL / CONFIG_FIELD
    json_schema: dict[str, Any] | None     # the published property; None for INJECTED / REJECTED_DISCOVERY
    injection: Injection | None = None
    reject_reason: str | None = None       # REJECTED_DISCOVERY: "<reason>. <remedy>" (§5.7 wording)
    display: str = ""                      # the human type label; FieldDescriptor.type_annotation is removed (SS-3 = B)
    description: str = ""
```

## Invariants (asserted by the contract's own unit tests, task 1.1)

1. **Exactly one verdict per parameter.** `build_contract` decides it from the declaration only and
   receives no DI registry (spec B-2). One pure function, `admit(contract, has_provider)`, applies
   B-2's availability rule.
   - It returns the contract unchanged, unless the contract is `INJECTED` through `Provide` or an
     unmarked class and `has_provider(provider_type, qualifier)` is false. Then it returns a
     `REJECTED_DISCOVERY` contract whose `reject_reason` names the type, the qualifier and the
     remedy.
   - `has_provider` is a predicate the caller builds from the boot's registry. The primitive never
     imports the registry.
   - Capability and `FromJob` contracts are never changed.
   - The cache stores the contract **before** `admit`, so availability is re-decided on every boot
     (B-7).
2. **`json_schema` is derived from `shape`** by one function. No surface derives a JSON type any other
   way (B-20).
3. **`default_json` round-trips through `cache.json` unchanged.** A cold descriptor and a warm one
   compare equal (B-7; F-34 was a cold `Enum` member against a warm `"red"`).
4. **`cli` is present exactly when a command line can spell the parameter.** `INVOCATION_ONLY` has
   `cli=None` (B-15).
5. **Contracts are built from `resolved_hints()`** (`_types/annotations.py`), so the same module
   compiled with and without `from __future__ import annotations` yields equal contracts (B-6).

6. **Every signature parameter has exactly one contract on its descriptor** *(added 2026-11-23,
   task 3.2)*.
   - A parameter that `parameters` lists carries its contract on its `FieldDescriptor`.
   - A parameter that discovery keeps off `parameters` has its contract in
     `JobDescriptor.omitted_contracts`. These are the 15 capability types, `FromJob(...)`, and a
     `GroupOptions` injection point. The contract is the one `build_contracts` already produced.
   - The two sets are disjoint. Their union is `build_contracts(function)` by name (`self`, `cls`,
     `*args` and `**kwargs` excluded, as the engine excludes them).
   - No surface reads `omitted_contracts`. The engine door (task 5.1) is its only reader. So
     `--help`, completion, `func builtin info schema` and the MCP `inputSchema` are unchanged by it.
7. **A choice set keeps its declared value type** *(task 4.4)*.
   - `enum_values` is all `str` or all `int`, never mixed, and never a stringified `int`.
   - `shape_json_schema` publishes the matching JSON `type`.
   - Text surfaces spell a choice as `str(value)`, and binding maps such a token back to its value.

```python
@dataclass
class JobDescriptor:                       # existing fields unchanged
    ...
    omitted_contracts: tuple[ParameterContract, ...] = ()   # contracts of signature parameters `parameters` omits
```

## Cache encoding

`FieldDescriptor` gains `contract: ParameterContract | None`. `_field_to_dict` / `_field_from_dict`
(`_types/descriptors.py:631`, `:685`) encode it as a nested JSON object, and `CACHE_VERSION`
(`_primitives/cache_format.py:178`, today `25`) is bumped (`pitfalls.md` §5).

`JobDescriptor.omitted_contracts` *(task 3.2)* is encoded by the same contract codec, under the key
`"omitted_contracts"`, a list in signature order. `CACHE_VERSION` goes from 26 (`cache_format.py:180`)
to **27**, so a version-26 cache is rebuilt rather than decoded without it.

**SS-3 = B** (member comment `01a201b6`, 2026-11-22T05:24:10Z): `type_annotation` is **removed**
from `FieldDescriptor`. The codec neither writes nor reads it, nor the legacy `"type"` key
(`descriptors.py:701`); a cache from an older version is rebuilt rather than decoded, because of the
version bump. The `type` alias property (`:87-89`) goes with it. A human-readable type label comes
only from `contract.display`. Sequencing: wave 9 makes the field transitional, and wave 10 deletes
it (`tasks.md`).

## Binding (`_primitives/argument_binding.py`)

```python
def bind(function, contracts: Sequence[ParameterContract], raw: Mapping[str, Any], *, surface: str) -> dict[str, Any]
    # raises BindRefusal(argument: str | None, reason: str) — never TypeError/ValidationError to the caller
```

1. **Refusals.** An unknown key → `BindRefusal`. A key naming an `INJECTED` parameter →
   `BindRefusal`. A required, non-injected parameter that is absent → `BindRefusal`.
2. **Defaults.** Absent parameters take `default_json`, decoded to the declared type.
3. **Conversion.** Supplied values are converted with a pydantic `TypeAdapter` built from the live
   annotation, which the engine has because it materialises the job before calling it. The adapter is
   cached per `(function, name)`. `Field(...)` constraints are honoured, which subsumes today's
   `ArgValidator`.
   - For a choice shape with `int` values, a `str` token is first mapped to the choice whose `str()`
     it equals (`"1"` → `1`), so a text surface's token converts (invariant 7, task 4.4).
4. **Result.** The binder returns only caller-supplied and defaulted values. DI then fills `INJECTED`
   names and nothing else.

Measured cost: `matrix/evidence/binder-cost.txt` (plan §*Risks*, H3).
