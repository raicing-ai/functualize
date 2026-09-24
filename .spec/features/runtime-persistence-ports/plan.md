# FUN-17 — Plan

**Status:** architecture gate **satisfied** 2026-09-23 against `1f3b760`. Supersedes the
scaffold, whose BEFORE/AFTER were `TODO`.

## Retrieval pass 3a — what was actually reachable

The gate names three tools. Two of them could not be reached from this runtime, and that
is recorded rather than glossed, because "a tool you cannot reach is not a tool that is
absent":

| Tool | Status |
|---|---|
| **graphify** | **unavailable** — MCP server failed to start (`EACCES` spawning `/root/.local/bin/graphify-mcp`). Not "unconfigured"; a permission failure on a binary that exists. |
| **serena** | **unavailable** — MCP connection closed on startup. |
| **zvec-grep** | reachable |
| `rg` + the codemaps | reachable, and carried the dependency-direction work the other two would have |

The dependency direction this plan asserts therefore comes from
`contributor/architecture/codemaps/dependencies.md` and from `rg` over real import lines,
not from a graph query. Every such claim below quotes its command. **A reviewer should
re-run the graphify/serena passes if either server comes back**, because they answer
"what references this" better than `rg` does, and this plan's blast radius is the weaker
for their absence.

## Codemaps read

`overview.md`, `modules.md`, `dependencies.md`, `data-flow.md`, `entry-points.md`.

One finding, and it changes an acceptance criterion rather than a drawing:
`dependencies.md:37` records that `exclude_type_checking_imports = true` makes
`lint-imports` blind to a deferred cross-layer import — "a deferred `_types → _app` import
leaves `lint-imports` reporting '7 kept, 0 broken', measured by adding one." Criterion 5
as written ("the seven contracts still pass") is therefore satisfiable by an illegal
design. `spec.md` §5 and T15 now pair it with an import-line test.

## Design skills consulted

- **`python-design-patterns`** (in-repo, `.claude/skills/python-design-patterns`, a symlink
  to `.agents/skills/python-design-patterns`). Principles: KISS, separation of concerns,
  single responsibility, God-class decomposition, composition over inheritance.
- **`design-patterns-refactoring`** (user-level, Refactoring.Guru catalogue + *Dive Into
  Design Patterns*). This is the skill `.claude/rules/spec-workflow.md` refers to as
  `coding__design-patterns-refactoring`; **on this machine it is slugged
  `design-patterns-refactoring`**. Worth correcting in the rule, since the hardcoded slug
  is exactly what that section warns against.

Confirmed by running the check the rule specifies rather than trusting the listing:
`rg -ci 'long method|feature envy|shotgun surgery|divergent change|middle man|primitive
obsession' .claude/skills/python-design-patterns/` returns **0**. The catalogue names below
all come from the user-level skill.

## BEFORE

```
  _types/  (stdlib only)                                      LAYER: _types
  ┌──────────────────────────────────────────────────────┐
  │ protocols.py                                         │
  │   StoreSubstrate     port for JSON documents         │
  │   Stored / Revision  opaque token  (NEW in FUN-24)   │
  │   EngineHost.substrate_override :470   ◄─────────────┼──┐ declared, but
  └──────────────────────────────────────────────────────┘  │ read by getattr
          ▲                    ▲                            │
          │ imports            │ imports                    │
  ┌───────┴──────────┐  ┌──────┴───────────────────────┐    │
  │ _primitives/     │  │ _engine/                     │    │
  │  substrate.py    │  │  executor.py  2744 lines     │    │
  │   substrate_for_ │◄─┼── :1524 LOCAL IMPORT ────────┼────┘
  │   project()      │  │  JobExecutionEngine :163     │
  │  scope_store.py  │◄─┼── :1565 ScopeStore(self.sub) │
  │   claim_scope    │  │  :936 :1059 :1071            │
  │   → raises       │  │    self._state_store()       │
  │     LeaseHeldErr │  │      .substrate  ×3          │
  │  run_store.py    │  │  frontier.py :183 claim_scope│
  │  scope_state_    │  │    → LeaseHeldError :170     │
  │   store.py       │  └──────────────────────────────┘
  └──────────────────┘            ▲
       LAYER: _primitives         │ build_engine(app)   ← NO storage argument
                          ┌───────┴──────────────────────┐
                          │ _app/boot.py  2084 lines     │
                          │  :220 def build_engine(host) │
                          │  :403 boot_static   ─┐       │
                          │  :622 boot_standard ─┴─ BOTH │
                          │        before config resolves│
                          └──────────────────────────────┘
                                   LAYER: _app
  ┌──────────────────────────────────────────────────────┐
  │ app/_workflow_control.py :430 claim_scope            │  PUBLIC
  │   :439 except Exception:  ← swallows the refusal     │
  └──────────────────────────────────────────────────────┘

  CROSSES A BOUNDARY (all legal today):
    _engine → _types            protocols
    _engine → _primitives       ILLEGAL AS A RUNTIME PEER IMPORT? No —
                                _primitives is above the peer layers, so
                                _engine → _primitives is downward and legal.
    _app    → _engine           composition root → peer, legal
  THE DEFECT IS NOT A CONTRACT VIOLATION. It is a direction the contracts
  cannot see: the engine pulls its collaborator instead of being handed it.
```

