# Proposal: One Resolver, One Detector, One Name

**Status**: proposed — scope settled with the maintainer 2026-08-27
**Date**: 2026-08-27
**Supersedes**: ADR-008 §1, §1b, §2, §5 · **withdraws** §3 · retains §4 verbatim
**Amends**: ADR-007 (decision is a no-op without `boot.py:494`)
**Evidence**: `contributor/reports/2026-08-27-config-and-secrets-scrutiny.md` — 17
verified defects, all reproduced against a running process

---

## The thesis in one paragraph

ADR-008 is right that two answers to "is this a secret" is how a field gets redacted in
one place and echoed in another. It is aiming at the wrong pair. The framework has **six**
secret-detection mechanisms (two of them dead) sitting on top of **four** config
resolvers (which disagree about values). Unifying detection alone produces a system that
masks the right fields and reports the wrong values — and the widget ADR-008 proposes to
fix is a dead duplicate that never mounts, while the three surfaces that *are* mounted
leak credentials in cleartext. **Fix the resolver and the type before touching the
presentation, and most of ADR-008's remaining decisions become small or unnecessary.**

---

## Settled scope

| Question | Decision |
|---|---|
| TUI secret editing | **Mask as typed.** Cheap: `SmartBar` subclasses Textual's `Input`, which has a native `password` reactive (textual 8.2.7, verified). See §1.4. |
| `JOB__FIELD` deprecation window | **One minor release.** Small user base; it was never documented. |
| `[secrets]` block (ADR-008 §3) | **Dropped.** Not wanted. §4 stays — required-ness lives in Pydantic and nowhere else. |
| Sequencing | **Phases 1–3 land together**, in one session, so the cross-surface parity test arrives before any further surfaces are added. |

## Principles

These are the load-bearing rules. Every phase below is an application of one of them.

**P1 — One resolver.** Exactly one function answers "what value will this field have?"
Every display surface calls it. A surface that re-derives a value is a surface that will
eventually lie at the moment it matters most.

**P2 — One detector.** `is_secret_field` is the only answer to "is this a secret". A
mechanism that cannot be validated against it is deleted, not added — including
`tui.sensitive_keywords`.

**P3 — One name.** The tool prints the environment variable name it actually reads. No
convention is documented that the resolver does not honour first, and no convention is
honoured that the tool does not print.

**P4 — Mask on presence, not on value.** Already the rule in
`app/adapters/cli.py:1119`. An empty secret still reads as a secret; a *missing* secret
reads as missing. Masking must never make "set" and "unset" indistinguishable.

**P5 — Declaration travels in the cache.** Any property a boot-free surface must respect
lives on `FieldDescriptor`, not behind a model import. True-lazy boot (warm boot: 0
imports) is not negotiable for a display concern.

**P6 — Prove it by breaking it.** Per `contributor/guides/wiring-discipline.md`: every
change below ships with a test that fails if the production call path is removed — not
one that constructs the subject and its collaborators itself.

---

## Phase 1 — Stop the bleeding

*Closes D1, D2, D3, D4, D10, D13. No new surface, no new vocabulary.*
*Lands together with Phases 2 and 3 (maintainer decision).*

### 1.1 Delete `PreFlightWidget` — the *dead duplicate*, not the live preflight

**There are two preflight modules, and only one is real:**

| Module | Status |
|---|---|
| `_cli/tui/preflight_summary.py` | **live** — wired at ten call sites in `app.py`; renders the `job —` + `● field: value (source)` block under the SmartBar on every keystroke |
| `_cli/tui/preflight_widget.py` | **dead** — zero mount points; a second, unmounted implementation of the same idea |

Delete `preflight_widget.py`, its two exports in `_cli/tui/__init__.py`, and
`tests/_cli/test_preflight_widget_unit.py` +
`tests/_cli/test_inline_tui_preflight_integration.py`.

