# 16 — The skill compiler: prose procedure → workflow with AI gates

*"A functualize skill that can turn any skill into a more deterministic and
hermetic functualize workflow, with outbound / inbound AI gates for steps
that need intelligence."*

The finding that reframes this page: **the compile target already exists and
is complete in functualize 0.2.3.** `Gate`, `Step`, `ConditionalEdge`,
`BLOCKED`, schema publication, deposit-and-resume, and the strategy names
`ai_inbound` / `ai_outbound` all ship today, verified end to end in
`evidence/probe_16_workflow_gates.py`. Nobody has to design the IR. What is
missing is the **compiler** — and the compiler is a skill.

---

## 1. The compile target, verified [probed]

```python
class Triage(BaseModel):
    severity: str
    owner: str
    rationale: str

@workflow(
    steps=[
        Step(collect),
        Gate(name="triage", awaits=Triage, tools=[collect], strategy="ai_outbound"),
        Step(apply_label),
    ],
    edges=[Edge("collect", "triage"), Edge("triage", "apply_label"),
           Edge("apply-label", END)],
)
def triage_issue() -> None:
    """Epilogue: runs when the walk reaches END."""
```

Running it:

```
[collect] ran
status: RunStatus.BLOCKED
blocked_on: triage
workflow_scope: triage_issue-4c98d7b5
workflow_status: blocked
```

The deterministic step ran. The judgment step stopped the walk and published
its contract:

```json
{"title": "Triage", "type": "object",
 "properties": {"severity": {"type": "string"}, "owner": {"type": "string"},
                "rationale": {"type": "string"}},
 "required": ["severity", "owner", "rationale"]}
```

An agent deposits a conforming payload — `func builtin workflow resume <id>`,
or the MCP `resume_gate` tool, both routed through **one** implementation
(`app/_workflow_resume.py`) — and the walk continues from where it stopped.

### The four gate mechanics that matter

| Mechanic | What it says | Source |
|---|---|---|
| `Gate.awaits: type[BaseModel]` | the intelligent step has a **typed contract**. Not "think about severity" — a schema that either validates or doesn't | `_types/workflow.py:257` |
| `Gate.tools: Sequence[ToolRef]` | jobs the agent may run *while* deciding — **"a permission, not a hint, enforced at MCP dispatch"**, capped at 50 | `_types/workflow.py:259` |
| `Tool(job, **pinned)` | pinned arguments are **removed from the schema the agent is shown**, so a forbidden call "is not merely refused, it is inexpressible" | `_types/workflow.py:140` |
| `Tool(job, arg=FromStep("setup"))` | the pin is **this walk's recorded output** of an earlier step — narrowing computed at runtime, not written at authoring time | `_types/from_job.py:246` |
| `ConditionalEdge` | the branch key is recorded on first evaluation and **replayed on resume**, so a paused walk cannot resume down a different branch | `_types/workflow.py:340` |

`Tool` narrowing is the sharpest of the four. A prose skill that says
*"refund up to $50, never more"* is a request. `Tool(issue_refund,
cap_cents=5_000)` means the agent is never shown a parameter it could
exceed. The instruction becomes a type.

### The two AI strategies are not symmetric [probed]

```python
def _gate_strategy_list(gate, prompt_gates):
    if declared == "ai_outbound":  return None                          # always block
    if declared == "ai_inbound":   return ["ai_inbound", "prompt", "resolve"]
```
`_engine/workflow_walker.py:456`

| Strategy | Shape | Ships where |
|---|---|---|
| `ai_outbound` | the workflow **stops**, publishes the schema, and waits. The agent is *outside*, driving — MCP, CLI, another process | **core.** It needs no resolver; blocking *is* the mechanism |
| `ai_inbound` | a resolver answers **in-process** and the walk never pauses. Falls back to `prompt` (ask a human), then `resolve` (config chain) | **`functualize-ai`** — `AIInboundGateResolver`, registered with two presets by `register_ai_inbound_gate_strategy(app, ai)` |

> **Correction (2026-09-05).** An earlier draft of this page said `ai_inbound`
> was "the name only, no shipped resolver." That was wrong: it greps clean in
> `src/functualize/` because the resolver lives in the workspace plugin
> `plugins/functualize-ai/src/functualize_ai/_gate_strategy.py`. You install
> it, you do not write it.

```python
class AIInboundGateResolver:
    def resolve(self, ctx: GateContext) -> BaseModel:
        if self._ai is None:
            raise AINotAvailableError("... pip install functualize-ai-pydantic ...")
        return self._ai.complete(_build_prompt(ctx), response_model=ctx.model_class)
```