### Smells the BEFORE already carries

Catalogue names, each with the symbol it lives on and the count that found it.

| Smell | Where | Evidence |
|---|---|---|
| **Message Chains** | `executor.py:936, :1059, :1071` — `self._state_store().substrate` to build a `RunStore` | `rg -c '_state_store\(\)\.substrate' src/functualize/_engine/executor.py` → `3` |
| **Inappropriate Intimacy** | `executor.py:1526` — `getattr(self.host, "substrate_override", None)` against a slot the repo declares at `_types/protocols.py:470` | `rg -c 'substrate_override' src/functualize/_engine/executor.py` → `2` |
| **Primitive Obsession** | capability expressed as prose in docstrings; there is no capability type at all | `rg -c 'StoreProfile' -g '*.py' src/ plugins/` → `0` |
| **Large Class** | `JobExecutionEngine`, `executor.py:163-2744` ≈ **2580 lines** against the constitution's ~500 threshold | `rg -n '^class ' src/functualize/_engine/executor.py` |
| Exception as expected outcome (→ *Replace Exception with Test*, ch42) | `lease.py:226` raises `LeaseHeldError`; `app/_workflow_control.py:439` catches `Exception` bare | `rg -c 'except Exception:' src/functualize/app/_workflow_control.py` → `1` |

**Naming the first two is what produced the design.** *Message Chains* and *Inappropriate
Intimacy* both route to the same technique — **Hide Delegate / Move Method**, i.e. hand the
collaborator in rather than let the object walk to it. That is the construction move,
arrived at from the diagram rather than argued for.

## AFTER

