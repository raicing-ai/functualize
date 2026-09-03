# Shape Intent: Output-Flag Normalization

**Status: specified, not yet implemented**
**Date: 2026-09-03** (opened from the `standalone-distribution` Specify-phase flag audit;
verified against HEAD `39a0be2`)
**Scope: six shipped builtin commands in `_cli/builtins.py`, plus `_cli/info.py`'s renderer
resolution. No kernel change, no new layer, no new public API. Breaking, and free to be —
`.spec/CONSTITUTION.md` → Pre-Release Stance.**

Six first-party commands answer one question — *"text or JSON?"* — with **two spellings and
three behaviors**. Collapse them to one spelling with one behavior.

---

## The finding

Measured 2026-09-03 by running each command against `FUNCTUALIZE_CLI_OUTPUT`. Not inferred
from code.

| Command | Spelling | `…=json` honoured | `…=plain` honoured |
|---|---|---|---|
| `builtin info` | `--json` (bool) | **yes** | **yes** — distinct from `rich` |
| `builtin info jobs` | `--json` (bool) | **yes** | **no** — byte-identical to `rich` |
| `builtin info all` | `--json` (bool) | **yes** | **no** — byte-identical to `rich` |
| `builtin why` | `--json` (bool) | **no** | **no** |
| `builtin workflow list` | `--format` (choice) | **no** | **no** |
| `builtin workflow state` | `--format` (choice) | **no** | **no** |

Observed output, in `examples/quickstart/step1_basic`:

```
FUNCTUALIZE_CLI_OUTPUT=json func builtin info           → {  "functualize": "0.1.2", …
FUNCTUALIZE_CLI_OUTPUT=json func builtin info jobs      → [  {    "name": "forecast", …
FUNCTUALIZE_CLI_OUTPUT=json func builtin info all       → {  "functualize": "0.1.2", …
FUNCTUALIZE_CLI_OUTPUT=json func builtin workflow list  → No active workflows.        ← text
FUNCTUALIZE_CLI_OUTPUT=json func builtin why forecast   → forecast → WOULD RUN …      ← text

FUNCTUALIZE_CLI_OUTPUT=plain func builtin info          → functualize 0.1.2environment: …
FUNCTUALIZE_CLI_OUTPUT=rich  func builtin info          → ╭─────────────────────…      ← differs
FUNCTUALIZE_CLI_OUTPUT=plain func builtin info jobs     → forecast   Check today's …
FUNCTUALIZE_CLI_OUTPUT=rich  func builtin info jobs     → forecast   Check today's …   ← identical
```

**Three behaviors, not two:**

1. `--json` **through** `resolve_renderer` — honours the configured default (`info` family)
2. `--json` as a **raw bool** — ignores it (`why`)
3. `--format` **choice** — ignores it (`workflow list`, `workflow state`)

An agent that exports `FUNCTUALIZE_CLI_OUTPUT=json` — the documented way to avoid passing a
flag on every call — gets JSON from three commands and prose from three.

## What is *not* in scope

**The global `--output` stays exactly as it is.** It is a different axis, and folding builtin
rendering into it would be a regression, not a cleanup:

- It is plumbed to one consumer — `app._output_format` →
  `_engine/capabilities/stdout.py:156` → `_primitives/stdout_emitter.py` — and decides how
  `out.emit(value)` serializes **a job's emitted value**. Builtins have no `Stdout`
  capability and never call `out.emit()`.
- The separation is documented: `docs/cli/workflow.md:37-40` calls `--format` "domain-aware"
  and "distinct from the global `--output`, which only formats the dispatch layer's return
  value."
- `docs/guides/composition.md:56`: "`out.emit()` honours `--output`; `print` does not."

That doc distinguishes `--format` from `--output`. **It never distinguishes `--format` from
`--json`**, because there is no distinction to draw. That gap is this document.

