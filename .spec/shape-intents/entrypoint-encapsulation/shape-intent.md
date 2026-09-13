# Shape Intent: Engine Entrypoint Encapsulation

**Status: proposed** (synthesis of two independent audits; open decisions below)
**Date: 2026-09-08** (audits verified against `origin/master` @ `c0c921f`)
**Amended 2026-09-09** — Open/Closed accounting; performance assessment (boot budgets,
resolution-cost evidence, T8 guard); DI-capability boundary (ADR-014 precedent, hand-wired
`RunContext` exposure residual → D6); Dagger external precedent (→ D5).
**Scope: the invocation boundary of `JobExecutionEngine` — how a run starts, how it is resolved,
how it ends — across every surface. No new layer, no new registry. Breaking, and free to be —
`.spec/CONSTITUTION.md` → Pre-Release Stance.**

The maintainer's two gripes — "there are a lot of ways a job can be invoked and the entry points
may diverge inconsistently" and "the engine is too loose, open for modification" — are one
complaint: **every rule lives in N places, and every new feature adds a place**. Two independent
audits (one for coverage, one for depth) ran in parallel on this commit and converged on the same
four causes. This document is the supervisor's synthesis of both, and the shape of the fix.

---

## The finding

**Measured, not inferred** — the coverage audit ran the binary; the depth audit ran
`uv run lint-imports`, AST span measurements, serena reference enumeration, and graphify
edge queries. Every claim below carries `file:line` and is cross-referenced in the two audit
documents:

- `contributor/architecture/audit-entrypoint-coverage.md` (the empirical half — 17 surfaces,
  13 concrete divergences, 14 leakage rows, a STATUS/ADR ledger)
- `contributor/architecture/audit-engine-encapsulation.md` (the design half — 4 root causes,
  15 smell mappings, pattern selection with rejections, a 9-step roadmap)
- `contributor/adr/020-engine-entrypoint-encapsulation.md` (the decision proposal, `proposed`)

### Four causes, converged

1. **The engine's entry contract is a 12-parameter procedure that takes the resolved function
   as an argument** (`_engine/executor.py:656`). Eight production sites resolve name→function
   themselves (coverage §A lists all 17 starts; depth §1 Cause 1 lists the 8 resolution sites).
   The engine already resolves by name for its own children (`executor.py:1214,1793`). Every
   feature adds a parameter; every surface independently decides whether to pass it — the exact
   mechanism behind the `--scope-id` gate-resume defect.
2. **The engine is mutable white-box state.** `_app/boot.py:286,498,701,1586` and
   `app/core.py:514` write private attributes after construction; `RunContext` reads them back
   through `engine._app` message chains (`runcontext.py:698`). Construction is duplicated across
   `boot_static` and `boot_standard` (`boot.py:270-288` vs `482-500`). Nothing seals the object.
