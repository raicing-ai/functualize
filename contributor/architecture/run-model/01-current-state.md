# 01 · Current state — the doors, the leaks, the budgets

Everything here was re-derived at `e57f0c9`. Where a claim is a count or a negative, the
command that establishes it is named — `.spec/CONSTITUTION.md` → *Retrieval Before Assertion*.

The coverage audit counted **17** ways a job execution starts at `c0c921f`, against
documentation claiming **9**. Two releases later the honest number is **21**.

---

## A. The doors

**21 rows. 19 of them start a job or workflow body**; `builtin self doctor` boots without
running one, and MCP's `answer_gate` records without executing. All 17 of the audit's rows
still exist; PR #35 added four.

### A.1 The four added by 0.3.0, and they share one funnel

| # | Door | Entry | Reaches execution via |
|---|---|---|---|
| N1 | `guarded_execute` — **the funnel, not a door** | `app/_workflow_control.py:154` | policy check `:175` → `app.execute(...)` `:176` |
| 5b | `func builtin workflow resume` | `_cli/builtins.py:1273` / `:1300` | `resume_scope` (`_workflow_control.py:239`) → `guarded_execute` `:327` with `policy=None` |
| 5c | `func builtin workflow gate-tool` | `builtins.py:1368` / `:1382` | `call_gate_tool` (`_workflow_control.py:454`) → `guarded_execute` `:514` |
| 11d | MCP `resume_workflow` | `_workflow_tools.py:259` | → `resume_scope` `:269` |
| 11e | MCP `call_gate_tool` | `_workflow_tools.py:306` | → `call_gate_tool` `:310` |

`guarded_execute` has exactly **two** callers — `resume_scope` (`:327`) and `call_gate_tool`
(`:514`). It routes through `app.execute`, so the number of name→function resolution sites
did **not** change.

New code that is *not* a door: the `answer`, `list`, `show`, `cancel` and `purge` verbs, five
MCP read tools, and PR #34's persistence layer.

### A.2 Three of the original 17 changed shape

| # | Change |
|---|---|
| 14 | `_execute_command` is **gone** (repo-wide grep: zero hits). The executing body is now `inline_tui.py::_run_handoff:143` → `app.execute:239` |
| 11c | `resume_gate`/deposit became `answer_gate`, which **records only**. The `_deposit` helper survives at `_workflow_tools.py:423-432` with **no remaining caller** — orphaned |
| 1,2,3,7a | The `--scope-id` global flag was **removed**; resume moved to the post-command `--wf-*` family (nine flags, `workflow_flags.py:86-147`). New channels on existing doors, not new doors |

### A.3 Grouped

For design purposes this set groups the 21 rows into **nine architectural doors** — `func`
pre-boot · click adapters · TUI · MCP · HTTP · Lambda · `rc.invoke` · `app.execute` ·
`guarded_execute`. That grouping is this document's, not an independent finding; the 21-row
enumeration is the measured fact.

## B. What each door can and cannot do

`~` marks an **accidental** channel — see §B.1.

| # | Door | scope? | group opts? | resume? | force? |
|---|---|---|---|---|---|
| 1 | `func <job>` | persisted ✓ (mint; `--wf-run-id`) | ✓ | ✓ `--wf-resume` | ✓ |
| 2 | `func <group> <job>` | as 1 | ✓ (`dispatch.py:763` → `:1073`) | ✓ | ✓ |
| 3 | `func <file>.py` | as 1 | ✓ | ✓ | ✓ |
| 5 | `func builtin parallel` | persisted, **unaddressable** | ✗ — items are `(name, {})` (`core.py:679`) | ✗ | ✗ |
| 5b | `workflow resume` | ✓ | ✗ | ✓ — this is the resume door | ✗ |
| 5c | `workflow gate-tool` | ✓ | ✗ | scope ✓, walk-advance ✗ | ✗ |
| 7a | job commands on an app's own CLI | persisted ✓ | ✓ | ✓ | ✓ |
| 8 | `app.execute` | in-memory ✓ **always** · persisted ✓ | ✓ | ✓ | **✗** |
| 9 | HTTP | persisted fresh | **~** | **~** | ✗ |
| 10 | Lambda | persisted fresh | **~** | **~** | ✗ |
| 11 | MCP per-job tools | persisted fresh | ✓ (`_server.py:278`) | ✗ | ✗ |
| 11a | MCP `run_job` | persisted fresh | **~** | **~** | ✗ |
| 11b | MCP async worker | as 11a | **~** | **~** | ✗ |
| 11d | MCP `resume_workflow` | ✓ | ✗ | ✓ | ✗ |
| 11e | MCP `call_gate_tool` | ✓ | ✗ | scope ✓, advance ✗ | ✗ |
| 12 | `rc.invoke` | runs in the parent's scope (`:398`); `parallel` items `None` (`:603`) | ✗ | inherits, cannot address | ✗ |
| 13 | inline TUI | persisted fresh | ✓ (`:244`) | ✗ | ✗ |
| 14 | full-screen TUI | persisted fresh | ✓ (`:241`) | ✗ | ✗ |
| 15 | `interactivity.job.submit` | persisted but **unaddressable** | ✗ | ✗ | ✗ |
| 16 | engine recursion | inside its own walk's scope | ✗ | continues its own | ✗ |
| 17 | `builtin self doctor` | boots only | — | — | — |

