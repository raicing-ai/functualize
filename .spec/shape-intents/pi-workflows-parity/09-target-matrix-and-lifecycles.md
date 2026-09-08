# 09 · Target surface matrix & lifecycles

What the command / flag / MCP surface should look like when the roadmap in
[07](07-roadmap.md) lands, and what using it feels like. Grounded in
[01](01-surface-inventory.md) (what exists), [08](08-handoff-critique.md) (what the
in-flight handoff gets wrong), and the state-machine defects in §1.

---

## 0. The organising rule

Three layers, three actors, one naming rule.

| Layer | Who acts | Contract | Spelling |
|---|---|---|---|
| **Record** | a *second actor* — a human elsewhere, a reviewer, CI, an agent with no runner | **never advances the walk** | `func builtin workflow <verb>` · MCP tool |
| **Invocation** | the *invoker* — whoever owns this process | **advances the walk in-process** | `--wf-*` flag on the `@workflow` job |
| **Execution** | the caller starting or driving a run | starts, or continues to the next boundary | `func <wf>` · MCP `run_job` |

**The naming rule: `deposit` never advances; `resume` always advances.**

Today both spellings say "resume" and mean opposite things — `func builtin workflow
resume` deposits, `func <wf> --scope-id` advances. The previous study noticed the
collision and chose to live with it. Don't: the repo is pre-release
(`.spec/CONSTITUTION.md:176-179`), and the fix is a rename that preserves every contract.

> **Deviation flagged.** The handoff's decision 3 says *"`func builtin workflow resume` is
> NOT retired."* Renaming is not retiring — the deposit-only contract, the shared
> `deposit_gate_input` implementation, and the CLI↔MCP mirror all survive. But it is a
> deviation from a stated binding decision, so it needs your explicit yes.

---

## 1. Fix the state machine first — three defects

Verified: **no deposit path writes scope status.** The only writers are the walker
(`workflow_walker.py:223,327,347,450`, `frontier.py:105,158,190`) and `cancel`
(`builtins.py:948`, `_workflow_tools.py:446`).

### D-1 · "Answered, awaiting re-entry" has no name

Depositing sets `gates[name].payload` and nothing else. The scope stays `blocked` and
`pending_gates` becomes `[]`. So `workflow list` shows:

```
a3f9c2e1b7d4  release-pipeline  blocked  gates: -
```

— which reads as *"stuck, cause unknown"* and is actually *"answered, ready to go, just
needs someone to re-enter the walk."* That is the single most common state in a
two-actor flow and nothing names it.

### D-2 · A resumed walk reports `blocked` for its entire duration

`FrontierWalk.start` sets `RUNNING` **only when there is no persisted position**
(`frontier.py:103-106`). Every resume returns early. So a scope actively executing a
long step reports `blocked`, and `list` cannot distinguish "running right now" from
"waiting for you".

### D-3 · `cancelled` is not terminal

Nothing in the execution path reads it ([01 §C.3](01-surface-inventory.md)).

### Target status model

`status` stays the stored field; add `state` as a **derived** value the projection
computes — no new stored field, no `STATE_VERSION` bump:

| Derived `state` | Derivation | Means |
|---|---|---|
| `running` | status `running`, **or** status `blocked` and a live claim exists (Tier 2) | executing now |
| `waiting` | status `blocked` **and** `pending_gates` non-empty | needs an answer |
| `ready` | status `blocked` **and** `pending_gates` empty **and** no epilogue | answered — needs re-entry |
| `completed` | status `completed`, epilogue ok | done |
| `stalled` | status `completed`, epilogue `failed` | the sticky-body case |
| `failed` | status `failed` | a step raised; re-entry re-runs it |
| `cancelled` | status `cancelled` | terminal — re-entry refused |

`ready` is the one that pays for itself immediately: it is exactly the set
`--wf-resume` can advance without input, and exactly what a scheduler polls for.

D-2 needs one line (`set_scope_status(RUNNING)` on re-entry) but is only *honest* once a
lease exists — until then a crashed walk stays `running` forever. **Recommendation:**
ship `waiting`/`ready` now (pure derivation, zero risk); defer `running`-vs-`blocked`
accuracy to the Tier-2 runner, and until then render it `resumed` rather than lying.

---

## 2. The target matrix

Legend: **have** · **fix** (exists, wrong) · **new** · **lift** (exists elsewhere, share it) · *(T2)* Tier 2.

### 2.1 Record layer — `func builtin workflow` ↔ MCP