3. **Delivery is a per-surface act.** The number tables are single authorities
   (`_types/exit_codes.py:50-68`, `_types/http_status.py:78`), but the failure-set rule is spelled
   in three places coordinated by comment citations, BLOCKED/REFUSED reporting lives only in the
   click-side `deliver_job_result`, and the coverage audit counted **seven** translation sites
   (the doc's six, plus `func builtin parallel` at `builtins.py:604`).
4. **The deposit protocol is the divergence generator.** The kernel reads delivery-layer
   attributes off the app — `_prompt_gates` (`executor.py:1283`), `_output_format`
   (`_engine/capabilities/stdout.py:156`), `_force` (`click_params.py:82`) — an untyped,
   undocumented cross-layer contract. Its consequences are concrete and live today:
   `--prompt-gates` and `--output` are `func`-only despite being "about the program"
   (coverage D-1, D-2); `app.execute`/MCP/HTTP/Lambda cannot force a run (D-3);
   `interactivity.job.submit` runs jobs with **no WorkflowScope** (`_app/impl.py:861`,
   D-13/C-5); MCP is split three ways on `group_option_values` (`_server.py:272` passes it,
   `_tools.py:254,408` do not — D-5).

### The god-object budget is broken, and nothing enforces it

Both audits measured the same numbers independently: `RunContext` **781** LOC vs the 500-LOC
cap (AGENTS.md), `FunctualizeApp` **1265** vs 300, `JobExecutionEngine` **2401** with a 329-LOC
`_execute_lifecycle`. `contributor/reference/code-map.md:31` still says "~500" — the constraint
is prose, the prose is stale, and no test fires on the breach.

### Where the two audits disagree — and what that means

One substantive difference survived cross-checking, and it is a genuine open question rather
than an error on either side:

- **Coverage found 17 surfaces where the docs claim 9.** Depth deliberately did not re-enumerate.
  The extras are real (verified: `interactivity.job.submit`, MCP's three call sites, `builtin
  parallel`, single-file mode's second boot, engine-internal recursions). **Conclusion:** the
  surface *count* will keep growing (that is what surfaces do); the fix must make the count
  irrelevant, not shrink it. Depth's `RunRequest` design does exactly that — surfaces pass an
  opaque request, so a new surface inherits every program feature by construction.

Everything else agrees, and the agreement is the finding: both audits, started from opposite
directions (enumerate-first vs cause-first), landed on the deposit protocol, the unresolved
entry contract, and the per-surface delivery act as the load-bearing defects.

---

## The target shape

Third application of the house move (ADR-001 collapsed five interactivity concepts; ADR-004
collapsed seven namespace derivations). Find the single authority, collapse the re-derivations,
seal the boundary. No new layer, no new registry — everything builds on authorities that already
exist (`GroupTrie`, `negative_flag_for`, `exit_code_for_status`, `CapabilitySpec`,
`HookRegistry`/`EventBus`, the 20-step lifecycle).

```
 func pre-boot │ click adapters │ TUI │ MCP │ HTTP │ Lambda │ rc.invoke │ app.execute
 (parse ONLY their own syntax into a RunRequest — no resolution, no engine knowledge)
        │                                  │
        ▼                                  ▼
        FunctualizeApp.execute(request)      engine.run(request)   ← single entry, single authority
        (Facade: scope + deposit-and-read)     │ resolves name → job (materialize)
                                              │ _execute_lifecycle  ← Template Method, unchanged
                                              │ collaborators injected once via EngineHost protocol
                                              ▼
                                          JobResult
        ┌──────────── one outcome module in _types: exit code │ http status │ failure-set │ report line ────────────┐
        ▼                        ▼                        ▼                             ▼
 deliver_job_result         TUI panel               MCP tool response           HTTP / Lambda payload
 (Adapter: process)     (Adapter: terminal)         (Adapter: tool)             (Adapters: wire)
```

Four consolidations, specified in full in the depth audit §3 and ADR-020:

1. **`RunRequest`** — one frozen value object (`_types/run_request.py`, stdlib-only) for
   everything a run needs. The engine signature stops being the extension point.
2. **One resolution authority** — `engine.run(request)` resolves and materializes internally;
   `execute(name, function, ...)` is deleted (clean cutover). `FunctualizeApp.execute` becomes
   the single surface-facing facade, including for the click family that currently bypasses it.
3. **Sealed construction** — an `EngineHost` protocol wired once by a single
   `build_engine(host)`; all post-hoc private writes die; `Path.cwd()` leaves the kernel.
4. **One outcome module** — the `RunStatus → family` mappings plus the failure-set rule and
   BLOCKED/REFUSED report lines live in one `_types` module; delivery surfaces become Adapters
   that choose a family and render, and stop deciding.

Plus the two structural repairs the evidence demands: the flag vocabulary consolidates into
`_types/flag_grammar.py` (generalizing the `negative_flag_for` precedent — one rule, seven
consumers today, unpinned count), and the facade LOC guards become executable tests.

**Regrowth resistance** (the reviewer's first question, answered in depth §3): ADR-001/004
collapsed rules but left the protocol that demands per-surface re-derivation. This removes the
protocol: after step 2 there is *no API* by which a surface can resolve a job, restate the
failure set, or re-spell a flag rule. Divergence then requires adding a new authority, which the
absence-tests (no private writes, LOC limits, panel≡table parity) make visible as a failing test
rather than a convention drift.

---

## Open/Closed accounting

OCP is bidirectional, and the audits found the engine inverted on both ends: closed where
extension was needed (no surface extension point — each new surface re-implemented rules) and
open where modification must be impossible (post-hoc private writes, a 12-param signature every
feature grew). What this design does to each direction, stated explicitly:

| Direction | Today | After |
|---|---|---|
| **Closed for modification** | `execute()` grows a parameter per feature; owners edit the engine after construction; a new `RunStatus` or flag rule is N edits | `RunRequest` field + lifecycle step — surfaces inherit it opaquely; the engine is complete at construction (`EngineHost` + one `build_engine`); one outcome module, one flag grammar. There is **no API** by which a surface can restate a rule — the door is deleted, not guarded |
| **Open for extension** | A new delivery surface re-derives resolution and delivery semantics — the literal history of the cold/warm exit-code, Lambda-200, and HTTP line/body divergences | A new surface = a new Adapter over the outcome module. Additive only — zero edits to the engine or existing adapters |

Two honest limits. (a) Extension machinery was deliberately **not** added — Mediator, Command,
Strategy, and new registries were rejected because the defect is missing *authorities*, not
missing variation; the lifecycle already extends by declaration
(`CapabilitySpec.preflight_bind`, gate resolvers). (b) This OCP fix is on the **surface/entry
axis only**. The DI-capability axis is already healthy — ADR-014's declared-beside
`CapabilitySpec` + import-time invariant is the mechanism this design generalizes, and it is
left untouched (see the capability note in "Relationship to other work"; its one residual is
D6).

---

## Assertions

### 1. The current state — cross-verified

| # | Assertion | Verdict |
|---|---|---|
| `CUR.1` | 17 distinct ways a job run starts; the docs claim 9 | **CONFIRMED** — coverage §A, each row with entry symbol + boot path |
| `CUR.2` | `execute()` takes 12 parameters including the resolved `function`; 8 production sites resolve themselves | **CONFIRMED** — depth §1 Cause 1 (serena-verified); signature at `executor.py:656` |
| `CUR.3` | The engine is post-hoc mutated by its owners; `RunContext` reaches back through `engine._app` | **CONFIRMED** — `boot.py:286,498,701,1586`, `core.py:514`, `runcontext.py:698` |
| `CUR.4` | Seven RunStatus translation sites; the TUI treats BLOCKED as success (0) against the table's 5 | **CONFIRMED** — `job_execution.py:271-285` vs `exit_codes.py:56`; `builtins.py:604` is the seventh |
| `CUR.5` | `interactivity.job.submit` executes with no WorkflowScope — the only surface that does | **CONFIRMED** — `_app/impl.py:845-866` calls `app.execution_engine.execute` directly |
| `CUR.6` | `--prompt-gates` and `--output` are `func`-only, both "about the program" | **CONFIRMED live** — `--output` on an app's own entry point: `Error: No such option '--output'`; `FUNCTUALIZE_CLI_OUTPUT` is help-text-only and read by nothing |
| `CUR.7` | MCP split three ways on `group_option_values`; HTTP/Lambda have no group-option or resume channel; `Invoke` cannot pass them | **CONFIRMED** — `_server.py:272` vs `_tools.py:254,408`; plugin `__init__` files; `invoke.py:86-97` |
| `CUR.8` | LOC budgets breached: RunContext 781/500, FunctualizeApp 1265/300, JobExecutionEngine 2401 | **CONFIRMED** — measured twice, independently, same numbers |
| `CUR.9` | `negative_flag_for` is one rule with **seven** consumers; the count is pinned by no test | **CONFIRMED** — graphify + grep agree: `click_params.py` ×4, `bar.py`, `sync.py`, `dispatch.py` |
| `CUR.10` | STATUS items X1–X4, F2, F3, #16, #21, #30, #32 closed; #5, #13, #14, #17, #27, #37, #38 open | **CONFIRMED** — coverage §D ledger, most reproduced live at HEAD |

### 2. The target

| # | Assertion | Verdict |
|---|---|---|
| `TGT.1` | No production code outside `_engine` passes a job function for execution; `engine.run(request)` is the single entry | **GAP** |
| `TGT.2` | The engine is complete at construction; zero post-hoc private-attribute writes (grep-asserted, `test_typer_isolation.py` style) | **GAP** |
| `TGT.3` | `RunStatus → family` has one home; delivery surfaces choose a family and render, and stop deciding | **GAP** |
| `TGT.4` | The flag vocabulary has one home; parsers keep only their syntax (two parsers remain — inherent to pre-boot) | **GAP** |
| `TGT.5` | `_execute_lifecycle` order unchanged at every commit — `tests/engine/test_lifecycle_order.py` stays the proof | **CONFIRMED (constraint)** |
| `TGT.6` | RunContext ≤500 LOC, FunctualizeApp ≤300, enforced by tests | **GAP** |
| `TGT.7` | Every surface builds an opaque `RunRequest`; job-author-declared features work on every surface by construction (surface-boundary §4 becomes structural) | **GAP** |

### 3. Blast radius

| # | Assertion | Verdict |
|---|---|---|
| `RAD.1` | Every production call site of `engine.execute` changes once (depth §1 Cause 1 table = the full list; 8 sites + plugin surfaces) | **CONFIRMED** — serena enumeration |
| `RAD.2` | External plugins reaching past `AdapterPlugin` (direct engine construction, `engine._app` reads) break silently — not enumerable from this repo | **CONFIRMED** — stated in ADR-020 consequences; needs a plugin-guide release note |
| `RAD.3` | Job authors using `RunContext`'s observability/discovery re-exposures change imports once (Additional Facades) | **CONFIRMED** — pre-release, one release note |
| `RAD.4` | The kwargs-split/stdin move (depth step 2) is the riskiest change; defended by `TestWarmBootParity` and the dual-surface `cli_run` harness | **CONFIRMED** — depth §4 step 2 risk statement |
| `RAD.5` | `_config → _events` TYPE_CHECKING blind spot (`chain.py:22`, `sources.py:36`) — the layer contract the design leans on is unenforced on this one edge; measure the flag flip (depth step 8) | **CONFIRMED** — `.serena/memories/architecture-layer-contract.md` |
| `RAD.6` | `func why`'s second verdict engine (`core.py:711-822`) must not be orphaned by any preflight move (coverage C-9 / handoff 7) | **CONFIRMED** |
| `RAD.7` | The perf budgets (3ms pre-boot, 5ms static, boot phases) gate this design at every PR; a warm-cache `func <job>` phase must be added after step 2 (T8) | **CONFIRMED** — the budget suite exists and is enforced in `test-fast`; the new phase is part of step 2's completion criteria |

---

## Performance assessment

The codebase carries explicit boot-time budgets — `tests/perf/test_startup_budget.py` (all
`perf_budget`-marked, enforced serially per-PR in `test-fast`), `boot_static` cold start <5ms
(`test_static_wiring_fast_path.py:314`), pre-boot routing ~3ms with zero job-module imports
(`test_group_trie_ingestion.py:9`). This design is **boot-time neutral by construction**: it
changes what happens *after* `FunctualizeApp(...)` construction, not during it.

| Boot phase (budget) | Effect |
|---|---|
| Pre-boot routing (~3ms, zero-import trie) | **None.** Parsers keep their syntax; aliases, cache-first routing names, `detect_mode` stay pre-boot; resolution happens after boot. The zero-imports test fires if pre-boot is ever re-routed through the facade |
| Config resolution (300ms) | **None.** Dominated by 7× `importlib.metadata.entry_points()` scans (~53ms of ~65ms app construction, per the budget file's own note); untouched |
| Job registration (50ms) | **None.** Registry, trie, cache reads unchanged |
| `boot_static` cold start (<5ms) | **None, possibly less.** `build_engine(host)` collapses the duplicated construction blocks (`boot.py:270-288` vs `482-500`) into one builder — no new boot work |
| Import weight | **Zero.** `RunRequest`, the outcome module, and `flag_grammar` are stdlib-only `_types` residents; kernel/delivery split preserved |

Runtime cost of the resolution move: **already paid.** `execute()` itself looks the job up by
name and materializes (`executor.py:803-807`; `_ensure_materialized` imports once, then no-ops).
Consolidating resolution into `engine.run()` removes the caller-side duplicate (`func`'s dispatch
materializes to build the click command, then the callback re-resolves) and shifts the eager
click path's build-time binding to a call-time dict lookup — noise against ~100-300ms process
startup, amortized on long-running surfaces (TUI, HTTP). `RunRequest` is one frozen dataclass
per run.

Regression risks, and what already catches them: pre-boot re-routing (the 3ms zero-import test),
eager materialization on the lazy path (`TestWarmBootParity`), step 8's TYPE_CHECKING flip
(import-time only, zero runtime effect). **Required addition:** after step 2, extend
`tests/perf/test_startup_budget.py` with a warm-cache `func <job>` wall-clock phase (T8) so the
resolution consolidation is measured, not assumed.

Separately noted, unrelated to this design: the largest boot win available today is memoizing
`importlib.metadata.entry_points()` — seven scans per boot, ~53ms of the ~65ms app construction.
Worth doing regardless of this document.

---

## External precedent: Dagger

Dagger (docs.dagger.io, 1.0-beta) solves the same core loop — functions + declarative
dependencies + engine-mediated execution + caching — with exactly the boundary this design
adopts: every surface (SDKs, `dagger check`, `dagger api call`) compiles into one typed call
graph and streams results back; the engine is a sealed service; there is nothing for a surface
to re-derive. Independent validation of the `RunRequest`/one-outcome direction — *without*
Dagger's client-server split, which would forfeit this repo's boot budgets and in-process
`Invoke`.

- **Steal:** content-addressed artifact caching ("incremental execution"). Functualize decides
  *whether* a job is fresh (`Fingerprint`, refusal, staleness) but caches nothing — that gap is
  the strategic opportunity this document records but does not design (D5).
- **Don't steal:** container-sandboxed execution (in-process is the perf edge); the
  client-server split (kills <5ms boot and ~3ms pre-boot routing); OCI module distribution
  (PyPI entry points already do this for Python).

---

## Open decisions

| # | Question | Why it cannot be defaulted |
|---|---|---|
| **D1** | Adopt ADR-020 as the decision vehicle, or amend first? | It is already `proposed` and complete; the amendments to consider before accept are (a) fold the urgent-tranche fixes into decision scope, (b) the TUI BLOCKED question (D3) is explicitly left to the maintainer, and (c) `app/utils.py`'s 2,021-LOC corridor stays open as the next surface-boundary question |
| **D2** | Urgent fixes first, or roadmap first? | Coverage found three shipping-class defects that do not need the redesign: D-13 (scope-less `job.submit`), D-1/D-2 (`--prompt-gates`/`--output` parity). Each is a two-surface fix in the surface-boundary §4 pattern and lands in days. My recommendation: **urgent tranche first** — it closes the live unresumable-workflow hole and the parity defects while the roadmap is reviewed, and it is independent of every step |
| **D3** | What should the inline TUI exit when a gate blocks — 0 (it is a shell; the user stays in it) or 5 (it is the process)? | Deliberate on both sides today, coordinated by comment citations. The outcome module must make "which family am I" an explicit, greppable per-surface choice; whether the inline TUI's *process* exit should be 5 when it is the process is a maintainer call (depth §5.4) |
| **D4** | Group-option channel for `Invoke`, HTTP, and Lambda | `Invoke` cannot pass `group_option_values` (STATUS #17, documented as deliberate in `docs/guides/group-options.md`); HTTP/Lambda have no channel at all. Under `TGT.7` this becomes structural; until the redesign, decide whether #17's boundary stands or gets a request-field-level fix |
| **D5** | Content-addressed artifact caching — pursue Dagger-style incremental execution (`Fingerprint → artifact store`) as its own shape-intent? | The highest-value gap the audits did not cover: functualize has freshness *decisions* but no artifact cache. It is a new execution-model axis, not a boundary fix — folding it in would blur this document's scope |
| **D6** | Declarative job-author exposure for capabilities (kill the hand-wired `RunContext` delegation) — follow-up shape-intent, or accepted manual ceremony? | ADR-014 derives injection; exposure is still 58 hand-written facade methods. A `CapabilitySpec` field declaring `rc.*` methods plus an import-time completeness invariant is the ADR-014 shape; the counter-argument is that each `rc.` promotion is a deliberate public-API decision |

---

## Test tiers

Per `.spec/TESTING.md`.

| # | Criterion | Tier |
|---|---|---|
| T1 | `cli_run` dual-surface harness: every feature row of coverage §B passes identically on `func` and an app entry point (the harness already caught the epilog and capability-leak defects — ADR-010 §5) | CLI integration |
| T2 | Warm-boot parity: `TestWarmBootParity` green through the resolution move (step 2) — cold/warm equality is the defence | engine |
| T3 | Lifecycle order: `tests/engine/test_lifecycle_order.py` green at every commit of step 6 | engine |
| T4 | Absence assertions: no `engine._<attr> =` writes outside `_engine`; no `_engine` imports in `app/adapters/*` (end state) | unit, `test_typer_isolation.py` style |
| T5 | LOC tripwires: `RunContext` ≤500, `FunctualizeApp` ≤300 fail the suite on breach | unit |
| T6 | Panel≡table parity: TUI failure-set derives from the outcome module (`TestReadinessAgreesWithClick` pattern — expectations from the table, never a second list) | TUI audit |
| T7 | Plugin status-code suites stay green (already parametrized over every terminal `RunStatus`) | plugins |
| T8 | Warm-cache `func <job>` wall-clock phase in `tests/perf/test_startup_budget.py` after step 2 — the resolution consolidation is measured, not assumed | perf budget (test-fast serial) |

### Wiring paths to name at close

- `func pre-boot` → `_handle_job/_handle_group/_handle_single_file` → request construction → `FunctualizeApp.execute` → `engine.run` → `_execute_lifecycle` → `JobResult` → per-surface Adapter over the outcome module
- `interactivity.job.submit` → must pass through the facade (fixes D-13 before or with step 2)
- Sabotage each: drop `group_option_values` from the request builder → `tests/group_options/` red; make materialization raise on the lazy path only → warm-parity pair fails; restore one post-hoc write → absence test fails (commit-then-sabotage per wiring-discipline §3)

---

## Relationship to other work

- **The urgent tranche (D2) is independent** of the roadmap and of every other feature; it can
  land before, during, or after the 0.1.1 release work in STATUS.md.
- **`standalone-distribution`'s `self doctor` probe** (coverage §A #17) is a 17th surface the
  redesign must not break; it boots without running jobs.
- **ADR-016's vault/remote work** is untouched by all four consolidations.
- The **`app/utils.py` corridor** (2,021 LOC) is deliberately out of scope; the
  `read_group_options_from_cache` fingerprint gap (STATUS follow-up, still UNTOUCHED) is its
  open wound and the next shape-intent after this one.
- **The DI-capability pipeline is deliberately untouched.** ADR-014's declared-beside
  `CapabilitySpec` + import-time name invariant already killed the five-site capability chore;
  this design generalizes that precedent without re-opening it. The one residual — the
  hand-wired `RunContext` exposure (58 delegations; step 7 shrinks but does not derive them) —
  is recorded as D6, not folded in.

---

## Adjacent defects — not this document's scope

Found by the coverage audit, live at `c0c921f`, reproduced:

1. **`GroupOptionsConflictError` escapes as a raw traceback** (exit 1) from
   `cached_provider.py:916` — ADR-018's "reported, not fatal" surface covers module reads, not
   group-option conflicts. File separately.
2. **Stale group-options binding surviving cache repairs** — the conflict persisted across
   `func builtin cache clear` and mtime bumps in one fixture transition before self-healing;
   the group-options cache section has no fingerprint at all (coverage handoff H6, `utils.py:1589`).
   Needs a reproduction before it is filed.
3. **Single-file mode's second boot executes CWD module top-level code** and can hijack routing
   with a misleading error (coverage D-11, `main.py:1643-1653`). File separately.