Also out of scope: `builtin parallel --output` (`interleaved`/`grouped`/`prefixed`) is a
*layout* selector, a third unrelated meaning of the word. Renaming it is defensible but
independent.

---

## Assertions

### 1. The current state

| # | Assertion | Verdict |
|---|---|---|
| `CUR.1` | Two spellings exist for one question across six commands | **CONFIRMED** — `--json` at `_cli/builtins.py:1063,1571,1676,1767`; `--format` at `:763,795` |
| `CUR.2` | `--format` carries `["table","json"]`; the renderer vocabulary is `("rich","plain","json")` | **CONFIRMED** — `_cli/builtins.py:763,795` vs `_cli/info.py:41`. **The vocabularies are not the same set**, which is the substance of D1 below |
| `CUR.3` | `resolve_renderer(json_flag, cli_config)` treats the flag as an *override*, falling back to config then `FUNCTUALIZE_CLI_OUTPUT` then `"rich"` | **CONFIRMED** — `_cli/info.py:44-65` |
| `CUR.4` | `builtin why` declares `--json` but never calls `resolve_renderer` | **CONFIRMED** — binds a raw `as_json` bool and branches on it directly (`_cli/builtins.py:1063-1091`) |
| `CUR.5` | `plain` is honoured by `builtin info` only; the other two `info` subcommands render it identically to `rich` | **CONFIRMED by experiment** — `:1602` has the `plain` branch; `info jobs` and `info all` have none |
| `CUR.6` | The setting is validated against `("rich","plain","json")` in two places | **CONFIRMED** — `_cli/data/func_settings.py:187`, `_cli/config.py:226,242` |

### 2. The target

| # | Assertion | Verdict |
|---|---|---|
| `TGT.1` | All six commands accept one spelling | **GAP** |
| `TGT.2` | All six honour `[cli] output` / `FUNCTUALIZE_CLI_OUTPUT` when no flag is passed, and the flag overrides it | **GAP** — today only the `info` family does |
| `TGT.3` | One vocabulary spans all six, resolving D1 | **GAP** |
| `TGT.4` | A command that cannot render a value in the requested form says so, rather than silently rendering something else | **GAP, and this is the trap** — `info jobs` currently *accepts* `plain` and silently emits `rich`. Whatever vocabulary wins, silent equivalence is the defect to remove, not preserve |
| `TGT.5` | `--output`, `--perf-report` and `builtin parallel --output` are untouched | **GAP (constraint)** |
| `TGT.6` | No command ships both spellings, even transitionally | **GAP (constraint)** — pre-release stance forbids deprecation shims |

### 3. Blast radius

| # | Assertion | Verdict |
|---|---|---|
| `RAD.1` | Only `_cli/builtins.py` and `_cli/info.py` change | **GAP, needs confirmation** — the setting validators at `_cli/config.py:226` and `_cli/data/func_settings.py:187` also encode the vocabulary and move if D1 changes it |
| `RAD.2` | Documentation naming these flags is updated | **GAP** — `docs/cli/workflow.md:34-46` documents `--format table\|json` explicitly; `docs/` also carries `--json` usages |
| `RAD.3` | doc-verify scenarios that invoke these commands still pass | **GAP** — `examples/docs/scenarios/a-core-builtins.toml` invokes `builtin config show`; scenarios naming `--json`/`--format` must be re-run, and a **failing scenario is reported, never silently updated** (doc-verify rule 4) |
| `RAD.4` | The agent skills in `skills/` do not instruct `--json`/`--format` in a form this breaks | **GAP, must be checked before any edit** — `skills/` ships end-user agent instructions and `evals/` measures them; a changed flag that a skill still teaches is a silent eval regression |

---

## Open decisions

