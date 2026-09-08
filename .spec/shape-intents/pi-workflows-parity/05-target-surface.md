# 05 · The target surface

Three tiers, one vocabulary, one implementation per verb. What exists today is in
[01](01-current-state.md); the order to build this in is [13](13-roadmap.md).

---

## 1. Three tiers, by actor

Each surface serves a different actor, and that decides every inclusion question without
case-by-case argument:

| Tier | Surface | Serves | Knows |
|---|---|---|---|
| **1 — rich** | `func builtin workflow …` | anyone operating **any** run: a second actor, an operator, CI, a scheduler | nothing; every target is explicit |
| **2 — parity** | MCP tools | an agent doing the same | same |
| **3 — convenience** | `--wf-*` flags on the job | the invoker about to run **this** workflow | **which workflow it is** |

Tier 1 is the superset. Tier 2 matches it verb for verb. Tier 3 is a strict subset — not
a separate design.

### 1.1 The inclusion test for tier 3

The job command's one unique piece of knowledge is *which workflow*. A verb earns a
`--wf-*` flag only if:

- **the workflow is implied** — the flag saves you naming it, **and**
- **the scope is inferable or already in hand** — one advanceable scope, or an id you
  just read off the blocked output, **and**
- **it is what the invoker wants** — someone holding this job command intends to *run*
  it, not to audit somebody else's runs.

Everything failing that test is tier 1 only. That is why answer-only, `--reopen`,
incremental `--set` drafts, `gate-tool`, `cancel`, `purge` and cross-workflow filtering
never reach the job: each needs an explicit target, or serves an actor who does not have
this job command in hand.

---

## 2. The matrix

Legend: ● full · ◐ convenience form · — absent by design · *(T2)* later tier.