```
  _types/  (stdlib only)                                      LAYER: _types
  ┌──────────────────────────────────────────────────────────────┐
  │ persistence.py  NEW  698 lines at T6, zero logic              │
  │   StoreProfile         10 measured fields + 2 labels         │
  │   8 commands · 6 outcomes · 6 views                          │
  │   10 @runtime_checkable Protocols                            │
  │     RuntimeStore  RuntimeTransaction                         │
  │     5 writers  ·  3 readers                                  │
  │ protocols.py   StoreSubstrate / Stored / Revision  UNCHANGED │
  │ errors.py      + RuntimeStoreCapabilityError                 │
  │                + CrossAggregateRefusedError                  │
  └───────▲──────────────────────▲───────────────────────▲───────┘
          │ implements           │ speaks ONLY this      │
  ┌───────┴──────────────┐  ┌────┴─────────────────┐     │
  │ _primitives/         │  │ _engine/             │     │
  │  document_store.py   │  │  recording/  NEW     │     │
  │   DocumentRuntime    │  │   run_recorder.py    │     │
  │   Store              │  │     started/finished │     │
  │   DOCUMENT_PROFILE   │  │   workflow_recorder  │     │
  │    cross_aggregate_  │  │     claimed          │     │
  │    atomicity=False   │  │     step_completed   │     │
  │    → REFUSES a       │  │     suspended        │     │
  │      spanning tx     │  │     resumed          │     │
  │  scope_store.py etc. │  │  executor.py         │     │
  │   (wrapped, not      │◄─┼─  NO substrate       │     │
  │    rewritten)        │  │    property          │     │
  └──────────────────────┘  │  __init__(*,         │     │
       LAYER: _primitives   │    runtime_store,    │     │
                            │    substrate)  ──────┼─────┘
                            └──────▲───────────────┘
                                   │ build_engine(app,
                                   │   runtime_store=store,
                                   │   substrate=substrate)
                          ┌────────┴─────────────────────────────┐
                          │ _app/boot.py       LAYER: _app       │
                          │  step 4   load plugins               │
                          │  step 6   resolve config             │
                          │  step 6.5 select + prepare  NEW      │
                          │           check_required_capabilities│
                          │           → RuntimeStoreCapability   │
                          │             Error (refuse, never     │
                          │             degrade)                 │
                          │  step 6.6 build_engine(…)            │
                          │  step 9   APP_READY                  │
                          └──────────────────────────────────────┘

  WHAT CROSSES A BOUNDARY, AND WHETHER IT IS LEGAL
    _engine      → _types/persistence     downward       legal (contract 1)
    _primitives  → _types/persistence     downward       legal
    _app         → _types, _engine, _prim composition    legal (contract 5)
    _types       → anything internal      NEVER          contract "Types
                                                         import nothing
                                                         internal" — and
                                                         invisible to
                                                         lint-imports if
                                                         deferred, hence T15
  NO NEW PEER LAYER. Seven contracts unchanged. Compare Design 1, which adds
  src/functualize/_persistence/ as a sixth peer and needs an ADR first.
```

### What the AFTER removes

- *Message Chains* — gone. The engine holds `substrate` and `runtime_store`; nothing walks
  `self._state_store().substrate`.
- *Inappropriate Intimacy* — gone. The `getattr` host read is deleted; the value arrives as
  a keyword-only constructor argument.
- *Primitive Obsession* — gone. `multi_machine` becomes a field with a measured value
  instead of a sentence in a docstring.
- Exception-as-outcome — replaced at the port by `Claimed | Conflict`, and **reached** by
  the two production call sites (T14), not merely declared.

### Smells each candidate AFTER introduces — the iteration

Three shapes were drawn. Two were rejected on the smells they introduced.

**Candidate A — widen `StoreSubstrate` with query methods.** Rejected. Introduces
*Divergent Change* on one port (it would change both for a new document format and for a
new query), and D-2/D-3's rejected-alternatives section already argues it. Not re-argued
here.

**Candidate B — one `RuntimeStore` protocol with ~25 methods, no writer/reader split.**
Rejected. Introduces **Large Class** on a Protocol and **Refused Bequest** on every
partial implementer: a document store that cannot answer `resumable()` would have to
raise from a method the type says it has. The split into five writers and three readers
is what keeps the profile the only place a capability is declared.

**Candidate C — `DocumentRuntimeStore` in `_engine` beside the recorders.** Rejected on a
hard rule, not a preference: it wraps `ScopeStore`, `RunStore` and `ScopeStateStore`, all
in `_primitives`. Placing it in `_engine` is fine directionally, but it would put storage
adaptation in the layer that owns lifecycle meaning — the line §3 of the design draws
("a store implementation must never contain the word *resume* in a conditional"). It lives
in `_primitives/document_store.py`.

**Candidate D — the shape above.** Accepted, and it introduces two smells, declared below.

## Surviving smells

All five are **absent from `.spec/CONSTITUTION.md` → *Forbidden Patterns***, which is
what makes them eligible to be accepted rather than blocking. 3–5 were added by T12's
install-moment decision (TD-1), recorded there and carried here.

1. **Middle Man** — `DocumentRuntimeStore` (`_primitives/document_store.py`). It forwards
   to three existing stores and adds no behaviour of its own beyond the honest profile and
   the cross-aggregate refusal. *Accepted, and temporary:* it exists so this wave can land
   without FUN-19's `SqliteRuntimeStore`. The standard answer to middle man — remove it —
   is what FUN-19 does. Marked `# TRANSITIONAL(FUN-17/T7)` at the class, per
   *Transitional Changes*. **Does not need maintainer review.**

