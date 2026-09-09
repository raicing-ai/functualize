# 13 · Roadmap — nine features, one branch, one PR

The pi-workflows roadmap's Tier 0 and Tier 1 shipped as 0.3.0. Its Tier 2 (items 7, 8, 9)
and the entrypoint audit's nine steps are merged here into **nine features**, ordered by
what each one makes possible for the next.

---

## A. The features

| # | `.spec/features/<name>/` | What it does | Depends on | Sizing |
|---|---|---|---|---|
| **F1** | `run-request-entry` | `RunRequest`; `engine.run(request)`; delete `execute(name, function, …)`; the click family converges on the facade; the kwargs-split and stdin move; the deposit protocol becomes request fields; **D-13**, **D-1**, **D-2**, **D-3**; the T8 perf phase; parallel-batch history (#5) | — | Large. The riskiest feature in the set |
| **F2** | `run-outcome-authority` | One `_types` outcome module — exit table, HTTP table, failure-set rule, BLOCKED/REFUSED report line; `_types/flag_grammar.py`; **D-7** (TUI exits 5), **D-8** | — | Medium |
| **F3** | `engine-sealed-construction` | `EngineHost`; one `build_engine(host)`; every post-hoc write deleted; three `Path.cwd()` sites leave the kernel; `WorkflowOrchestrator` + `DependencyRunner`; facade diets; LOC tripwires | F1, F2 | Large, **high risk** |
| **F4** | `surface-request-parity` | **D-4**, **D-5**, **D-6** — group-option and resume channels for `Invoke`, HTTP, Lambda, and MCP's three doors; the `cli_run` harness extended over every feature row; the seal — last `app/adapters/* → _engine` imports deleted | F1, F3 | Medium |
| **F5** | `durable-run-layer` | Roadmap **item 8**. Run records, event log, lifecycle verbs, runner leases **with a fencing token**, per-step timeouts, thin effects outbox, graph-projection source identity, depth guard | F1, F3 | **Multi-release** |
| **F6** | `agent-step-port` | Roadmap **item 7**. `AgentStepExecutor` Protocol + capability flags; `EXECUTOR_PROVIDERS`; engine refuses rather than degrades | F1 | One release |
| **F7** | `workflow-graph-semantics` | Roadmap **item 9**. Loops, failure routing, typed step outcomes, `watch`, `notify`, `--wf-retry-epilogue` | F5 | Incremental |
| **F8** | `adjacent-defects` | **D-9**…**D-12**; the `TYPE_CHECKING` blind spot; the group-options cache fingerprint; the stale perf comment and three `entry_points` bypasses; STATUS #13, #14, #27, #37, #38 | — | Small, many tasks |
| **F9** | `job-owned-freshness` | Expose the pre-flight verdict to the body (ADR-012's `Sources` shape); let a job declare it handles its own freshness so the body is entered when fresh | — | Small |

## B. Order

```
   F1 ─┬─────────────► F3 ──────────► F4
       │                 │
   F2 ─┘                 ├──────────► F5 ──────────► F7
                         │
                         └── F6  (needs F1 only)

   F8, F9   independent — anywhere
```

`F1 ∥ F2` → `F3` → `F4` → `F5 ∥ F6` → `F7`.

Recorded here **and** in each `spec.md`'s "Depends on" line, because the wave graph in
`tasks.md` models ordering *within* a feature only. Nothing in the tooling enforces
cross-feature order; this table is the authority.

Three sequencing choices worth defending:

- **F2 is not behind F1.** It touches no door and needs no request. Running it in parallel
  establishes the *one authority, parity-tested* pattern on low-risk ground before F3 applies
  it to the engine's construction.
- **F6 does not wait for F5.** An agent step that cannot be durably recorded is still a
  working agent step. It needs F1 (a request to carry provenance), not F5.
- **F7 is genuinely last.** Every one of its six pieces needs something F5 builds — most
  sharply loops, which need an iteration identity on the step record
  ([10 §C](10-graph-semantics.md)).

## C. Two deviations from the audit's own recommendation

**1. The urgent tranche is not landed first.** The audit's D2 recommends shipping D-13, D-1
and D-2 separately, ahead of everything, because they need no redesign and land in days. That
argument is paid for by *shipping early* — and the single-PR constraint removes the payment
while keeping the cost, which is doing the work twice: once in the surface-boundary §4
pattern, once as `RunRequest` fields. They are folded into F1 and ordered first *within* it
(decision **G7**).

**2. The audit's five steps 1–2 and 4–5 are two features, not four.** Steps 1 and 2 cannot be
usefully separated: step 1 leaves `execute()` as a transitional request-builder that step 2
completes, and a feature boundary between them would ship a labelled half-state across a
review. Steps 4 and 5 are both "one vocabulary, many consumers" and share the parity-test
shape. The audit's steps 3, 6 and 7 all reshape the engine object and become one feature (F3)
for the same reason — 6 and 7 need the host that 3 builds.

## D. How this lands

**One branch. One PR. At the end.**

`.spec/features/` carries all nine feature directories for the life of the branch — the
`CONSTITUTION.md` exception that makes spec artifacts reviewable beside the diff. The
required `spec-artifacts-cleared` check (VCS.2) blocks the merge while
`git ls-files .spec/features/` is non-empty, so the PR opens only after every feature has
been executed, verified and cleared, with each one's durable half migrated to
`.spec/STATUS.md` or `contributor/adr/`.

Two mechanical notes for whoever executes this:

- **Wave graphs use the key `id`.** `.claude/hooks/spec_gate.py::has_wave_graph` requires
  every element of `"waves"` to be a dict carrying **both** `"id"` and `"tasks"`. The merged
  `workflow-continuation/tasks.md` used `{"wave": 1, …}`, which does not validate — the gate
  passed because a *sibling* feature directory had a valid graph. Decision **M5**.
- **CI does not run on branch pushes**, only on `pull_request` against master (and pushes to
  master). A long spec-only branch costs nothing until the PR opens.

## E. Traceability — every inherited id lands somewhere

Nothing from either source is silently dropped. An id is either in a feature or in
[11 §C](11-boundaries.md) with a reason.

### The coverage audit's divergences

| id | Lands in | id | Lands in |
|---|---|---|---|
| D-1 `--prompt-gates` func-only | **F1** | D-8 `parallel` 7th site / history | **F2** + **F1** |
| D-2 `--output` func-only | **F1** | D-9 unknown-command (#37) | **F8** |
| D-3 `--force` no channel | **F1** | D-10 enum arrives as `str` (#38) | **F8** |
| D-4 `Invoke` group options (#17) | **F4** | D-11 single-file second boot | **F8** |
| D-5 MCP split three ways | **F4** | D-12 conflict raw traceback | **F8** |
| D-6 HTTP/Lambda no channel | **F4** | D-13 `job.submit` no scope | **F1** |
| D-7 TUI BLOCKED → success | **F2** | | |

### The leakage scoreboard

| id | Lands in | id | Lands in |
|---|---|---|---|
| C-1 registry eviction | **F3** | C-8 `surface_gate` → `_engine` | **F4** |
| C-2 `_resolution_chain` write | **F3** | C-9 `func why`'s second verdict engine | **F3** (constraint: must not be orphaned) |
| C-3 `_app` + registry mirror | **F3** | C-10 `execute_parallel` builds `WiredInvoke` | **F3** |
| C-4 the deposit protocol | **F1** | C-11 TUI pokes `app._pending` | **F3** |
| C-5 `job.submit` bypass | **F1** | C-12 `app/utils.py` corridor | **N3** (out of scope; its fingerprint wound in **F8**) |
| C-6 `click_params` → `_engine` | **F4** | C-13 `_cli` runtime imports | none — **confirmed clean** |
| C-7 `lazy_command` → `_engine` | **F4** | C-14 size drift | **F3** |

### The target assertions and the audit's nine steps

| id | Lands in | Step | Lands in |
|---|---|---|---|
| TGT.1 no function passed | **F1** | 1 `RunRequest` | **F1** |
| TGT.2 no post-hoc writes | **F3** | 2 resolution move | **F1** |
| TGT.3 one `RunStatus → family` | **F2** | 3 `EngineHost` | **F3** |
| TGT.4 one flag vocabulary | **F2** | 4 outcome module | **F2** |
| TGT.5 lifecycle order unchanged | **constraint, every feature** | 5 flag grammar | **F2** |
| TGT.6 LOC enforced by tests | **F3** | 6 Extract Class | **F3** |
| TGT.7 every surface builds a request | **F4** | 7 facade diets | **F3** |
| | | 8 `TYPE_CHECKING` | **F8** |
| | | 9 the seal | **F4** |

### The test tiers

| id | Lands in | id | Lands in |
|---|---|---|---|
| T1 `cli_run` dual-surface over every feature row | **F4** | T5 LOC tripwires | **F3** |
| T2 warm-boot parity through the resolution move | **F1** | T6 panel ≡ table parity | **F2** |
| T3 lifecycle order green at every commit | **every feature** | T7 plugin status-code suites | **F2** |
| T4 absence assertions | **F3**, **F4** | T8 warm-cache `func <job>` perf phase | **F1** |

### The pi-workflows roadmap and its open STATUS items

| Item | Lands in | STATUS | Lands in |
|---|---|---|---|
| 7 agent step as a port | **F6** | #5 parallel items missing from history | **F1** |
| 8 durable run layer | **F5** | #13 / #14 dead code with no caller | **F8** |
| 9 loops, routing, watch, notify | **F7** | #17 `rc.invoke` group options | **F4** |
| | | #27 parse failure vanishes on run two | **F8** |
| | | #37 / #38 | **F8** |
| | | dead `config_class` at the `run_step` seam | **F1** — it dies with the parameter |
| | | group-options cache fingerprint | **F8** |

### Not covered, and named as such

| | Why |
|---|---|
| STATUS **#4** — shell-completion model unification | Real and confirmed open, but a separate subsystem: `shell-init` and `SmartBar` consume one trie and compute partitions independently. It is not an entry-boundary or a run-durability question |
| STATUS **#22** — `tui.default_surface` inert until shell import | The test discipline is resolved and pins the gap; the product gap is a surface-registration question, not a run question |
| `app/utils.py` corridor, artifact caching, declarative `RunContext` exposure, subject modeling | [11 §C](11-boundaries.md) — **N3**, **N1**, **N2**, **N11** |

## F. The parity tests, and when each goes green

The pi-workflows roadmap's six parity tests, and where each is finally satisfied:

| # | Test | Green after |
|---|---|---|
| 1 | An agent drives a workflow to completion over MCP with no human typing | **already** — 0.3.0, `tests/integration/test_mcp_workflow_loop_e2e.py` |
| 2 | `kill -9` mid-workflow; a new runner resumes; an effect step re-runs exactly once | **F5** |
| 3 | Editing the graph refuses a resume; editing an unrelated job in the same file does not | **F5** (source identity, decision **K3**) |
| 4 | A *protected* gate cannot be answered by an agent that answered the previous one | **F6** (capability-flag refusal) |
| 5 | `func builtin workflow watch` shows the live graph | **F7**, on **F5**'s lease |
| 6 | A `STATE_VERSION` bump never silently empties a blocked scope | **already** — `24c5cc0`, `tests/test_state_split_regression.py` |