| Operation | Tier 1 · `builtin workflow` | Tier 2 · MCP | Tier 3 · `--wf-*` |
|---|---|---|---|
| **start** | — (the job's role) | ● `run_job(name, config)` | ● `func <wf> [config…]` |
| start under a chosen id | — | ● `run_job(…, run_id=)` | ◐ `--wf-run-id <id>` |
| **resume** (advance) | ● `resume <id> [--input] [--gate] [--set]` | ● `resume_workflow(id, input?, gate?)` | ◐ `--wf-resume [id]` |
| answer + resume in one | ● `resume <id> --input '{…}'` | ● `resume_workflow(id, input=…)` | ◐ `--wf-resume [id] --wf-input '{…}'` |
| **answer** (record only) | ● `answer <id> <gate> [--input\|--set] [--show] [--commit/--no-commit]` | ● `answer_gate(id?, gate?, values, mode, commit)` | — |
| correct an answer | ● `answer <id> <gate> --reopen` | ● `answer_gate(…, reopen=true)` | — |
| survey runs | ● `list [--workflow N] [--state S] [--blocked-on G] [--tree] [--format]` | ● `list_workflows(workflow_name?, state?, blocked_on?)` | ◐ `--wf-status` (this workflow) |
| inspect one run | ● `show <id> [--fields] [--format]` | ● `get_workflow_state(id)` | ◐ `--wf-show [id]` — same full projection |
| run a gate tool | ● `gate-tool <id> <tool> [--args]` | ● `call_gate_tool(id, tool, args)` | — |
| retry a stalled epilogue | ● `resume <id> --retry-epilogue` | ● `resume_workflow(id, retry_epilogue=true)` | ◐ `--wf-retry-epilogue` |
| epilogue control | ● `resume <id> --no-epilogue \| --epilogue-only` | ● same params | — |
| cancel | ● `cancel <id>` | ● `cancel_workflow(id)` | — |
| purge finished | ● `purge [--older-than] [--state]` | ● `purge_workflows(…)` | — |
| watch live | ● `watch <id>` *(T2)* | — *(a stream, not a tool)* | ◐ `--wf-watch` *(T2)* |

### 2.1 Tier 3, as it appears on `--help`

Nine flags, every one *this workflow, right now*:

```
  --wf-resume [ID]     Advance a scope of this workflow (the only advanceable one
                       if ID is omitted). Walks in this process.
  --wf-input JSON      Gate input for --wf-resume: validated, recorded, then the
                       walk advances.
  --wf-gate NAME       Which pending gate --wf-input answers (when several).
  --wf-status          List this workflow's scopes, then exit 0.
  --wf-show [ID]       Full projection of one scope — graph, position, per-step
                       results and inputs, gate schemas — then exit 0.
  --wf-retry-epilogue  With --wf-resume: clear a stalled epilogue and re-fire it.
  --wf-run-id ID       Start under a caller-chosen scope id (idempotent start).
  --wf-watch           Render the walk's position until it settles.        (T2)
```

Gated to `@workflow` jobs, so a plain `@job`'s `--help` is unchanged.

**`--wf-show` renders the same full projection as `builtin workflow show`.** The flag
saves naming the workflow; it does not reduce the output. A reduced form would recreate
the split [01 §C.2](01-current-state.md) documents, where one surface knows the graph and
the other prints five fields.

### 2.2 `--scope-id` is replaced, both spellings

`--wf-resume` is strictly more capable:

| | `--scope-id X` | `--wf-resume [X]` |
|---|---|---|
| Advance a named scope | yes | yes |
| Omit the id when unambiguous | no | **yes** |
| Fuse gate input | no | **yes** (`--wf-input`) |
| Unknown id | **silently starts a new run under it** | **errors** |
| Pre-command spelling | yes (a category error — [12](12-scope-id.md)) | no |

That fourth row is a defect fix. Verified:

```
$ func trip-planner --scope-id my-own-chosen-id-001 ; echo $?
5
$ func builtin workflow list
my-own-chosen-id-001  trip-planner  blocked  gates: preferences
```

`WorkflowRunner.__init__` does `scope_id or new_scope_id()` and `FrontierWalk.start` calls
`ensure_scope`, so **a typo'd id silently becomes a phantom run**. Splitting *start under
an id* (`--wf-run-id`) from *advance an id* (`--wf-resume`, which requires the scope to
exist) fixes that while preserving idempotent start — a capability that exists today only
as a side effect of the flag's double duty. **`--wf-run-id` is O5, the one open
question.**

`--wf-*` are ordinary post-boot Click options, so they never enter
`_GLOBAL_OPTIONS_ALWAYS_VALUE` and cannot reproduce the cold-cache hazard that removing
the early-parse flag closes.

### 2.3 The vocabulary

> **`answer` records. `resume` advances.** One meaning each, on every surface.

`answer <id> <gate>` fills a gate's payload slot and never runs anything. `resume <id>`
walks to the next durable boundary. Two verbs, distinct contracts, **no aliases**.

Three reasons this is the right assignment, not an arbitrary pick:

1. **The repository already says so.** `docs/guides/mcp.md:55` describes
   `resume_workflow` as *"Advance a paused workflow"*, `:200` says the workflow
   *"resumes when the AI agent calls `resume_workflow`"*, and
   `docs/guides/workflows.md:247` says *"deposit gate input **and advance**"*. The code
   only deposits — `_workflow_tools.py:21-24` is explicit that it reports
   `input_accepted` *"not `resumed` — because nothing has run yet"*. Two guides written
   by people who knew this system reached for the universal meaning. **The code moves to
   match the docs.**
2. **Every peer system agrees.** Temporal, pi-workflows (`resumeRun`), LangGraph
   (`Command(resume=…)`) and Argo all use `resume` = advance.
3. **It removes the collision instead of managing it.** No docstring rule, no grep test,
   no alternative spelling for the flag.

`answer` over `deposit` for the record verb: it is pi-workflows' word for the same
operation, and `deposit` is already overloaded three ways internally —
`deposit_gate_payload` (store write), `deposit_gate_input` (validate + write), and
`cli.py:400 _deposit` (group option values, unrelated to gates). `deposit_gate_input`
stays as the internal function name: accurate about mechanism, where `answer` is accurate
about intent.

---

## 3. Derived run state

`status` stays the stored field. Add `state` as a **derived** value the projection
computes — no new stored field, no `STATE_VERSION` bump:

| Derived `state` | Derivation | Means |
|---|---|---|
| `running` | status `running`, or `blocked` with a live claim *(T2)* | executing now |
| `waiting` | status `blocked` **and** pending gates | needs an answer |
| `ready` | status `blocked`, **no** pending gates, no epilogue | answered — needs `resume` |
| `completed` | status `completed`, epilogue ok | done |
| `stalled` | status `completed`, epilogue `failed` | the sticky-body case |
| `failed` | status `failed` | a step raised; `resume` re-runs it |
| `cancelled` | status `cancelled` | terminal — `resume` refused |

`ready` pays for itself immediately: it is exactly the set `resume` can advance without
input, and exactly what a scheduler polls for. It also fixes the unnamed state
[01 §C.6](01-current-state.md) records, where an answered scope reads `blocked` with no
pending gates and looks stuck.

Accuracy caveat: a resumed walk currently reports `blocked` for its whole duration
(`FrontierWalk.start` sets `RUNNING` only on first entry). Ship `waiting`/`ready` now —
pure derivation, zero risk — and defer `running`-vs-`blocked` accuracy to the tier-2
lease, rendering it `resumed` rather than lying in the meantime.

---

## 4. The parity contract

Parity between CLI and MCP was *asserted* before and was false: today's `resume` takes
`(id, gate)` and no MCP tool takes both; `list`/`state` return different shapes
([02 §6](02-prior-study-corrections.md)). Stating it is not enough. Pin it:

1. **One implementation per verb**, in `app/` and re-exported through
   `functualize.app.utils` — the `deposit_gate_input` pattern, and the only arrangement
   `_cli` may legally import ([11 §1](11-boundaries.md)).
2. **Same addressing.** Every verb takes the same identifiers on both surfaces.
   `answer_gate(id?, gate?)` accepts **both**, each optional when unambiguous — which
   closes the hole where `resume_gate` and `resume_workflow` each referred the caller to
   the other.
3. **Same result shape.** `show` and `get_workflow_state` return the same projection;
   `list --format json` and `list_workflows` return the same rows.
4. **Same error codes.** `gate_not_found`, `ambiguous_gate`, `workflow_not_found`,
   `scope_cancelled` — one table, both surfaces.
5. **A parity test enumerates the verbs** and fails when either surface gains a verb or a
   parameter the other lacks. Without it, this drifts again.

### 4.1 The one honest exception

`--prompt-gates` resolves gates **interactively, inline**. MCP cannot: its gate strategy
is `ai_outbound`, which always blocks by design. So parity is on **verbs and their
contracts**, not on interactive capability — and this is the one place functualize is
ahead of pi-workflows, which deliberately never resolves protected decisions inline.
Document it rather than pretending.

---

## 5. Rules that hold across all three tiers

- **Ambiguity never guesses.** Zero candidates → error naming the survey verb; exactly
  one → use it; several → list them and exit 2. Never "newest wins" — that is silently
  picking, and `blocked_at` resets on every re-block so it is not computable anyway.
- **The blocked output is load-bearing.** With no `--scope-id`, "re-run the command you
  remember" is gone. Exit 5 must print the exact `resume` command, and `func <wf>` should
  note when a scope of that workflow is already waiting — a hint, never a refusal.
- **`cancelled` is terminal.** `resume` refuses it with exit 2 and points at a fresh
  start.
- **Tier 1 executes jobs.** `resume` walks a graph, which is a real boundary change for a
  group whose other verbs only read the store. It must route through the same funnel the
  MCP tools use (`_server.py:239-242`) so the gate-tool policy still applies.
- **Concurrency needs the lease.** Advancing without knowing the job makes concurrent
  `resume` one keystroke ([06 §L3](06-lifecycles.md)); the flock serializes writers but
  fences no stale walker.
