# ADR-008: One Answer to "Is This a Secret", and Making Secrets Discoverable

**Status**: proposed
**Date**: 2026-08-27
**Deciders**: Hakim

## Context

### Problem 1 — a config file gives no sign that a job needs a credential

Secrets resolve from the environment or `.env` by naming convention. Config
files carry no reference to them: `IniFormatProvider` disables interpolation
outright, `_config/migration.py` *rejects* `%(key)s` references, and there is no
`expandvars`, no `${VAR}` handling, and no per-field `env=` alias anywhere in
`_config/`. The binding is entirely implicit.

That is a good security property — a config file has no vocabulary for naming a
secret's location, so it cannot leak one. It is also a discoverability failure:
nothing short of reading the Pydantic model tells an operator that a credential
is required at all.

The problem is worse than it looks, because **two env-naming conventions
coexist**: `EnvSource` builds `SECTION_KEY` (`sources.py:242`) while
`_config/job_config.py:437` builds `JOB__FIELD` with a bare `FIELD` fallback.
Only the first is documented. An operator deriving a variable name by hand has
a real chance of guessing wrong.

### Problem 2 — four independent answers to "is this a secret"

`is_secret_field` in `_types/redaction.py` is documented as the single answer,
and its docstring says exactly why:

> *"Two independent answers to 'is this a secret' is how a field gets redacted
> in state.json and then echoed to the screen while being typed."*

It already accepts **two** markers — the `Secret` annotation, and
`json_schema_extra={"secret": True}` — and is consumed by `func builtin env`
(`_cli/builtins.py:352`), the executor's prompt spec (`executor.py:2166`), and
the CLI adapter (`app/adapters/cli.py:1123`). Value-based redaction
(`collect_secret_values` / `redact`) covers the Shell capability and `Stdout`,
and `redacted_snapshot` covers `resolved_inputs` metadata.

**The TUI preflight widget does not participate.**
`_cli/tui/preflight_widget.py` decides secretness with an independent regex over
the *field name*:

```python
_SENSITIVE_PATTERN = re.compile(r"(secret|password|token|key)", re.IGNORECASE)
_MASK = "********"
```

It never sees the field's type or its `json_schema_extra`, and it uses a
different mask string from the canonical `MASK = "•••"`. Two live consequences:

- **False negative — a real leak.** A field declared `Secret[str]` but named
  `credential`, `auth`, `pat`, `bearer`, or `session` does not match the regex,
  so the preflight panel renders it in cleartext — on the screen a user studies
  immediately before running the job, while every other surface masks it.
- **False positive — mask erosion.** `keywords`, `sort_key`, `partition_key`,
  and `monkey_patch` all match on substring, so plain values are masked in
  preflight and shown in cleartext everywhere else. Users learn the mask is
  noise.

This is precisely the drift the canonical helper's docstring warns about,
already shipped.

## Decision

### 1. Collapse detection to one answer

`preflight_widget.py` calls `is_secret_field` and uses the canonical `MASK`.
`_SENSITIVE_PATTERN`, `_is_sensitive`, and the local `_MASK` are deleted.

This is a bug fix and should not wait on the rest of this ADR. Per
`contributor/guides/wiring-discipline.md`, prove it by breaking it: a
`Secret[str]` field named `credential` must render masked in the preflight
panel, and a plain `str` field named `keywords` must not.

Adding a *fifth* mechanism is therefore rejected on principle. Any new
declaration must be validated against `is_secret_field`, never consulted
instead of it.

### 1b. Connect the two halves of the secrets system

Verified empirically against pydantic 2.13 on this tree:

| Form | Model builds | Accepts a plain string (config/env) | `is_secret_field` | Masked in output |
|---|---|---|---|---|
| `x: str = Field(json_schema_extra={"secret": True})` | yes | **yes** | **True** | **no** |
| `x: Secret[str]` on a plain `BaseModel` | **no — `PydanticSchemaGenerationError`** | — | — | — |
| `x: Secret` with `arbitrary_types_allowed=True` | yes | **no — `ValidationError`** | True | yes |

Two consequences, both defects:

- **`is_secret_field()` returning `True` does not imply the value is masked.**
  Output redaction runs through `collect_secret_values`, which gathers only
  real `Secret` instances. A field marked with `json_schema_extra` stays a
  plain `str` and contributes nothing, so it is masked by
  `func builtin env` and the CLI adapter while leaking through log lines,
  f-strings, tracebacks, and `Stdout`.
- **No config-sourced value can ever populate a `Secret` field.** The wrapper
  rejects plain strings, and nothing wraps resolved config values: the sole
  `Secret(...)` construction site in the tree is `_resolve_sudo_password`
  (`executor.py:1511`), hardcoded for `[shell] sudo_password`.

The module docstring of `_types/redaction.py` therefore describes behavior that
does not exist. It states that `Secret[str]` is "accepted as a type annotation
… so config authors can write `token: Secret[str]`" (it raises), and that
config fields declared secret are "handled by the config consumer, which wraps
their resolved values in `Secret`" (no such consumer exists).

**Decision:** give `Secret` a `__get_pydantic_core_schema__` that accepts a
`str` and wraps it, returning a `Secret` instance. Then a single annotation
works from every source — config file, environment, CLI — with no
`arbitrary_types_allowed`, and the declaration marker and the value wrapper
stop being two half-systems.

