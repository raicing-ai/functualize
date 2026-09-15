# 14 · Decision register

Every accepted decision for this set, numbered clean. Decisions inherited from
`~/code/raicing-ai/pi-workflow-parity/14-decisions.md` (ids `A1`–`A9`, `B1`–`B8`, `C1`–`C9`,
`D1`–`D6`, `E1`–`E6`, `F1`–`F6`) are **not restated** — they stand, and are cited by id where
this set builds on them.

Non-goals are in [11 §C](11-boundaries.md) as `N1`–`N11`. Retired arguments are in
[CHANGELOG §3](CHANGELOG.md) — **not here**, so this file reads as one set.

New id spaces, chosen to avoid collision with the inherited register:
**G** entry · **H** seal · **J** outcome · **K** durable runs · **L** steps and graph ·
**M** method.

---

## G. Entry and request

| # | Decision | Where |
|---|---|---|
| **G1** | **`RunRequest` is a frozen, stdlib-only value object in `_types/`.** Same placement logic as `exit_codes.py` and `naming.py`, so `_cli`, `app`, `_engine` and plugins import it with no cycle | [04 §D.1](04-request-and-entry.md) |
| **G2** | **The request carries the job *name*, never a function.** Resolution is an engine capability; `engine.run(request)` resolves and materializes internally, as it already does for steps (`executor.py:1216`) and dependencies (`:1795`) | [04 §D.2](04-request-and-entry.md) |
| **G3** | **`execute(job_name, function, …)` is deleted.** Clean cutover, no shim, no deprecation — a shim preserves the door this work exists to close. Pre-release stance | [04 §D.2](04-request-and-entry.md) |
| **G4** | **`FunctualizeApp.execute(request)` is the single surface-facing Facade, including for the click family.** Scope creation (`core.py:606-628`) stops being skippable, which *is* the D-13 fix — the alternative is removed, not patched | [04 §D.3](04-request-and-entry.md) |
| **G5** | **The deposit protocol dies: `prompt_gates`, `output_format` and `force` become request fields.** All ten writes are in `_cli/main.py`, which is why a project's own entry point never had them | [04 §B](04-request-and-entry.md) |
| **G6** | **`RunRequest` carries `surface` provenance.** Neither audit asked for it and both needed it — the coverage audit had to reconstruct which door a run came from by reading code. Once it is a field, the run record gets it free | [04 §D.1](04-request-and-entry.md) |
| **G7** | **The urgent tranche (D-13, D-1, D-2) is folded into F1, not landed separately first.** The audit recommends doing it first because it ships in days; that benefit is paid for by shipping early, and the single-PR constraint removes it. Doing the work twice — once as deposits, once as request fields — is waste | [13 §C](13-roadmap.md) |

## H. The seal

| # | Decision | Where |
|---|---|---|
| **H1** | **`EngineHost` is a narrow `@runtime_checkable Protocol` in `_types/protocols.py`**, wired once by `build_engine(host)`. No ABC — `.spec/CONSTITUTION.md` → *Ports* | [05 §E.1](05-engine-seal.md) |
| **H2** | **Every post-hoc private write is deleted**, and the rule becomes an absence test in the `test_typer_isolation.py` style: `engine\._[a-z_]+ *=` outside `_engine/` must return empty | [05 §A](05-engine-seal.md) |
| **H3** | **`Path.cwd()` leaves the kernel — all three sites**, not the one the audit reported. The host answers "where does this project's state live", once | [05 §C](05-engine-seal.md) |
| **H4** | **`WorkflowOrchestrator` and `DependencyRunner` are extracted as engine-owned collaborators**, constructed from the host — not as peers, not as a new layer | [05 §E.2](05-engine-seal.md) |
| **H5** | **The facade LOC budgets become executable tests**, and `code-map.md:31`'s stale "~500 LOC" description is corrected in the same commit. The point is not the number; it is that the constraint acquires a failure mode | [05 §E.3](05-engine-seal.md) |
| **H6** | **`_execute_lifecycle`'s 20-step order is untouched at every commit.** `tests/engine/test_lifecycle_order.py` staying green is the proof each move was pure, and the reason the moves are possible at all | [05 §E.2](05-engine-seal.md), [11 N5](11-boundaries.md) |

## J. Outcome and vocabulary

