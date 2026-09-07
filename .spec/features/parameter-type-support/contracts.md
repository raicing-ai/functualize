# Contracts

## C1 — one list of CLI value types

`_primitives/parameter_types.py`, beside `_primitives/capability_names.py` and
for the same stated reason: several layers classify a job signature, each kept
its own copy of "what counts as what", and the copies drifted. That file's
docstring records `Shell` missing from one copy and failing only on a warm
boot; this is the mirror image — a type absent from no list at all, because
the classification was "not a builtin" rather than a list.

```python
CLI_VALUE_TYPE_NAMES: frozenset[str]      # matched by name, like INJECTED_PARAM_TYPE_NAMES
def is_cli_value_type(annotation: object) -> bool
def has_explicit_cli_marker(annotation: object) -> bool
```

Matched by **name**, not identity, for the same reason the injected-capability
list is: a layer forbidden from importing a type still has to classify it.
`Enum` is the exception — a subclass check, since the names are user-defined.

## C2 — `validate_di_bindings` reports per job instead of raising for all

```python
# before
def validate_di_bindings(self) -> None:        # raises DIValidationError for the whole app

# after
def validate_di_bindings(self) -> dict[str, list[ResolutionError]]:
    """Unsatisfiable jobs, by job name. Empty when everything binds."""
```

The caller decides the disposition. `_app/boot.py` unregisters each affected
job and records a `DiscoveryFailure` for it; nothing else changes.

**This is the deliberate constitutional departure** named in `spec.md`, and it
is a behaviour change for a library-mode host that catches `DIValidationError`
around `FunctualizeApp(...)`. Three test modules pin the exception (24
references); they are rewritten to pin the per-job outcome, not deleted.

`_ensure_materialized`'s deferred validation for lazy proxies is unchanged: a
job that fails at first use still raises there, because at that point the
caller has asked for *that* job specifically.

## C3 — the report payload

An unsatisfiable job is published through the existing `discovery_failures`
key, like a module that failed to import and like a job-name collision:

| Key | Value |
|---|---|
| `module` | the job's module path |
| `path` | the job's source file |
| `error_type` | `"UnsatisfiableParameter"` |
| `message` | names the job, the parameter, its annotation, and the two fixes |

No new key, and the list stays always-present.

## C4 — `_resolve_type` gains conversions

`app/utils.py::_resolve_type` maps a `FieldDescriptor.type_annotation` string
to the type click converts with. `Path` is already mapped; `UUID`, `date`,
`datetime` and `Decimal` are added. A value that does not parse is a click
usage error naming the parameter — click's own behaviour for a callable type,
not new handling.

`Enum` keeps its existing treatment: `choices` are published from the member
names and click validates against them.
