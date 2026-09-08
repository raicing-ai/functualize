# 06 · Lifecycles

What using [05](05-target-surface.md) feels like, per actor. Nine walkthroughs, each
naming the state transitions it drives.

---

## L1 · Human, one actor — the fast path

```bash
$ func release-pipeline --env prod
Blocked: gate 'approval' in scope 'a3f9c2e1b7d4' awaits input.
  resume in one command:
      func release-pipeline --wf-resume --wf-input '{"approved": true, "reason": "…"}'
  or answer now and resume later:
      func builtin workflow answer a3f9c2e1b7d4 approval --input '{…}'
$ echo $?
5

$ func release-pipeline --wf-resume --wf-input '{"approved": true, "reason": "SRE ok"}'
✓ approval accepted · advancing a3f9c2e1b7d4
  deploy … ok
  smoke  … ok
released
```

`running → waiting → running → completed`. **No id typed** — the workflow is implied by
the command and there is exactly one advanceable scope. That is the whole point of tier 3.

Ambiguity never guesses:

```bash
$ func release-pipeline --wf-resume
Error: 3 scopes of 'release-pipeline' can be advanced. Name one:
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

## L2 · Agent over MCP — two calls

```
run_job("release-pipeline", {"env": "prod"})
  → {"status":"blocked","metadata":{"workflow_scope":"a3f9c2…","state":"waiting",
      "blocked_on":"approval","input_schema":{…}}}

resume_workflow("a3f9c2…", input={"approved": true, "reason": "SRE ok"})
  → {"status":"success","return_value":"released"}
```

Today this is **impossible** — `run_job` drops `metadata` so the agent never learns the
scope id, and no MCP tool advances a walk. Fixing the metadata passthrough
([13 item 1](13-roadmap.md)) is what makes the first call useful; `resume_workflow`
gaining advance semantics makes the second call terminal.

Because parity is real, the agent can also do everything tier 1 can:

```
list_workflows(state="waiting", blocked_on="approval")
answer_gate(workflow_id="a3f9c2…", gate="approval", values={"approved":true}, commit=false)
call_gate_tool("a3f9c2…", "check-quota")
resume_workflow("a3f9c2…/deploy", input={"window":"02:00Z"})
```

## L3 · Two actors, and the scheduler case

```
agent  : run_job("release-pipeline", {...})                    → waiting, a3f9c2…
human  : func builtin workflow answer a3f9c2 approval --input '{...}'   → state: ready
cron   : func builtin workflow list --state ready --format json \
           | jq -r '.workflows[].workflow_id' \
           | xargs -n1 func builtin workflow resume
```

That last line is the payoff of addressing by id alone: **a scheduler advances every
ready run without knowing a single job name.** The `ready` state
([05 §3](05-target-surface.md)) is what makes it pollable.

It is also why the lease matters — concurrent `resume` on one scope is now one keystroke,
and nothing fences a stale walker today.

## L4 · Incremental answer across two people

A gate whose model has four fields owned by two people:

```bash
# SRE fills their half
$ func builtin workflow answer a3f9c2 approval --set approved=true --set risk='"low"'
draft saved · still missing: reason (string), ticket (string)

# release manager, hours later
$ func builtin workflow answer a3f9c2 approval --set reason='"Q3 cutover"' --set ticket='"REL-914"'
draft complete · validated · approval accepted · state: ready
```

`--show` at any point prints the draft, the schema, and what is missing. State stays
`waiting` throughout and flips to `ready` on commit. Nothing reaches the walker until the
model validates whole — the invariant in [07](07-gate-answers.md).

## L5 · Correcting an answer before the walk consumes it

```bash
$ func builtin workflow answer a3f9c2 approval --show
approval: {"approved": true, "reason": "SER ok"}      ← typo, already committed

$ func builtin workflow answer a3f9c2 approval --reopen
payload moved to draft · state: waiting

$ func builtin workflow answer a3f9c2 approval --set reason='"SRE ok"'
draft complete · validated · state: ready
```

`--reopen` **refuses** once the scope's position is past the gate: recorded downstream
results were derived from the old value, so the error names the position and points at a
fresh run. Today this whole flow requires hand-editing `state.json`.

## L6 · Failure — two different shapes

A failed **step** is not sticky. The record is `status: "failed"` and replay only skips
`success`, so re-entry re-runs it:

```bash
$ func builtin workflow resume a3f9c2
  deploy … FAILED  ConnectionError: registry unreachable     # state: failed, exit 1

$ func builtin workflow resume a3f9c2          # registry back
  deploy … ok
  smoke  … ok
released
```

A failed **epilogue** is sticky — `record_body` writes on failure too and `prelude`
treats any epilogue record as done, so re-entry answers with the recorded failure forever:

```bash
$ func builtin workflow list
a3f9c2e1b7d4  release-pipeline  stalled  (epilogue failed: PermissionError)

$ func builtin workflow resume a3f9c2 --retry-epilogue
✓ epilogue cleared · re-running body against recorded step values
released
```

This asymmetry is why `--retry-epilogue` is the recovery primitive worth building and a
step-level retry flag is not.

## L7 · Cancel

```bash
$ func builtin workflow cancel a3f9c2
Cancelled a3f9c2e1b7d4 (was: waiting at approve).

$ func builtin workflow resume a3f9c2
Error: scope 'a3f9c2e1b7d4' is cancelled and cannot be advanced.
       Start a new run:  func release-pipeline --env prod
$ echo $?
2
```

Today this advances silently to completion while the MCP tool's own description says it
cannot ([01 §C.3](01-current-state.md)).

## L8 · Nested scopes, addressed directly

With the `/` separator and `parent`/`mount` recorded ([09](09-nesting.md)):

```bash
$ func builtin workflow list --tree
a3f9c2e1b7d4            release-pipeline  waiting:child  at deploy
  └ a3f9c2e1b7d4/deploy  deploy-service    waiting        gate: rollout-window

$ func builtin workflow resume a3f9c2e1b7d4/deploy --input '{"window":"02:00Z"}'
✓ rollout-window accepted · advancing the child, then the parent
released
```

Today the parent records **no gate at all** when blocked on a child's gate, so the state
is indistinguishable from "answered, awaiting re-entry" and `resume_workflow(parent)`
replies with the self-contradiction *"no gate awaiting input (status: blocked)"*.

## L9 · Finding the id

Three doors, and they all matter because there is no "re-run the command you remember"
fallback:

```bash
$ func builtin workflow list                       # everything live
$ func builtin workflow list --workflow release-pipeline --state waiting
$ func builtin workflow show a3f9c2 --format json  # graph, results, gate schemas
```

Plus the blocked output (L1), the per-workflow shortcut (`--wf-status`), and for agents
`metadata.workflow_scope` on the run result.

---

## Learnability, stated plainly

Today the recovery instinct is *"re-run the same command with `--scope-id`."* After this
change the fast path is still on the job command (`--wf-resume`), so that instinct
survives — which is the main reason tier 3 exists rather than routing everything through
`builtin workflow`. Three mitigations are still not optional:

- exit 5 prints the exact `--wf-resume` command (L1);
- `func <wf>` on a project with a waiting scope of that workflow says so, as a hint;
- `func builtin workflow --help` leads with `resume` and `answer`, not with `list`.
