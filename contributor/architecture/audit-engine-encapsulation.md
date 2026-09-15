# Engine encapsulation — depth audit

**Date**: 2026-09-08
**Branch**: `refactor/engine-encapsulation-audit`
**Companion**: the COVERAGE audit (sibling worktree, `refactor/entrypoint-coverage-audit`) owns the
empirical surface inventory and divergence matrix. This document is the design half: *why* the
entry points diverge, and what shape the fix must take. It does not re-enumerate surfaces;
`contributor/architecture/surface-boundary.md` §1–§3 remains the map.

**Method.** Every claim about the code below carries `file:line` and was read on this worktree at
`c0c921f` (this document committed at `c9bae1e`). Where a claim needed proof it was run, routed
per `.agents/skills/code-intel/SKILL.md`:

- **serena** (reference enumeration): `activate_project` on the worktree root, then
  `find_referencing_symbols` on `JobExecutionEngine/execute` (produces the eight-site table in §1
  Cause 1) and on `JobExecutionEngine/get_job` (the engine's internal resolution authority).
- **graphify** (typed dependency edges): `graphify explain "JobExecutionEngine"` (CLI on PATH) —
  a 95-degree node; the inbound `[imports]`/`[calls]`/`[uses]` edges are cited in §1.
- **zvec-grep** (prose / why): the `zg` CLI is **not installed on this host** (no npm/node
  toolchain). The same index was queried through the mounted `zvec_grep_search` MCP tool against
  this worktree's root; it reported the index **fresh** (2026-09-08) and its hits are cited in §1
  Cause 3 and §1 Cause 4.
- plus `uv run lint-imports` (6 kept, 0 broken, 322 files), AST measurements of class/method spans,
  and targeted greps.

No file under `src/`, `plugins/*/src/`, or `tests/` was modified.

---

## 1. Root-cause model

The maintainer's two gripes — "many ways a job can be invoked, entry points may diverge
inconsistently" and "the engine is too loose, open for modification" — are one complaint seen from
two sides. The historical fixes (ADR-001: five interactivity concepts → Surface + PromptCollector +
TTY; ADR-004: namespace re-derived in ~7 places → one GroupTrie) each collapsed *a* rule. Neither
touched the structure that makes every *new* rule sprout new re-derivation sites. Four load-bearing
causes remain, each verified below.

### Cause 1 — The engine's entry contract is a 12-parameter procedure that takes the *resolved function as an argument*

`JobExecutionEngine.execute` (`src/functualize/_engine/executor.py:656-672`) is:

```python
def execute(self, job_name, function, *, kwargs, invoke_depth, cwd, job_directory,
            config_class, parent_scope, workflow_scope_id, run_dependencies,
            force_fresh, force, group_option_values) -> JobResult
```

The engine owns execution but **not resolution**: every caller must first turn a name into
`function` + `config_class` and then hand both over. Production resolution sites (serena
reference enumeration, 2026-09-08):

| Site | Resolves how |
|---|---|
| `app/core.py:620-624` (`app.execute`) | `job_registry.get_job(name)` |
| `app/adapters/click_params.py:1129-1144` (eager click callback) | `app_ref.get_job` + function bound at command build |
| `app/adapters/lazy_command.py:141-144` (lazy click callback) | descriptor-bound function |
| `app/adapters/cli.py:698-714` (`_try_discovered_job`) | `engine.materialize_job` |
| `_cli/main.py:1469-1497` (`_handle_job`) | `_materialize_for_dispatch` → builds a click command → callback re-resolves |
| `_cli/main.py:900+` (`_dispatch_group`) | its own materialization path |
| `_app/impl.py:857-864` (`on_job_submit_event`) | `job_registry.get_job` |
| `_engine/capabilities/invoke.py:400-409, 597-601` | `registered_job` lookup |

Cross-checked with serena (`find_referencing_symbols`, run 2026-09-08: every row above is a
reference of `JobExecutionEngine.execute`) and corroborated by graphify's typed edges into
`JobExecutionEngine` (95-degree node): `core.py [imports]` L37, `click_params.py [imports]` L1012,
`boot_static [calls]` L219, `boot_standard [calls]` L431, `WiredInvoke [uses]` L268,
`FunctualizeApp [uses]` L113. `JobExecutionEngine`'s outbound `[uses]` edges fan over `RunContext`,
`StateStore`, `Prompt`, `JobGraph`, `ExecutionContext`, `ExecutionMiddlewareChain`, `ResolutionPlan`,
`GuardState`, `Secret`, `FromJob` — the fan-out a 2,401-LOC class implies (see the supporting
observation below).

Meanwhile the engine *already* resolves by name for its own children —
`executor.py:1214-1215` (workflow steps) and `executor.py:1793-1794` (dependencies) both call
`self.get_job(...)` then `self.execute(...)`. Resolution is an engine capability exposed only on
the inside; outside, it is re-implemented per surface.

Two consequences follow directly:

- **The signature grows by parameter for every feature, and each surface independently decides
  whether to pass the new knob.** `workflow_scope_id`, `group_option_values`, `force`,
  `force_fresh` are all later additions (gates S6a, §A.7). This is the exact mechanism behind the
  `--scope-id` defect (`surface-boundary.md` §4 worked example): the resume flag was threaded
  through `func`'s pre-boot layer only, so a `@workflow` `Gate` on a `FunctualizeApp` blocked at
  exit 5 forever. A parameter-added-to-engine feature is "open for modification" by construction:
  N call sites, N decisions, no detection.
- **Engine-level knowledge is duplicated into the adapters.** The eager click callback splits
  config-model fields out of kwargs itself (`click_params.py:1099-1104`), resolves stdin markers
  (`1108-1124`), gates the stdout surface (`1126-1138`), and reads the force deposit
  (`1148`, `_force_requested`) — all *program* concerns (surface-boundary §4's own vocabulary)
  living in delivery code, re-stated by the lazy wrapper and by `_cli/main.py`'s handlers.

### Cause 2 — The engine is mutable white-box state, wired after construction by its owners

The engine is constructed, then *edited* by the composition root and the app facade:

| Write | Where |
|---|---|
| `app._execution_engine._app = app` | `_app/boot.py:286` and `:498` (both boot paths) |
| `app._execution_engine._resolution_chain = app._resolution_chain` | `_app/boot.py:701` |
| `app._execution_engine._max_invoke_depth = depth` | `_app/boot.py:1586` |
| `engine._resolution_chain = self._resolution_chain` (on `refresh()`, i.e. at *runtime*) | `app/core.py:514` |
| shared mutable dict: `add_registry_mirror(app.job_registry._registered_jobs)` | `_app/boot.py:288`, `:500` |

The engine also self-wires ambient state: `_state_store()` builds a `StateStore.for_project(Path.cwd())`
lazily inside the kernel (`executor.py:1087-1097`), and `_job_graph` / `_exec_policy_impl` /
`_preflight_pipeline` are `None` until first use (`executor.py:211-214`, `1686`, `1863`, `1992`).
The private `_app` attribute is then read *back* by `RunContext` — including the message chain
`self._execution_engine._app.job_registry.get_descriptor(...)` (`runcontext.py:698`; further `_app`
reaches at `425`, `479`, `719`, `764`) and by `_engine/surface_routing.py:39-52` (live-zone
reads). Nothing seals the object: there is no point after which the engine's behaviour is fixed by
its construction, and the `REGISTRY_FROZEN → APP_READY` boot contract (AGENTS.md boot sequence,
step 8–9) covers the DI registry but not the engine itself. This is the literal sense of "open for
modification": the engine's collaborators arrive by post-hoc private-attribute writes, so any
future owner (a new adapter, a plugin, a refresh) can and will add more.

Construction is also duplicated: `boot_static` and `boot_standard` each build the engine with
near-identical code (`boot.py:270-288` vs `482-500`) — a Divergent Change trap where the next
engine parameter must be added twice.

### Cause 3 — Exit-side delivery is a per-surface act; the *tables* were centralized, the *rule* was not

`surface-boundary.md` §3 maps six terminators. The two `RunStatus → number` tables are single
authorities (`_types/exit_codes.py:50-68` for the process family; `_types/http_status.py:78` for
the HTTP family, consumed by the HTTP plugin at `plugins/functualize-http/.../__init__.py:193` and
Lambda at `plugins/functualize-lambda/.../__init__.py:65`). But the *semantic* questions around a
terminal status are re-derived per surface:

- **"Which statuses count as failure?"** is answered by `exit_code_for_status` (exit family), by
  the TUI panel (`_cli/tui/job_execution.py:274-285`: `SUCCESS/SKIPPED/BLOCKED` → "Done", code 0),
  and by `func builtin parallel` (cited in the TUI's own comment as the *reason*,
  `job_execution.py:269-270`). Three implementations of one rule, coordinated by comment
  citations, not by code. The live instance: a workflow blocked at a gate exits **5** as
  `func <job>` (`exit_codes.py:56`, decision D-a) but **0** from the inline TUI
  (`job_execution.py:274-278` → `execute_job_sync` return → `tui.return_code` →
  `launch_inline_tui` return at `_cli/inline_tui.py:64` → process exit via `_handle_bare`,
  `_cli/main.py:353`). Both are deliberate; neither cites a shared authority for *which family it
  is in*, and that is the divergence class.

  A third family mapping exists and is honest about the hazard — which makes it the precedent for
  the fix. `_engine/explain.py:105-126` (`explain_exit_code`) maps a pre-flight `GuardVerdict` to
  the exit table's numbers for `func builtin why`, and its docstring states the argument:
  "Inventing a second vocabulary for 'what would happen' versus 'what happened' is how two tables
  drift." It reuses the table rather than re-deriving — and records that `ExitCode.STALE` (4) was
  pinned in the table with **no producer anywhere in the codebase** until `why` grew one
  (`explain.py:107-113`): a family member whose only producer had been forgotten. The
  failure-set rule is the STALE of today — pinned in three comment citations with no
  producer-level authority. The same drift axis is named in prose where it was consciously
  avoided: `app/core.py:642-645` (`execute_parallel`) explains it lives on the app because
  "two implementations would drift on the parts that matter (ordering, the timeout, how a failure
  is reported)" — a sentence that concedes failure-reporting is exactly the axis that drifts.
- **"What does a status say before it exits?"** — BLOCKED/REFUSED reporting, validation-error
  panels, `MissingValueError` rendering — lives only in `deliver_job_result`
  (`app/adapters/click_params.py:1156-1241`), which is the boundary for the two *click* surfaces
  only (`click_params.py:1151`, `lazy_command.py:161`). MCP answers with its own vocabulary
  (`plugins/functualize-mcp/.../_tools.py:255-267`: raw `status.value` string plus a private
  `_error_response` taxonomy). The history here is the proof of the mechanism: cold-boot exit 1 vs
  warm-boot exit 0 for the same failure (documented in the `deliver_job_result` docstring,
  `click_params.py:1163-1172`); Lambda's `{"statusCode": 200}` for every outcome
  (`plugins/functualize-lambda/tests/test_status_codes.py:8-12`); HTTP's status line disagreeing
  with its body (`plugins/functualize-http/tests/test_status_codes.py:3-7`). Three of six sites
  were fixed by adding tables; the delivery *act* (report, render, translate, exit) remains
  per-surface, so a new `RunStatus` or a new delivery family still costs N edits.

### Cause 4 — `func`'s pre-boot layer is a permanent second CLI, and the "one rule" fixes are per-rule hand extractions, not a mechanism

The pre-boot layer must parse before an app exists (legitimate — `surface-boundary.md` §1), so
`_cli/dispatch.py` carries a hand-written tokenizer: value-taking globals
(`dispatch.py:81`), optional-value lookahead sets (`:90-101`), bool flags (`:121`), an
`_OptionAccumulator` + `_assign_option` state machine (`:503-626`), and the group-flag matchers
`_flag_aliases`/`_negative_aliases`/`_match_group_flag` (`:703-767`). A *third* parser exists in
the TUI (`_cli/tui/cli_arg_parser.py:16-71`, `parse_cli_args_to_kwargs`). And pre-boot reads the
discovery cache directly, through functions re-published as public API in `app/utils.py`
(2,021 LOC — the sanctioned corridor `_cli` needs to avoid `_` imports):
`read_routing_names_from_cache` (`app/utils.py:1388`), `read_group_options_from_cache`
(`:1589`), consumed at `_cli/main.py:1968`, `:980`, `_cli/completions/data.py:130`, and
`_cli/tui/cli_arg_parser.py:120`. The group-options read *cannot* honour the cache fingerprint
(`.spec/STATUS.md:186-189`) — a raw cache read bypassing the resolution layer, by design gap.

The repo already knows the remedy and has applied it rule-by-rule: `negative_flag_for`
(`_types/naming.py`, re-exported `app/utils.py:65`) is consumed by **seven call sites in four
modules** — `_cli/tui/bar.py:295`, `_cli/tui/sync.py:134`, `_cli/dispatch.py:736`,
`app/adapters/click_params.py:322, 608, 675, 876` — which is why `--no-cache` means one thing on
both surfaces (STATUS.md:806-810, "One rule, two surfaces"). But that was one rule, extracted by
hand, after the fact ("five flag-rendering sites, not the four the plan named",
STATUS.md:834-836). The boolean-negation episode is the whole causal story in miniature: the
*plan* counted the re-derivation sites, the *test* found one more, because counting sites is not a
mechanism — the vocabulary itself has no single home.

### Supporting observation — the god-object guards are prose, both are breached, nothing enforces them

Measured by AST on this worktree:

| Class | Constraint (CONSTITUTION.md:175-176, AGENTS.md) | Measured |
|---|---|---|
| `RunContext` (`_engine/capabilities/runcontext.py:117-897`) | ≤ 500 LOC facade | **781 LOC**, 58 methods (904-line file) |
| `FunctualizeApp` (`app/core.py:64-1328`) | ≤ 300 LOC facade | **1,265 LOC**, 75 methods |
| `JobExecutionEngine` (`executor.py:157-2557`) | "if a class exceeds ~500 LOC, decompose it" (CONSTITUTION.md:94) | **2,401 LOC**, 55 methods; `_execute_lifecycle` alone is 329 LOC |

`contributor/reference/code-map.md:31` still describes `RunContext` as "~500 LOC" in
`job/context.py` — a stale description of a breached, unenforced constraint. The `RunContext`
overflow is *breadth, not depth*: the class re-exposes five subsystems as one-liner delegations —
`Invoke` (`invoke`/`invoke_parallel`, `runcontext.py:365,376`), `PromptCollector` (`prompt*`,
`:776`), `EventBus` (`emit`/`on_event`/`off_event`, `:430-434`), `PerfTimeline` (`perf_mark*`,
`:587-599`), plugin config (`get_plugin_config`/`with_plugin_config`, `:627`), plus discovery
(`get_job_schema`, `list_jobs`, `:690,702`). That is
the ch14 "Facade as god object" anti-pattern exactly: one delegation per capability accreted
rather than additional facades. `JobExecutionEngine` holds execution *and* workflow walking
(`_run_workflow_prelude`, 140 LOC) *and* dependency scheduling (`_run_dependencies`, 112 LOC)
*and* shell-program/sudo/redaction resolution *and* history — many reasons to change, one file.

**The TYPE_CHECKING blind spot** (`.serena/memories/architecture-layer-contract.md:31-38`):
`exclude_type_checking_imports = true` means `_config/chain.py:21-23` and
`_config/sources.py:34-36` import `EventBus` from `_events` invisibly to every contract. The layer
rules that the target design must preserve are therefore *not fully enforced today*; any new
boundary type placed where it needs a TYPE_CHECKING escape inherits the same blindness.

### Why these four, and not the others

The prompt's candidate list included two items that evidence downgrades:

- **"per-surface translation of RunStatus/exit codes"** as a standalone cause — refuted as
  *stated*: the two number tables are already single authorities. What remains is Cause 3: the
  translation *act* and the failure-set rule. The evidence (three shipped divergences, all fixed
  at the table level) contradicts "no authority exists"; the correct claim is "the authorities
  cover numbers, not semantics".
- **"discovery-cache reads that bypass the resolution layer"** — confirmed but *derivative*: it is
  Cause 4's consequence (pre-boot must answer routing questions before boot; the corridor exists
  to serve it), not an independent driver. The cache *writes* scattered across provider
  construction sites (pitfalls.md §5, "a fingerprint is only worth the number of construction
  sites that supply it") are the same shape on the write side and are already fixed
  (ADR-011; children now write the all-defaults digest, `boot.py:1150-1158`).

`deliver_job_result` covering only click surfaces is real but is Cause 3's evidence, not a cause.
The four causes above are the generators; every STATUS.md case file decomposes into them (see §2).

---

## 2. Smell mapping

Catalogue: *Dive Into Design Patterns / Refactoring.Guru* smell taxonomy (skill chapters ch31–ch36),
routing per the ch31 table. "Where" names this codebase. A smell earns its row only with change
pressure — every row below has shipped a defect.

| # | Defect (evidence) | Smell (family) | Remedy technique (ch31/cheatsheet) | Where it lands |
|---|---|---|---|---|
| 1 | `execute()` 12 params, one more per feature; surfaces choose whether to pass each (`executor.py:656`) | Long Parameter List / Data Clumps (Bloaters, ch32) | **Introduce Parameter Object** | `_types/run_request.py` (new); `execute` collapses to `run(request)` |
| 2 | 8 production sites resolve name→function and re-derive engine knowledge (§1 Cause 1 table) | Shotgun Surgery (Change Preventers, ch34) | **Move Method/Field** — consolidate into the class that owns the concept (the engine already owns `get_job`/`materialize_job`) | resolution moves inside `engine.run` |
| 3 | Post-construction private writes: `engine._app`, `._resolution_chain`, `._max_invoke_depth`; shared mirror dict (`boot.py:286,498,701,1586`; `core.py:514`) | Inappropriate Intimacy (Couplers, ch36) | **Move Field + make the relationship official** (protocol port, constructor injection — the house recipe, `dependency-graph.md:80-104`) | `EngineHost` protocol in `_types/protocols.py`; one `build_engine(host)` |
| 4 | `rc → engine._app → job_registry → get_descriptor` (`runcontext.py:698`) | Message Chains (Couplers, ch36) | **Hide Delegate** | sanctioned accessor on the host/engine |
| 5 | "Which statuses are failures" decided in 3 places; delivery act per-surface; BLOCKED=5 vs 0 (`job_execution.py:274`; `exit_codes.py:56`; STATUS.md:810) | Shotgun Surgery + Primitive Obsession (status as bare enum, delivery as scattered `SystemExit`) | **Replace Data Value with Object / Move Method** — translations move beside the data they translate | one `RunStatus → family` module in `_types/` |
| 6 | Hand tokenizer in dispatch.py, third parser in TUI, 7 render sites for one flag rule (§1 Cause 4) | Divergent Change / Duplicate Code (ch34/ch31) | **Extract Class** for the vocabulary; parsers keep only their syntax | `_types/flag_grammar.py`; `negative_flag_for` becomes one field of it |
| 7 | `JobExecutionEngine` 2,401 LOC / 55 methods; `_execute_lifecycle` 329 LOC; workflow + deps + shell + history in one class | Large Class + Long Method (Bloaters, ch32) | **Extract Class** per axis of change; keep the 20-step skeleton as the one template | `WorkflowOrchestrator`, `DependencyRunner` out of `executor.py` |
| 8 | `RunContext` 781 LOC re-exposing 5 subsystems (58 one-liner delegations) | Large Class; Facade-as-god-object (ch14 anti-pattern) | **Additional Facades** (ch14's named remedy) | observability/discovery re-exposures split out; ≤500 enforced by test |
| 9 | `FunctualizeApp` 1,265 LOC vs ≤300 (`core.py:64`) | Large Class | **Extract Class** (to `_app/impl.py`, which already exists for exactly this) | explain/parallel/scope plumbing move down |
| 10 | ADR-014's five-site capability registration (historical) | Shotgun Surgery | **declared-beside + import-time invariant** (already shipped — ADR-014) | the *mechanism precedent* this proposal generalizes |
| 11 | Capability names: one string set in `_primitives` + registry assertion (ADR-014, `pitfalls.md` #19) | "One rule spelled in layers that may not import each other" | keep the import-time invariant; **do not** "fix" by breaking peer independence | unchanged — recorded as the sanctioned residual |
| 12 | Five flag-rendering sites not four; three disagreeing resolvers (STATUS.md:834, ADR-008 §P3) | Shotgun Surgery | collapse to one authority (done per-rule: `negative_flag_for`, unified resolvers) | generalized into #6's grammar module |
| 13 | Cache fingerprint gaps per surface (STATUS.md F1-F3; pitfalls.md §5) | Primitive Obsession (`discovery_hash: None` sentinel reaching writers) + Shotgun Surgery on construction sites | sentinel must never reach a writer; construction consolidated (ADR-011, shipped) | residual: `read_group_options_from_cache` fingerprint gap (open) |
| 14 | `deliver_job_result` is click-only (§1 Cause 3) | Feature Envy inverted — the *data's* behaviour lives in one client | **Move Method** onto the outcome view | `_types/` outcome module; adapters translate only |
| 15 | Layer contract blind to TYPE_CHECKING imports (`.serena/memories`, `_config/chain.py:22`) | "A rule you wrote down is not a rule you enforce" (wiring-discipline §13) | measure the flag flip; legalize or eliminate the escape | step 8 of the roadmap |

---

## 3. Pattern-grounded target design

**Shape first.** This must be the third application of the house move — ADR-001 collapsed five
interactivity concepts to three, ADR-004 collapsed seven namespace derivations to one GroupTrie —
*find the single authority, collapse the re-derivations, seal the boundary*. It is a
consolidation, not a new layer. Nothing below adds a registry, a bus, or a framework; everything
builds on authorities that already exist (`GroupTrie`, `negative_flag_for`, `exit_code_for_status`,
`CapabilitySpec`, `HookRegistry`/`EventBus`, the 20-step lifecycle).

### Target picture

```
 func pre-boot │ click adapters │ TUI │ MCP │ HTTP │ Lambda │ rc.invoke │ app.execute
 (parse ONLY their own syntax into a RunRequest — no resolution, no engine knowledge)
        │                                  │
        ▼                                  ▼
        FunctualizeApp.execute(request)      engine.run(request)   ← single entry, single authority
        (Facade: scope + deposit-and-read)     │ resolves name → job (materialize)
                                              │ _execute_lifecycle  ← Template Method (20 steps, unchanged)
                                              │ collaborators injected once via EngineHost protocol
                                              ▼
                                          JobResult
        ┌──────────── one outcome module in _types: exit code │ http status │ failure-set │ report line ────────────┐
        ▼                        ▼                        ▼                             ▼
 deliver_job_result         TUI panel               MCP tool response           HTTP / Lambda payload
 (Adapter: process)     (Adapter: terminal)         (Adapter: tool)             (Adapters: wire)
```

### 3.1 Introduce Parameter Object — `RunRequest` (technique, ch32/ch38 routing)

**Intent.** Freeze the *inputs* of a run into one frozen dataclass so the engine signature stops
being the extension point.

- **Structure.** `RunRequest` in a new `_types/run_request.py` (stdlib-only — same placement logic
  as `exit_codes.py` and `naming.py`: importable by `_cli`, `app`, `_engine`, plugins, no cycle).
  Fields = today's 12 parameters, minus `function`/`config_class` (see 3.2), plus provenance
  (`surface: str`) so history and `state.json` can record *how* the run was reached — the thing
  the coverage audit currently has to reconstruct.
- **Why a technique, not a GoF pattern.** It is Refactoring.Guru's named remedy for Long Parameter
  List (smell #1). Dressing it as Command or Facade would misdescribe it.
- **Cost.** One more type; every caller touched once (clean cutover, pre-release).

### 3.2 Move Method — resolution into `engine.run(request)` (technique, ch39)

**Intent.** The question "which function is this name?" gets one answer, inside the engine, where
`get_job`/`materialize_job`/`_ensure_materialized` already live (`executor.py` symbols;
`executor.py:1214-1215, 1793-1794` prove the engine already does this for steps and deps).

- **Structure.** `run(request)` resolves, materializes, splits config-fields from direct kwargs
  (the knowledge currently duplicated at `click_params.py:1099-1104`), resolves stdin markers,
  and enters `_execute_lifecycle`. The request carries the *name*; nothing outside `_engine`
  ever holds a job function for execution purposes.
- **Why Move Method and not a new Resolver service.** The engine already owns the collaborators
  (`RegisteredJob` registry, mirrors, lazy materialization, the warm-cache parity property).
  A parallel resolution service would be a second authority — the exact disease.
- **Cost / risk.** The kwargs-split and stdin semantics must move *identically*; this is the
  highest-risk step of the roadmap (warm/cold parity, `TestWarmBootParity` defends it).

### 3.3 Protocol port + constructor injection — `EngineHost` (house pattern: DIP via `_types` protocols)

**Intent.** Seal construction (Cause 2). The engine's external needs become a narrow
`@runtime_checkable Protocol` in `_types/protocols.py` — job lookup, config resolution, gate
resolution, state-store root, surface stack — wired **once** by a single `build_engine(host)` in
`_app/boot.py` (collapsing the duplicated `boot.py:270-288` / `482-500` constructions). All
post-hoc private writes die; `refresh()` re-resolves through a sanctioned host method;
`Path.cwd()` leaves the kernel (`executor.py:1093-1096`).

- **Why this and not Mediator.** The relationships are one-way (engine *consumes* host services);
  nothing needs two-way coordination. ch20's own disambiguation: Facade/ports for one-way
  simplification, Mediator when components must talk to each other. A Mediator engine would also
  bless the existing god-object creep — ch20's first anti-pattern — on a class already at 2,401
  LOC.
- **Cost.** The `RunContext → engine._app` reads (`runcontext.py:425-764`) must be re-pointed at
  the host (they become legitimate accesses, killing smell #4's message chain).

### 3.4 Move Method onto the data — one `RunStatus → delivery-family` module (technique)

**Intent.** Close Cause 3's semantic gap. One `_types` module (extend `exit_codes.py` or a sibling
`outcome.py`) owns: the exit table (exists), the HTTP table (re-homed from `http_status.py` or
re-exported), the **failure-set rule** (`is_failure(family)` — the rule the TUI, `parallel`, and
the exit table each spell today), and the **report line** for BLOCKED/REFUSED (currently
click-only, `click_params.py:1244-1256`). Adapters keep only their family choice and their
rendering medium.

- **Why Move Method (ch36 Feature Envy routing: "things that change together live in the same
  place").** Every mapping changes together — add a `RunStatus`, all families change. Today the
  TUI envies `JobResult`'s status (`job_execution.py:274-285`), HTTP envies it
  (`__init__.py:178-193`), Lambda envies it (`__init__.py:63-73`); the behaviour belongs beside
  the status. This is *not* a Facade: no subsystem is being simplified, one concept is being
  given its behaviour.
- **What stays per-surface, deliberately.** The *family choice* (a panel is not a process; the
  TUI's BLOCKED→0-in-panel can remain right) and the rendering medium (stderr line vs rich panel
  vs tool response). The mapping and the rule become shared; the choice of family becomes the only
  per-surface decision — and it is a one-word, greppable one.
- **Cost.** Two plugins gain a `functualize.types` import they already partly have
  (`http_status_for_status` is already public); MCP's raw string stays (its family is "the enum
  name") but reads it from the same module.

### 3.5 Extract Class — the vocabulary grammar (technique, ch39)

**Intent.** Generalize the `negative_flag_for` precedent (STATUS.md:806-810) from *one rule
extracted by hand* to *the whole flag vocabulary extracted once*. A `_types/flag_grammar.py`
holds: which flags take values / optional values / are bool; the negative-spelling rule; the
group-flag alias matching (`dispatch.py:703-767`). Consumers: the click builders
(`click_params.py:322-876`), the pre-boot parser (`dispatch.py`), the TUI bar/sync
(`bar.py:295`, `sync.py:134`), completions. Parsers keep only their *syntax* (lookahead stays
`func`-only — it is "about reaching the program", surface-boundary §4).

- **Why not Strategy.** There is one grammar and many consumers, not many interchangeable
  algorithms selected by a client (ch24's own anti-pattern: pattern overhead for trivial
  variation). The pre-boot parser and click remain *two parsers* — that is inherent to
  pre-boot — but they consume one vocabulary, so a flag rule changes one file.
- **Cost.** Pure move; the `--perf-report` lookahead stays in `dispatch.py` with a comment naming
  why it is `func`-only.

### 3.6 Facade — used twice, both times the *ch14 remedy* for an existing facade (pattern, ch14)

**Intent.** (a) `FunctualizeApp.execute` remains the *only* surface-facing entry — today the
non-click surfaces already use it (MCP `_tools.py:254`, HTTP, Lambda, TUI `execute_job_sync`);
the click family bypasses it because the facade could not accept what click has (parsed kwargs).
`RunRequest` fixes exactly that, so the click family converges on the facade too. (b)
`RunContext` gets **Additional Facades** (ch14's named anti-pattern remedy): the job-author core
stays (name, config, log, invoke, prompt, status/phases, state); observability re-exposures
(`emit`/`on_event`/`perf_*`) and discovery re-exposures (`get_job_schema`/`list_jobs`) move to
focused facades or direct capability exposure.

- **Facade vs Mediator disambiguation** (cheatsheet): one-way simplification, subsystem unaware —
  yes here; two-way coordination — no. **Facade vs Adapter** (ch10/ch14): the facade defines the
  entry; adapters (below) translate the exit.
- **Cost.** Breaking for job authors who used the re-exposures (pre-release: free, one release
  note). Enforced thereafter by a LOC tripwire test (see roadmap step 7) — turning
  CONSTITUTION.md:175-176 from prose into a contract.

### 3.7 Adapter — the delivery surfaces, demoted to translators (pattern, ch10)

**Intent.** `deliver_job_result`, the TUI panel, the MCP tool response, the HTTP/Lambda handlers
are Adapters over the one outcome module: each implements its external interface (process exit /
terminal panel / tool payload / wire response) by *translating* the shared view, adding no rules.

- **Adapter vs Facade** (ch10 Connects-To): each wraps one contract into one external interface —
  interface translation, not subsystem simplification. **Adapter vs the current state**: today
  the click adapter *decides* (failure set, report text, validation rendering); after 3.4 it
  *translates*. The ch10 anti-pattern runs in reverse here: the thing to delete is the adapter's
  opinion, not the adapter.
- **Cost.** None beyond 3.4; this is a relabeling that makes an existing structure honest, plus
  the removal of `_engine` imports from `app/adapters/*` (they go through the facade).

### 3.8 Template Method — `_execute_lifecycle`, named and kept (pattern, ch25)

The 20-step lifecycle (`execution-lifecycle.md` table; `executor.py`, 329 LOC) **is** a Template
Method: fixed skeleton, constraint-pinned order (`tests/engine/test_lifecycle_order.py` fires on
any reorder), variant steps driven by declarations (`_bind_preflight_capabilities` loops over
`CapabilitySpec.preflight_bind` — ADR-014). The redesign changes none of it. Naming it matters for
two rules: (a) surfaces must never re-implement a step (the click callback's kwargs-split was a
step re-implementation — 3.2 removes it); (b) the template stays `final` in spirit — extension is
declaration (a capability, a hook), never editing the skeleton.

- **Template Method vs Strategy** (ch25 takeaways): the steps do not vary by client choice at
  runtime; they vary by *declaration*, and the order is the invariant. Strategy already exists
  where it belongs — `CapabilitySpec.factory` and `GateResolver` strategies (ADR-014, gate
  registry) — and the design builds on those, adding none.

### 3.9 Observer — already shipped, extended not duplicated (pattern, ch22)

`EventBus` + `HookRegistry` + `Surface.handle_event` (ADR-001) are the Observer fabric. Any
surface that needs to *react* to a run (MCP async progress, TUI live panel) subscribes; it does
not get a parallel execution path. The proposal adds no publisher; it removes the *reason*
adapters ever wanted one (they will hold a `JobResult` and an outcome view, not a re-implementation
of delivery logic).

### 3.10 Explicit rejections (a rejection with reasons is a finding)

| Pattern | Why rejected |
|---|---|
| **Mediator (ch20)** | No component-to-component chatter to centralize; HookRegistry/EventBus already own notification. A mediator engine is ch20's God-Object anti-pattern applied to a 2,401-LOC class. |
| **Command (ch18)** | `RunRequest` *looks* like Command but exists to carry data and seal parameters, not to be deferred/queued/undone — ch18's actual intent. Deferral, queuing and replay already exist where they're real: `WiredInvoke.parallel` queues, workflow `record_body` replays (execution-lifecycle step 19). A `execute()/undo()` protocol at the entry boundary buys an extra layer and nothing else. |
| **Strategy (ch24)** | One grammar, one resolution rule, one lifecycle — no client-selected interchangeable algorithms at this boundary. Already correctly used inside (capability factories, gate resolvers); adding more would be ch24's own "pattern overhead for trivial variation". |
| **Bridge (ch11)** | No two-dimension class-hierarchy variance; kernel/delivery separation is a layer *rule*, already enforced by import-linter. |
| **New registry (house pattern)** | The defect is missing *authorities*, not missing registries. GroupTrie, BUILTIN_COMMANDS, CapabilitySpec, exit tables exist; the design adds zero registries. |
| **A second Facade over the engine** | A "JobRunner service" between surfaces and the engine would be a new layer with the same looseness one step removed. The engine itself becomes the sealed authority. |

### Regrowth resistance — answering the reviewer's first question

ADR-001/004 partially regrew because they collapsed *rules* while leaving the *protocol* that
demands per-surface re-derivation: `execute(name, function, **knobs)` still forced every surface
to resolve, assemble, and thread. Every later feature re-entered through that door. This proposal
removes the door, in four layers:

1. **Structural**: after 3.2 there is *no API* by which a surface can pass a function or re-derive
   resolution — `engine.execute`/`function` disappears (clean cutover). A new surface cannot
   diverge in resolution because it has nothing to resolve with.
2. **Mechanical**: after 3.1/3.5, a new engine-level feature is a `RunRequest` field + a lifecycle
   step. Surfaces that build requests from their own parsing inherit the field automatically;
   only *exposing* it in a surface's syntax is per-surface work, and that is precisely what the
   dual-surface `cli_run` harness (`tests/conftest.py:434,454`, parameterized over surfaces)
   exists to pin — the harness that caught the epilog and capability-leak defects (ADR-010 §5).
3. **Contractual**: after 3.4 the failure-set and family mappings are importable data, and the
   existing plugin status-code suites (which already parametrize over every terminal `RunStatus`)
   extend to assert TUI/panel agreement with the table.
4. **Tripwired**: the LOC guards become tests; the no-private-writes rule becomes a grep-able
   assertion in the same style as `test_typer_isolation.py` (which asserts *absence*); the
   lifecycle order test already pins the template. Regrowth then requires *failing a named test*,
   not merely forgetting a convention — the difference between ADR-014's import-time invariant
   and the four hand-maintained lists it replaced.

---

## 4. Migration roadmap

Constraints honoured: pre-release (breaking changes free, **no compatibility shims** — old
signatures are deleted, not deprecated); each step lands independently (suite green, no dead
intermediate states); refactor commits only (`refactor(engine): …`), never mixed with features;
wiring-discipline sabotage named per step. Targeted suites named per AGENTS.md command discipline;
full suite only at the end (shared infrastructure changes).

**Step 1 — `RunRequest` value object; engine gains `run(request)`.**
Files: `src/functualize/_types/run_request.py` (new, stdlib-only); `executor.py` (`run()` added;
`execute()` marked `# TRANSITIONAL(run-request):` and reimplemented as a request builder —
completion is step 2); `app/core.py` (`execute()` builds the request).
Invariant: the engine's public signature stops growing; every execution input has one home.
Verification: fast suite green (pure behaviour-preserving extraction); `tests/engine/test_lifecycle_order.py` green. Sabotage: drop `group_option_values` from the request
builder → `tests/group_options/` goes red (the combination matrix exercises it through both
surfaces).
Risk: low.

**Step 2 — resolution moves inside `run()`; `function`/`config_class` leave the public call.**
Files: `executor.py` (`run()` resolves via `get_job`/`materialize_job`; kwargs-split + stdin
resolution move in from `click_params.py:1099-1124`); `app/core.py:620` (drop registry lookup);
`_app/impl.py:857`; `click_params.py` / `lazy_command.py` / `cli.py:698` (callbacks pass the
name; the click commands keep only argv→kwargs parsing); `_cli/main.py` (`_materialize_for_dispatch`
and `_dispatch_group`'s own path shrink to request construction). Delete `execute(name, function,
...)` — clean cutover.
Invariant: zero production sites outside `_engine` resolve a job name to a function (grep
`materialize_job|job_registry.get_job` outside `_engine`/`_app` returns nothing execution-shaped).
Verification: `tests/group_options/` (both surfaces, `--run-slow`), workflow-gate resume suites,
`tests/integration/test_declared_capabilities_e2e.py` incl. `TestWarmBootParity` (resolution now
includes lazy materialization on every surface — cold/warm equality is the defence). Sabotage:
make materialization raise on the lazy path only → the warm-parity pair fails.
Risk: **highest in the roadmap** — the kwargs-split and stdin semantics must move verbatim; do it
as one commit with the parity suites as the gate.

**Step 3 — sealed construction: `EngineHost` protocol, one `build_engine(host)`.**
Files: `_types/protocols.py` (`EngineHost`); `_app/boot.py` (single builder replacing
`boot.py:270-288` and `482-500`; delete the `:286/:498/:701/:1586` private writes);
`app/core.py:514` (`refresh()` re-resolves via a host method); `executor.py` (`_state_store`
reads the host's state-store root — `Path.cwd()` leaves the kernel, `executor.py:1093-1096`);
`runcontext.py:425-764` (`_app` reaches become host accesses — kills the message chain at
`:698`).
Invariant: the engine is complete at construction; no external private-attribute writes (grep
`engine\._[a-z_]+ *=` outside `_engine` is empty — the same absence-assertion style as
`test_typer_isolation.py`).
Verification: boot tests + fast suite; new absence test. Sabotage: restore one post-hoc write →
the absence test fails.
Risk: **high** — the `RunContext`/`surface_routing` `_app` reads are load-bearing (live zones);
re-point them in the same commit, with the TUI audit suite (`tests/tui_audit/`) green.
**Commit before sabotaging** (wiring-discipline §3; the process note in STATUS.md:779-782).

**Step 4 — one outcome module: failure-set rule + report lines join the tables.**
Files: `_types/exit_codes.py` (or new `_types/outcome.py` re-homing `http_status.py`);
`_cli/tui/job_execution.py:274-285` (consumes `is_failure(family="panel")` / report line);
`func builtin parallel`'s rule re-pointed; MCP `_tools.py:255-261` and the HTTP/Lambda handlers
read the same module (already public via `functualize.types`).
Invariant: `RunStatus → <family>` has one home; BLOCKED/REFUSED reporting is family-level data,
not click-local code.
Verification: the three plugin `test_status_codes.py` suites (already parametrized over every
terminal status) stay green; add the TUI-panel-≡-table parity test (`TestReadinessAgreesWithClick`
pattern — derive expectations from the table, never a second list). Sabotage: change the TUI's
failure set locally → parity test fails.
Risk: low.

**Step 5 — flag vocabulary grammar.**
Files: `_types/flag_grammar.py` (new: the `dispatch.py:81-121` tables, `negative_flag_for`,
`_flag_aliases`/`_negative_aliases`/`_match_group_flag` from `:703-767`); consumers re-pointed:
`dispatch.py`, `click_params.py:322-876`, `_cli/tui/bar.py:295`, `sync.py:134`, completions.
Invariant: one vocabulary definition; a flag rule is one edit.
Verification: `tests/group_options/` surface parity, `TestReadinessAgreesWithClick`, the
`emit(resolve(text)) == text` round-trip tests. Sabotage: diverge one alias in the click builder
only → parity red.
Risk: low-medium (pure move; two parsers remain by design — only the vocabulary unifies).

**Step 6 — engine Extract Class: `WorkflowOrchestrator`, `DependencyRunner`.**
Files: `executor.py` loses `_run_workflow_prelude` (140 LOC) + walker glue and `_run_dependencies`
(112 LOC) + scheduler glue to two engine-owned collaborators constructed from the host;
`_execute_lifecycle` keeps the 20-step skeleton and shrinks.
Invariant: the lifecycle order is untouched — `tests/engine/test_lifecycle_order.py` green at
every commit in the step (it is the proof the move was pure).
Verification: engine suite + declared-capabilities e2e; sabotage = reorder two steps → the order
test fires (already wired; demonstrate once, per wiring-discipline).
Risk: medium — the order is load-bearing; land as a sequence of pure Move-Method commits.

**Step 7 — facade diets + executable LOC guards.**
Files: `runcontext.py` (Additional Facades: observability/discovery re-exposures out; core stays
≤500); `app/core.py` (explain/`execute_parallel`/scope plumbing → `_app/impl.py`, which exists
for this; ≤300); new `tests/test_facade_loc_limits.py` asserting both numbers.
Invariant: CONSTITUTION.md:175-176 becomes a contract, not prose; `code-map.md:31`'s stale
"~500 LOC" description is corrected in the same commit.
Verification: LOC test + job-authoring example suites (`pytest examples/`); sabotage: append 10
lines to `RunContext` → test fails.
Risk: low (pre-release; job authors change imports once).

**Step 8 — TYPE_CHECKING blind spot (investigation, own commit).**
Measure flipping `exclude_type_checking_imports` in `pyproject.toml`. If `_config → _events`
(`chain.py:22`, `sources.py:36`) is the only violation: either legalize it as a documented
contract exception (memory + ADR note) or move the consumption behind a `_types` protocol.
Invariant: the layer contract that steps 1–7 lean on is fully enforced, or its one hole is
explicitly owned.
Verification: `uv run lint-imports` green under the new setting; no new contract breakage.
Risk: medium (unmeasured; several contracts may surface violations at once — that is the finding,
not a failure).

**Step 9 (end state) — the seal.** Delete the last `app/adapters/* → _engine` imports (adapters
go through the facade); every surface's invocation is: parse own syntax → `RunRequest` →
`app.execute` → `JobResult` → own Adapter over the outcome module. Full gate run
(`HYPOTHESIS_PROFILE=ci --run-slow -n auto`, plugins, examples, doc-verify) once, at the end —
shared infrastructure changed across the roadmap.

End state vs §1: per-surface resolution — impossible (no API accepts a function);
parameter-addition divergence — a field + a lifecycle step, inherited opaquely by every surface
that builds requests; status-semantics divergence — one module, family choice only; flag-rule
divergence — one vocabulary; mutation divergence — constructor-sealed, absence-tested. The
"open for modification" complaint becomes structurally impossible for the four divergence classes
this audit found.

---

## 5. Open questions

1. **External `AdapterPlugin` blast radius.** Plugins outside this repo may call
   `engine.execute(function=...)` or read `engine._app` directly; not enumerable from here. *Rec:* the
   `AdapterPlugin` protocol only promises `__call__(app)`, so facade-only entry is already the
   documented contract — state the break in the plugin guide and bump the minor version.
2. **Direct `JobExecutionEngine` construction by consumers.** Undocumented but importable; the
   seal makes it unsupported. *Rec:* declare it in ADR-020's consequences; offer no shim
   (pre-release stance).
3. **`Invoke.parallel` at `invoke_depth=0` from `app.execute_parallel`** (`core.py:672-678`) and
   the parallel-batch history gap (STATUS.md follow-up #5). *Rec:* keep depth as a request field;
   fold the history-recording fix into step 2's commit so the resolution move and the recording
   rule land together.
4. **TUI in-panel BLOCKED→0 vs process BLOCKED→5** (§1 Cause 3). Deliberate on both sides but
   decided by comment citations. *Rec:* treat as the acceptance case for step 4 — the outcome
   module must make "which family am I" an explicit, greppable choice; whether the inline TUI's
   process exit should be 5 when it *is* the process is a maintainer decision to take then.
5. **The `app/utils.py` corridor (2,021 LOC).** It satisfies the `_cli` dogfooding rule
   letter-perfectly while re-publishing internals (`read_*_from_cache`, vault functions). *Rec:* out
   of scope here; record as the next surface-boundary question — the group-options fingerprint gap
   (STATUS.md:186-189) is its open wound.
6. **`--perf-report` optional-value lookahead** stays `func`-only (surface-boundary §4 table).
   *Rec:* confirm the grammar module deliberately excludes it so the exclusion is a documented
   decision, not an omission.

---

## Related

- `contributor/architecture/surface-boundary.md` — the map this audit digs beneath
- `contributor/adr/020-engine-entrypoint-encapsulation.md` — the decision proposal arising from
  this audit
- `contributor/adr/001-surface-architecture-collapse.md`, `004-cli-shell-convergence.md`,
  `014-capability-registry.md` — the precedent fixes whose *shape* this proposal repeats
- `contributor/guides/wiring-discipline.md` — the sabotage discipline the roadmap steps cite
- `.spec/STATUS.md` — the case files (boolean-flag negation, 0.1.1 cache findings, standalone
  seven defects) decomposed into the causes above
