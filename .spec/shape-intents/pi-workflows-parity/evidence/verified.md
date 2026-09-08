# Evidence index — re-derived from source

functualize @ `78d9ff4` (`~/code/raicing-ai/functualize`) ·
pi-workflows @ `2b3cf35` (`~/code/open-source/pi-workflows`)

Every line reference below was opened and read. Five citations in the previous study had
drifted; those are marked ⚠ with the correct location.

---

## functualize — engine

| Fact | Location |
|---|---|
| Workflow = prelude (walk) + epilogue (body); body-once-per-scope | `src/functualize/_engine/workflow_runner.py:1-21` |
| `prelude` never reads scope status — a `failed` or `cancelled` scope re-walks freely | `workflow_runner.py:101-127` |
| Epilogue record is written on failure too → **failed body is sticky** | `executor.py:1029-1037` + `workflow_runner.py:120-126` |
| BFS walk loop; join deferral counter for asymmetric diamonds | `workflow_walker.py:230-252` |
| `_ready()` join logic — unreachable-predecessor reasoning, cycle tie-break | `workflow_walker.py:378-396` |
| Changed graph → `unknown node` **fails loudly** (not silent) | `workflow_walker.py:255-259` |
| Gate block path; `blocked_reason` carries unregistered-strategy diagnostics | `workflow_walker.py:261-310` |
| Strategy path stores `model.model_dump()` | `workflow_walker.py:270-277` |
| Replay skips only `status == "success"` → **failed steps re-run** | `workflow_walker.py:314` |
| `_fail` records the step failed, stops the walk; no failure routing | `workflow_walker.py:442-456` |
| **`_key()` hardcodes `args_hash=""`** — no args-based memoization | `workflow_walker.py:466-473` |
| `step_key(job, args_hash) -> "<job>::<hash>"` | `frontier.py:245-247` |
| `WalkState` is a plain class of string constants, not an Enum | `frontier.py:69-74` |
| `FrontierWalk.start` returns the persisted position with **no status check** | `frontier.py:95-107` |
| `gate_payload` returns `None` while blocked | `frontier.py:203-206` |
| Blocked `JobResult.metadata` built here: `workflow_scope`, `workflow_status`, `blocked_on`, `blocked_reason` | `executor.py:1257-1283` |
| `Exec` rejects job-level timeout by design | `_types/job_declaration.py:387-403` |
| No `cancel`, no `timeout` anywhere in walker / runner / frontier | verified by absence |

## functualize — persistence

| Fact | Location |
|---|---|
| `save_state` **is** atomic — mkstemp → write → flush → fsync → `os.replace` | `_primitives/state_format.py:178-201` |
| `load_state` degrades **any** bad content to `empty_state()` | `state_format.py:162-175` |
| `normalize_state` discards on `format_version` mismatch | `state_format.py:142-159` |
| `update_state` = load → mutate → save under one lock | `state_format.py:296-310` |
| `state_lock` **degrades to a no-op** where OS locking is unavailable | `state_format.py:205-231` |
| `_SECTIONS = ("fingerprints", "scopes", "history", "session")` — one envelope | `state_format.py:56` |
| The discard rationale — *"runtime state is derived… worst case is one extra run"* — with `scopes` listed two lines below | `state_format.py:40-47` |
| `STATE_VERSION = 1` | `state_format.py:48` |
| `set_scope_status(scope_id, status: str)` | `state_store.py:164-170` |
| `record_step` — one record serving four consumers (§D.7d) | `state_store.py:172-182` |
| `deposit_gate_payload` overwrites unconditionally | `state_store.py:232-241` |
| `clear()` writes `empty_state()` — **wipes scopes** | `state_store.py:361-365` |
| `batch()` holds the lock for many mutations, one write | `state_store.py:98-114` |
| **`_blank_scope()` has no timestamps** — `{workflow, status, steps, branches, gates, position, epilogue, tool_calls}` | `state_store.py:45-56` |
| `put_gate` **replaces the whole gate record** → `blocked_at` reset on every re-block | `state_store.py:215-222` + `frontier.py:164-200` |
| `_block(node)` supplies `blocked_at=_now()`; reached on every walk hitting an unanswered gate | `workflow_walker.py:459-472` |
| CLI **does** print scope id + gate on exit 5 (stderr, default level) — MCP does not | `app/adapters/click_params.py:909-940`, `:1177` |

## functualize — surfaces