`_build_prompt` hands the model the already-resolved fields as context and
asks only for the unresolved ones, using each field's type and `Field(
description=…)`. So **the pydantic model is simultaneously the prompt, the
parser, and the validator** — one declaration, no prompt engineering.

Two presets come with it — and `functualize-mcp` registers `ai_outbound` as a
real strategy plus a third preset:

| Preset | Registered by | Ladder |
|---|---|---|
| `"ai_inbound"` | `functualize-ai` | `ai_inbound → prompt → resolve` |
| `"ai"` | `functualize-ai` | `ai_outbound → ai_inbound → prompt → resolve` |
| `"ai_outbound"` | `functualize-mcp` | `ai_outbound → prompt → resolve` |

**Presets are not reachable from a `Gate`.** `Gate.__post_init__` validates
`strategy` against `_VALID_GATE_STRATEGIES` — the four bare names only — so
`Gate(strategy="ai")` raises. A preset is usable only through
`app.resolve_gate` and the imperative `rc.invoke(..., gate_strategy=…)` path.
`docs/guides/ai.md` lists the presets under "Gate Strategies" without saying
so. [probed: `evidence/probe_17_gate_fallback.py` case F]

## 1a. What each gate actually falls back to [probed]

`evidence/probe_17_gate_fallback.py` runs the same workflow under five
conditions. The walker's contract is: *anything that fails to resolve
blocks* — except one case that does not.

| Gate | Installed | Result |
|---|---|---|
| `strategy=None` | — | `BLOCKED` |
| `strategy="ai_outbound"` | nothing | `BLOCKED` — the walker short-circuits *before* resolution (`return None`), so the MCP resolver is never called and no provider is consulted |
| `strategy="ai_inbound"` | resolver present, provider missing (raises) | `BLOCKED` — the resolver's exception is swallowed per-strategy, prompt has no surface, resolve has unmet required fields, `GateResolutionError` → block |
| `strategy="ai_inbound"` | **`functualize-ai` absent** | **`ValueError` — the walk crashes** |

The last row is a defect. `workflow_walker.py:278` catches only
`GateResolutionError`, but an *unregistered* strategy name raises a plain
`ValueError` from `GateRegistry.resolve_gate` outside the per-strategy
`try`. So a broken API key degrades gracefully and a missing `pip install`
does not:

```
ValueError: Unregistered gate strategy 'ai_inbound' referenced during
resolution of gate 'triage'
```

The fix is one of: catch `ValueError` alongside `GateResolutionError` in the
walker, or have `resolve_gate` skip unregistered names when the list has more
than one entry (keeping the hard error for a single explicit strategy).
Filed as upstream ask 9 (§6).

**The rule to design against:** blocking is the universal fallback, and
`ai_outbound` *is* that fallback rather than a route to it. The intelligence
is optional at every point where it is used — provided the plugin declaring
the strategy is installed.

### Two gate surfaces, not one

Gates are not only a workflow-graph construct. `rc.invoke` raises one
imperatively from inside any job body:

```python
rc.invoke(child_job, awaits_input=Decision, force_gate=True,
          gate_strategy="ai", available_tools=["search"])
```

`_engine/capabilities/invoke.py:289`. Same registry, same strategy ladder,
same `_input_schema` published in the result metadata — but no `@workflow`
declaration needed. A skill with **one** judgment step does not have to
become a graph to get a typed gate.

---

## 2. So what is the thing being asked for?

**A skill whose subject matter is other skills.** It reads a procedure
written as prose and emits a workflow, deciding — step by step — which parts
are mechanical and which need a mind.

That classification *is* the product. Everything else is transcription.

```
scrill-compile/
├── SKILL.md              # the classification method (§3) — the judgment
├── references/
│   ├── gate-strategies.md    # which of the four, and why
│   └── worked-examples.md    # three compilations, before and after
└── scripts/
    └── jobs.py           # rise scrill compile / verify / diff
