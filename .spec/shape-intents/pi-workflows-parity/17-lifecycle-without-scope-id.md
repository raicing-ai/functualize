# 17 · The lifecycle and usability matrix after `--scope-id` is dropped

Supersedes [09](09-target-matrix-and-lifecycles.md) §0, §2.2 and §2.4, which were written
under the `--wf-resume` design. The design here is D1g: **a scope is addressed by id
alone, so a verb replaces the flag.**

Verb spellings below use `answer` (record an answer) and `continue` (advance). If D1
is re-decided per [16 §1.1](16-replacing-scope-id.md) the pair becomes `deposit`/`resume`
— the matrix is unchanged, only the two words move.

---

> **Superseded by [18](18-three-tier-surface.md)** for §1-§3: the job command keeps a
> `--wf-*` convenience subset rather than becoming start-only. The lifecycles in §4, the
> costs in §5 and the capability finding in §5.2 all still hold — read them with
> `--wf-continue` available as the job-side shortcut.

## 1. The structural change: three layers collapse to two


[09 §0](09-target-matrix-and-lifecycles.md) had record / invocation / execution. Under
D1g the **invocation layer disappears as a control surface**:

| | Before (doc 09) | After |
|---|---|---|
| **Execution** — the job command | start, *and* resume via `--scope-id`/`--wf-resume` | **start only** |
| **Invocation** — `--wf-*` flags | continue, answer-and-continue, survey, retry | *gone* |
| **Record** — `builtin workflow` ↔ MCP | observe, answer, cancel | observe, answer, **continue**, retry, cancel, purge |

One sentence: **the job command starts runs; the `workflow` group operates them.**

That is a better split than the flag design, because it matches who actually acts. A
second actor — a scheduler, CI, a reviewer, an MCP agent — never knows which job produced
a scope, and now never needs to.

## 2. Every flag, accounted for

| Today / planned | After | Replaced by |
|---|---|---|
| `--scope-id` (pre-command global) | **deleted** | `continue <id>` |
| `--scope-id` (per-command on `@workflow`) | **deleted** | `continue <id>` |
| `--wf-resume [id]` | never built | `continue <id>` |
| `--wf-input JSON` | never built | `answer <id> <gate> --input` / `continue <id> --input` |
| `--wf-gate NAME` | never built | `answer <id> <gate>` — positional, so no disambiguation flag |
| `--wf-status` | never built | `list --workflow <name>` |
| `--wf-retry-epilogue` | never built | `continue <id> --retry-epilogue` |
| `--wf-no-epilogue` / `--wf-epilogue-only` | never built | `continue <id> --no-epilogue` / `--epilogue-only` |
| `--wf-actor` | never built | still blocked on provenance ([01 §C.6](01-surface-inventory.md)) |
| `--prompt-gates`, `--force`, `--output` | **unchanged** | they are global `func` options, not workflow control |

### 2.1 A workflow job's `--help` goes back to being a job's `--help`

```
# today
$ func trip-planner --help
Options:
  --city TEXT      City to check
  --days INTEGER   Days to forecast
  --scope-id TEXT  Resume the named workflow scope instead of starting a fresh one.
  --help

# after
$ func trip-planner --help
Options:
  --city TEXT     City to check
  --days INTEGER  Days to forecast
  --help
```

Identical to a plain `@job`. **No flag is conditional on the job being a `@workflow`
any more**, which deletes a whole mechanism: `_scope_id_option()`, both injection points
(`click_params.py:1233`, `lazy_command.py:168`), the `_declares_workflow(function)` and
`descriptor.workflow` gates, and the per-command-wins-over-pre-command precedence rule
(`click_params.py:1040-1042`).

That last deletion matters more than it looks. The documented cold-cache hazard
(`main.py:2075-2081`) exists *because* a state-addressing flag's presence depended on
discovery state. Remove the conditional flag and the hazard class goes with it.

---

## 3. The matrix

### 3.1 Record layer — `func builtin workflow` ↔ MCP, one implementation per row

| Verb | CLI | MCP | Class | Advances? |
|---|---|---|---|---|
| list | `list [--workflow N] [--state waiting\|ready\|running\|stalled\|all] [--blocked-on G] [--format]` | `list_workflows(workflow_name?, state?, blocked_on?)` | Obs | no |
| inspect | `show <id> [--fields …] [--format]` | `get_workflow_state(id)` | Obs | no |
| answer | `answer <id> <gate> [--input JSON \| --set K=V …] [--show] [--commit/--no-commit] [--reopen]` | `answer_gate(id, gate?, values, mode, commit)` | Ctl | **no** |
| **continue** | **`continue <id> [--input JSON] [--gate N] [--set K=V] [--retry-epilogue] [--no-epilogue] [--epilogue-only]`** | **`continue_workflow(id, input?, gate?)`** | Ctl | **yes** |
| gate tool | `gate-tool <id> <tool> [--args JSON]` | `call_gate_tool(id, tool, args)` | Ctl | no |
| cancel | `cancel <id>` | `cancel_workflow(id)` | Ctl | no |
| purge | `purge [--older-than D] [--state …]` | `purge_workflows(...)` | Mgmt | no |