**`force` is available on exactly two of nineteen executing doors** — the click surfaces that
deposit `app._force`. `app.execute` has no `force` parameter (`core.py:573-580`), so nothing
routed through it can force a run.

### B.1 Two scope objects, and the audit conflated them

A correction this set makes to its own source. There are two:

| | Minted by | Where |
|---|---|---|
| in-memory `WorkflowScope` trace | `FunctualizeApp.execute` | `app/core.py:606-628` |
| **persisted** scope record | the engine, for every `@workflow` | `_engine/workflow_runner.py:97` — `scope_id or new_scope_id()`, from the prelude at `executor.py:869-877` |

The click doors bypass `app.execute` entirely (`click_params.py:1148`, `lazy_command.py:153`)
and so create **no** in-memory scope — yet they mint persisted scopes for workflows perfectly
well. So "which doors create a scope" has two different answers, and the audit's
"`job.submit` runs with no `WorkflowScope`" is true only of the in-memory one.

The defect survives the correction and is sharper for it: `job.submit`'s scope is created and
**unaddressable**. See [04 §C](04-request-and-entry.md).

### B.2 The accidental channel

`FunctualizeApp.execute` declares control inputs as keywords:

```python
def execute(self, job_name: str, *, scope_id=None, group_option_values=None, **kwargs): ...
```

HTTP splats the decoded request body straight into it
(`functualize_http/__init__.py:177`: `self._app.execute, job_name, **kwargs`); Lambda and
MCP's `run_job` and async worker do the same with their event and argument dicts. **A payload
key named `scope_id` binds to the control parameter.** Doors documented as having no resume
channel have an unvalidated one that appears in no schema.

`force` does not leak this way — not being an `app.execute` parameter, it lands in job kwargs,
and a `@workflow` refuses unexpected launch arguments (`executor.py:851-863`).

## C. The leaks

Fourteen rows in the coverage audit's scoreboard; the load-bearing ones, re-verified:

| | What | Where |
|---|---|---|
| The deposit protocol | **seven** private app attributes read by the kernel via `getattr` with silent defaults; all ten writes in `_cli/main.py` | [04 §B](04-request-and-entry.md) |
| Post-hoc engine writes | five, across both boot paths, one of them at **runtime** | [05 §A](05-engine-seal.md) |
| Message chain | `runcontext.py:698` — three hops, unguarded | [05 §B](05-engine-seal.md) |
| Self-wiring from the process | **three** `Path.cwd()` sites in the kernel | [05 §C](05-engine-seal.md) |
| Hooks reached through the private map | `boot.py:354`, `:733`, `invoke.py:390,440,449` read `app._hook_registry._global_hooks` directly, bypassing `invoke()` | measured |
| `_cli` runtime imports of internals | **zero** — AST-checked. The contract holds | confirmed clean |

## D. The budgets

| Class | Constraint | Measured | Over |
|---|---|---|---|
| `RunContext` | ≤ 500 LOC | **782** | 1.6× |
| `FunctualizeApp` | ≤ 300 LOC | **1,265** | 4.2× |
| `JobExecutionEngine` | decompose above ~500 | **2,401**, 55 methods | 4.8× |
| `_execute_lifecycle` | — | **329** | — |
| `app/utils.py` | — | **2,068**, 93 re-exports | +18 re-exports in one release |

`contributor/reference/code-map.md:31` still calls `RunContext` "~500 LOC" and puts it in
`job/context.py`. Stale description, breached constraint, no test.

## E. Declared and never used

Found while surveying, all the same shape as STATUS #13 and #14 — a declaration with no
producer or consumer:

| | Where |
|---|---|
| `job.execute.error`, `cli.parse.start`, `tui.session.start/end` | declared in `_events/_catalog_entries.py`, **emitted nowhere** |
| `JobContext.deadline` | `_engine/capabilities/job_context.py:27,38` — *"Optional deadline after which the job should abort"*; **no construction site ever sets it** |
| `_deposit` | `_workflow_tools.py:423-432` — orphaned by 0.3.0's `answer_gate` |
| ~~`FUNCTUALIZE_CLI_OUTPUT`~~ | ~~help text at `builtins.py:1961, 2072, 2166`; read by nothing~~ — **no longer true.** Read at `_cli/info.py:63` via `resolve_renderer`, which all three help sites route through; verified by behaviour (`FUNCTUALIZE_CLI_OUTPUT=json func builtin info jobs` emits JSON) and pinned by `tests/cli/test_info_subcommands.py`. Fixed between `c0c921f` and execution, not by this roadmap (run-request-entry/T14) |
| `get_missing_required_args`, `omit_defaults` | STATUS #13, #14 |

## F. One comment that is false

`app/_workflow_control.py:17-18` states that `--wf-resume` *"passes through
`guarded_execute`"*. It does not: `apply_workflow_flags` returns a scope id
(`workflow_flags.py:376-402`) and the click wrappers call the engine directly
(`click_params.py:1100 → 1148`, `lazy_command.py:77 → 153`).

Harmless today — the resumed job *is* the workflow, which the policy exempts by design — but
the sentence is false as written, and it is the kind of false that a later reader builds on.
Corrected in **F8**.