2. **Large Class (module-scale)** — `_types/persistence.py`. The plan projected ~340
   lines for T1–T6; measured `wc -l` read 618 at wave 1 (the trigger below fired a
   wave early) and **698 at T6**, carrying 21 dataclasses and 10 protocols.
   *Re-examined at T6 and still accepted:* it is one contract read as a unit, it holds
   zero logic, and `_types/commands.py` proves the alternative split collides on the
   word "command" (`contracts.md` §1). The ~500-line threshold in the constitution is
   about **classes**, and the largest class here is ~25 lines. The projection line in
   *Files expected to change* is corrected to the measured number.
   **Complete at T6** — `contracts.md` §1.1–§1.5 have all landed and no later task in
   this wave names this file (`*Files:*` lines at `:39, :57, :70, :92, :115, :133` are
   the only ones), so it does not grow again inside FUN-17. A line-count trigger is
   therefore unreachable here; re-examine if **a later feature adds to this module**, or
   if any executable logic appears in it — a split, if ever, runs along the
   vocabulary/ports boundary and is its own decision, not this ticket's. **This file is
   deleted by the pre-merge cleanup, so that obligation is migrated to
   `contributor/adr/026-persistence-ports-need-no-new-layer.md` → *What would reopen
   this*, which ships to master.** **Does not need maintainer review.**

3. **Speculative member (port sized past measured use)** — `PluginHost.install_substrate`
   (`_types/host.py`). After T12 moved `functualize-substrate-sqlite` to
   `offer_substrate`, no shipped plugin calls it, against the port's own rule that
   members are sized to measured use. *Accepted:* it is the door for a plugin whose
   choice needs no configuration, the app's own door (`app/core.py`), and what the
   tests' installing probes use; removing it would make the config-free case wait for a
   config read it does not need. Recorded in its docstring. **Does not need maintainer
   review.**

4. **Duplicated query (two upward walks on the standard path)** — `boot_standard` step
   0.5 (`_app/boot.py`, `resolve_fresh_location`) and the project substrate's first
   document access (`_primitives/substrate.py`, `JsonFileSubstrate.root`). No catalogue
   name fits exactly; it is one question asked twice. *Accepted:* they agree because
   nothing between them creates `.functualize/` — the sqlite plugin's `_db_path` is
   read-only and `JsonFileSubstrate.write` creates the directory only after its root is
   resolved — and `tests/primitives/test_substrate_root_is_lazy.py` pins that the late
   answer is the eager one. The alternative, threading step 0.5's answer into step 6.5,
   adds a second `JsonFileSubstrate` construction site against
   `test_exactly_one_place_names_the_filesystem_substrate`. **Does not need maintainer
   review.**

5. **Temporary Field** — `app._registering_plugin`, set by both registration loops
   (`_plugins/loader.py`, `boot_static` in `_app/boot.py`) around `plugin(app)` and
   cleared in a `finally`. It exists only so a two-claimant refusal names plugins rather
   than a lambda's qualname. *Accepted:* scoped to one call, never read outside
   `_app/impl._claimant`, and not declared on the facade (whose line budget is 305).
   **Does not need maintainer review.**

### And one that is NOT ours, but must be stated

**Large Class on `JobExecutionEngine`** — `executor.py:163-2744`, roughly **2580 lines**
against a constitution threshold of ~500. This is a standing *Forbidden Patterns*
condition that **pre-dates FUN-17 and is not created by it**. The relevant constraint on
this wave is therefore *do not worsen it*: the recorders are separate modules in
`_engine/recording/` precisely so the lifecycle-to-command translation does not become
twenty more methods on that class. T12's net effect on the file is a **deletion**.

**This one needs maintainer review** — not to unblock FUN-17, but because a forbidden
pattern is sitting in the file this wave and the next six all edit, and nobody has
recorded a decision about it.

## Approvals — cleared 2026-09-23, Execute is authorized