`continue --input` fuses answer-and-advance in one command — what
[09 §L1](09-target-matrix-and-lifecycles.md) wanted from `--wf-resume --wf-input`, at the
record layer, with no job flag.

### 3.2 Execution layer

| Surface | Verb | Role |
|---|---|---|
| CLI | `func <workflow> [config…]` | **start** |
| MCP | `run_job(name, config)` | **start** |

`run_job` needs no `scope_id` parameter — continuing is `continue_workflow`.

### 3.3 Collapsed

| | Control | Observability | Management |
|---|---|---|---|
| **`builtin workflow`** | `answer`, `continue`, `gate-tool`, `cancel` | `list`, `show` | `purge` |
| **MCP** | `answer_gate`, `continue_workflow`, `call_gate_tool`, `cancel_workflow`, `run_job` | `list_workflows`, `get_workflow_state` | `purge_workflows` |
| **Job flags** | — (globals only) | — | — |

---

## 4. The UX

### L1 · Human, one actor

```bash
$ func release-pipeline --env prod
Blocked: gate 'approval' in scope 'a3f9c2e1b7d4' awaits input.
  1. answer the gate (records input; does not run the workflow):
       func builtin workflow answer a3f9c2e1b7d4 approval --input '{…}'
  2. then continue the run:
       func builtin workflow continue a3f9c2e1b7d4
  or do both at once:
       func builtin workflow continue a3f9c2e1b7d4 --input '{…}'
$ echo $?
5
```

```bash
$ func builtin workflow continue a3f9c2e1b7d4 --input '{"approved": true, "reason": "SRE ok"}'
✓ approval accepted · continuing a3f9c2e1b7d4
  deploy … ok
  smoke  … ok
released
```

**The blocked output is now the whole discovery mechanism**, so it has to be right — see
§5.1. Note it can finally offer the one-command form, because both halves live on the
same verb.

### L2 · Agent over MCP

```
run_job("release-pipeline", {"env": "prod"})
  → {"status":"blocked","metadata":{"workflow_scope":"a3f9c2…","state":"waiting",
      "blocked_on":"approval","input_schema":{…}}}

continue_workflow("a3f9c2…", input={"approved": true, "reason": "SRE ok"})
  → {"status":"success","return_value":"released"}
```

**Two calls.** Under the flag design it was three (`run_job` → `deposit` → `run_job` with
`scope_id`), and today it is impossible.

### L3 · Two actors, and the scheduler case this unlocks

```
agent  : run_job("release-pipeline", {...})                → waiting, a3f9c2…
human  : func builtin workflow answer a3f9c2 approval --input '{...}'   → state: ready
cron   : func builtin workflow list --state ready --format json \
           | jq -r '.workflows[].workflow_id' \
           | xargs -n1 func builtin workflow continue
```

That last line is the point. **A scheduler can advance every ready run without knowing a
single job name.** Under the flag design it would have to map each scope back to its
workflow and synthesise a different command per job.

### L4 · Incremental answer across two people

```bash
# SRE
$ func builtin workflow answer a3f9c2 approval --set approved=true --set risk='"low"'
draft saved · still missing: reason (string), ticket (string)

# release manager, hours later
$ func builtin workflow answer a3f9c2 approval --set reason='"Q3 cutover"' --set ticket='"REL-914"'
draft complete · validated · approval accepted · state: ready
```

State stays `waiting` throughout, flips to `ready` on commit. Nothing reaches the walker
until the model validates whole ([04](04-gate-deposit.md)).

### L5 · Correction before the walk consumes it

```bash
$ func builtin workflow answer a3f9c2 approval --show
approval: {"approved": true, "reason": "SER ok"}      ← typo, committed
$ func builtin workflow answer a3f9c2 approval --reopen
payload moved to draft · state: waiting
$ func builtin workflow answer a3f9c2 approval --set reason='"SRE ok"'
draft complete · validated · state: ready
```

`--reopen` refuses once the scope's position is past the gate.

### L6 · Failure — the two shapes

```bash
$ func builtin workflow continue a3f9c2
  deploy … FAILED  ConnectionError: registry unreachable      # state: failed, exit 1

$ func builtin workflow continue a3f9c2        # registry back — the step re-runs
  deploy … ok
  smoke  … ok
released
```

A failed **step** is not sticky. A failed **epilogue** is:

```bash
$ func builtin workflow list
a3f9c2e1b7d4  release-pipeline  stalled  (epilogue failed: PermissionError)
$ func builtin workflow continue a3f9c2 --retry-epilogue
✓ epilogue cleared · re-running body against recorded step values
released
```

### L7 · Cancel

