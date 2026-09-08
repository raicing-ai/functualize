# 05 — Diagnosis & Validation

`diagnose` and `validate` are written once, on `Resource`, and reflect over the
subclass they are called on. This depends on nothing from functualize beyond
`Stdout` and an exit code — it is the part of rise that is pure Python.

## 1. The record models

Per-substrate pydantic models in `risekit.core.models`, shared by assembly and
validation. The closed-record rule has a precise spelling:

```python
class BaseDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")   # criterion 14: extra fields rejected
    substrates: tuple[SubstrateName, ...]
    actions: tuple[ActionName, ...]
    tags: dict[str, str]
    target: TargetRecord | None                 # new — Axis 3
    status: Literal["N/A"]                      # criterion 13: the fixed sentinel
```

Two notes:

- **`extra="forbid"` is the mechanism for criterion 14**, not `strict=True`.
  `strict` governs coercion; `extra` governs unknown keys. Both are wanted, for
  different criteria.
- **The `"N/A"` sentinel is retained** because criterion 13 names it, and the
  record is a wire format. A deprecation candidate for format version 2, with a
  migration — not a silent removal (`14` §4).

A multi-substrate module (`Executable + Package`) carries **one presence block
per substrate**, which is the concrete payoff of `01` §2.

## 2. Meta-reflected diagnose

```python
class Resource:
    def diagnose(self) -> Diagnosis:
        decl = declaration_of(type(self))                  # MRO + attributes
        blocks = {
            s.name: assemble(s, self, probes_for(s, type(self)))
            for s in decl.substrates
        }
        return build_record(decl, blocks, target=resolve_target(self))
```

`declaration_of` is pure reflection, and `declaration_of_source` gives the same
answer without importing (`02` §5). There is no extraction step to get wrong:
the class *is* the declaration, so the intent's off-disk extraction problem
cannot occur.

`Nothing`-substrate modules emit the base record with no presence block —
criterion 19, dispatched by the MRO rather than a `TYPE` switch.

## 3. Probes come from the substrate

| Substrate | Default probe | Criterion |
|---|---|---|
| `Executable` | `shutil.which`; `--version` **executed** for `runs_correctly` | 20, 21 |
| `Package` | `importlib.util.find_spec` — proved by **import**, never by path | 22 |
| `Process` | lifecycle/status query → running / stopped / unknown | 23 |
| `Repository` | `git rev-parse` → sha, branch, dirty, ahead/behind | — |

Override only when a default is wrong:

```python
class Jsonschema(Executable, Installable, Runnable):
    class PROBES:
        installed = staticmethod(jsonschema_installed_probe)
        runs_correctly = staticmethod(jsonschema_version_probe)
```

`runs_correctly` is executed, never inferred, and the record carries the
verification method — which is what makes it trustworthy as the single source
of truth (criterion 24).

## 4. Meta-reflected validate

```python
class Resource:
    def validate(self) -> Verdict:
        return Verdict(
            structure=self._validate_structure(),   # binding checks, as findings
            behavior=self._validate_diagnosis(),    # the record vs its model
        )
```

The two-step pipeline keeps identical semantics:

| Intent step | New mechanism |
|---|---|
| 1 — structure | mypy (authoring) → substrate/action/attr checks (binding) → re-run as findings (`validate`) |
| 2 — behavior | the reflected `diagnose()` validated against its per-substrate model |

**One honest limit.** Step 2 validates the record's *shape*, not its *truth*. A
probe reporting `installed: true` for an absent binary produces a schema-valid
lie. The intent's answer is the `test` lifecycle (`08` §6), which installs and
uninstalls for real — which is why criterion 45 is load-bearing rather than
ceremonial.

## 5. Schemas: derived, exported, standard

Intent criterion 17 asks that both check steps use *standard, draft-stable
schema documents* that any conformant validator reproduces. It is recoverable
for the half with observable consequences:

```
rise schema export --out contracts/
```

writes each substrate's diagnosis model via `model_json_schema()`. Pydantic v2
emits **JSON Schema draft 2020-12**, so an auditor with `check-jsonschema`,
`ajv` or any conformant implementation can re-check a `rise diagnose` NDJSON
stream with no Python and no risekit.

- **Restored** — step 2 is a standard document; an independent validator
  reproduces rise's verdict on any record.
- **Not restored** — step 1 is a property of *code*. No schema language
  expresses "this class implements its substrate's abstract set". A third party
  re-derives it with mypy or the AST reader.

`12` scores criterion 17 **partial** on exactly that line.

The same derivation covers input contracts: `builtin info schema <job>` renders
each job's arguments as JSON Schema — and through the plugin binding path this
is correct with **no upstream patch** **[probed]** (`03` §1).

## 6. The universal vocabulary

`Resource` supplies, once: `diagnose()`, `validate()`, `audit(event)`
(`08` §5), and the group's `--help`. Binding check 10 rejects a class that
shadows any of them, which is what makes "declare, don't reimplement" a
guarantee rather than a style.

## 7. The tree walk

```
rise diagnose  [--group X] [--output ndjson]     # one record per module
rise validate  [target]                          # aggregated verdict
```

Top-level, never under `builtin` (`00` fact 5). In the guest delivery the same
verbs are `func rise diagnose` / `func rise validate` (`04` §5).

The walk enumerates bound modules in deterministic order (group path, then
class name), calls the inherited methods, and streams one NDJSON line per
module through `Stdout.emit` (`_primitives/stdout_emitter.py:129`). Child
namespaces are walked in the same pass — which is what makes validation
recursive (criterion 15). A failing verdict exits 1; a walk blocked by an unmet
precondition exits 3.