The maintainer approved the four decisions **as drawn in this file** on 2026-09-23, and
the ADRs recording them landed as wave −1. They are decisions of record now; this table
is the pointer, and `contributor/adr/` is the authority.

| ID | What | Recorded in |
|---|---|---|
| D-2 | Engine owns transition meaning; stores own durability | `contributor/adr/025-engine-owns-transition-meaning.md` |
| D-3 | No new peer layer; ports in `_types`, recorders in `_engine`, wiring in `_app` | `contributor/adr/026-persistence-ports-need-no-new-layer.md` |
| D-4 | Move engine construction after config resolution | `contributor/adr/027-engine-construction-moves-after-config.md` |
| D-13 | Storage is pluggable; execution is not | `contributor/adr/028-storage-is-pluggable-execution-is-not.md` |

D-3 got its own ADR rather than sharing D-2's, and D-13 got one at all — the register's
own §1 gloss had predicted `D-2+D-3`, `D-4`, `D-6`, `D-9`. `09-decisions.md` §1.1 records
why the written set follows the approval instead.

**Nothing blocks Execute.** Wave 0 (T1–T3) is authorized.

### Still open, and not blocking

- **D-6** — `Attempt` as a first-class aggregate. Needs its own ADR because it changes
  what `func builtin history` shows a user when a run failed twice. Not blocking: this
  wave defines `Attempt` as vocabulary and nothing renders it.
- **D-9** — `StoreSubstrate` becomes public. A public-API decision, deliberately not
  implemented this wave (`contracts.md` §4).
- **The `JobExecutionEngine` size decision** — the surviving-smell entry above, ~2580
  lines against a ~500 threshold. Pre-dates this wave and is not worsened by it.

All three remain the maintainer's to answer.

## Files expected to change

Sizes measured with `wc -l` on the rebased tree, not copied from the research.

| File | Now | Change | Task |
|---|---|---|---|
| `src/functualize/_types/persistence.py` | — (absent) | new, 698 measured at T6 (projection was ~340; overtaken at wave 1) | T1–T6 |
| `src/functualize/_types/errors.py` | 556 | +2 error classes | T8, T13 |
| `src/functualize/_primitives/document_store.py` | — (absent) | new | T7, T8 |
| `src/functualize/_engine/recording/run_recorder.py` | — (absent) | new | T9 |
| `src/functualize/_engine/recording/workflow_recorder.py` | — (absent) | new | T10 |
| `src/functualize/_app/boot.py` | 2084 | step 6.5 + both `build_engine` call sites | T11, T13 |
| `src/functualize/_engine/executor.py` | 2744 | accept the two arguments; **delete** :1509-1528 | T11, T12 |
| `src/functualize/_engine/frontier.py` | 478 | claim through the port | T14 |
| `src/functualize/app/_workflow_control.py` | 784 | branch on `Conflict`, drop the bare catch | T14 |
| `src/functualize/app/core.py` | 831 | comment at :286 names the old signature | T11 |
| `tests/…` | — | tripwire, refusal, import-line test | T12, T8, T15 |

## Risks

1. **The gate suite is red for the whole wave, by construction.**
   `tests/spec/test_task_gates_still_hold.py` asserts ≥12 gates parse, and only gates
   belonging to **ticked** tasks parse. `.spec/features/` on this branch holds one feature,
   so nothing back-stops the count: it reads `0` now and crosses 12 partway through wave 5.
   This is a disclosed transitional state, not a regression — see `tasks.md` → *Why this
   suite is red until T15*.
2. **A gate whose value a later task moves becomes a false failure.** Every gate in
   `tasks.md` was chosen to be true against the **end state** of the wave, not only at its
   own task. Any executor who must weaken one says so in writing and marks it
   `superseded`, per the constitution.
3. **graphify and serena were unavailable**, so blast radius rests on `rg` and the
   codemaps. `rg` cannot answer "what references this symbol" as well as a reference query
   can. Re-run 3b if either server returns.
4. **`ruff format` wrapping a signature can silently break a single-line gate** — one of the
   ten defect shapes `test_task_gates_still_hold.py` was written to catch. No gate here
   matches a full signature; they match class headings, call fragments, and counts.