```bash
$ func builtin workflow cancel a3f9c2
Cancelled a3f9c2e1b7d4 (was: waiting at approve).
$ func builtin workflow continue a3f9c2
Error: scope 'a3f9c2e1b7d4' is cancelled and cannot be continued.
       Start a new run:  func release-pipeline --env prod
$ echo $?
2
```

### L8 · Nested scopes become first-class — a synergy

Addressing by id alone means a child scope is addressable like any other. With D11's `/`
separator and `parent`/`mount` recorded:

```bash
$ func builtin workflow list --tree
a3f9c2e1b7d4          release-pipeline   waiting:child   at deploy
  └ a3f9c2e1b7d4/deploy  deploy-service   waiting         gate: rollout-window

$ func builtin workflow continue a3f9c2e1b7d4/deploy --input '{"window":"02:00Z"}'
✓ rollout-window accepted · continuing child, then the parent
released
```

Under the flag design this case was awkward — you had to run the *parent job* with the
*parent* scope and hope the child re-entered. Here the child is named directly. (The
parent still advances via re-entry; the verb just makes the addressing honest.)

### L9 · Finding the id — now the critical path

Three doors, and they must all work because there is no "re-run the command you
remember" fallback any more:

```bash
$ func builtin workflow list                       # everything live
$ func builtin workflow list --workflow release-pipeline --state waiting
$ func builtin workflow show a3f9c2 --format json  # graph, results, gate schemas
```

Plus the blocked output (L1) and, for agents, `metadata.workflow_scope` on the run result.

---

## 5. What this costs, and what needs deciding

### 5.1 Learnability: the muscle-memory path disappears

Today the recovery instinct is *"re-run the same command with `--scope-id`."* After this
change, continuing means running a **different command in a different namespace**. That is
a real cost, and the mitigations are not optional:

- The blocked stderr block must print the exact `continue` command (D1c — already needed).
- `func <workflow>` on a project with a live scope of that workflow should **say so**:
  *"note: 1 scope of 'release-pipeline' is waiting (a3f9c2…); this starts a new run.
  Continue instead with: func builtin workflow continue a3f9c2…"* — a hint, never a
  refusal.
- `func builtin workflow --help` must lead with `continue`, not bury it fifth.

### 5.2 A capability that would be silently lost — caller-chosen run ids

Verified: passing a **previously unknown** id creates the scope under it.

```
$ func trip-planner --scope-id my-own-chosen-id-001 ; echo $?
5
$ func builtin workflow list
my-own-chosen-id-001  trip-planner  blocked  gates: preferences
```

`WorkflowRunner.__init__` does `scope_id or new_scope_id()` and `FrontierWalk.start` calls
`ensure_scope`. So `--scope-id` today is really **start-or-continue under a caller-chosen
id** — Temporal's start-if-not-exists / dedup-key pattern, available for free. CI wants
one run per commit SHA; a scheduler wants one run per day; an agent wants not to start
twice.

`continue <id>` cannot express it — the scope must already exist. **Do not drop this
without a decision.** Three options:

| Option | Shape | Cost |
|---|---|---|
| **(a)** `func <wf> --run-id X` | one start-time flag returns, on the job | Reintroduces one job flag — but it is honestly a *start* parameter, not a control flag, and it is unconditional (any job could have a run id) |
| **(b)** `continue <id> --start-if-absent <workflow>` | one verb does both | Overloads `continue` with start semantics and needs the workflow name anyway, defeating §1 |
| **(c)** Defer | engine mints ids; callers correlate via the returned id / `metadata.workflow_scope` | Loses idempotent start. CI re-runs would duplicate runs |

**Recommendation: (a).** It keeps the split clean — *start* takes a run id, *control* takes
a scope id — and it is the one flag whose presence does not depend on the job being a
`@workflow`, so it reintroduces none of the machinery §2.1 deletes.

### 5.3 `builtin workflow` gains the right to execute a job

`list`/`show`/`cancel` read the store with no boot; `answer` boots only to materialize a
gate model. `continue` walks a graph — a genuine boundary change for that group. It must
route through the same funnel the MCP tools use (`_server.py:239-242`) so the gate-tool
policy and refusal machinery still apply.

### 5.4 Concurrency stops being theoretical

When advancing needs no job name, two actors will `continue` the same scope — L3's
`xargs` line makes it one keystroke. The flock serializes writers but fences no stale
walker ([02](02-corrections.md)). **D1i stands: the lease moves from Tier-2 nicety to a
prerequisite for shipping L3 as a documented pattern.**

---

## 6. Open

| # | Question |
|---|---|
| **O5** | §5.2 — caller-chosen run ids: `--run-id` on the job (recommended), overload `continue`, or defer? |
| **O6** | [16 §1.1](16-replacing-scope-id.md) — `answer`/`continue` or `deposit`/`resume`? Cheapest to settle before these verbs are named in code. |

Everything else in this document follows from D1g and the two prerequisites in D1h.
