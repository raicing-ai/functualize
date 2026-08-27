# Scrutiny: Config Fields, Secrets, and Their Interaction

**Date**: 2026-08-27
**Scope**: ADR-007 (TOML-only config formats), ADR-008 (secret discoverability), and
the live `_config/` + secrets behaviour they describe
**Method**: every claim below was executed against this worktree — a scratch project
with a credential-bearing job, the real `func` CLI, and the live TUI driven through a
PTY (`observe-tui`). Nothing here is inferred from reading alone.
**Verdict**: **REVISE both ADRs before adopting.** ADR-007's decision is a no-op as
written. ADR-008 correctly diagnoses the disease and then operates on the wrong organ.

---

## 1. Executive summary

Both ADRs are unusually well-researched documents. Every line number ADR-008 cites is
accurate. Its central architectural instinct — *one answer to "is this a secret"* — is
right, and its rejection of `${env:VAR}` interpolation is well-argued.

The problem is that both ADRs describe a system that is **less wired than they assume**.
Their premises were checked against the source; they were not checked against a running
process. Three consequences:

| | ADR says | Actually |
|---|---|---|
| **ADR-007** | Removing the `ini` entry point unregisters INI | `boot.py:494` re-registers it unconditionally. **The change does nothing.** |
| **ADR-008 §1** | The preflight regex is "an active leak … already shipped" | `PreFlightWidget` is **never mounted**. It is dead code. The leak is latent. |
| **ADR-008 §1** | Fixing it is "a bug fix that should not wait" | The three panels that **do** render config before a run mask **nothing at all**. |

The live leak is real and worse than described — it is just not where ADR-008 looks. I
reproduced secrets rendered in cleartext on three separate TUI surfaces a user reaches
with two keystrokes, including a value the TUI **fetched from the environment itself**
and put on screen unprompted.

Underneath both ADRs sits a structural fact neither names: **there are four independent
config resolvers**, and they disagree. Unifying *secret detection* on top of four
disagreeing *resolvers* produces a system that masks correctly and reports the wrong
value. ADR-008 §5 ("preflight shows presence") is built directly on this sand.

**17 defects verified**, 4 of them user-visible credential leaks, 3 of them dead wiring
of exactly the shape `contributor/guides/wiring-discipline.md` exists to prevent.

---

## 2. Map of the current system

There are **two** config systems that share vocabulary and confuse everyone:

| | Framework settings | Job config |
|---|---|---|
| Declared in | `[tool.functualize]`, `~/.config/functualize/config.toml` | a Pydantic model per job |
| Env prefix | `FUNCTUALIZE_*` | `JOB_FIELD` / `JOB__FIELD` / bare `FIELD` |
| Inspected with | `func builtin config show` | `func builtin info --job <j>` |
| Example | `examples/standalone/config_lab` | `examples/project/weather_app` |

Both ADRs are about the **second**. `config_lab`, the project's flagship config example,
teaches the **first**. There is no example anywhere in the tree that demonstrates a job
config with a credential — which is itself part of the discoverability gap.

### 2.1 Four resolvers, four answers

This is the finding that reframes both ADRs.

| # | Resolver | Used by | Env forms it knows | Coerces types? |
|---|---|---|---|---|
| 1 | `resolve_job_config` (`_config/job_config.py:394`) | **the executor — authoritative** | `JOB__FIELD`, bare `FIELD`, then chain (`JOB_FIELD`) | via Pydantic |
| 2 | `chain.resolve_section` (`_cli/tui/chain_resolution.py:397`) | **TUI preflight + Config Table** | `JOB_FIELD` only | no |
| 3 | `_resolve_field_with_source` (`app/adapters/cli.py:1189`) | `func builtin info --job` | `JOB_FIELD` only | no |
| 4 | `_resolve_env_vars` (`_cli/builtins.py:327`) | `func builtin env` | reads resolver #1's output | n/a |

Resolvers 2 and 3 are blind to two of the three env conventions resolver 1 honours.
Verified divergence, same process, same environment:

```
$ USER=root-ambient func builtin info --job sync
│ user │ service-account │ model default │      ← what the tool reports

$ USER=root-ambient func sync
INFO:functualize.job.sync:… user=root-ambient   ← what the job receives
```

