# 07 — What changes, file by file

The question this answers: **if we do this, how much of the existing system moves?**

Sizes are real (`wc -l` at `8d450ad`). Change estimates are the author's and should be
treated as order-of-magnitude, not as a bid. "Existing" means the file is already
there; "new" means it does not exist yet.

**Headline: no existing file is deleted, and no existing file is rewritten.** The
largest change to any current file is roughly 12 % of `frontier.py`. Compare Design 1,
whose Wave 1 cleanup step proposes to "move or delete runtime stores from
`_primitives`" — that is three files totalling 1,526 lines, four of whose classes are
public API.

---

## Wave 0 — Repair (no new abstraction)

Fixes B1–B4 plus the two documentation defects. **Nothing here depends on any design
decision**, which is the point: it can land while the ADRs are still being argued.

| File | Size | Change | What |
|---|---:|---:|---|
| `_primitives/scope_state_store.py` | 235 | **+40** | accept a generation; check it in `_mutate`; new `ScopeStateFencedError` path (**B1**) |
| `_primitives/scope_store.py` | 923 | **+15** | pass the held generation into `_state_store()`; pass `expect=` on the claim write (**B1, B4**) |
| `_primitives/lease.py` | 305 | **+10 / −4** | add owner to `check_generation`; **correct the module docstring**, which currently teaches that fencing holds without locking (**B4**) |
| `_engine/frontier.py` | 478 | **+8** | retry a refused CAS claim; surface a lost claim rather than swallowing it |
| `_app/boot.py` | 2,016 | **+25** | install the substrate in a step that may raise, before `APP_READY` (**B2**) |
| `_cli/tui/shell_mode.py` | 331 | **+3 / −1** | pass the app through so shell history writes to the installed substrate (**H5**) |
| `plugin/__init__.py` | 131 | **+4** | export `StoreSubstrate`, `Stored` (**H4**) |
| `.../functualize_substrate_sqlite/substrate.py` | 225 | **−6** | delete the "different machines" paragraph (**H3**) |
| `docs/guides/workflows.md` | — | **±12** | remove the `/mnt/shared` recommendation; point at the public port |
| `docs/guides/hosting.md` | — | **±8** | remove the load-balancer pairing |
| `_engine/capabilities/state.py` | 285 | **−0 / ±20** | correct the stale docstring (**M3**) |
| `_primitives/scope_store.py` | — | **−14** | delete the dead `"state": {}` field and its wrong docstring |
| `_types/protocols.py` | 930 | **+3 / −1** | `Stored.revision` becomes an opaque token, not an `int` — the type contradicts its own docstring and forecloses every remote backend ([`02`](02-what-exists-today.md) §9) |
| `.../functualize_state_sqlite/substrate.py` | 225 | **±1** | return the revision as the opaque type |

**New tests** (~6 files, ~400 lines): a two-process claim race that must yield two
distinct generations; a stale-runner state write that must be refused; a substrate
install failure that must fail boot; a TUI-write / CLI-read agreement test.

**Totals: ~155 lines of source across 14 existing files. No new modules.**

---

## Wave 1 — Ports and recorders

| File | Size | Change | What |
|---|---:|---:|---|
| `_types/persistence.py` | — | **new, ~340** | `StoreProfile` (ten fields, incl. `offline_capable` and `interactive_transaction`), `RuntimeStore`, the buffering `RuntimeTransaction`, the five writers, the three readers, the command and view dataclasses |
| `_types/protocols.py` | 930 | **+6 / −4** | `EngineHost` drops `substrate_override`; the engine no longer discovers storage |
| `_engine/recording/__init__.py` | — | **new, ~20** | |
| `_engine/recording/run_recorder.py` | — | **new, ~180** | lifecycle moments → `StartAttempt` / `FinishAttempt` commands |
| `_engine/recording/workflow_recorder.py` | — | **new, ~240** | walk moments → `ClaimWorkflow` / `CompleteStep` / `SuspendAtGate` / `ResumeWorkflow` |
| `_engine/executor.py` | 2,743 | **+60 / −85** | accept `runtime_store`; delete the lazy `substrate` property (`:1509-1527`); replace `_open_run_record` / `_close_run_record` with recorder calls; **the best-effort swallows at `:982, :1032, :1061, :1073` become explicit policy** |
| `_engine/frontier.py` | 478 | **+55 / −40** | claim/renew/release/record go through the workflow recorder; `Claimed \| Conflict` instead of `LeaseHeldError` |
| `_engine/capabilities/state.py` | 285 | **+20 / −15** | `State` writes become a fenced `StateBatch` command |
| `_app/boot.py` | 2,016 | **+90 / −20** | steps 6.5 / 6.6: select, prepare, capability-check, then `build_engine(app, runtime_store=...)`; same in `boot_static` |
| `_app/store_selection.py` | — | **new, ~140** | scheme registry, config resolution, `require(profile, ...)` |
| `_persistence_document/` | — | — | **does not exist.** The adapter lives beside the stores it wraps: |
| `_primitives/document_runtime_store.py` | — | **new, ~380** | `DocumentRuntimeStore` — wraps `ScopeStore`, `RunStore`, `ScopeStateStore`; declares the weak profile |
| `plugin/__init__.py` | 131 | **+8** | export `RuntimeStoreFactory`, `StoreProfile` |