```

It is alternative **A** from `15` §3 — a directory whose scripts are jobs —
and it dogfoods: the tool that turns skills into workflows is itself a
skill-with-jobs.

---

## 3. The classification method

This is the part that cannot be automated away, and therefore the part that
belongs in a skill rather than in code.

For each imperative sentence in the source skill, ask **"could this be wrong
in a way a schema would catch?"**

| The sentence is… | Compiles to | Because |
|---|---|---|
| a command with a fixed shape (`run the test suite`) | `Step(job)` | deterministic; failure is an exit code |
| a precondition (`make sure the cluster is up first`) | `Guards(preconditions=[Precondition(check, msg)])` | it is a *check*, not a step. Refusal carries the instruction (`15` §1) |
| an idempotency note (`skip if already migrated`) | `Guards(status=[...])` → `SKIPPED`, exit 0 | precondition would exit 3 and abort the walk — the R10a distinction |
| a branch (`if it's a hotfix, skip staging`) | `ConditionalEdge` | the key is recorded and replayed on resume |
| **a judgment with a nameable output** (`decide the severity`) | `Gate(awaits=Severity)` | the output has a shape even though the reasoning doesn't |
| **a judgment with no nameable output** (`use your best judgment`) | **leave it as prose** | a gate whose model is `{"answer": str}` has bought nothing |
| a fact about the world (`the API is rate-limited to 10/s`) | stays in `SKILL.md` | not a step at all |

The last two rows are the ones that keep the compiler honest. A compiler
that gates everything produces a workflow that blocks constantly and is
worse than the prose it replaced. **A gate must narrow something.** If the
model it awaits is a free-text field, the gate is ceremony.

### Choosing the strategy

```
Does the decision need tools, or a human, or context outside this process?
├── needs to look things up / call jobs      → ai_outbound + tools=[…]
├── a person must actually approve           → prompt
├── a model can answer from what's in scope  → ai_inbound (+ prompt fallback)
└── it's really config someone forgot to set → resolve
```

Default to `ai_outbound` when unsure. It blocks, which is visible and
recoverable; a wrong `ai_inbound` silently invents an answer.

---

## 4. Lifecycles

### Human

```console
$ rise scrill compile ./deploy-runbook            # the existing prose skill
  read      deploy-runbook/SKILL.md — 14 imperative steps
  classify  9 deterministic · 2 preconditions · 1 branch · 2 judgments
  emit      deploy-runbook/scripts/workflow.py
  review    2 gates need models you must name:
              step 6  "decide whether the canary looks healthy"
              step 11 "pick a rollback target"

$ $EDITOR deploy-runbook/scripts/workflow.py      # name the two models
$ rise scrill verify ./deploy-runbook
  ✓ every Step names a registered job
  ✓ every Gate's awaits model has ≥1 non-string field
  ✗ gate "canary_health": awaits model is {ok: str} — a free-text gate
    narrows nothing (§3). Give it an enum, or leave the step as prose.

$ $EDITOR ...                                     # ok: bool, p99_ms: float
$ rise scrill verify ./deploy-runbook             # green
$ func deploy run                                 # runs; blocks at canary_health
```

Six months later the runbook changes. The human edits the workflow, not the
prose — and `rise scrill diff` reports which SKILL.md paragraphs no longer
have a corresponding node, which is the staleness check scrill-design wanted
(D10) arriving as a by-product.

### Agent, driving a compiled workflow

```
1. invoke    func deploy run                      (or the MCP tool)
2. observe   exit 5 · BLOCKED · blocked_on: canary_health
             + the awaits schema, + tools: [metrics_query, canary_logs]
3. gather    calls metrics_query, canary_logs — the only two jobs it may
             call here. issue_rollback is not in the list, so it is not
             merely forbidden, it is absent from the tool set
4. decide    deposits {"ok": false, "p99_ms": 812.0}
5. resume    func builtin workflow resume deploy-4c98d7b5
             the walk continues down the recorded branch
6. repeat    blocks again at rollback_target; decides; resumes; END
```

Compare with the same agent running the same procedure as prose: it reads
fourteen steps, executes them by generating shell commands, and any one of
them can be paraphrased into something adjacent. Here **twelve of the
fourteen are not the agent's to get wrong** — they are jobs, with guards,
fingerprints, and exit codes. The agent's contribution is narrowed to the
two places a mind was actually needed, and even there it answers a schema.

### Agent, running the compiler

```
1. trigger   "make this runbook reliable" / "turn this skill into a workflow"
2. load      scrill-compile/SKILL.md — the classification method
3. read      the target SKILL.md
4. classify  per §3, sentence by sentence — this is the agent's real work
5. emit      run `func scrill compile <dir>`, then fill the model stubs
6. verify    `func scrill verify` refuses free-text gates; iterate to green
```

Step 6 matters: the compiler's own quality bar is enforced by a job, not by
the agent's diligence. Generate → validate → fix, the same convergence
property `09` §4 requires of the scaffolds.

---

## 5. What is actually gained — and lost

The honest ledger, because "more deterministic and hermetic" should be paid
for in something.