| Fact | Location |
|---|---|
| `func builtin workflow` group: `list`, `state`, `resume`, `cancel` | `_cli/builtins.py:820-951` |
| CLI `_scope_summary` — **5 fields only** | `_cli/builtins.py:831-841` |
| CLI `resume <id> <gate>` — takes **both** | `_cli/builtins.py:900-911` |
| `resume` docstring: *"Accepting input does not run the workflow"* | `_cli/builtins.py:913-917` |
| `state clear` help says "fingerprints, history" — never scopes | `_cli/builtins.py:778-806` |
| `--scope-id` in `_GLOBAL_OPTIONS_ALWAYS_VALUE` (early parse) | `_cli/dispatch.py:63-81` |
| Per-command `--scope-id` option definition | `app/adapters/click_params.py:56-73` ⚠ *study wrote `_cli/click_params.py`* |
| Added on the cold path when `_declares_workflow(function)` | `click_params.py:1230-1233` |
| Added on the warm path when `descriptor.workflow is not None` | `lazy_command.py:163-168` |
| Per-command wins over pre-command | `click_params.py:1036-1041` |
| `build_click_params_from_descriptor` does **not** add `_scope_id_option`; one caller only | `click_params.py:214-225`, called from `lazy_command.py:163` |
| Projection/renderer split precedent for survey surfaces | `_cli/info.py:110-176` (`job_catalog`, `job_detail`), `:405-419` (`render_*_text`), `:47` (`resolve_renderer`) |
| Cold-cache hazard for state-addressing flags | `_cli/main.py:2075-2081` |
| `deposit_gate_input` — validates `model(**payload)`, stores the **raw dict** | `app/_workflow_resume.py:60-107` |
| `pending_gates` = gates with `payload is None` | `app/_workflow_resume.py:18-31` |
| `_resolve_gate_model` — the one place importing the declaring module | `app/_workflow_resume.py:34-57` |

## functualize — MCP

| Fact | Location |
|---|---|
| `run_job(name, config)` — **no `scope_id`**; returns `{status, return_value, duration_ms}` | `functualize-mcp/_tools.py:207-266` ⚠ *study said `:207-268`* |
| `run_job_async` — same signature, `daemon=True` thread, in-memory dict | `_tools.py:278-345` |
| `get_execution_status` — also drops metadata | `_tools.py:347-381` |
| `_execute_job` — the per-job funnel; drops metadata; returns raw `RunStatus` **enum** | `_server.py:230-282` |
| `RunStatus(Enum)` — plain Enum, not `str` enum; value is `"Blocked"` | `_types/enums.py:12-22` |
| Gate policy enforced at the funnel — *"the one place a call cannot get past"* | `_server.py:239-242` |
| `_gate_refusal` comment admitting generic/per-job duplication | `_tools.py:79-95` |
| Registration order: 5 core + task + history + management + 6 workflow + one per job | `_server.py:72-108` |
| `MCPConfig`: `include_tags`, `exclude_tags`, `exclude_jobs`, `enable_management` | `_config.py:33-39` |
| Task tools (4) gated on `functualize_tasks` importable | `_task_tools.py:88-109` |
| History tools (2) gated on `functualize_state` importable | `_history_tools.py:81-100` |
| Management tools (4) gated on `enable_management` | `_management_tools.py:52-70` |
| Description builder appends examples; schema inlines field descriptions + examples | `_translator.py:186-208`, `:229-268` |
| 6 workflow tools registered unconditionally | `_workflow_tools.py:168-180` |
| **`_describe`** — full graph, position, branches, per-step `return_value` + `inputs`, gate schemas | `_workflow_tools.py:471-509` |
| `_topology` falls back to the live declaration for plugin-registered workflows | `_workflow_tools.py:511-536` |
| `resume_gate(gate, input)` → ambiguous points at `resume_workflow` | `_workflow_tools.py:212-244` |
| `resume_workflow(workflow_id, input)` → ambiguous points at `resume_gate` | `_workflow_tools.py:247-278` |
| `call_gate_tool` — bound args refused | `_workflow_tools.py:281-323` |
| `_tool_summaries` — schema **minus** bound params | `_workflow_tools.py:578-607` |
| `cancel_workflow` — *"Cancelled scopes are not resumable"* (unenforced) | `_workflow_tools.py:434-458` |

## functualize — tasks

| Fact | Location |
|---|---|
| `TaskLink.kind: str  # "job" \| "workflow_step" \| "job_phase"` — unvalidated | `functualize-tasks/_types.py:20-29` |
| Every occurrence of `workflow_step` in the repo (5 sites, all docstrings/help) | `_types.py:24,28`, `_tasks.py:140,235`, `_task_tools.py:125,156` |
| `src/functualize/` references `functualize_tasks` **zero** times | verified by absence |

## functualize — measurements