Nothing mounts it. Its regex is the mechanism ADR-008 §1 wants gone, its mask string
disagrees with the canonical `MASK`, and its tests assert the buggy behaviour by name
(`_is_sensitive("api_key") is True`), so they would have to be rewritten regardless.
Deleting a dead duplicate of a live module is strictly cheaper than rewiring it.

> ADR-008 §1 said "`preflight_widget.py` calls `is_secret_field`". It cannot — the widget
> receives `PendingExecution`, which carries `{name: (value, source)}` and no `FieldInfo`.
> The fix belongs in `preflight_summary.py` (§1.3), which already receives descriptors.

**This also shrinks §5.** `preflight_summary.py` already renders presence — `●` filled,
`○` empty-and-required, `·` optional-and-empty — and it works today:

```
 req —
   ○* token: (default)  str  required, no default, secret
   ●  opt: (default)    str  optional empty default, secret
```

So ADR-008 §5 is not a new panel. It is two corrections to a working one: mask the value
(§1.3), and stop labelling a required-no-default field `(default)` (Phase 4).

### 1.2 Carry secretness on `FieldDescriptor` *(P5 — unblocks everything visual)*

```python
@dataclass(frozen=True)
class FieldDescriptor:
    ...
    secret: bool = False
```

- `_discovery/schema_extractor.py` — one line, because the marker already survives into
  the JSON schema (verified):
  ```python
  secret=bool(prop.get("secret")),
  ```
- `_types/descriptors.py` — add to the serializer; the deserializer already uses
  `data.get(...)` for newer keys.
- `_primitives/cache_format.py` — `CACHE_VERSION` 14 → 15.
- `_discovery/providers.py` (the signature/AST path) — read the `Secret` marker from
  `Annotated` metadata; default `False` for plain parameters.

This is what lets a boot-free surface mask without importing the job module.

### 1.3 Mask the three surfaces that actually render

| Surface | Change |
|---|---|
| `preflight_summary.format_preflight_field_line` | mask `display_value` when `fd.secret` — this covers **both** a bar-typed value and a non-empty *default*, which currently renders unprompted |
| `chain_resolution.build_command_panels` | `FieldDef` gains `secret: bool` from the descriptor |
| `panels/config_table.ConfigTablePanel._format_field_cells` | render `MASK` when `field_def.secret` |
| `tui/source_chain_detail.SourceChainDetailView._display_value` | render `MASK` when the key is secret, for **every** row — losing sources included |

Use the canonical `MASK` (`•••`) everywhere. The preflight keeps its `● ○ ·` indicator and
its source label; the detail view keeps its status glyphs (`★` winning / `●` overridden /
not-set). A secret's *provenance* stays fully visible while its value never is — which is
the useful half.

### 1.4 Mask as typed *(maintainer decision; verified cheap)*

`SmartBar` subclasses Textual's `Input`, and `Input` has a native `password` reactive
(textual 8.2.7 — verified present in both `__init__` and as a reactive). INSERT mode
reuses the bar rather than opening a separate editor, so the whole change is threading one
flag:

```python
# bar.py
def enter_edit_mode(self, field_name, value, hint, *, secret: bool = False) -> None:
    self.password = secret
    ...
# and clear it in restore_state() / _restore_and_exit()
```

plus carrying `secret` from `FieldDef` through `InsertModeController.enter_insert`. Roughly
ten lines, no new widget.

**Two caveats, both worth stating rather than discovering:**

- **Autocomplete must be suppressed while `password` is on.** `textual-autocomplete` is
  attached to the SmartBar; a dropdown that suggests completions for a masked value
  re-renders it in cleartext one row below the mask.
- **COMMAND mode is out of scope, deliberately.** `sync --credential hunter2` typed as a
  whole command line cannot be masked with a per-widget flag without breaking editing of
  the rest of the line. Masking is for INSERT mode, where the bar holds exactly one
  field's value. The command-line case is mitigated instead by §1.3 — the preflight below
  the bar stops echoing it — and by the fact that history does not persist arguments.