One shared implementation per row. This is the parity the previous study *asserted* and
this table makes true.

| Verb | CLI builtin | MCP tool | Class | Status |
|---|---|---|---|---|
| list scopes | `list [--workflow N] [--state waiting\|ready\|running\|all] [--blocked-on G] [--format table\|json]` | `list_workflows(workflow_name?, state?, blocked_on?)` | Obs | **fix** + **new** filters |
| inspect one | `show <id> [--fields …] [--format]` | `get_workflow_state(workflow_id)` | Obs | **lift** `_describe` |
| deposit input | `deposit <id> <gate> [--input JSON] [--set K=V] [--unset K] [--replace] [--show] [--commit/--no-commit]` | `deposit_gate(workflow_id?, gate?, values, mode, commit)` | Ctl | **new** (rename of `resume`) |
| reopen an answer | `deposit <id> <gate> --reopen` | `deposit_gate(..., reopen=true)` | Ctl | **new** |
| run a gate tool | `gate-tool <id> <tool> [--args JSON]` | `call_gate_tool(workflow_id, tool, args)` | Ctl | **lift** (MCP-only today) |
| cancel | `cancel <id>` | `cancel_workflow(workflow_id)` | Ctl | **fix** — make terminal |
| purge finished | `purge [--older-than D] [--state completed,failed,cancelled]` | `purge_workflows(...)` | Mgmt | **new** |

**`deposit_gate` replaces both `resume_gate` and `resume_workflow`.** Today neither
accepts `(workflow_id, gate)` together and each refers the caller to the other on
ambiguity — the addressing hole in [01 §C.5](01-surface-inventory.md). One tool with both
optional, each inferred when unambiguous, closes it and matches the CLI's arity.

### 2.2 Invocation layer — flags on a `@workflow` job

All `--wf-` prefixed, all per-command Click options, added at the **two** injection points
(`click_params.py:1233`, `lazy_command.py:168`) — not three ([08 §E-1](08-handoff-critique.md)).

| Flag | Class | Advances? | Status |
|---|---|---|---|
| `--scope-id <id>` (pre-command global **and** per-command) | Ctl | yes | **have** — keep both; the global is the only spelling guaranteed on every dispatch mode |
| `--wf-resume [id]` | Ctl | yes | **new** — no id ⇒ the workflow's one advanceable scope |
| `--wf-input JSON` / `--wf-set K=V` | Ctl | yes | **new** — validate + deposit + continue, one process |
| `--wf-gate NAME` | Ctl | — | **new** — disambiguates when several gates pend |
| `--wf-status` [`--wf-waiting-only`\|`--wf-all`] | Obs | **no** | **new** — this workflow's scopes, then exit 0 |
| `--wf-retry-epilogue` | Ctl | yes | **new** — clears a `stalled` epilogue record and re-fires the body |
| `--wf-no-epilogue` / `--wf-epilogue-only` | Ctl | yes | **new** — power-user; low priority |
| `--prompt-gates` / `--force` | Ctl | yes | **have** |
| `--wf-watch` | Obs | — | *(T2)* — needs the event log |

**Cut from this layer:** `--wf-retry-failed` (failed steps already re-run on resume —
[02 §9](02-corrections.md)), `--wf-actor` and every time column (no timestamps in state —
[01 §C.6-C.7](01-surface-inventory.md)), `--fresh` (absence already means new).

**Ambiguity rule, everywhere:** zero → error naming `--wf-status`; exactly one → use it;
several → list them and exit 2. Never "newest wins" — that is silently picking, and
`blocked_at` resets on every re-block so it is not computable anyway.

### 2.3 Execution layer — MCP

| Tool | Change | Why |
|---|---|---|
| `run_job(name, config, scope_id?)` | **fix**: return `metadata`; **new**: accept `scope_id` | The single largest agent gap. Three return dicts + one parameter. |
| `run_job_async(...)` / `get_execution_status` | **fix**: return `metadata` | Same defect, async door |
| per-job tools (`_execute_job`) | **fix**: return `metadata`, normalize `RunStatus` | Two doors currently disagree on `status`'s shape |
| per-job tool registration | **new**: `MCPConfig.job_tools: all\|tagged\|none` | Context bloat — [03 §3](03-mcp-assessment.md) |
| `submit_step` / `get_workflow_step` | *(T2)* | The agent-step port — [06 §1](06-pi-workflows-model.md) |

