# 19 · No aliases: what `resume` becomes, or whether it goes

Decision memo. Answers: *"I don't want any aliases. What would `resume` be without alias?
Can we remove it?"*

Settles **O6** and retires **D1a** and **D1b**.

---

## 1. A finding that reframes the question

Before choosing, note what the repository already says. **The docs claim
`resume_workflow` advances the walk. In three places.**

| Site | Text |
|---|---|
| `docs/guides/mcp.md:55` | `resume_workflow(id, input)` — **"Advance a paused workflow"** |
| `docs/guides/mcp.md:200` | *"…and **resumes** when the AI agent calls `resume_workflow(id, input)`"* |
| `docs/guides/workflows.md:247` | `resume_workflow(id, input)` — **"deposit gate input and advance"** |

The code does not. Its own module docstring is emphatic
(`_workflow_tools.py:21-24`):

> *"It fills the gate's payload slot; the next invocation of the workflow job replays the
> walk… So a successful deposit reports `input_accepted` — **not `resumed`** — because
> nothing has run yet, and the caller still has to invoke the job."*

Two consequences:

1. **This is a live documentation defect**, on top of the four already recorded. An agent
   following `docs/guides/mcp.md` believes two calls suffice and is wrong — which is
   exactly the dead end [09 §L2](09-target-matrix-and-lifecycles.md) described, now with
   the docs actively causing it.
2. **It is the strongest available evidence for what the word should mean.** Two
   different guides, written by people who knew this system, independently reached for
   `resume` = *advance*. Nobody writes "deposit and advance" about a verb they think only
   deposits. The word wants its universal meaning.

---

## 2. The two options

### Option A — `resume` becomes the **advance** verb

Not an alias: a second verb with a distinct contract.

| Verb | Contract |
|---|---|
| `answer <id> <gate>` | record input · **never advances** |
| `resume <id>` | **advance** the walk to the next durable boundary |

Both survive, as O1 asked, and neither is a shim for the other.

**What this fixes, beyond the alias:**

- **The collision disappears rather than being mitigated.** `resume` means one thing on
  every surface, so **D1a** (the standing docstring rule) and **D1b**
  (`--wf-continue` to dodge the word) are both unnecessary. `--wf-resume` becomes the
  correct spelling of the job-side shortcut.
- **The docs become true** without editing their meaning — only `resume`'s implementation
  moves to match what they already promise.
- **Peer alignment.** Temporal, pi-workflows (`resumeRun`), LangGraph
  (`Command(resume=…)`) and Argo all use `resume` = advance. functualize stops being the
  outlier, so knowledge transfers in both directions.

**What it costs:** an existing verb changes meaning. `func builtin workflow resume` would
stop depositing and start advancing. With no users to consider that is free, but it is a
genuine semantic reassignment and the CHANGELOG has to say so plainly.

### Option B — remove `resume`

| Verb | Contract |
|---|---|
| `answer <id> <gate>` | record input · never advances |
| `continue <id>` | advance |

Smallest surface, one word per operation, and no verb ever changes meaning — `resume`
simply stops existing. But it declines the universal word for the operation users will
reach for it by, and `continue` needs `_continue`/`workflow_continue` at the
implementation level because `continue` is a Python keyword.

---

## 3. Recommendation: **A**

The deciding argument is §1.2 — the word already means *advance* to the people who wrote
this repository's own documentation, twice, unprompted. Option B spends a rename to avoid
a word that the codebase is already using correctly in prose and incorrectly in code.
Option A fixes the code instead.

It is also the only option that makes **D1a and D1b deletable**. Every other arrangement
leaves a collision that has to be managed by documentation and a grep test; this one
removes the collision.

### 3.1 The verb table under A

| Operation | `builtin workflow` | MCP | `--wf-*` |
|---|---|---|---|
| record input, no advance | `answer <id> <gate> [--input\|--set] [--show] [--commit/--no-commit] [--reopen]` | `answer_gate(id?, gate?, values, mode, commit)` | — |
| **advance** | `resume <id> [--input] [--gate] [--set] [--retry-epilogue]` | `resume_workflow(id, input?, gate?)` | `--wf-resume [id]` |
| survey · inspect | `list …` · `show <id>` | `list_workflows(…)` · `get_workflow_state(id)` | `--wf-status` · `--wf-show` |
| gate tool · cancel · purge | `gate-tool` · `cancel` · `purge` | `call_gate_tool` · `cancel_workflow` · `purge_workflows` | — |
| start | — | `run_job(name, config, run_id?)` | `func <wf>` · `--wf-run-id` |

Note both MCP names already exist: **`resume_workflow` keeps its name and gains the
semantics its docs already advertise**, and `resume_gate` is absorbed into `answer_gate`
(which fixes the joint-addressing hole — [01 §C.5](01-surface-inventory.md)).

### 3.2 `answer` over `deposit` for the record verb

- It is the natural English word for responding to a gate, and pi-workflows' word for
  exactly this operation (`/workflow answer <json>`).
- `deposit` is already overloaded internally — `deposit_gate_payload` (store write),
  `deposit_gate_input` (validate + write), and `cli.py:400 _deposit` (**group option
  values**, unrelated to gates).
- Keep `deposit_gate_input` as the internal function name. It is accurate about the
  mechanism; `answer` is accurate about the intent. Different layers, different words, no
  alias.

### 3.3 What changes

| Site | Change |
|---|---|
| `builtins.py:900` `@workflow_app.command("resume")` | now advances; add `answer` for the deposit path |
| `builtins.py:145`, `:821`, `docs/cli/workflow.md:4` | group help — *"Inspect, answer, resume, and cancel persisted workflow scopes"*; the claim becomes true |
| `_workflow_tools.py` `resume_gate` | removed; folded into `answer_gate(id?, gate?)` |
| `_workflow_tools.py` `resume_workflow` | **name kept**, semantics become advance |
| `_gate_strategy.py:98` | *"Use the `answer_gate` tool to provide input"* |
| `docs/guides/mcp.md:55,200`, `docs/guides/workflows.md:116,247` | **no wording change** — they become correct |
| `docs/cli/workflow.md:12,25,57,65,69` | re-point `resume` rows at `answer` |
| `app/_workflow_resume.py` | → `_workflow_gate_input.py` (D1d) |
| `_workflow_resume.py:95-101` `resume_hint` | → `continue_hint`, and it now names `resume <id>` |

## 4. Decisions

| # | Status |
|---|---|
| **D1** | **revised** — both verbs survive with **distinct contracts**, not as aliases: `answer` records, `resume` advances |
| **D1a** | **retired** — no collision left to mitigate by documentation |
| **D1b** | **retired** — `--wf-resume` is correct; `--wf-continue` is unnecessary |
| **D1o** | **new** — fix the docs/code contradiction: three doc sites promise `resume_workflow` advances and it does not. Under D1 revised, the code moves to match the docs rather than the reverse. |
| **O6** | **closed** — `answer` (record) / `resume` (advance) |

## 5. Direct answer

**Yes, `resume` can be removed** — Option B, and it is clean. But it should not be. Without
an alias the honest choice is between deleting the word and *fixing* it, and the
repository's own documentation already tells you which: it describes `resume_workflow` as
advancing a workflow, in two separate guides, because that is what the word means
everywhere else. Give `resume` that meaning, name the deposit verb `answer`, and the two
verbs you asked to keep both do real work — with no alias, no collision to document, and
three doc sites that stop lying.