### 1.5 Fix `_collect_job_secrets` *(D10)*

`executor.py:1513` calls `_make_config_view(job_name)` and looks for `model_fields` on a
`JobConfigView`, which has none — so it iterates `dir()`, finds four bound methods, and
returns `frozenset()` every time. Pass the **resolved config model** instead:

```python
model = self.resolve_config_model(job_name)
if model is None:
    return frozenset()
return frozenset(collect_secret_values(
    getattr(model, name, None) for name in type(model).model_fields
))
```

Keep the best-effort `except` — redaction must not be why a job fails.

> **P6**: today's test hands `WiredStdout` its `secrets=` set directly. Replace it with a
> job-level test that declares a secret, runs the job, and asserts the value is absent
> from captured stdout. That test fails if this wiring is removed; the current one does
> not.

### 1.6 Remove `tui.sensitive_keywords` *(D13, P2)*

Drop it from `func_settings.py:173`, `settings_schema.py:62`, `_cli/config.py:60`, and
`contributor/architecture/tui-architecture.md:175`. A setting that promises masking and
delivers nothing is worse than no setting; after 1.3, masking is model-driven and the
name-list has no meaning to restore.

**Phase 1 exit criteria** — a `json_schema_extra={"secret": True}` field named
`credential`:
- renders `•••` in the preflight summary, the Config Table, and the drill-down detail view;
- renders `•••` when it carries a non-empty *default*, with nothing typed;
- is masked in the SmartBar while being edited in INSERT mode, with autocomplete suppressed;
- is absent from captured `Stdout`;
- and a plain `str` field named `sort_key` renders its value on all three surfaces.

---

## Phase 2 — Make `Secret` usable

*Closes D11, D12, D16, D17. This is ADR-008 §1b, completed.*

`functualize.types.Secret` is public API. Using it today makes the job **silently
disappear** from `func` with a stderr warning. Three gates must open together — opening
any two still fails.

### 2.1 Core schema — accept a `str`, produce a `Secret`

```python
@classmethod
def __get_pydantic_core_schema__(cls, source, handler):
    return core_schema.no_info_after_validator_function(
        cls,
        core_schema.union_schema([
            core_schema.is_instance_schema(cls),
            core_schema.str_schema(),
        ]),
        serialization=core_schema.plain_serializer_function_ser_schema(
            lambda _: MASK, return_schema=core_schema.str_schema()
        ),
    )
```

The serializer matters as much as the validator: it makes `model_dump()` safe by
default, so a resolved config cannot leak through any JSON path that bypasses
`redacted_snapshot`.

### 2.2 JSON schema — emit the marker *(the constraint ADR-008 omits)*

```python
@classmethod
def __get_pydantic_json_schema__(cls, schema, handler):
    out = handler(core_schema.str_schema())
    out["secret"] = True
    return out
```

Without this, `Secret[str]` is invisible to `extract_field_descriptors` (§1.2) and
therefore to every cached surface — the annotation would mask in `info --job` and leak in
the TUI. **This is what makes the two markers genuinely one mechanism** rather than two
that happen to agree in `is_secret_field`.

### 2.3 The second gate — `validate_job_config_types`

`SUPPORTED_TYPES` / `_is_supported` (`job_config.py:26,370`) reject `Secret` outright,
independently of Pydantic. Teach both `Secret[str]`, and teach `coerce_value` to wrap a
resolved string. Without this, §2.1 ships a type that builds a schema and is then refused
at registration.

### 2.4 Correct the docstring

