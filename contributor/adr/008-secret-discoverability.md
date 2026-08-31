# ADR-008: One Answer to "Is This a Secret", and Making Secrets Discoverable

**Status**: accepted
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

**The TUI preflight does not participate.**

> **Correction.** This ADR was first written against
> `_cli/tui/preflight_widget.py`. That module had **zero mount points** — it was
> a dead duplicate, and fixing it would have changed nothing a user sees. The
> preflight that actually runs is `_cli/tui/preflight_summary.py`, wired at ten
> call sites in `app.py`. Two further live surfaces were missed entirely: the
> Config Table panel and the source-chain detail view, neither of which masked
> anything at all. The dead module has been deleted; the three live surfaces are
> fixed. The scrutiny that found them is a session document (`.spec/`); what
> survives it is recorded in this ADR.

The dead widget decided secretness with an independent regex over the *field
name*:

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
already shipped — and, on the live surfaces, worse than the regex: they applied
no test at all.

### Problem 3 — the resolvers disagreed about the values, not just the masks

Underneath both problems sat four independent config resolvers.
`USER=root-ambient func builtin info --job sync` reported `service-account`
while the run received `root-ambient`, because `_config/job_config.py` read a
bare, unprefixed `FIELD` from the environment ahead of everything else. A field
named `user` resolved to the shell's `$USER` and its declared default was
unreachable; on a field named `token` or `password` that is credential
substitution.

Unifying *detection* on top of resolvers that disagree about *values* yields a
system that masks the right field and reports the wrong one. Fixing this came
first.

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


**Shipped.** `Secret` now carries `__get_pydantic_core_schema__` (accepting
`str | Secret`, serializing to `MASK`) and `__get_pydantic_json_schema__`
(emitting `{"secret": true}`). The JSON-schema half is what makes the two
markers genuinely one mechanism: without it `Secret[str]` is invisible to the
descriptor extractor and would mask in `info --job` while leaking in the TUI.
`SUPPORTED_TYPES` / `_is_supported` / `coerce_value` were taught the type too —
a second gate that would otherwise have refused at registration a type that now
builds a schema.

### 2. Emit the `.env` skeleton — no `--template` flag needed

`func builtin env <job>` emits an unset field **commented out**, with why:

```console
$ func builtin env sync
export SYNC_API_URL='https://api.example.com'   # source: config.prod.toml
export SYNC_CREDENTIAL='•••'                    # source: env
# SYNC_TOKEN=  # REQUIRED — not set
```

The draft proposed a `--template` flag for this. It is unnecessary: the fix that
makes set and unset distinguishable *is* the skeleton, and a flag whose output
differs from the default output would be a second thing to keep in step.
`--template` is withdrawn.

An empty secret renders as empty, not as `•••`. Masking nothing manufactures
the appearance of a configured credential, which is the one question these
surfaces exist to answer. All five sinks now share a single `display_value`
predicate rather than each re-deriving one — three of them had drifted.

### 3. `[secrets]` — withdrawn

The draft proposed a declaration-only `[secrets]` block listing expected
variables. It is **not adopted**, on the maintainer's call.

Everything it was for is delivered by decisions 2 and 5 without a new config
surface to document, validate and keep in step with the model. Its remaining
purpose was *timing* — an early presence check — and `builtin env` plus the
preflight indicator both answer that from the model directly.

A `${env:VAR}` form in TOML was considered and rejected, and that rejection
stands verbatim: it inverts the resolution model. Today sources are
independently ranked and composed by `ResolutionChain`, whereas a config-side
redirect makes one source's *content* reconfigure another source's *lookup*. It
reintroduces the interpolation class that `interpolation=None` and
`migration.py` deliberately excluded, and leaves an unanswerable precedence
question when a conventionally-named variable and a redirected one are both set.

There is no `[secrets]` section and none is planned. A credential is a field in
its job's own section, marked secret — one concept, not two.

### 4. Required-ness belongs to Pydantic

A field with no default is required; `str | None = None` is optional. That
vocabulary already exists, is enforced at validation, and produces a proper
error. Restating it in TOML would create a fourth place for two answers to
disagree — the exact failure this ADR exists to close.

One case Pydantic genuinely cannot express — "has a default, but production must
override it" — is deployment policy rather than schema. Out of scope; it needs
its own decision if it is ever wanted.

### 5. Preflight shows presence, never value