`info --job` is documented as the honest seam ("both must agree with each other and
with a real run — so they resolve through the one path the engine uses, not a
re-implementation", `app/core.py:682`). It is a re-implementation, and it disagrees.

### 2.2 Six answers to "is this a secret"

ADR-008 counts four and rejects a fifth on principle. The real count is six, and two of
the extras are already shipped:

| # | Mechanism | Where | Status |
|---|---|---|---|
| 1 | `Secret` annotation | `is_secret_field` | **unusable** — see D11/D12 |
| 2 | `json_schema_extra={"secret": True}` | `is_secret_field` | works for *display*, not for *value* |
| 3 | `collect_secret_values` / `redact` | Shell, Stdout | **inert for job config** — see D10 |
| 4 | `redacted_snapshot` | state store, MCP | works |
| 5 | `_SENSITIVE_PATTERN` regex | `preflight_widget.py:31` | **dead code** — see D1 |
| 6 | **`tui.sensitive_keywords`** | a registered, user-settable setting | **no consumer** — see D13 |

ADR-008 never mentions #6. It matters for the decision: #6 is a user-facing promise. If
§1 deletes the regex without addressing the setting, a user who writes
`sensitive_keywords = "credential,pat,bearer"` still gets nothing — and now the setting
is permanently unimplementable, because detection has become model-driven rather than
name-driven.

---

## 3. Verified defect register

Severity: **S1** credential exposure · **S2** wrong information at a decision point ·
**S3** broken developer experience · **S4** dead code / doc drift.

### D1 · S4 — `PreFlightWidget` is a dead duplicate of a live module

> **Two modules share the name.** `_cli/tui/preflight_summary.py` is the **live**
> preflight — wired at ten call sites in `app.py`, and the source of the `job —` +
> `● field: value (source)` block under the SmartBar. `_cli/tui/preflight_widget.py`
> is a **second, unmounted** implementation of the same idea. This defect is about the
> second; D2 is about the first.


```
$ grep -rn "PreFlightWidget" --include='*.py' src/
src/functualize/_cli/tui/__init__.py:31     (import)
src/functualize/_cli/tui/__init__.py:64     (__all__)
src/functualize/_cli/tui/preflight_widget.py  (the definition itself)
```

No `compose()`, no `mount()`, no `update_from_pending()` call anywhere in `src/`. Two
test files construct it directly. Its "integration" test opens with a helper commented
*"This mirrors the `_parse_cli_args_to_kwargs` in `inline_tui.py`"* — a hand-copied
collaborator, for a module that no longer exists. This is the exact pattern
`wiring-discipline.md` §"A test that supplies its own collaborators cannot detect that
production supplies none" was written about.

**Impact on ADR-008**: §1 is not a bug fix, because the regex it targets does not
execute — the leak is in `preflight_summary.py`, which the ADR never mentions.

**§5 is the opposite of what I first assessed: it is largely already built.**
`preflight_summary.py` already renders presence indicators — `●` filled, `○`
empty-and-required, `·` optional-and-empty — and they work:

```
 req —
   ○* region: (default)  str  required, no default, NOT secret
   ○* token: (default)   str  required, no default, secret
   ●  opt: (default)     str  optional empty default, secret
```

Two things are wrong with it, not one missing panel: the values are unmasked (D2), and
a required field with **no** default is labelled `(default)` — the same class of
mislabel as D7. §5 is therefore a correction to a working panel, not a new feature.

### D2 · S1 — the live preflight summary renders secrets in cleartext

`preflight_summary.py` — the block under the SmartBar, refreshed on every keystroke, and
the panel a user actually reads before pressing Ctrl+Enter. Field declared
`Field(json_schema_extra={"secret": True})`; `is_secret_field` returns `True` for it:

```
│ sync --credential hunter2-super-secret --api-url https://x.example.com     │
│ sync —                                                                     │
│   ●  api-url: https://x.example.com (cli)  str                             │
│   ●  credential: hunter2-super-secret (cli)  str      ← cleartext          │
│   ●  sort-key: created_at (default)  str                                   │
```

`format_preflight_field_line` computes `display_value = value or str(default)` and has no
masking of any kind. Both halves leak: a value typed on the bar (above), and a non-empty
**default** — `Field(default="dev-token-123", json_schema_extra={"secret": True})` renders
that default on screen for every job that declares it, with nothing typed at all.

### D3 · S1 — the Config Table panel displays a secret it fetched from the environment

`Ctrl+R`. The user typed nothing but the job name; the TUI went and got the credential:

```
│ [R:1/3] Config Table                                                       │
│ Setting       Type  Value              Source   Description                │
│ ● credential  str   env-secret-abc123  env             ← cleartext         │
│ Ctrl+J/K switch  … i edit  r reset  / filter  Enter detail  Esc back       │
```

Worse than D2: D2 echoes what the user typed; this **retrieves** a credential and puts
it on a persistent, navigable, `i`-editable panel.

### D4 · S1 — the drill-down detail view shows every source's value unmasked

`Enter` on that row:

```
│ Detail: credential                                                         │
│   ● CLI        (not set)                                                   │
│   ★ Env        env-secret-abc123                       ← cleartext         │
│   ● Remote     (not set)                                                   │
```

`SourceChainDetailView._build_rows` uses `str(entry.value)` throughout
(`source_chain_detail.py:226,250`). It also stages edits and **writes them to disk on
Ctrl+S** — so a credential typed here lands in a config file.

### D5 · S2 — ambient environment variables silently override model defaults

`resolve_job_config` falls back to a **bare, unprefixed** `FIELD` env lookup
(`job_config.py:439`). Any config field whose name collides with a normal shell variable
is captured by it. With nothing functualize-related set anywhere:

```python
class SyncConfig(BaseModel):
    user: str = Field(default="service-account")
```
```
$ func sync
INFO:functualize.job.sync:… user=viltohmyst      ← ambient $USER, not the default
```

The declared default never applies. Same trap for `path`, `home`, `shell`, `lang`,
`term`, `editor`, `pwd`, `hostname`, `debug`. On a field named `token` or `password`
this is a credential-substitution bug, not just a correctness one.

### D6 · S2 — the documented env convention is the *lowest*-priority of three

Measured precedence, highest first:

```
CLI  >  SYNC__USER  >  USER  >  SYNC_USER  >  config file  >  model default
        (undocumented) (undocumented, ambient)  (the documented one)
```

```
$ USER=root SYNC_USER=service-account func sync
INFO:functualize.job.sync:… user=root            ← the documented form loses
```

`docs/guides/job-config.md:140` documents only `JOBNAME_FIELDNAME` and presents it as
priority 2 of 4. Meanwhile the framework's own error message names a *different* form:

```
You can also set STRICT__<FIELD> in the environment.
```

So the guide, the error message, `func builtin env`'s output, and the resolver each name
a different variable. ADR-008 §"Problem 1" calls this "two env-naming conventions"; it is
three, ranked against each other, with the documented one last.

### D7 · S2 — `info --job` reports a required, unset credential as "•••  model default"

```python
class ReqConfig(BaseModel):
    region: str = Field(description="required, no default")
    token:  str = Field(json_schema_extra={"secret": True})   # required, no default
    opt:    str = Field(default="", json_schema_extra={"secret": True})
```
```
┃ Field  ┃ Value             ┃ Source        ┃
│ region │ PydanticUndefined │ model default │
│ token  │ •••               │ model default │      ← reads as "configured"
│ opt    │ •••               │ model default │      ← identical to token
```

Cause: `_resolve_field_with_source` guards with `default is not None and default is not
...`, but a Pydantic v2 required field's default is `PydanticUndefined`, which is neither.
The `"not set (required)"` branch is **unreachable for every required field**. A
non-secret field leaks the sentinel to the screen; a secret field is indistinguishable
from a configured one.

This is precisely the question ADR-008 exists to answer, answered wrongly, on the surface
best placed to answer it.

### D8 · S3 — `func builtin env` crashes when a required credential is missing

The operator scenario the ADR targets:

```
$ func builtin env strict
pydantic_core._pydantic_core.ValidationError: 1 validation error for StrictConfig
token
  Field required [type=missing, input_value={}, input_type=dict]
```

A raw traceback, from the command whose entire purpose is telling you what to set.
`resolved_job_config` is documented as *"May raise ValidationError … a caller asking for
the config is better told it is incomplete than given a partial"* — reasonable for a
programmatic seam, unhandled at the CLI boundary.

**Impact on ADR-008 §2**: `--template` is described as "additive to a command whose
entire purpose is already this". The command cannot run at all in the case the template
is for.

### D9 · S3 — `func builtin env` cannot distinguish a set secret from an unset one

```
$ SYNC_CREDENTIAL=hunter2 func builtin env sync
export SYNC_CREDENTIAL='•••'

$ func builtin env sync                     # nothing set
export SYNC_CREDENTIAL='•••'                # byte-identical
```

`_env_print` masks on *secretness*, never on *presence*. The one command an operator
would reach for to answer "is the credential configured?" gives the same answer either
way. This is the discoverability gap ADR-008 describes, living inside the tool it
nominates as the fix.

### D10 · S1 — `Stdout` secret redaction is dead wiring

`_collect_job_secrets` (`executor.py:1513`) feeds `WiredStdout`. It calls
`_make_config_view(job_name)`, which returns a **`JobConfigView`** — not the resolved
model. `JobConfigView` has no `model_fields`, so the fallback iterates `dir(view)`:

```
model_fields on instance: None
model_fields on type   : None
dir() names used       : ['get', 'get_model', 'set', 'set_prefix']
collect_secret_values  : set()
```

Four bound methods. **The function can only ever return `frozenset()`.**

Its test constructs `WiredStdout("json", secrets={"hunter2"}, stream=buf)` — supplying
the collaborator production never supplies. ADR-008 states that value-based redaction
"covers the Shell capability and `Stdout`". It covers Shell. It does not cover Stdout for
job config.

### D11 · S3 — the public `Secret` type makes a job silently disappear

`functualize.types.Secret` is a **public export**. A user following it:

```python
from functualize.types import Secret

class VaultConfig(BaseModel):
    token: Secret[str]
```
```
$ func
WARNING:…: Failed to import and extract from '…/job_pub.py': Unable to generate
pydantic-core schema for functualize._types.redaction.Secret[str].
mcp — 6 commands
```

The job is **gone from the listing**. Exit code 0. A warning on stderr and an empty
result — the worst available failure mode, worse than a crash.

`redaction.py`'s own module docstring says `Secret[str]` is "accepted as a type
annotation … so config authors can write `token: Secret[str]`". It raises. ADR-008 §1b
identifies the schema problem correctly; it does not mention that the observable symptom
is a vanishing job.

### D12 · S3 — `validate_job_config_types` independently rejects `Secret`

ADR-008 §1b proposes giving `Secret` a `__get_pydantic_core_schema__`. Necessary, not
sufficient. A second gate rejects it regardless:

```
C validate_job_config_types: TypeError: Unsupported type for field 'x':
  <class 'functualize._types.redaction.Secret'>. Supported types are: str, int,
  float, bool, Enum subclasses, Optional[T] …
```

`SUPPORTED_TYPES` (`job_config.py:26`) and `_is_supported` (`job_config.py:370`) must
both learn `Secret[str]`, plus `coerce_value`. The ADR names none of these. As written,
§1b would ship a `Secret` that builds a schema and is then refused at registration.

### D13 · S4 — `tui.sensitive_keywords` is a user-facing setting with no consumer

Registered (`func_settings.py:173`), schema'd (`settings_schema.py:62`), whitelisted
(`_cli/config.py:60`), documented (`contributor/architecture/tui-architecture.md:175`),
default `"secret,password,token,key"` — the same four words as the dead regex. The TUI's
own code admits it:

> `_apply_settings`: *"the rest — `default_surface`, `history_retention`,
> `sensitive_keywords`, … — are resolved and displayed truthfully but have no consumer
> reading them yet"*

A user can set it, see it echoed back by `config show`, and believe they have closed a
leak. This is worse than a hardcoded regex, and ADR-008 does not account for it.

### D14 · S4 — ADR-007's decision is a no-op

ADR-007's premise: *"`ProviderRegistry.register_format_provider` loads them, so the
format layer is a genuine extension seam."* True — and irrelevant, because boot does not
rely on it:

```python
# _app/boot.py:493-494
app.config_registry.register_format_provider(TomlFormatProvider())
app.config_registry.register_format_provider(IniFormatProvider())   # unconditional
```

`discover_entry_points()` runs afterwards (line 530), and
`test_discover_entry_points_does_not_remove_programmatic_registrations` guarantees it
cannot remove what boot registered. Simulating the ADR's exact change:

```
entry-points only, ini removed  -> ['.toml']
boot sequence, ini entry point removed -> ['.cfg', '.ini', '.toml']   ← unchanged
```

Deleting the `ini` line from `pyproject.toml` changes nothing for `func` or for any
`FunctualizeApp`. The ADR's Consequences section predicts a "**Breaking change** … needs a
deprecation window" for a change that breaks nothing.

### D15 · S4 — the INI migration path has no entrance

`migrate_ini_to_toml` (`_config/migration.py:19`) has **zero callers in `src/` and zero
tests**. ADR-007 keeps the module because "its whole purpose is helping existing users off
INI", and its Migration step 1 points users at "`func builtin config` migration". The
`config` builtin has exactly three subcommands: `show`, `path`, `edit`. The command does
not exist.

Relatedly, ADR-007's stated reason for *retaining* `IniFormatProvider` — that it
"preserves … a test that exercises registration" — does not hold: `tests/config/
test_registry_properties.py` and `test_provider_registry_idempotent_properties.py`
exercise the seam with Hypothesis-generated providers, not with INI. The seam is already
independently tested. (The argument for keeping a real second implementation is still
defensible; the evidence offered for it is not the evidence that exists.)

### D16 · S3 — `FieldDescriptor` carries no secret flag (the blocker for every TUI fix)

`FieldDescriptor` is the cached, serialized, **boot-free** shape of a job's config fields —
what the TUI, completions, and dispatch read on a warm boot without importing the job
module. It has ten fields; none is `secret`. `PendingExecution` likewise carries only
`{name: (value, source)}`.

So ADR-008 §1's "`preflight_widget.py` calls `is_secret_field`" **cannot be implemented as
written**: the widget has no `FieldInfo` to pass, and obtaining one means importing the
config model, which forfeits the true-lazy-boot property (warm boot: 0 imports).

**Good news, verified**: the marker survives into the JSON schema, so the fix is cheap —

```json
"credential": { "default": "", "secret": true, "title": "Credential", "type": "string" }
```

`extract_field_descriptors` already reads `model_json_schema()`, so this is
`secret=bool(prop.get("secret"))` plus a `CACHE_VERSION` bump (currently 14). The
deserializer already uses `data.get(...)` for newer keys. **Design constraint this
implies**: if §1b gives `Secret` a core schema, it must *also* emit
`{"secret": true}` into the JSON schema, or annotation-marked fields will be invisible
to every cached surface.

### D17 · S1 — `json_schema_extra` secrets leak through logs and f-strings

ADR-008 §1b states this; confirmed:

```
$ SYNC__CREDENTIAL=hunter2-real-token func sync
INFO:functualize.job.sync:… credential=hunter2-real-token …
```

The field is `is_secret_field == True`. It is masked by `info --job` and `builtin env`,
and cleartext in every log line, traceback, and `Stdout` write. The two halves of the
secrets system — the declaration marker and the value wrapper — genuinely are disjoint.

---

## 4. What holds up

Not everything is broken, and the proposal should preserve these:

- **`func builtin info --job` is the right shape.** It uses `is_secret_field`, masks on
  presence rather than on value, and names the concrete source (`env var
  (SYNC_CREDENTIAL)`). Its comment — *"masking on presence, not on value, so an empty
  secret still reads as a secret"* — is the correct principle. Its defects (D7, and
  resolver #3) are fixable without changing its design.
- **Run history does not persist arguments.** `func sync --credential hunter2-cli-secret`
  leaves no trace of the secret on disk; `func builtin history` records job/status/
  duration only. Verified by grep across the project tree.
- **`redacted_snapshot` is sound**, and honours both markers with a correct depth guard.
- **ADR-008's rejection of `${env:VAR}`** is the strongest argument in either document,
  and the reasoning (a config-side redirect makes one source's *content* reconfigure
  another source's *lookup*) should survive verbatim into any successor.
- **ADR-008 §4** — required-ness belongs to Pydantic, `[secrets]` must not carry
  `required` — is correct and should be kept without change.
- **All eight line-number citations in ADR-008 are accurate.**

---

## 5. Gap analysis by persona

### Ana, the operator — clones the repo, must run `sync` in production, does not read Python

| Step | What she does | What happens |
|---|---|---|
| 1 | `func builtin env sync` to learn what to set | prints `SYNC_CREDENTIAL='•••'` whether or not it is set (D9) |
| 2 | tries the same on a job with a required token | raw Pydantic traceback (D8) |
| 3 | falls back to `func builtin info --job sync` | required credential reads `•••  model default` — looks configured (D7) |
| 4 | reads `docs/guides/job-config.md`, exports `SYNC_CREDENTIAL` | works — unless her shell has an ambient collision, which silently wins (D5/D6) |
| 5 | job fails; error says set `SYNC__CREDENTIAL` | a *fourth* spelling, contradicting the guide (D6) |

**Ana cannot complete her task without reading Python.** That is ADR-008's stated
problem, and none of its three decisions closes any of steps 1–5 as they actually fail.

### Ben, the job author — wants one credential handled safely

| Step | What he does | What happens |
|---|---|---|
| 1 | reads `functualize.types.Secret` in the public API, writes `token: Secret[str]` | **his job vanishes from `func`** with a stderr warning (D11) |
| 2 | adds `arbitrary_types_allowed=True` | `TypeError: Unsupported type for field 'token'` (D12) |
| 3 | finds `json_schema_extra={"secret": True}` | builds — masked in `info --job`, cleartext in every log line (D17) |
| 4 | opens the TUI to check before running | cleartext on three panels (D2/D3/D4) |
| 5 | sets `tui.sensitive_keywords` to close the gap | setting accepted, echoed back, does nothing (D13) |

**There is no way to declare a credential in a job config that is both settable and
masked.** ADR-008 §1b says this; the report adds that step 1's failure mode is silent
disappearance and that step 2 is a second, unnamed blocker.

### Cara, the reviewer — must certify no credential reaches screen, disk, or logs

Cara's checklist against the tree today: **screen — fails** (D2/D3/D4); **logs — fails**
(D17, D10); **disk — passes** (history and state redaction hold); **detection — six
mechanisms, two dead** (§2.2). The one control she would most want, `tui.sensitive_keywords`,
is inert.

---

## 6. Disposition of each ADR decision

### ADR-007

| Decision | Verdict |
|---|---|
| Unregister `ini` from entry points | **No-op.** Must also remove `boot.py:494` (D14). |
| Keep `IniFormatProvider` in-tree | **Keep** — but on honest grounds. The seam is already tested without it (D15); the real argument is optionality for existing users. |
| Keep `migration.py` | **Only with an entrance.** Zero callers, zero tests, and the command the ADR points at does not exist (D15). |
| "Breaking change, needs deprecation window" | **Overstated** for the change as specified; **accurate** once `boot.py:494` is included. |
| Doc sweep is mandatory | **Confirmed and larger than stated**: 27 files reference `.ini` (docs 5, examples 7, tests 19, contributor 4); `docs/guides/configuration.md` alone mentions it 24 times, and `examples/project/weather_app` ships `config.base.ini` + `config.prod.ini`. The runtime error text ("`.toml, .ini, .cfg` by default") also needs updating. |

### ADR-008

| Decision | Verdict |
|---|---|
| §1 Collapse detection to `is_secret_field` | **Right principle, wrong target.** The named widget is a dead duplicate (D1); the live leaks are in `preflight_summary.py`, `ConfigTablePanel` and `SourceChainDetailView` (D2/D3/D4). Also unimplementable as written without D16. |
| §1b Give `Secret` a core schema | **Necessary and insufficient** — D12 is a second gate, and D16 imposes a JSON-schema requirement the ADR does not state. |
| §2 `--template` for `func builtin env` | **Blocked** — the host command crashes in the target scenario (D8) and cannot report presence (D9). Fix those first; the template may then be unnecessary. |
| §3 `[secrets]` declaration-only | **Drop** (maintainer decision, 2026-08-27). It schedules a presence check against resolvers that report the wrong value (§2.1), and `preflight_summary.py` already renders presence from the model — so the block would be a second declaration of a fact the tool already knows. |
| §4 Required-ness belongs to Pydantic | **Adopt unchanged.** Correct — and it is what makes dropping §3 safe. |
| §5 Preflight shows presence | **Already ~80% built** in `preflight_summary.py` (D1). Two corrections, not one new panel: mask the values, and stop labelling a required-no-default field `(default)`. |
| "Adding a fifth mechanism is rejected on principle" | **Adopt** — and apply it to `tui.sensitive_keywords`, the sixth, which the ADR misses (D13). |
| Rejection of `${env:VAR}` | **Adopt unchanged.** Strongest argument in either document. |
| Open question: `[secrets]` in project config or `pyproject.toml` | Moot until §3 is unblocked. |
| Open question: `--template` overwrite behaviour | Stdout-only is right, for the reason given. |
| Open question: unify the env conventions (deferred to ADR-006) | **Promote to blocking.** D5 makes it a correctness and credential-substitution bug, not a convenience question. |

---

## 7. Recommended sequencing

The ADRs' own ordering (detection → template → `[secrets]` → preflight) front-loads the
lowest-value item and builds the last two on an unfixed foundation. Corrected order:

1. **Stop the bleeding.** Mask on the three live TUI surfaces (D2/D3/D4). Delete
   `PreFlightWidget` and its two test files (D1). Fix `_collect_job_secrets` (D10).
2. **Make `Secret` usable.** Core schema + `SUPPORTED_TYPES` + `coerce_value` +
   `{"secret": true}` in the JSON schema (D11/D12/D16).
3. **One resolver.** Collapse resolvers 2–4 onto `resolve_job_config`; delete the bare
   `FIELD` fallback (D5/D6/§2.1).
4. **Make the answer discoverable.** Fix D7/D8/D9 in place — at which point `--template`
   is a small addition rather than a workaround, and the preflight's `(default)` mislabel
   goes with it (§5).
5. **ADR-007** is independent and can proceed in parallel, once its decision is amended to
   include `boot.py:494`.

Steps 1–3 are the whole of the risk. `[secrets]` (§3) is dropped; §5 falls out of steps 1
and 4 rather than needing a phase of its own.

**Maintainer decisions, 2026-08-27**: mask-as-typed in the TUI (cheap — the SmartBar is a
Textual `Input`, which has a native `password` flag); one minor release is enough
deprecation for `JOB__FIELD`, given the small user base; `[secrets]` is dropped; and
steps 1–3 land together in one session, so the cross-surface parity test arrives before
any further surfaces are added.

---

## 8. Reproduction

Every claim above reproduces from a four-file scratch project:

```
repro/
├── pyproject.toml          # [tool.functualize] jobs_directories = ["jobs"]
└── jobs/job_sync.py        # SyncConfig: api_url, credential (secret), sort_key, user
                            # StrictConfig: token (secret, required, no default)
```

```bash
func sync                                     # D5 — ambient $USER wins over the default
USER=root SYNC_USER=svc func sync             # D6 — documented form loses
func builtin env sync                         # D9 — '•••' whether set or not
func builtin env strict                       # D8 — raw ValidationError
func builtin info --job req                   # D7 — PydanticUndefined / '••• model default'
SYNC__CREDENTIAL=tok func sync                # D17 — cleartext in the log line
```

TUI leaks (D2/D3/D4), via `observe-tui`:

```bash
uv run --with pyte python .claude/skills/observe-tui/scripts/tui_probe.py \
  --cwd repro --step "wait:Type a command" \
  --step "send:sync --credential hunter2-super-secret" --step sleep:3 --step snap \
  -- uv run func
```

Dead-wiring proofs (D1/D10/D14) are pure greps and a ten-line script; §3 gives each
inline.
