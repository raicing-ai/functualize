# 18 · The three-tier surface: rich record layer, MCP parity, job-flag convenience

**Supersedes** [16 §2.3](16-replacing-scope-id.md) and [17 §1-3](17-lifecycle-without-scope-id.md),
which deleted the job-side control surface entirely. That was an over-correction: it
solved the `--scope-id` problem by removing an affordance rather than by re-layering it.

The design constraint, as set:

1. **`func builtin workflow …` is the most feature-rich surface** — the superset.
2. **MCP has parity with it** — same verbs, same parameters, same errors.
3. **`--wf-*` flags on the job are a smaller convenience subset** — not a separate design.

---

## 1. The principle that decides what goes where

Each surface exists for a different actor, and that answers every inclusion question
without case-by-case argument:

| Surface | Serves | Knows |
|---|---|---|
| `builtin workflow` | **anyone operating any run** — a second actor, an operator, CI, a scheduler | nothing; everything is addressed explicitly |
| MCP | **an agent doing the same** | same as above |
| `--wf-*` on the job | **the invoker about to run *this* workflow** | **which workflow it is** |

The job command's one unique piece of knowledge is *which workflow*. So the convenience
subset is exactly the operations where "this workflow" plus an obvious scope is enough
information — and nothing else.

### The inclusion test

A verb belongs in the `--wf-*` subset if and only if:

- **the workflow is implied** — the flag saves you naming it, and
- **the scope is inferable or trivially given** — one advanceable scope, or an id you
  already have from the blocked output, and
- **it is what the invoker wants** — someone holding this job command intends to *run*
  it, not to audit somebody else's runs.

