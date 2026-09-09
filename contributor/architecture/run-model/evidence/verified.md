# Verified — fact index at `e57f0c9`

Every fact this set asserts, with the location that proves it. Grouped by subsystem. A `⚠`
marks a citation that differs from the source audits' — see
[drift-2026-09-09.md](drift-2026-09-09.md) for the before/after.

Where a fact is a **count** or a **negative**, the command that establishes it is given
inline. That is `.spec/CONSTITUTION.md` → *Retrieval Before Assertion*: a claim with no
command is not a finding.

---

## functualize — the engine

| Fact | Location |
|---|---|
| `execute()` takes 13 parameters excluding `self`, two of them a resolution the caller performed | ⚠ `_engine/executor.py:657-672` |
| The engine resolves by name for workflow steps | ⚠ `_engine/executor.py:1216` |
| …and for dependencies | ⚠ `_engine/executor.py:1795` |
| `_execute_lifecycle` is 329 LOC | `_engine/executor.py:757-1085` |
| `JobExecutionEngine` is 2,401 LOC, 55 methods | `_engine/executor.py:157-2557` |
| The body is **not entered** when the pre-flight says skip | `_engine/executor.py:1026` |
| `force_fresh` overrides only `SKIP_FRESH`; `force` also overrides `SKIP_SATISFIED`; neither overrides a failing `Precondition` or a gate | `_engine/executor.py:1000-1025` |
| History records only `invoke_depth == 0` | `_engine/executor.py:705` |
| `PreflightDecision` already carries the verdict, key, recorded value and source map | `_engine/preflight.py:49-64` |
| The kernel asks the OS for the working directory in **three** places | ⚠ `_engine/executor.py:1096`, `_engine/preflight.py:116`, `_engine/capabilities/runcontext.py:291` |
| `Sources` is the precedent for handing the body what the pre-flight computed (ADR-012) | `_engine/capabilities/sources.py:1-20` |
| A step failure ends the walk — one `except`, one exit | `_engine/workflow_walker.py:336-337` |
| `ConditionalEdge` dispatches on the step's **return value**; a raised step never reaches it | `_engine/workflow_walker.py:410-425` |
| A recorded branch is *read*, and the condition is not called at all | `_engine/workflow_walker.py:412-417` |
| No node runs twice — the `visited` set, added for diamond joins | `_engine/workflow_walker.py:227, 237-238` |
| Resume replay skips records whose outcome is `"success"` | `_engine/workflow_walker.py:314-317` |
| In-graph cycles are legal to declare — only workflow *nesting* cycles are validated | `_engine/workflow_validation.py:187-213` |
| `.ok` is on `WalkReport`, not on `RunStatus` | `_engine/workflow_walker.py:138-141` |

## functualize — construction and boot