`_types/redaction.py`'s module docstring currently describes behaviour that does not
exist ("config fields declared secret … handled by the config consumer, which wraps their
resolved values in `Secret`" — no such consumer). After Phase 2 it becomes true; update
it in the same commit so the two never diverge again.

**Phase 2 exit criteria** — `token: Secret[str]` in a job config model:
- the job appears in `func` (D11);
- `SYNC_TOKEN=abc func sync` populates it from the environment;
- `rc.log(f"{config.token}")` prints `•••` (D17);
- `func builtin info --job` and all three TUI surfaces mask it;
- and `functualize.types.Secret` becomes the **documented** way to declare a credential,
  with `json_schema_extra={"secret": True}` retained as the marker for fields that must
  stay a plain `str`.

---

## Phase 3 — One resolver, one name

*Closes D5, D6, and the divergence in §2.1 of the report. This is the highest-severity
work and the precondition for Phase 4. Lands with Phases 1–2.*

### 3.1 Delete the bare `FIELD` env fallback *(D5 — breaking, and necessary)*

`job_config.py:439` falls back to an unprefixed `os.environ.get(FIELD.upper())`. With
nothing functualize-related set, a field named `user` resolves to the ambient `$USER`
and the declared default never applies. The same trap holds for `path`, `home`, `shell`,
`lang`, `term`, `editor`, `pwd`, `hostname`, `debug` — and on a field named `token` or
`password` it is credential substitution, not just a wrong default.

There is no configuration that makes this safe and no deprecation that makes it safer;
the correct value is currently unreachable. Remove it, and say so plainly in the
CHANGELOG under a "silently wrong values" heading.

### 3.2 Settle on one env convention *(P3)*

Precedence today, highest first:

```
CLI  >  JOB__FIELD  >  FIELD  >  JOB_FIELD  >  config file  >  default
        (undocumented)  (ambient)  (the documented one)
```

After 3.1 the bare form is gone. Of the two survivors, **`JOB_FIELD` is the one to keep**:
it is what the docs teach, what `func builtin env` emits, what `info --job` reports, what
`EnvSource` and `env_var_for` build, and what round-trips through the resolution chain.
`JOB__FIELD` is named only by an error message.

Accept `JOB__FIELD` for one minor release with a deprecation warning naming the
`JOB_FIELD` replacement, then remove it. Fix `missing_value.py`'s error text — currently
`STRICT__<FIELD>` — to name the surviving form.

> ADR-008 deferred this to ADR-006 as a convenience question that `[secrets]` would
> reduce to cosmetics. D5 makes it a correctness bug. It is promoted to blocking, and
> `[secrets]` does not mitigate it — a declaration block that names one variable while
> three resolve is a fifth opinion, not a fix.

### 3.3 Collapse resolvers 2 and 3 onto resolver 1

`chain.resolve_section` (TUI) and `_resolve_field_with_source` (`info --job`) each
re-derive values, know one env form, skip coercion, and disagree with the executor.
Replace both with a single seam that returns, per field, the value the run will use
**and** the source that produced it:

```python
@dataclass(frozen=True)
class ResolvedField:
    name: str
    value: Any | None          # None == genuinely unresolved
    source: str                # "cli" | "env" | "file" | "default" | "unset"
    origin: str                # "SYNC_CREDENTIAL" | "config.prod.toml" | "model default"
    secret: bool
    required: bool

def resolve_job_fields(job_name) -> list[ResolvedField]: ...
```

`resolve_job_config` becomes a thin wrapper that feeds `resolve_job_fields`' values to
Pydantic. `info --job`, the TUI Config Table, the drill-down, and `func builtin env` all
read `ResolvedField`. `origin` is what lets P3 hold — the tool prints the name it read.

**P6**: a cross-surface parity test — one job, one environment, assert `info --job`, the
Config Table, and an actual run agree field-for-field. That test is the enforcement
mechanism for P1 and it fails the moment a fifth resolver appears.

---

## Phase 4 — Make the answer discoverable

*Closes D7, D8, D9. This is ADR-008 §2's goal, reached mostly by fixing the existing
commands rather than adding a flag.*

### 4.1 Required-and-missing must read as missing *(D7, and ADR-008 §5)*

Two surfaces make the same mistake, for the same reason, and one fix serves both.

`_resolve_field_with_source` guards with `default is not None and default is not ...`,
but a Pydantic v2 required field's default is `PydanticUndefined` — neither. So the
`"not set (required)"` branch is **unreachable for every required field**, and a required
credential renders `•••  model default`, which reads as "configured".

`preflight_summary.py` gets it half-right — it already shows `○*` for a required-unset
field — but then labels the source `(default)` for a field that has no default:

```
   ○* token: (default)  str  required, no default, secret
```

After 3.3 both disappear: `ResolvedField(value=None, source="unset")` renders `⚠ not set`
with the variable name in `origin`, on both surfaces. **This is the whole of ADR-008 §5** —
the presence indicator already exists and works; only the label was wrong.

### 4.2 `func builtin env` must not crash *(D8)*

`resolved_job_config` may raise `ValidationError` — reasonable for a programmatic seam,
unhandled at the CLI boundary, so the operator scenario the command exists for produces a
raw traceback. After 3.3 it consumes `resolve_job_fields`, which reports unresolved
fields instead of raising.

### 4.3 `func builtin env` must report presence *(D9, P4)*

Today `export SYNC_CREDENTIAL='•••'` is byte-identical whether the credential is set or
not. With `ResolvedField`:

```bash
export SYNC_API_URL='https://api.example.com'      # source: config.prod.toml
export SYNC_CREDENTIAL='•••'                       # source: env  (set)
# SYNC_TOKEN=                                      # REQUIRED — not set
```

Commented-out lines for anything unset make the output **already** the `.env` skeleton
ADR-008 §2 wanted. `--template` then reduces to "emit the same thing with values
stripped", if it is still wanted at all. Stdout-only, per the ADR's open question — right,
for the reason given there.

This is also what makes dropping `[secrets]` safe: the discoverability the block was for
is delivered here, by a command that prints the names it actually reads (P3) rather than
by a file a human must keep in step with the model.

### 4.4 Documentation *(P3)*

- `docs/guides/job-config.md:113-141` — correct the precedence table and the mermaid
  diagram; document `JOB_FIELD` as the single form; add the deprecation note for
  `JOB__FIELD`.
- **New**: a "Credentials" section in `docs/guides/configuration.md` — declare with
  `Secret[str]`, discover with `func builtin env`, verify with `info --job`, and the
  explicit statement that config files have no vocabulary for naming a secret's
  location, and why that is deliberate (ADR-008's `${env:VAR}` argument, kept verbatim).
  State plainly that there is **no** `[secrets]` block and none is planned — the model is
  the only declaration.
- **New example**: `examples/standalone/secrets_lab`, walking Ana's five steps. Today no
  example anywhere in the tree shows a job config with a credential — which is itself
  part of the discoverability gap the ADR is about.

---

## Phase 5 — withdrawn

**ADR-008 §3 (`[secrets]`) is dropped** (maintainer decision, 2026-08-27). Two independent
reasons, and either alone would be sufficient:

- **The tool already knows.** After Phase 1.3, `preflight_summary.py` renders `○*` for
  every required-and-unset field, and after Phase 4.3 `func builtin env` emits a commented
  line naming each one. A TOML block restating that is a second declaration of a fact the
  model already carries — exactly what P2 exists to prevent.
- **Timing was its only real contribution**, and Phase 3 delivers that instead:
  `ResolvedField(value=None, source="unset")` is available before the job runs, without a
  new config surface to document, validate, and keep in step with the model.

**ADR-008 §5 is absorbed into Phases 1 and 4**, not deferred. `preflight_summary.py`
already renders presence and already works; §5 reduces to masking the value (§1.3) and
correcting the `(default)` label on a required-no-default field (§4.1). There is no fifth
phase.

**ADR-008 §4 is adopted verbatim**: required-ness belongs to Pydantic. With §3 dropped
this is no longer a constraint on a new config block — it is simply the rule, and the
reason dropping §3 is safe.

---

## Amendment to ADR-007

ADR-007's decision is a **no-op as written** and its Consequences section overstates the
risk of a change that currently breaks nothing.

1. **The decision must include `_app/boot.py:494`.** `register_format_provider(
   IniFormatProvider())` runs unconditionally, before `discover_entry_points()`, and
   `test_discover_entry_points_does_not_remove_programmatic_registrations` guarantees the
   entry point cannot undo it. Simulated: removing the `ini` entry point leaves
   `['.cfg', '.ini', '.toml']` registered. Editing `pyproject.toml` alone changes nothing.
2. **Correct the retention argument.** ADR-007 keeps `IniFormatProvider` partly because it
   "preserves … a test that exercises registration". It does not — `tests/config/
   test_registry_properties.py` and `test_provider_registry_idempotent_properties.py`
   exercise the seam with Hypothesis-generated providers. The honest argument for keeping
   it is optionality for existing users, which is sufficient on its own.
3. **`migration.py` needs an entrance or an exit.** Zero callers, zero tests, and the
   `func builtin config` migration the ADR's Migration §1 points at does not exist
   (`config` has `show`, `path`, `edit`). Either add `func builtin config migrate
   <in.ini> <out.toml>` with a wiring test, or delete the module — a migration path with
   no entrance helps nobody, and per `wiring-discipline.md` it is the third instance of
   this exact shape in this review.
4. **Size the doc sweep honestly.** 27 files reference `.ini` (docs 5, examples 7, tests
   19, contributor 4); `docs/guides/configuration.md` alone mentions it 24 times, and
   `examples/project/weather_app` ships `config.base.ini` + `config.prod.ini` as its
   working example. The runtime error text ("`.toml, .ini, .cfg` by default") needs
   updating too.
5. **Sequencing**: independent of Phases 1–5 and can proceed in parallel. It touches the
   same guide as Phase 4.4, so land the doc sweeps together.

---

## Risks

| Risk | Mitigation |
|---|---|
| 3.1 (bare `FIELD` removal) is breaking for anyone who relies on it | They cannot be relying on it deliberately — the behaviour is undocumented and the correct value is unreachable while it stands. CHANGELOG under a "silently wrong values" heading. |
| 3.3 is a large refactor touching four call sites | It is the smallest change that makes Phase 4 correct, and it lands in the same session as Phases 1–2 so the parity test arrives before any further surfaces. |
| `CACHE_VERSION` 14 → 15 invalidates every user's cache | Routine; the deserializer already tolerates missing newer keys. |
| Phase 2's core schema changes `model_dump()` output for `Secret` fields | Intended (safe by default). Callers needing the real value use `get_secret_value()` / `reveal()`, already the documented contract. |
| 1.4's `password` flag interacts with `textual-autocomplete` | Suppress the dropdown while `password` is on; a completion list under a masked field re-renders the value one row below the mask. Covered by a Pilot test. |

## Settled — no longer open

All four questions this proposal opened were answered by the maintainer on 2026-08-27 and
are folded into the phases above:

1. **TUI secret editing** — mask as typed (§1.4). Assessed first, as asked: `SmartBar`
   subclasses Textual's `Input`, which has a native `password` reactive, and INSERT mode
   reuses the bar rather than opening a separate editor. ~10 lines, not the "more work"
   the question assumed. Disabling `i` is no longer needed.
2. **`JOB__FIELD` deprecation** — one minor release (§3.2).
3. **`[secrets]`** — dropped (Phase 5, withdrawn). §4 is kept.
4. **Sequencing** — Phases 1–3 land together in one session (§Settled scope), so the
   cross-surface parity test gates every later change.

## Correction against the first draft of this proposal

The first draft asserted that ADR-008 §5 needed a preflight panel "built and wired first".
That was wrong: `_cli/tui/preflight_summary.py` is live, wired at ten call sites, and
already renders presence indicators that work. The dead module is
`_cli/tui/preflight_widget.py`, a second implementation of the same idea — which is why
§1.1 deletes it rather than fixing it. §5 is correspondingly *cheaper* than first
assessed, not larger: it is absorbed into §1.3 and §4.1 and needs no phase of its own.