| # | Question | Why it cannot be defaulted |
|---|---|---|
| **D1** | Which spelling and which vocabulary? | Two sub-choices that interact — see below |
| **D2** | Does `plain` become real everywhere, or is it dropped? | `CUR.5` shows it is honoured by exactly one command. Making it real is work in five; dropping it is breaking for anyone who set it. **Neither is obviously right** |
| **D3** | Is `builtin parallel --output` renamed for the same reason? | Out of scope as written, but it is the last remaining overload of the word and the cheapest moment to change it is while touching neighbours |

### D1 in detail

| Option | Spelling | Vocabulary | Cost |
|---|---|---|---|
| **A** | `--format` everywhere | `rich \| plain \| json` | `workflow` loses the word `table`; `table` becomes `rich`. Choice-typed, extensible, matches the setting's existing vocabulary |
| **B** | `--format` everywhere | `table \| json` | The `info` family loses `plain` and `rich` collapses to `table`. Smaller vocabulary, but `rich` panels are not a "table" and the setting's three values no longer map |
| **C** | `--json` everywhere | boolean | Simplest and smallest diff; `workflow` loses `--format`. But a bool cannot express `plain`, so D2 is forced to "drop", and the flag can never grow a third form |

**Recommendation: A.** It preserves the setting's existing `("rich","plain","json")`
vocabulary — which is already validated in two places and already the config surface — and it
is the only option that leaves room to grow. Its cost is renaming `table` to `rich` in two
commands' help text and docs.

**A also forces D2 to "make `plain` real"**, which `TGT.4` wants anyway: today `info jobs`
accepts `plain` and silently lies.

---

## Test tiers

Per `.spec/TESTING.md`.

| # | Criterion | Tier |
|---|---|---|
| T1 | For each of the six commands and each vocabulary value, the rendered form is the requested one — asserted as the right answer, never `!= wrong` (`pitfalls.md` #15) | CLI integration (`cli_run`) |
| T2 | With no flag, each of the six honours `[cli] output`, then `FUNCTUALIZE_CLI_OUTPUT`, then the default — the same ladder for all six | CLI integration |
| T3 | An explicit flag overrides a conflicting configured default, on all six | CLI integration |
| T4 | No command accepts the retired spelling — asserted, so a leftover is a failure rather than a silent alias | CLI integration |
| T5 | The global `--output`, `--perf-report` and `builtin parallel --output` are unchanged | existing suites, re-run |
| T6 | doc-verify scenarios naming these flags pass | `run-scenario`, on demand |

> `tests/conftest.py:170-187` strips `FUNCTUALIZE_*` autouse, so every T2/T3 case must pass
> `FUNCTUALIZE_CLI_OUTPUT` explicitly via `cli_run(env=…)`.

### Wiring paths to name at close

- `_run_cli` → `detect_mode` → `Mode.BUILTIN` → the `builtin` group → each of the six
- resolution — `resolve_renderer` (or its successor), called by **all six** rather than three
- Sabotage `resolve_renderer`'s config fallback and confirm a T2 case fails

---

## Relationship to other work

**`standalone-distribution` does not depend on this and must not wait for it.** That feature
adds `--format json` to its new commands and rides `info`'s existing `--json` where it extends
it — consistent with the tree as it stands today, and consistent with **option A** if this
lands. If **B** or **C** wins, its two new commands change with the other six.

Sequencing is free either way. The only coupling worth noting: if this lands **first**, the
new commands join a settled convention instead of a contested one.

## Two adjacent defects — not this document's scope

Both found in the same audit, both live at `39a0be2`, both reproduced:

1. **The global `--output` hard-errors on every builtin.** `func --output json builtin version`
   → `Error: No such option '--output'.` It is a dispatch-layer global never declared on
   click's root group; `--log-level` works on both routes, `--output` on one.
2. **`--perf-report` misparses in its documented bare form before a builtin.**
   `func --perf-report builtin version` → `Error: No such command 'version'.` Dispatch
   implements optional-value lookahead; click declares `--perf-report TEXT`, always requiring
   a value, so `builtin` is swallowed as the value.

Neither is a rendering-flag problem. File separately.