`run_job` gaining `scope_id` is what lets an agent **continue** a walk. It is the MCP
mirror of `--wf-resume`, and it is one parameter threaded to an argument
`app.execute` already takes.

### 2.4 The matrix, collapsed

| | Control | Observability | Management |
|---|---|---|---|
| **CLI builtin** (record, never advances) | `deposit`, `gate-tool`, `cancel` | `list`, `show` | `purge` |
| **Job flags** (invocation, advances) | `--scope-id`, `--wf-resume`, `--wf-input/--wf-set`, `--wf-gate`, `--wf-retry-epilogue`, `--prompt-gates`, `--force` | `--wf-status` | — |
| **MCP** (both) | `deposit_gate`, `call_gate_tool`, `cancel_workflow`, `run_job(scope_id=…)` | `list_workflows`, `get_workflow_state` | `purge_workflows` |

Every observability cell is the **same lifted projection**. Every deposit cell is the
**same `deposit_gate_input`**. That is the whole architectural claim.

---

## 3. Lifecycles

### L1 · Human, one actor — the common case

```bash
$ func release-pipeline --env prod
Blocked: gate 'approval' in scope 'a3f9c2e1b7d4' awaits input.
  Continue with: ./main.py release-pipeline --wf-resume a3f9c2e1b7d4 --wf-input '{...}'
$ echo $?
5
```

*(exit 5 + scope id on stderr already works today — `click_params.py:909-940`.)*

```bash
$ func release-pipeline --wf-status
SCOPE         STATE    POSITION  GATES
a3f9c2e1b7d4  waiting  approve   approval
  approval expects: {"approved": bool, "reason": str}

$ func release-pipeline --wf-resume --wf-input '{"approved": true, "reason": "SRE ok"}'
✓ approval accepted · continuing a3f9c2e1b7d4
  deploy … ok
  smoke  … ok
released
```

`running → waiting → running → completed`. **One command replaces today's two**, and
`--wf-resume` needs no id because exactly one scope is advanceable.

### L2 · Agent over MCP — today vs. target

**Today (broken):**

```
run_job("release-pipeline", {"env":"prod"})
  → {"status": "Blocked", "return_value": null, "duration_ms": 812}
```

No scope id. The agent calls `list_active_workflows()`, gets *every* live scope in the
project, and guesses. Then `resume_gate("approval", {...})` deposits — and returns a
**shell command** the agent cannot run. Dead end; a human must go to a terminal.

**Target:**

```
run_job("release-pipeline", {"env":"prod"})
  → {"status":"blocked","metadata":{"workflow_scope":"a3f9c2…","state":"waiting",
      "blocked_on":"approval","input_schema":{…}}, "duration_ms":812}

deposit_gate(workflow_id="a3f9c2…", gate="approval",
             values={"approved":true,"reason":"SRE ok"})
  → {"status":"input_accepted","state":"ready"}

run_job("release-pipeline", scope_id="a3f9c2…")
  → {"status":"success","return_value":"released"}
```

Three calls, no human, no shell. The whole change is *return the metadata* and *accept
`scope_id`*.

### L3 · Two actors — the case the record layer exists for

```
agent  : run_job("release-pipeline", {...})        → waiting, scope a3f9c2…
agent  : (tells the human: approval needed, here is the schema)
human  : func builtin workflow deposit a3f9c2 approval --input '{"approved":true,…}'
         → accepted · state: ready
cron   : func release-pipeline --wf-resume a3f9c2   → completed
```

Three different actors, three different surfaces, one scope. **The `ready` state is what
makes this schedulable** — a cron job asks `list --state ready` and advances everything
in it, with no knowledge of who answered or why.

### L4 · Incremental fill — the `deposit` proposal in motion

A gate whose model has four fields owned by two people:

```bash
# SRE fills their half
$ func builtin workflow deposit a3f9c2 approval --set approved=true --set risk='"low"'
draft saved · still missing: reason (string), ticket (string)

# Release manager fills theirs, hours later
$ func builtin workflow deposit a3f9c2 approval --set reason='"Q3 cutover"' --set ticket='"REL-914"'
draft complete · validated · approval accepted · state: ready
```

`--show` at any point prints draft + schema + `missing` + `invalid`. Nothing reaches the
walker until the model validates whole — the invariant from
[04](04-gate-deposit.md): **`payload` is only ever written as a complete `model_dump()`.**

State stays `waiting` throughout, then flips to `ready` on the commit.

### L5 · Correction before consumption