| Measure | Value |
|---|---|
| `src/functualize` | 84,062 LOC Python |
| Workflow engine | 1,072 (walker 483 · frontier 247 · runner 144 · validation 198) |
| Skills | 4 — `functualize`, `-app`, `-cli`, `-skill`; none operate workflows |
| Built-in workflows | 0 |

---

## pi-workflows

| Fact | Location |
|---|---|
| **`AgentStepExecutor`** port — one method + 3 capability flags | `src/workflows/types.ts:900-911` |
| Engine fails closed on missing capability (assistantMessage, allowedTools) | `engine.ts:1299-1320` |
| Timeout budget persisted only when `preservesActiveTimeBudget` | `engine.ts:980-992` |
| Origin-session executor — all three flags true | `server/workflow-runner-entry.ts:197-199` |
| `RpcStepExecutor` — headless `pi --mode rpc`, one child per run | `server/rpc-executor.ts:56-97` |
| Validation-retry loop lives in the **executor** via `request.accept` | `rpc-executor.ts:80-97` |
| `resumeRun` — *"Completed nodes replay from the recorded state"* | `engine.ts:323-326` |
| `resumePointFor` — in-flight node reruns; handles finish-before-terminal-event | `engine.ts:436-470` |
| Checkpoint / assistantMessage nodes keep their exact attempt id across resume | `engine.ts:353-373` |
| Park does not record the in-flight attempt | `engine.ts:592-596` |
| Park during `node_started` prevents dispatch | `engine.ts:965-970` |
| `workflowIdentityMismatch` — 3 checks | `engine.ts:1774-1783` |
| `definitionDigest` — sha256 over canonical compiled-graph snapshot | `engine.ts:1786-1789`, `store.ts:5036-5062` |
| Built-in source = `{kind:"builtin", id, revision}`; revision mismatch throws | `workflows/catalog.ts:95-113` |
| `legacySources` hash→revision migration | `catalog.ts:12-17`, `builtins/catalog.ts:22-42` |
| **7** registered built-ins (+3 composition-only children) | `builtins/catalog.ts:10-43` ⚠ *study said 8* |
| `outcomeForError` → `timed_out` / `cancelled` / `failed` | `engine.ts:916-925` |
| `maxSteps` (default 100); transitions excluded; per-include limits | `engine.ts:555-573` |
| Settings-route CAS retry: `StaleResourceError` → `restoreRunState` → bounded retry | `engine.ts:627-670` |
| Fan-out forbidden — *"must not declare multiple outgoing edges"* | `graph.ts:66-68` ⚠ *study said `:53-56`* |
| Switch edges route on `$.` / `$output.` / `$result.`; N cases per edge | `graph.ts:78-107` |
| Switch prefix validated at definition time to prevent post-side-effect routing errors | `schema.ts:255-259` |
| Action nodes **require** a managed effect — schema rule | `schema.ts:120-131` |
| `RESERVED_WORKFLOW_NAMES` — 9 names | `schema.ts:271-282` |
| **13** tool actions (study said 10; missed `change-settings`, `queue-follow-up`, `remove-follow-up`) | `extension/index.ts:1235-1280` |
| 12 slash-command subcommands (incl. `run`, `clear`) | `extension/index.ts:788-1011` |
| Leases (token hash + monotonic generation) · immutable `events` · effects outbox | `docs/SQLITE_STATE.md:75-112` |
| Effect idempotency key = run + type + full node path + **visit number** | `SQLITE_STATE.md:109` |
| PRAGMAs, STRICT tables, DDL digest, fail-closed reset | `SQLITE_STATE.md:47-67` |

| Measure | Value |
|---|---|
| `src/` | 56,105 LOC TS |
| `src/workflows/` | 18,191 — `store.ts` 5,145, `queue.ts` 2,086, `engine.ts` 1,940 |
| `tui/` | 13,552 LOC Rust ⚠ *study said 13,403* |
| Skills | 6 |

---

## Experiments run

**E1 — state-version erasure** (isolated temp dir, `src/functualize` on `sys.path`,
removed afterwards). Created a blocked scope with a deposited gate payload, bumped
`format_version`, then made one unrelated fingerprint write via `update_state`:

```
BEFORE  scopes: ['a3f9c2e1b7d4']
on-disk scopes still present: ['a3f9c2e1b7d4']
AFTER   scopes: []
AFTER   file  : {}
RESULT: gate payload survived? False
```

## Not verified

- Gate tool-binding **behaviour** (structure confirmed by location only; not exercised).
- pi-workflows' Rust TUI, channels/Telegram delivery, and resource-managers runtime —
  read at the docs level only.
- Whether `resume_workflow`'s `ambiguous_gate` branch is reachable: the walker returns on
  the first blocking gate, so a single scope with two pending gates could not be
  constructed by inspection. The branch may be dead.