Until that lands, documentation and skills must state the split honestly rather
than implying either form is complete. This supersedes any guidance that a
credential can be both config-settable and fully masked today.

### 2. Generate the `.env` skeleton rather than declaring it

Add `--template` to `func builtin env`:

```bash
func builtin env <job> --template > .env
```

It emits every resolved variable with its authoritative name, secret fields
left blank and commented as required.

The same generator should be able to emit a `config.<env>.toml` skeleton. The
project convention is that only `config.base.toml` is committed while the
environment overlays are not, so a fresh clone has no way to learn what its
overlay should contain — the identical discoverability gap this ADR addresses
for secrets, applied to the whole overlay. This solves discoverability *and* the
two-convention naming ambiguity in one move, because the tool prints the names
it actually uses rather than asking a human to derive them.

`func builtin env` currently takes only `--include-secrets`, so this is new but
small, and additive to a command whose entire purpose is already this.

### 3. `[secrets]` is declaration-only — it never resolves

An optional block naming the credentials a project expects:

```toml
[secrets]
required = ["ACME_SYNC__API_TOKEN"]
```

Rules, all load-bearing:

- It **names variables; it never holds values, and it never redirects lookup.**
  Resolution stays exactly as it is today.
- It is **validated against the model, never authoritative over it.** Naming a
  field the model does not mark secret, or omitting one it does, is a lint
  error — surfaced by `func builtin why` and at startup.
- It changes **when** a missing credential is reported (before the job runs
  rather than at model construction), and **where** that is surfaced. It does
  not change *whether* the field is required.

A `${env:VAR}` form in TOML was considered and rejected. It inverts the
resolution model: today sources are independently ranked and composed by
`ResolutionChain`, whereas a config-side redirect makes one source's *content*
reconfigure another source's *lookup*. It also reintroduces the interpolation
class that `interpolation=None` and `migration.py` deliberately excluded, and
leaves an unanswerable precedence question when a conventionally-named variable
and a redirected one are both set.

### 4. Required-ness belongs to Pydantic, not to `[secrets]`

A field with no default is required; `str | None = None` is optional. That
vocabulary already exists, is enforced at validation, and produces a proper
error. Restating it in TOML creates a fourth place for two answers to disagree —
the exact failure this ADR exists to close. **`[secrets]` must not carry a
`required` flag.**

What `[secrets]` legitimately adds is *timing*, not *schema*. Pydantic validates
at model construction, which is at job execution; an operator wants to know
before a long job starts, and the TUI wants to show it at preflight. Listing a
variable in `[secrets]` requests an early presence check for something the model
will demand anyway.

One case Pydantic genuinely cannot express — "has a default, but production must
override it" — is deployment policy rather than schema. It is out of scope here
and needs its own decision if it is ever wanted.

### 5. Preflight shows presence, never value

Once detection is unified, the preflight panel can show a secret's *status*
without ever showing its value:

```
api_token   ••• (env)          set
api_url     https://…          config.prod.toml
db_password ⚠ ACME__DB_PASSWORD not set
```

Masking is driven by `is_secret_field`. The presence indicator is driven by
`[secrets]` when present, and by the model's required fields otherwise. The two
concerns stay separate: **the model owns the schema, the config block owns
timing and display.**

## Consequences

### Positive

- One answer to "is this a secret", eliminating a live leak and a live
  false-positive class.
- Operators discover required credentials without reading Python.
- The `SECTION_KEY` / `JOB__FIELD` ambiguity stops mattering for users, because
  the tool emits the names.
- Preflight gains a genuinely useful failure mode: a missing credential is
  visible before the run rather than as a traceback during it.

### Negative

- `[secrets]` is a new config surface to document, validate, and keep in step
  with the model.
- `--template` needs to render every field type sensibly, including nested
  models.
- Fixing the preflight regex changes rendered output, so TUI snapshots move.

### Neutral

- Decisions 1 and 2 stand alone and deliver most of the value; 3 and 5 can be
  deferred or dropped without stranding them.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| `${env:VAR}` references in TOML | Explicit and visible in the file | Inverts the resolution model; revives excluded interpolation; unanswerable precedence when both forms are set | Rejected on architecture |
| Mark secrets in TOML as authoritative | One obvious place to look | A fifth detection mechanism, disagreeing per-deployment with the model that travels with the code | Rejected — the failure this ADR closes |
| `required` flag inside `[secrets]` | Reads naturally | Duplicates Pydantic's own vocabulary in a place that can disagree with it | Rejected; see decision 4 |
| Leave the preflight regex alone | No snapshot churn | A `Secret[str]` field named `credential` is rendered in cleartext | Rejected — an active leak |
| Documentation only | Zero code | Does not fix detection drift, and prose cannot resolve the naming ambiguity | Rejected |

## Open Questions

- Whether `[secrets]` belongs in the project config file or in `pyproject.toml`
  under `[tool.functualize]`.
- Whether `--template` should refuse to overwrite an existing `.env`, or emit to
  stdout only. Stdout-only is the safer default.
- Whether the two env-naming conventions should be unified outright, which would
  reduce `[secrets]` to a pure convenience. Tracked in ADR-006.