```bash
$ func builtin workflow deposit a3f9c2 approval --show
approval: {"approved": true, "reason": "SER ok"}     ← typo, already committed

$ func builtin workflow deposit a3f9c2 approval --reopen
payload moved to draft · state: waiting

$ func builtin workflow deposit a3f9c2 approval --set reason='"SRE ok"'
draft complete · validated · state: ready
```

Guarded: `--reopen` **refuses** once the walk has consumed the answer (scope position
past the gate), because recorded downstream results were derived from the old value.
The error names the position and points at a fresh run. Today this whole flow requires
hand-editing `state.json`.

### L6 · Failure — two different shapes

```bash
$ func release-pipeline --wf-resume a3f9c2
  deploy … FAILED  ConnectionError: registry unreachable
$ echo $?; # 1 — state: failed
```

**A failed step is not sticky.** The record is `status: "failed"`, and replay only skips
`success`, so re-entry re-runs it:

```bash
$ func release-pipeline --wf-resume a3f9c2    # registry is back
  deploy … ok
  smoke  … ok
released
```

**A failed epilogue is sticky.** `record_body` writes on failure too and `prelude` treats
any epilogue record as done — so re-entry answers with the recorded failure forever:

```bash
$ func release-pipeline --wf-status
a3f9c2e1b7d4  stalled  (epilogue failed: PermissionError)

$ func release-pipeline --wf-resume a3f9c2 --wf-retry-epilogue
✓ epilogue cleared · re-running body against recorded step values
released
```

This is why `--wf-retry-epilogue` is the recovery primitive worth building and
`--wf-retry-failed` is not.

### L7 · Cancel, once it means something

```bash
$ func builtin workflow cancel a3f9c2
Cancelled a3f9c2e1b7d4 (was: waiting at approve).

$ func release-pipeline --wf-resume a3f9c2
Error: scope 'a3f9c2e1b7d4' is cancelled and cannot be resumed.
       Start a new run, or inspect it with: func builtin workflow show a3f9c2e1b7d4
$ echo $?; # 2
```

Today this resumes silently to completion while the MCP tool's own description says it
cannot. Three lines in `prelude`.

### L8 · Tier 2 — the agent step

Once the executor port lands ([06 §1](06-pi-workflows-model.md)), the agent stops being a
caller and becomes the executor:

```
run_job("triage", {...})
  → {"status":"awaiting_step","metadata":{"workflow_scope":"7f01…","request_id":"step-7f01-2",
      "node":"classify","prompt":"…","expected_output":{…},"allowed_tools":["read_file"]}}

  (the agent does the work with its own context and tools)

submit_step(request_id="step-7f01-2", output={"severity":"p2","owner":"platform"})
  → {"status":"accepted","next":{"request_id":"step-7f01-3","node":"draft_fix", …}}
```

Rejection returns the validation error with the **same** `request_id` still pending, and
the agent retries in place. The engine **refuses** a workflow declaring
`allowed_tools` when the executor cannot enforce them, rather than degrading — that is
the capability-flag discipline worth copying verbatim.

---

## 4. Sequencing this matrix onto the roadmap

| Roadmap item | Matrix rows it delivers |
|---|---|
| 0 — state erasure | *(none — a precondition; item 4 touches the same envelope)* |
| 1 — return `metadata` | L2 target, half of §2.3 |
| 2 — enforce `cancel` | L7, `cancelled` terminal in §1 |
| 3 — lift the projection | Every Obs cell; `waiting`/`ready` derivation; `--wf-status`; `show` |
| 4 — `deposit` | L4, L5; the rename; MCP joint addressing |
| 5 — `--wf-resume` | L1, L3, L6; `run_job(scope_id=…)` |
| 6 — trim MCP tools | §2.3 last row |
| 7 — the port | L8 |

Two rows have no roadmap home yet and are cheap: **`purge`** (management is empty today,
and without it `list` degrades as scopes accumulate) and **`gate-tool` on the CLI** (a
lift, MCP-only for no reason).

## 5. What this matrix deliberately does not add

- **`pause`.** Nothing runs long enough to pause without a runner; it belongs with Tier 2.
- **Cross-project listing.** Wants one indexed store — the fork
  [07 item 8](07-roadmap.md) reaches, not before.
- **Time columns and `--actor`.** No timestamps exist, and the gate-level `blocked_at`
  measures the last poke. Adding the columns before the state is dishonest UI.
- **A second viewer.** One renderer over the lifted projection. `--wf-watch` after the
  event log, and only then.