Everything failing that test lives only on the record layer. That is why `answer`
(deposit-only, the *second actor's* verb), `--reopen`, incremental `--set` drafts,
`gate-tool`, `cancel`, `purge` and cross-workflow filtering are record-only: each needs
an explicit target, or serves someone who does not have this job command in hand.

---

## 2. The matrix

Legend: ● full · ◐ convenience form · — absent by design.

| Operation | `builtin workflow` (rich) | MCP (parity) | `--wf-*` (subset) |
|---|---|---|---|
| **start** | — (that is the job's role) | ● `run_job(name, config)` | ● `func <wf> [config…]` |
| start under a chosen id | — | ● `run_job(…, run_id=)` | ◐ `--wf-run-id <id>` |
| **continue** | ● `continue <id> [--input] [--gate] [--set]` | ● `continue_workflow(id, input?, gate?)` | ◐ `--wf-continue [id]` |
| answer + continue in one | ● `continue <id> --input '{…}'` | ● `continue_workflow(id, input=…)` | ◐ `--wf-continue [id] --wf-input '{…}'` |
| answer only (no advance) | ● `answer <id> <gate> [--input\|--set] [--show] [--commit/--no-commit]` | ● `answer_gate(id?, gate?, values, mode, commit)` | — *second-actor verb* |
| correct an answer | ● `answer <id> <gate> --reopen` | ● `answer_gate(…, reopen=true)` | — |
| **survey runs** | ● `list [--workflow N] [--state S] [--blocked-on G] [--tree] [--format]` | ● `list_workflows(workflow_name?, state?, blocked_on?)` | ◐ `--wf-status` (this workflow only) |
| inspect one run | ● `show <id> [--fields] [--format]` | ● `get_workflow_state(id)` | ◐ `--wf-show [id]` |
| run a gate tool | ● `gate-tool <id> <tool> [--args]` | ● `call_gate_tool(id, tool, args)` | — |
| retry a stalled epilogue | ● `continue <id> --retry-epilogue` | ● `continue_workflow(id, retry_epilogue=true)` | ◐ `--wf-retry-epilogue` |
| epilogue control | ● `continue <id> --no-epilogue \| --epilogue-only` | ● same params | — |
| cancel | ● `cancel <id>` | ● `cancel_workflow(id)` | — |
| purge finished | ● `purge [--older-than] [--state]` | ● `purge_workflows(…)` | — |
| watch live | ● `watch <id>` *(T2)* | — *(stream, not a tool)* | ◐ `--wf-watch` *(T2)* |

### 2.1 The subset, as it appears on `--help`

Nine flags, and every one is *this workflow, right now*:

```
  --wf-continue [ID]      Continue a scope of this workflow (the only advanceable
                          one if ID is omitted). Advances the walk in this process.
  --wf-input JSON         Gate input for --wf-continue: validated, recorded, then
                          the walk continues.
  --wf-gate NAME          Which pending gate --wf-input answers (when several).
  --wf-status             List this workflow's scopes, then exit 0.
  --wf-show [ID]          Full state of one scope of this workflow, then exit 0.
  --wf-retry-epilogue     With --wf-continue: clear a stalled epilogue and re-fire it.
  --wf-run-id ID          Start under a caller-chosen scope id (idempotent start).
  --wf-watch              Render the walk's position until it settles.        (T2)
```

Still gated to `@workflow` jobs, so a plain `@job`'s `--help` is unchanged.

### 2.2 What happened to `--scope-id`

**Both spellings go, and `--wf-continue` is the replacement** — strictly more capable:

| | `--scope-id X` | `--wf-continue [X]` |
|---|---|---|
| Continue a named scope | yes | yes |
| Omit the id when unambiguous | no | **yes** |
| Fuse gate input | no | **yes** (`--wf-input`) |
| Unknown id | **silently starts a new run under it** | **errors** |
| Pre-command spelling | yes (the category error) | no |

That fourth row is a defect fix, not just a rename. Verified today:

```
$ func trip-planner --scope-id my-own-chosen-id-001 ; echo $?
5
$ func builtin workflow list
my-own-chosen-id-001  trip-planner  blocked  gates: preferences
```

`WorkflowRunner.__init__` does `scope_id or new_scope_id()` and `FrontierWalk.start`
calls `ensure_scope`, so **a typo'd id silently becomes a phantom run** instead of an
error. Splitting *start under an id* (`--wf-run-id`) from *continue an id*
(`--wf-continue`, which requires the scope to exist) fixes that, and preserves the
idempotent-start capability §2 of [17](17-lifecycle-without-scope-id.md) found would
otherwise be lost.

The early-parse removal from [15](15-scope-id-early-parse-removal.md) stands unchanged —
`--wf-*` are ordinary post-boot Click options on the job command, so they never touch
`_GLOBAL_OPTIONS_ALWAYS_VALUE` and cannot reproduce the cold-cache hazard.

### 2.3 Naming

`--wf-continue`, not `--wf-resume` — [14](14-resume-deposit-collisions.md)'s D1b, and it
matters *more* here than under the old design: the record layer keeps `resume` as a
deposit alias (D1), so the word must not also mean advance on the job. The vocabulary
ends up unambiguous:

> `answer`/`resume`/`deposit` **record**. `continue`/`--wf-continue` **advance**.

---

## 3. The parity contract, made testable

Parity was *claimed* between CLI and MCP before and was false — the CLI's `resume` takes
`(id, gate)`, no MCP tool takes both, and `list`/`state` returned different shapes
([02 §6](02-corrections.md)). Stating it is not enough; pin it:

1. **One implementation per verb**, in `app/` and re-exported through
   `functualize.app.utils` — the `deposit_gate_input` pattern, which is also the only
   arrangement `_cli` may legally import ([11 §1](11-core-plugin-boundaries.md)).
2. **Same addressing.** Every verb takes the same identifiers on both surfaces. MCP's
   `answer_gate(id?, gate?)` accepts *both*, each optional when unambiguous.
3. **Same result shape.** `show` and `get_workflow_state` return the same projection;
   `list --format json` and `list_workflows` return the same rows.
4. **Same error codes.** `gate_not_found`, `ambiguous_gate`, `workflow_not_found`,
   `scope_cancelled` — one table, both surfaces.
5. **A parity test enumerates the verbs** and fails when one surface gains a verb or a
   parameter the other lacks. Without it this drifts again.

### 3.1 The one honest parity exception

`--prompt-gates` resolves gates **interactively, inline**. MCP cannot: its gate strategy
is `ai_outbound`, which always blocks by design (`_gate/_strategy.py`,
`STRATEGY_PROVIDERS`). So parity is on **verbs and their contracts**, not on interactive
capability. Say so in the docs rather than pretending — and note it is the one place
functualize is ahead of pi-workflows, which deliberately never resolves protected
decisions inline.

---

## 4. The user experience, per tier

### 4.1 Tier 3 — the invoker (job flags): the fast path

```bash
$ func release-pipeline --env prod
Blocked: gate 'approval' in scope 'a3f9c2e1b7d4' awaits input.
  continue in one command:
      func release-pipeline --wf-continue --wf-input '{"approved": true, "reason": "…"}'
  or answer now and continue later:
      func builtin workflow answer a3f9c2e1b7d4 approval --input '{…}'
$ echo $?
5

$ func release-pipeline --wf-continue --wf-input '{"approved": true, "reason": "SRE ok"}'
✓ approval accepted · continuing a3f9c2e1b7d4
  deploy … ok
  smoke  … ok
released
```

**No id typed.** The workflow is implied by the command, and there is exactly one
advanceable scope. That is the whole point of the subset — and it is the affordance
[17](17-lifecycle-without-scope-id.md) threw away.

Ambiguity never guesses:

```bash
$ func release-pipeline --wf-continue
Error: 3 scopes of 'release-pipeline' can be continued. Name one:
  a3f9c2e1b7d4  waiting  at approve   gate: approval
  7f01cc9e2244  ready    at deploy    (answered)
  0c81b3a6f002  stalled  epilogue failed
$ echo $?
2
```

And the survey stays on the same command:

```bash
$ func release-pipeline --wf-status
SCOPE         STATE    POSITION  GATES
a3f9c2e1b7d4  waiting  approve   approval
7f01cc9e2244  ready    deploy    —
```

### 4.2 Tier 1 — the operator (record layer): everything, addressed explicitly

```bash
# cross-workflow survey — impossible from a job flag
$ func builtin workflow list --state waiting --blocked-on approval
a3f9c2e1b7d4  release-pipeline  waiting  approval   (2 pending gates)
b71ee0034a19  data-backfill     waiting  approval

# incremental answer by a second actor who has no job command in hand
$ func builtin workflow answer a3f9c2e1b7d4 approval --set approved=true
draft saved · still missing: reason (string)
$ func builtin workflow answer a3f9c2e1b7d4 approval --set reason='"Q3 cutover"'
draft complete · validated · state: ready

# investigate inside the paused gate
$ func builtin workflow gate-tool a3f9c2e1b7d4 check-quota
{"remaining": 812}

# nested runs
$ func builtin workflow list --tree
a3f9c2e1b7d4            release-pipeline  waiting:child  at deploy
  └ a3f9c2e1b7d4/deploy  deploy-service    waiting        gate: rollout-window
$ func builtin workflow continue a3f9c2e1b7d4/deploy --input '{"window":"02:00Z"}'
```

Everything here needs an explicit target or crosses workflows — which is exactly why none
of it belongs on a job flag.

### 4.3 Tier 2 — the agent (MCP): parity, two calls

```
run_job("release-pipeline", {"env":"prod"})
  → {"status":"blocked","metadata":{"workflow_scope":"a3f9c2…","state":"waiting",
      "blocked_on":"approval","input_schema":{…}}}

continue_workflow("a3f9c2…", input={"approved":true,"reason":"SRE ok"})
  → {"status":"success","return_value":"released"}
```

And because parity is real, the agent can also do everything tier 1 can — filter runs,
answer incrementally without advancing, call a gate tool, walk a child scope:

```
list_workflows(state="waiting", blocked_on="approval")
answer_gate(workflow_id="a3f9c2…", gate="approval", values={"approved":true}, commit=false)
call_gate_tool("a3f9c2…", "check-quota")
continue_workflow("a3f9c2…/deploy", input={"window":"02:00Z"})
```

### 4.4 The scheduler case, unchanged

```bash
func builtin workflow list --state ready --format json \
  | jq -r '.workflows[].workflow_id' | xargs -n1 func builtin workflow continue
```

Still works — advancing every ready run without knowing a job name is a *record-layer*
capability, and the job flags do not compete with it.

---

## 5. What each tier costs

| Tier | Cost |
|---|---|
| **Record layer** | The `workflow` group gains the right to execute a job (`continue`). It must route through the same funnel the MCP tools use (`_server.py:239-242`) so the gate-tool policy still applies. |
| **MCP** | The parity test (§3.5) is new machinery, and it is the only thing that keeps the claim true. |
| **Job flags** | Nine conditional Click options instead of one. They are ordinary post-boot options, so the cold-cache class stays closed — but each still needs the per-dispatch-mode test the repo demands for state-addressing flags (`main.py:2075-2081`). |

Concurrency still needs the lease (D1i): the `xargs` line makes concurrent `continue` one
keystroke, and nothing fences a stale walker today.

---

## 6. Decisions this changes

| # | Was | Now |
|---|---|---|
| D1g | replace `--scope-id` with a verb, delete the job surface | **revised** — three tiers; `--wf-continue` is the job-side replacement |
| D1j | no flag conditional on `@workflow` | **withdrawn** — nine are, deliberately; they are post-boot options, so the hazard class stays closed |
| D1k | `--run-id` as a start flag | **confirmed**, spelled `--wf-run-id`, and it now also fixes the phantom-run defect (§2.2) |
| D1b | `--wf-continue` over `--wf-resume` | **confirmed and strengthened** — the record layer keeps `resume` as a deposit alias |
| D2 | MCP `deposit_gate` with joint addressing | **generalized** — parity across every verb, with a test (§3) |

## 7. Open

| # | Question |
|---|---|
| **O6** | `answer`/`continue` or `deposit`/`resume` for the record verbs? Both survive per D1; which is *primary* decides the docs and the `--help` ordering. |
| **O7** | Does `--wf-show`/`--wf-status` render the full projection, or a summary with a pointer to `builtin workflow show`? Rendering budget question, not a contract one. |