| # | Decision | Where |
|---|---|---|
| **J1** | **One outcome module in `_types/` owns four things**: the exit table, the HTTP table, the failure-set rule, and the BLOCKED/REFUSED report line. The first two exist; the last two are spelled three times and once, respectively | [06 §D](06-outcome-authority.md) |
| **J2** | **Family choice is the only per-surface decision, and it is one greppable word.** Rendering medium stays per-surface. The mechanism does not forbid a surface differing; it makes the difference visible | [06 §D](06-outcome-authority.md) |
| **J3** | **The inline TUI's process exit is 5 when a gate blocks** (audit D3, resolved). 0.3.0 already changed `workflow resume` from always-0 to 5-when-blocked, deliberately breaking compatibility, because *"a script that resumes in a loop needs to know whether it finished"* (`builtins.py:1354-1367`). The TUI is the last surface reporting a blocked run as success. **The panel may keep rendering `✓ Done`** — family choice and render are different questions | [06 §C](06-outcome-authority.md) |
| **J4** | **The whole flag vocabulary moves to `_types/flag_grammar.py`, not one rule of it.** Extracting `negative_flag_for` by hand was correct and insufficient: the plan counted five sites and the test found a sixth. Counting re-derivations is not a mechanism | [06 §E](06-outcome-authority.md) |
| **J5** | **Two parsers remain, deliberately.** Pre-boot exists for a ~3 ms zero-import routing budget. `--perf-report`'s optional-value lookahead stays `func`-only, and `flag_grammar` says so in a comment so the exclusion is a decision | [06 §E](06-outcome-authority.md), [11 N7](11-boundaries.md) |
| **J6** | **The `negative_flag_for` consumer count is pinned by a test**, so an eighth cannot appear silently — the shape `pitfalls.md` §6 prescribes: one registry, and a test that checks it | [06 §G](06-outcome-authority.md) |

## K. Durable runs

| # | Decision | Where |
|---|---|---|
| **K1** | **The run record is opened inside `engine.run()`**, the one place every door now passes through. This is the whole reason F5 is sequenced behind F1 | [03 §C](03-the-run-model.md), [08](08-durable-runs.md) |
| **K2** | **The lease carries a fencing token**, closing the concurrency limitation 0.3.0 shipped deliberately. Raises pi-workflow **C8** to a hard requirement | [08](08-durable-runs.md) |
| **K3** | **Source identity is a canonical digest of the graph projection, not a file content hash** — inherited pi-workflow **C6**, with the declared-revision and legacy-mapping story shipping alongside it | [08](08-durable-runs.md) |
| **K4** | **New scope fields go inside the scope record, never into `_SECTIONS`** — inherited pi-workflow **F5**; the durable layer does not reopen the `state.json` / `scopes.json` split that PR #34 settled | [08](08-durable-runs.md) |

## L. Steps and graph semantics

| # | Decision | Where |
|---|---|---|
| **L1** | **The agent step is a port, not a node kind**: `AgentStepExecutor` Protocol plus capability flags, with the engine **refusing** rather than silently degrading — inherited pi-workflow **C5** | [09](09-agent-step-port.md) |
| **L2** | **The provider table is the existing house pattern**, copied not invented: name the package, never import it; a `*_PROVIDERS` table plus a grep test failing as a block with a diagnostic — inherited **F3**/**F4** | [09](09-agent-step-port.md) |
| **L3** | **Typed step outcomes copy pi-workflows' vocabulary** (`timed_out` / `cancelled` / `failed`) rather than inventing a third | [10](10-graph-semantics.md) |
| **L4** | **`--wf-retry-failed` stays withdrawn; `--wf-retry-epilogue` is genuinely needed** — inherited from the pi-workflow roadmap's own demotion | [10](10-graph-semantics.md) |

## M. Method — how this set was produced, and what that binds

| # | Decision | Where |
|---|---|---|
| **M1** | **Every inherited claim was re-run before being carried.** 15 of 17 held, 0 became false, and the two that moved are corrected in place with the current citation | [02](02-audit-corrections.md) |
| **M2** | **A claim that cannot be re-verified is dropped, not softened.** The `entry_points()` memoization recommendation is withdrawn because it shipped in PR #4; the §B matrix's D-13 cell is corrected because `rc.invoke` does propagate scope | [12 §D](12-performance.md), [02 §F](02-audit-corrections.md) |
| **M3** | **This set uses five causes, renumbered once**, because the two audits each compressed to four and each dropped a different one. The old numbering is never reused | [02 §E](02-audit-corrections.md), [A](appendix-a-audit-synthesis.md) |
| **M4** | **One branch, one PR, at the end.** `.spec/features/` carries all nine feature sets until every one is executed; `spec-artifacts-cleared` (VCS.2) blocks the merge until they are cleared, so the PR opens only after execution | [13 §D](13-roadmap.md) |
| **M5** | **Wave graphs use the key `id`, not `wave`.** `.claude/hooks/spec_gate.py::has_wave_graph` requires both `"id"` and `"tasks"` on every element; the merged `workflow-continuation/tasks.md` used `"wave"` and would not have validated | [13 §D](13-roadmap.md) |

## Open

**None.** D3 is decided (**J3**), D5 is rejected with a reason ([11 §B](11-boundaries.md)),
D6 is out of scope (**N2**), D1/D2/D4 are absorbed (**G7**, and D4 becomes structural under
[07](07-surface-parity.md)).