| Property | Prose skill | Compiled workflow | Mechanism |
|---|---|---|---|
| step execution is reproducible | no — regenerated each run | **yes** | `Step` names a registered job |
| dependencies pinned | no | **yes** | PEP 723 / `[risekit] requires` (`07`) |
| unsafe action prevented | asked politely | **yes** | `Tool(job, **pinned)` — inexpressible |
| precondition enforced | the agent must remember | **yes** | `Guards` → `REFUSED`, exit 3 |
| re-run is safe | hope | **yes** | `Guards(status=…)` → `SKIPPED`, exit 0 |
| interrupted run resumes | restart from the top | **yes** | BLOCKED position + scope id |
| branch cannot change on resume | n/a | **yes** | `ConditionalEdge` replay |
| audit of what happened | transcript | **yes** | scope state + `08`'s JSONL |
| **handles the case nobody anticipated** | **yes** | **no** | — |

The last row is the whole cost. A prose skill improvises; a workflow
refuses. The mitigation is not to soften the workflow — it is to recognise
that **the gates are the improvisation points**, deliberately chosen and
explicitly scoped. Compiling a skill is the act of deciding where improvising
is allowed.

Which yields the rule for when *not* to run this compiler:

> If, after classification, more than about half the steps are gates, the
> procedure is not a procedure. Leave it as prose.

### On "hermetic"

Worth being precise: the workflow structure buys **determinism**, not
hermeticity. Hermeticity comes from the layers underneath —
PEP 723 `dependencies` resolved by `uv` into a fresh environment,
`Fingerprint(sources=, generates=)` for content-addressed skipping, and
`Secret[str]` so credentials never reach a transcript. A workflow of
`Shell("kubectl …")` steps is deterministic in shape and hermetic in
nothing. The compiler should say so, and `rise scrill verify` should warn
when a compiled workflow's steps have no declared dependencies.

---

## 6. What this needs

Nothing upstream that is not already asked for. The compile target ships.

| Need | Where it lands | Status |
|---|---|---|
| an `ai_inbound` resolver | **already ships** in `functualize-ai`; a provider comes from `functualize-ai-pydantic` | `pip install`, not code |
| `rise scrill compile / verify / diff` | risekit, next to `rise skills build` (`15` §5) | new |
| the `scrill-compile` skill itself | `risekit/_skills/`, or standalone | new |
| unregistered-strategy crash (§1a) | upstream ask 9 — walker catches `ValueError`, or `resolve_gate` skips unknown names in a multi-entry list | new |
| third-party skill hosting | upstream ask 6 (`15` §6) | asked |
| `job_detail` exposes `declaration` | upstream ask 7 | asked |

One addition to the acceptance set, alongside N1–N3 (`15` §4):

- **N4** — A compiled workflow runs to completion with **no** agent present:
  every gate either resolves from config, prompts a human, or blocks
  visibly with a schema. A workflow that requires an AI to be reachable in
  order to terminate is a bug.

N4 is the non-forcing rule applied to gates. Intelligence is an input the
system can ask for, never a dependency it assumes.

## 7. A vocabulary collision worth knowing about

functualize uses "inbound" and "outbound" on **two different axes**, and they
point opposite ways.

| Axis | outbound | inbound |
|---|---|---|
| **Job level** (`docs/guides/ai.md`, the two standalone examples) | the job calls an LLM — *"the job is the caller, not the callee"* (`AI.complete`, `AI.run`) | the job is *"designed to be driven by an external AI agent"* (MCP, `run_job`) |
| **Gate level** (`_types/workflow.py:267`) | `ai_outbound` — hand the question **out** to whoever is driving; block and publish | `ai_inbound` — pull an answer **in** by calling a model |

So the gate strategy named `ai_inbound` is implemented by the capability the
guide calls **outbound** AI: `AIInboundGateResolver.resolve` calls
`ai.complete()`. Same physical action, opposite word, depending on which
document you are reading.

Both namings are internally coherent — job-level names the *scenario*, gate-level
names the *direction the answer travels* — but a design built on top of both
must say which axis it means every time. This page means the gate axis
throughout. The compiler's skill should state the axis in its first
paragraph, and it is worth an upstream doc note.

## 8. Unprobed

- MCP end to end: `resume_gate`, and whether `Gate.tools` narrowing is
  visible in the published tool list. The code says it is enforced at MCP
  dispatch (`_types/workflow.py:259`); that is read, not run. This is the
  same MCP gap carried from `14` §3 and `15` §7, now with a third reason to
  close it.
- `ai_outbound` resumed by a real agent over MCP rather than by
  `app.execute` plus a direct deposit.