Once detection and resolution were unified, this fell out almost for free — the
`○*` presence indicator already existed and worked. What did not work was the
required-and-missing test. Both `info --job` and `preflight_summary` guarded
`default is not None and default is not ...`, but a Pydantic v2 required field's
default is `PydanticUndefined` — neither — so `"not set (required)"` was
**unreachable for every required field**, and a required credential rendered as
`••• model default`, which reads as "configured".

`ResolvedField.is_missing_required` asks `is_required()`, which is the question
actually being asked, and every surface reads it.

Masking is driven by `is_secret_field`; presence by the model's required fields.
The model owns the schema; the display owns nothing but display.

## Consequences

### Positive

- One answer to "is this a secret", eliminating a live leak and a live
  false-positive class — on the surfaces that actually render.
- One answer to "what value will this field have", which is the precondition for
  the above meaning anything.
- Operators discover required credentials without reading Python.
- The naming ambiguity is gone rather than papered over: `JOB__FIELD` and the
  bare `FIELD` are deleted, so `JOB_FIELD` is the only spelling, and the tool
  emits it.
- A missing credential is visible before the run rather than as a traceback
  during it.

### Negative

- **Breaking**, with no deprecation window — pre-1.0, and
  `.spec/CONSTITUTION.md` forbids compat shims. `JOB__FIELD` and bare `FIELD`
  stop resolving. The correct value was *unreachable* while the bare fallback
  stood, so nobody can have been relying on it deliberately.
- `CACHE_VERSION` 14 → 15, since `FieldDescriptor` now carries `secret`.
- `Secret` fields serialize to `MASK` under `model_dump()`. Intended — safe by
  default; real values come from `get_secret_value()`.
- TUI rendered output changed, so snapshots moved.

### Neutral

- Decision 3 is withdrawn, and nothing depended on it.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| `${env:VAR}` references in TOML | Explicit and visible in the file | Inverts the resolution model; revives excluded interpolation; unanswerable precedence when both forms are set | Rejected on architecture |
| Mark secrets in TOML as authoritative | One obvious place to look | A fifth detection mechanism, disagreeing per-deployment with the model that travels with the code | Rejected — the failure this ADR closes |
| `[secrets]` declaration block | Names expectations in one place | A new surface to validate against the model; its only unique value was timing, which decisions 2 and 5 deliver | Withdrawn |
| `--template` flag on `builtin env` | Explicit intent | The default output already is the skeleton; a second output shape to keep in step | Withdrawn |
| Name-based detection (`_SENSITIVE_PATTERN`) | Zero declaration effort | Masks `sort_key`, leaks `credential` | Rejected — it was the bug |
| Fixing `preflight_widget.py` | Looked like the whole fix | The module has no mount points; the live surfaces are elsewhere | Rejected on evidence; see Context |
| Documentation only | Zero code | Does not fix detection drift, and prose cannot resolve a naming ambiguity | Rejected |

## Resolved Questions

- **Where `[secrets]` belongs** — nowhere; withdrawn.
- **Whether `--template` should refuse to overwrite `.env`** — moot; withdrawn.
- **Whether the two env-naming conventions should be unified** — yes, and they
  were. `JOB_FIELD` is the only spelling for a job config field. Group options
  keep `SCOPE__FIELD`, which is a different feature with a real reason: a nested
  group path is flattened with single underscores, so `DEPLOY_WEB_ENV` would be
  ambiguous with group `deploy` carrying a field named `web_env`.

---

## Addendum — implementation, and the review of it (2026-08-28)

The decisions above shipped. Two of them were amended by what implementation and
an adversarial review turned up; both amendments are recorded here because this
ADR is the committed record, and the working proposal and scrutiny reports that
produced them are session documents under `.spec/` (see `.spec/README.md`).

### A1. The TUI keeps its own resolver — deliberately

The unification aimed at one resolver behind every surface. It landed for
`func builtin info --job` and `func builtin env`, which read
`_config/resolved_field.resolve_job_fields`. **It deliberately did not land for
the inline TUI, and must not.**

`resolve_job_fields` needs a live Pydantic class — it reads `model_fields`,
calls `is_required()`, and asks `is_secret_field(info)`. Obtaining that class
means `materialize_job` → `LazyJobFunction.materialize()`, whose contract is
"Import the module (once)" (`_discovery/lazy_wrapper.py`). The TUI's panel path
is import-free by construction (`app.get_job` + cached `FieldDescriptor`s +
`app.resolution_chain()`) and rebuilds *while the user types*. Routing it
through the seam would import a job module on every panel refresh and forfeit
true-lazy boot — a display concern buying a boot-time cost.