**Net: ~1,280 new lines in 7 new files; ~300 changed lines across 7 existing files.**

The three biggest existing files barely move: `executor.py` changes about 5 % of its
lines, `boot.py` about 5 %, and `scope_store.py` not at all in this wave.

---

## Wave 2 — State machines enforced

| File | Change | What |
|---|---:|---|
| `_types/persistence.py` | **+90** | the transition table from [`06-data-model.md`](06-data-model.md) §1 as data, plus `IllegalTransition` |
| `_primitives/document_runtime_store.py` | **+70** | enforce the table; a terminal scope refuses |
| `_engine/workflow_walker.py` (1,153) | **+30 / −45** | the eight scattered `set_scope_status` calls become transition commands; the unbatched nested-block arm at `:767-770` merges |
| `app/_workflow_control.py` | **+20 / −15** | `cancel` stops proceeding unclaimed (`:439`) |

Note what this does to `workflow_walker.py`: it **shrinks**. Twelve status write sites
across five modules collapse to commands against one table.

---

## Wave 3 — Relational SQLite

Entirely inside the plugin. **No framework file changes.**

| File | Size | Change |
|---|---:|---:|
| `.../functualize_substrate_sqlite/substrate.py` | 225 | unchanged — still serves `fresh` and `shell-history` |
| `.../_runtime_store.py` | — | **new, ~650** |
| `.../_schema/*.sql` | — | **new, ~200** |
| `.../_migrations.py` | — | **new, ~180** |
| `.../_plugin.py` | 147 | **+30** — register a `RuntimeStoreFactory` alongside the substrate |

The plugin's package name, entry-point group and typed `PluginHost` usage are already
correct on `origin/master` (PR #45). Nothing there is re-done.

---

## Waves 4–6 — Attempts, interactions, outbox, import

| Area | New | Changed |
|---|---:|---:|
| Attempt identity end to end | ~120 | `executor.py` +40, `exec_policy.py` +25 |
| Input requests and candidates | ~260 | `workflow_walker.py` +50, `app/_workflow_answer.py` +40 |
| Outbox + dispatcher | ~340 | `_events/` +30 |
| Offline import from JSON and legacy SQLite | ~420 | — |
| `_events/run_log.py`, `walk_log.py` | — | **−120 net**: they stop being durable authorities and become pure observers |

---

## Totals

| | New lines | Changed lines in existing files | Existing files touched | Files deleted |
|---|---:|---:|---:|---:|
| Wave 0 | ~400 (tests) | ~155 | 14 | 0 |
| Wave 1 | ~1,300 | ~300 | 7 | 0 |
| Wave 2 | ~180 | ~110 | 4 | 0 |
| Wave 3 | ~1,060 | ~30 | 1 | 0 |
| Waves 4–6 | ~1,140 | ~185 | 6 | 0 |
| **Total** | **~4,080** | **~780** | **~27 distinct** | **0** |

`src/functualize/` is 102,083 lines. **This changes about 0.76 % of it** and adds
about 4 %.

---

## What does *not* change — and why that is the argument

| Untouched | Why it matters |
|---|---|
| The seven import-linter contracts (`pyproject.toml:249-390`) | no new layer, so no contract edit and no ADR to add one. Design 1 needs both before it can start. |
| `RunRequest` → `JobExecutionEngine.run()` | ADR-020's single entry point is untouched. Nothing gains a second path to storage. |
| The 20-step lifecycle and `tests/engine/test_lifecycle_order.py` | the engine keeps lifecycle ownership, so the ordering contract keeps meaning what it means. |
| `_app/` as sole composition root | strengthened: selection moves *into* `_app` from a plugin hook. |
| `StoreSubstrate` and both its implementations | retained for `fresh` and `shell-history`; ADR-022 is narrowed, not reversed. |
| `functualize.app.utils` public exports | no silent deletion. A deprecation is proposed in [`05-the-design.md`](05-the-design.md) §6 and is a decision, not a side effect. |
| `_discovery/`, `_config/`, `_gate/`, `_plugins/` | four of the five peer layers are not involved at all. |

---

## Comparison: what the other two designs move

| | Design 1 · Provider family | Design 2 · Minimal ports | **Design 3 · Engine-owned** |
|---|---|---|---|
| New top-level package | `_persistence/` (5 modules) | none | none |
| Import-linter contracts edited | yes — a new peer must be added to the independence contract | no | **no** |
| New ADR required before work starts | yes (new layer + public surface) | yes (ownership) | **no for Wave 0; yes for Wave 1** |
| `_primitives` stores | "move or delete" — 1,526 lines, 4 public classes | retained, adapted | **retained, adapted** |
| Lifecycle authority | split between `_engine` and `_persistence` | engine | **engine** |
| Boot mechanism | new `runtime_persistence` phase + bind-once handle | unspecified | **constructor argument; construction moves ~30 lines later** |
| Earliest date work can start | after the layer ADR | after the ownership ADR | **now** |

---

Next: [`08-delivery-and-tests.md`](08-delivery-and-tests.md).