| Fact | Location |
|---|---|
| Five post-hoc private writes on the engine | `_app/boot.py:286, 498, 701, 1586`; `app/core.py:514` |
| The registry's **private** map is shared by reference | `_app/boot.py:288, 500`; `_engine/executor.py:232` |
| `core.py:514` fires on `refresh()` — at runtime, not boot | `app/core.py:514` |
| Engine construction is duplicated across the two boot paths | `_app/boot.py:270-288` vs `:482-500` |
| Entry points are scanned **once per process**, not seven times | `_primitives/entry_points.py:38-60`; landed `84ed555` (PR #4), 2026-08-27 |
| Three callers still bypass that cache | `plugins/functualize-ai/.../_provider_discovery.py:53`; `_cli/skills.py:156`; `_cli/tui/display_provider_discovery.py:77` — `rg 'importlib\.metadata\.entry_points\(' src/ plugins/*/src/` |
| Six callers use it | `_plugins/loader.py`, `_plugins/domain_registry.py`, `_config/registry.py`, `_app/boot.py`, `_cli/plugin_cmd.py`, `_discovery/providers.py` |

## functualize — the deposit protocol

| Fact | Location |
|---|---|
| All **ten** deposit writes are in `_cli/main.py` — which is why an app's own entry point never has `--prompt-gates` or `--output` | `_cli/main.py:945, 1246-1248, 1366-1368, 1666-1668` — `rg 'app\._(prompt_gates\|output_format\|force) *='` |
| `_prompt_gates` is read by the kernel | `_engine/executor.py:1283` |
| `_output_format` is read by the kernel | `_engine/capabilities/stdout.py:151, 156` |
| `_force` is read by *delivery*, not the kernel | ⚠ `app/adapters/click_params.py:74` |
| Seven private app attributes are read via `getattr` from `_engine/` | `surface_routing.py:46,49,63,64,86,89`; `ambient.py:125,154`; `runcontext.py:425,428,479,698,719,764`; `invoke.py:710`; `live.py:135`; `stdout.py:151`; `tty.py:132` |
| The only unguarded reach-through — a three-hop message chain | ⚠ `_engine/capabilities/runcontext.py:698` |

## functualize — the doors

| Fact | Location |
|---|---|
| `interactivity.job.submit` executes with four arguments and no scope | `_app/impl.py:845-866`, call at `:861` |
| Scope creation lives inside the facade this door bypasses | `app/core.py:606-628` |
| `app.execute` resolves the function itself | `app/core.py:620-621` |
| `rc.invoke` **does** propagate `parent_scope` | ⚠ `_engine/capabilities/invoke.py:398, 406` |
| `parallel` passes `parent_scope=None` **deliberately** | `_engine/capabilities/invoke.py:603` |
| `guarded_execute` is the ninth door, and the funnel all three workflow surfaces use | `app/_workflow_control.py:176` |
| Single-file mode boots a second app that imports from CWD | ⚠ `_cli/main.py:1652-1668` |

## functualize — outcome and vocabulary

| Fact | Location |
|---|---|
| Nine `RunStatus` translation sites, two of them added in 0.3.0 | see [drift §Claim 7](drift-2026-09-09.md) |
| The TUI consults the table for failures and overrides it for BLOCKED | `_cli/tui/job_execution.py:271-285` |
| …citing `func builtin parallel` in a comment rather than an authority | `_cli/tui/job_execution.py:269-270` |
| `_resume_exit` reverse-looks-up a status string, with a hand-rolled fallback | ⚠ `_cli/builtins.py:1354-1367` |
| `workflow resume` already exits 5 when still blocked, deliberately breaking compatibility | `_cli/builtins.py:1354-1358` (docstring) |
| `wire_status()` exists because *"Three doors disagreed"* | `plugins/functualize-mcp/.../_tools.py:35-48` |
| `negative_flag_for` has seven consumers, pinned by no test | `_types/naming.py:100`; `click_params.py:322,608,675,876`; `bar.py:295`; `sync.py:134`; ⚠ `dispatch.py:729` |
| `RunStatus` has `.resumable` and `.ran`, and **no `.ok`** | `_types/enums.py:35, 47` |

## functualize — ports and providers

| Fact | Location |
|---|---|
| The node vocabulary is a closed `(Step, Gate)` pair | `workflow/_validation.py:28` |
| Node kind is `isinstance` dispatch inside the walker | `_engine/workflow_walker.py:261, 313` |
| The codebase's **one** `*_PROVIDERS` table | `_gate/_strategy.py:40-45` |
| …with `CORE_STRATEGIES` so the hint can return an empty string | `_gate/_strategy.py:52-66` |
| …pinned by a grep test asserting core imports no plugin | `tests/gate/test_registry.py:298-306` |
| The port template: registered, never auto-discovered | `_gate/_resolver.py:18-40` |
| A missing implementation names the package to install | `_gate/_registry.py:24-37, 180-203` |
| Capability names are checked at **import time** — a forgotten name is a startup crash | `_engine/capabilities/registry.py:97-123` |

## functualize — observation

| Fact | Location |
|---|---|
| A resumed walk reports `blocked` for its whole duration — liveness is not in the store | `app/_workflow_view.py:93-96` |
| The walker emits no events except scope creation | `rg 'emit\(' src/functualize/_engine/workflow_walker.py` |

## Discovery and config

| Fact | Location |
|---|---|
| `GroupOptionsConflictError` is raised and never caught in `src/` | `_discovery/cached_provider.py:916`; `rg 'except GroupOptionsConflictError' src/` → empty |
| `_config → _events` imports are invisible to the layer contracts | `_config/chain.py:22`; ⚠ `_config/sources.py:35` |
| `app/utils.py` is 2,068 LOC with 93 re-exports | `wc -l src/functualize/app/utils.py`; `__all__` length |

## Test infrastructure

| Fact | Location |
|---|---|
| Boot budgets, enforced serially in `test-fast` | `tests/perf/test_startup_budget.py:35-62, 95` |
| The stale comment recommending shipped work | `tests/perf/test_startup_budget.py:44-60` (written `b5495c6`, 2026-08-20) |
| Lifecycle order is AST-checked against the doc | `tests/engine/test_lifecycle_order.py` |
| Warm/cold parity | `tests/integration/test_declared_capabilities_e2e.py:540` |
| The dual-surface harness | `tests/conftest.py:454` |