So "one answer" holds at the level that matters: the TUI shares the **detector**
(the model's `secret` / `required` / `default`, carried through the discovery
cache) and reads values from the **same `ResolutionChain`**. There is no second
opinion about what a field is or where its value came from; there are two
readers of one chain, one of which may not import.

The risk this leaves is *cache drift*, not resolver drift, and it has its own
guard: `tests/config/test_descriptor_cache_fidelity.py` asserts the cached
descriptor's declaration properties equal what the live model says, field for
field.

### A2. `JOB__FIELD` was removed outright, not deprecated

The plan of record called for one minor release with a `DeprecationWarning`.
Reversed during implementation: `.spec/CONSTITUTION.md` forbids
`DeprecationWarning` and backward-compat shims pre-1.0 ("no users to deprecate
toward") and makes "no shims remain in `src/`" a completion criterion. A
one-release window would have been the only such shim in the tree, and the form
being removed was never documented — so there is no reader to warn who was
following the docs. Recorded in the CHANGELOG under "silently wrong values".

### A3. `Secret` masks into JSON, not between two of our own jobs

§1b gave `Secret` a Pydantic serializer so `model_dump()` could not leak. Masking
in *every* mode was wrong: the framework passes config models between jobs by
dumping and rebuilding them — `Invoke` builds a child job's kwargs from
`config.model_dump()`, `RunContext.with_plugin_config` rebuilds a model from its
own dump, and the argument validator merges `Field()`-validated params back. An
unconditional serializer replaced live credentials with the mask *in transit*,
and the child authenticated with `•••`.

The serializer is now `when_used="json"`. That closes the path §1b was actually
about — a resolved config reaching a file, a log sink, or an HTTP body without
passing `redacted_snapshot` — while leaving the python-mode object graph intact.
The wrapper masks itself in `str()`/`repr()`, so nothing leaks by keeping it.

`Secret[T]` for `T` other than `str` is now refused at registration: `Secret`
stores `str(value)` and `get_secret_value()` returns `str`, so any other
parameter was a claim it could not keep.

### A4. What the review found that the tests did not

Four defects survived a green suite (7122 passed), two introduced by this work:
a credential passed on the command line was written to stdout unredacted while
the same credential in the environment masked; `invoke(config=…)` corrupted
secrets (A3); the single line wiring masking into the TUI had no test at all
(defeating it left 2181 tests passing); and a project whose only config was
`config.base.ini` ran on model defaults in silence after ADR-007.

The structural causes — tests that start at the formatter rather than the
production entry point, one precedence tier and one field shape under test, and
a new protocol hook added without auditing the type's existing consumers — are
recorded as rules §8–§10 of `contributor/guides/wiring-discipline.md`, which is
where they will be read again.

### A5. A group option is a credential like any other (2026-08-28)

`GroupOptions` declares flags at a group that every descendant job inherits.
Nothing above said whether "detection follows the model" extends to them, and
the answer is that it already did — for free, and unnoticed.

`extract_group_options_fields` (`_discovery/group_options_extractor.py`) reuses
the job path's `extract_field_descriptors` and then `dataclasses.replace`s only
`short_flag` and `description`. `replace` preserves what it is not told about,
so `secret` rides through into the cached `GroupOptionsSpec` untouched. A field
declared `Secret[str]` on a `GroupOptions` subclass therefore arrives at the
import-free panel path already marked, with no code aware it happened. That was
verified against a real project rather than assumed, and is pinned by
`examples/standalone/group_options_lab/tests/`.

The consequence is that masking a group credential is not a feature to add but
a wire not to drop. The panel `FieldDef`s built for group rows must carry
`secret=` exactly as the job path does; omitting it renders the credential in
cleartext in the Config Table and the pre-flight, which is precisely the leak
this ADR closed. Sabotage-checked in both renderers: deleting the kwarg prints
the credential and turns three tests red.

Per §8 of `wiring-discipline.md`, those tests start from the `Secret[str]`
declared in the example project — a `FieldDef` stub carrying `secret=True`
would only prove the formatter masks when told to, which was never the thing in
doubt.

One asymmetry follows from A1 and is worth knowing before it looks like a bug:
a secret's default is not written to the cache (`_serialize_default` returns
`None` when `secret`), so any surface that omits a value for equalling its
default cannot make that comparison for a credential. It renders the flag
explicitly instead. See ADR-009 decision 3.
