# Class-based jobs — Internal types

The external surfaces are `contracts.md` C1–C6 and are not repeated here. These
are the internal shapes the plan adds or changes, with their serialization, so
the cache round trip in AC-7 and the collision identity in AC-10 can be checked
without reading the code.

## 1. `JobDescriptor.owner_class`

`_types/descriptors.py`, next to the existing provenance fields
(`python_name`, `source_file`, `module_path`).

| Field | Type | Default | Meaning |
|---|---|---|---|
| `owner_class` | `str \| None` | `None` | The simple name of the class that declared the method, for a method job. `None` for a plain function job. |

`None` is the function case, and it is also what an older cache payload
deserialises to, which is why the field is additive rather than required.

**Serialization.** `to_dict` writes the key `owner_class`; `from_dict` reads
`data.get("owner_class") or None` next to the existing
`python_name=data.get("python_name") or ""` (`_types/descriptors.py:471`). No
key is removed or renamed; `python_name` stays the method's bare name
(`start`), never dotted — `_discovery/naming.py:62-64` raises on a dot and
`LazyJobFunction` looks the attribute up by name.

```python
# round trip
{"name": "pg.start", "python_name": "start", "owner_class": "Postgres", ...}
    → JobDescriptor(... owner_class="Postgres")
    → to_dict()["owner_class"] == "Postgres"
```

## 2. Identity keys composed from `owner_class`

Both readers compose the same string, so a test can assert they agree.

| Reader | Function case (unchanged) | Class-method case |
|---|---|---|
| `cached_provider._entry_key` (`:545`) | `"<source_file>::<python_name or name>"` | `"<source_file>::<owner_class>.<python_name>"` |
| `collisions.claim_order` (`:40-57`) | `(source_file or "", python_name or name)` | `(source_file or "", "<owner_class>.<python_name>")` |

Why it matters: `_add_entry` (`:547-550`) overwrites silently, so without the
class in the key, `OtherPostgres.start` and `LocalPostgres.start` in one file
become one entry before collision resolution runs (AC-10).

## 3. Cache version

`_primitives/cache_format.py:160` — `CACHE_VERSION` 22 → **23**, with a
comment-block entry in the existing style (the block runs `# v10` at `:64` to
`# v22` at `:156-159`):

```
# v23 — JobDescriptor.owner_class: a method job records the class that
#       declared it, so two same-named methods in one file stay two entries.
```

No other cache section changes shape.

## 4. `RegisteredJob.method_name`

`_types/descriptors.py:552-579`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `method_name` | `str \| None` | `None` | The method to call on the resolved config instance, for a class job. |

`function` stays the callable the surfaces introspect (`ClassJobMethod` for a
class job), and `config_class` is the job class itself. `dependencies` is
unchanged: a class job's `deps` come from its method declaration, resolved at
registration as today.

## 5. `ExecutionContext.method_name`

`_engine/context.py:94-107`, beside `config_class`.

| Field | Type | Default |
|---|---|---|
| `method_name` | `str \| None` | `None` |

Set from `RegisteredJob.method_name` where the context is constructed
(`_engine/executor.py:1247-1259`). Read once, in `_resolve_config_model`, to
rebind `context.function`:

```python
context.function = functools.partial(
    getattr(context.config_class, context.method_name), config_instance
)
```

The receiver never enters `call_kwargs`, so `context.injected` — and therefore
the `call_kwargs - injected` fingerprint — is unaffected.

## 6. `ClassJobMethod`

`_types/class_job.py` (new; `_types` imports stdlib only, plus
`_types/annotations.resolved_hints`).

| Member | Source | Why |
|---|---|---|
| `job_class` | constructor | registration's `config_class` (plan.md §4.4) — boot never calls `_detect_config_class` for a class job |
| `method_name` | constructor, from `descriptor.python_name` | registration; the engine's bind. Derived, not stored on `JobDescriptor` (§8) |
| `__signature__` | method signature, first parameter removed, PEP 563 annotations resolved | `click_params.build_click_params` and `extract_parameters_from_signature` do not drop `self` by name; `ArgValidator` skips unannotated parameters |
| `__name__`, `__qualname__`, `__doc__`, `__module__`, `__annotations__`, `__wrapped__` | the underlying function | `inspect.getdoc`, error text, `get_type_hints` diagnostics |
| `__functualize_job__` | constructor argument: the descriptor's **effective merged** declaration | the one source of the declaration (plan.md §4.2, §4.4). An **own attribute**, never read through: `__getattr__` would answer with the *method's* unmerged `@job`, and `adopt_descriptor_declaration`'s early return would then treat it as already-correct |
| `__getattr__` | delegates to the function | `__functualize_workflow__`, capability markers — everything the descriptor already carries apart from the declaration |
| `__functualize_lazy__` | **absent** | `executor._execute_lifecycle:1220-1238` must not treat it as a cache stand-in |
| `__call__` | raises `RuntimeError` naming the job | the receiver is the run's config instance; a call without one would build a second instance |

## 7. Strict-collision record

`_types/discovery_report.py`.

| Name | Shape |
|---|---|
| `CLASS_JOB_NAME_COLLISION` | `"ClassJobNameCollision"` — a **different** `error_type` from `JOB_NAME_COLLISION`, so the existing four-key `as_dict` payload keeps its meaning (C5, AC-14) |
| `ClassJobCollisionDetail` | `canonical_name: str`, `claimants: tuple[tuple[str, str], ...]` — each claimant `(qualified_name, source_file)`, `qualified_name` being `owner_class.method` for a class job and the function's own name otherwise. `python_name` is the method name and would render two claimants identically |
| `DiscoveryFailure.collision` | type widened to `JobNameCollisionDetail \| ClassJobCollisionDetail \| None`; `as_dict` still emits exactly `module`, `path`, `error_type`, `message` |

The message names every claimant and its file:

```
Job name 'postgres.start' is declared twice: 'OtherPostgres.start'
(.functualize/jobs/databases.py) and 'LocalPostgres.start'
(.functualize/jobs/databases.py). Neither is registered.
```

`JobNameCollisionDetail`, `job_name_collision(...)` and their rendering are
untouched.

## 8. What is deliberately absent

- No envelope key, request field, invocation flag or run-record field: the run
  record carries `name` and `group` exactly as a function job's (C6).
- No `method_name` on `JobDescriptor`: the descriptor is cache, and the cache
  already separates the two halves (`python_name` = method,
  `owner_class` = class). A third spelling would be a fourth identity.
- No `class` field on `DiscoveryFailure`: a strict collision is a collision, and
  `collision` is where collisions live.
