# 14 · The `resume` / `deposit` collision map — current and future

Written because D1 kept both verbs, so the collision surface has to be known exactly
rather than assumed. Every site below was verified at `78d9ff4`.

**The headline correction:** I had been describing this as *"`resume` already means two
opposite things."* That is **not** what the code says. Today `resume` means **deposit**
on every user-facing surface, consistently — and the *advance* operation has **no name at
all**. The two-meanings collision does not exist yet. **The plan creates it**, by naming
the new advance flag `--wf-resume`.

That reframing changes the recommendation. See §5.

---

## 1. What "resume" means today — one meaning, two lies, one nameless operation

### 1.1 Every user-facing `resume` deposits

| Site | Surface | Contract |
|---|---|---|
| `_cli/builtins.py:900` | `func builtin workflow resume <id> <gate> --input` | **deposit** |
| `_cli/builtins.py:149` | registry entry: `("resume", "Deposit input for a blocked gate")` | **deposit** — the description says so |
| `_workflow_tools.py:238` | MCP `resume_gate(gate, input)` | **deposit** |
| `_workflow_tools.py:273` | MCP `resume_workflow(workflow_id, input)` | **deposit** |
| `_gate_strategy.py:98` | blocked reason: *"Use the resume_workflow tool to provide input"* | **deposit** |
| `click_params.py:940-943` | blocked stderr, line 2 | **deposit** |
| `docs/cli/workflow.md:25,57,65,69` | reference and examples | **deposit** |

Every docstring is explicit — *"Accepting input does not run the workflow"*
(`builtins.py:913-917`, `_workflow_tools.py:241-245`). The contract is stated
consistently and correctly wherever a verb is declared.

### 1.2 Two prose descriptions claim the group advances runs. It cannot.

| Site | Text | Why it is wrong |
|---|---|---|
| `_cli/builtins.py:145` | *"Inspect and **resume** persisted workflow scopes"* | No verb in the group advances a walk. |
| `_cli/builtins.py:822` | same string, on the click group's `help=` | ditto |
| `docs/cli/workflow.md:4` | *"inspects and **resumes** persisted workflow scopes"* | ditto |

Note what this means: **within nine lines of one file** (`builtins.py:145` and `:149`)
the word appears with both meanings — the group *claims* to resume runs, and its `resume`
subcommand is described as depositing. That is the whole collision in miniature, and it
is prose, not contract.

### 1.3 The advance operation is nameless

The only way to advance a walk is `--scope-id`. It has no verb, no noun, and no entry in
any table of workflow operations. `docs/cli/workflow.md:72` reaches for a code comment
because there is no word to use:

```
func release --scope-id rel-1   # replays past the answered gate to completion
```

**This absence is the actual defect.** The collision the plan was worried about is
downstream of it.

---

## 2. C-1 · The blocked output mis-instructs — the one collision that bites today

`click_params.py:925-957`. On exit 5 an operator receives, on stderr:

```
Blocked: gate 'approval' in scope 'a3f9c2e1b7d4' awaits input.
  ./main.py builtin workflow resume a3f9c2e1b7d4 approval --input '{…}'
  ./main.py release-pipeline --scope-id a3f9c2e1b7d4
```

Two commands, printed as a flat list, with **no label, no conjunction, and no ordering**.
Line 2 deposits and does not advance. Line 3 advances and does not deposit. Nothing in
the output says either thing.

Three failure modes, all likely:

- Run **only line 2** → "Input accepted for gate 'approval'." The operator believes they
  are done. The walk has not moved. The scope still reads `blocked`, now with **no pending
  gates** ([09 §1 D-1](09-target-matrix-and-lifecycles.md)), so the next person to look
  sees "stuck, cause unknown".
- Run **only line 3** → blocks again at the same gate, having deposited nothing.
- Run them **in the wrong order** → same as the previous case, then a deposit into a scope
  nobody re-enters.

The code comment above these lines defends printing them at default level because *"a
blocked run is the one outcome a script most needs to act on."* Correct — and that is
exactly why printing two contradictory instructions unlabelled is the sharpest version of
this problem in the codebase.

**This is fixable today, independently of any naming decision, and should be.** It is
one edit to one function:

```
Blocked: gate 'approval' in scope 'a3f9c2e1b7d4' awaits input.
  1. answer the gate (records input; does not run the workflow):
       ./main.py builtin workflow resume a3f9c2e1b7d4 approval --input '{…}'
  2. then continue the run:
       ./main.py release-pipeline --scope-id a3f9c2e1b7d4
```

## 3. C-2 … C-6 · The remaining current collisions

| # | Collision | Site | Severity |
|---|---|---|---|
| **C-2** | Group help claims the group resumes runs | `builtins.py:145`, `:822`, `docs/cli/workflow.md:4` | prose, but it is the first sentence a reader meets |
| **C-3** | The two MCP deposit tools each refer the caller to the other on ambiguity, and neither accepts `(workflow_id, gate)` | `_workflow_tools.py:231`, `:266` | real addressing hole ([01 §C.5](01-surface-inventory.md)); D2 closes it |
| **C-4** | The module holding the deposit implementation is named `_workflow_resume.py` | `app/_workflow_resume.py` | maintainer-facing; free to fix |
| **C-5** | The deposit result's own variable is `resume_hint`, and it holds an **advance** command | `_workflow_resume.py:95-101` | the one place the word genuinely crosses contracts in code |
| **C-6** | pi-workflows' `resume` **advances** (`/workflow resume`, `resumeRun`) | benchmark vocabulary, [06](06-pi-workflows-model.md) | anyone arriving from pi-workflows reads functualize's `resume` backwards |

Adjacent, and *not* a user-facing collision: `deposit` is also overloaded internally —
`deposit_gate_payload` (store write), `deposit_gate_input` (validate + write), MCP
`_deposit` (dispatch helper), and `cli.py:400 _deposit` (**group option values**, nothing
to do with gates). Only the last is a genuine name clash, and it never reaches a user.

`frontier.py:96` — *"Begin (or resume) the walk"* — is internal, accurate, and harmless.

---

## 4. What the plan adds — the collision ledger after everything lands

| Surface | Layer | Meaning | Status |
|---|---|---|---|
| `func builtin workflow resume <id> <gate>` | record | **deposit** | kept (D1) |
| `func builtin workflow deposit <id> <gate> …` | record | **deposit** | new (D1) |
| MCP `deposit_gate(workflow_id?, gate?, …)` | record | **deposit** | new, replaces both resume tools (D2) |
| `func <wf> --scope-id <id>` | invocation | **advance** | kept |
| **`func <wf> --wf-resume [id]`** | invocation | **advance** | **new — this is what creates the collision** |
| `run_job(name, scope_id=…)` | execution | **advance** | new |
| `provenance.resumes[]` | record | a log of **advances** | designed (doc 06) |
| pi-workflows `resume` | external | **advance** | benchmark |

Count the word: after the plan, **"resume" means deposit on 1 surface and advance on 3**
(`--wf-resume`, `provenance.resumes[]`, and the external benchmark), while the deposit
meaning it holds today gets a synonym (`deposit`) that is unambiguous.

So the plan does two things at once: it *introduces* the word on the advance side, and it
*dilutes* it on the deposit side. The net is that `resume` stops meaning anything
specific — which is worse than either the current state or a clean rename.

---

## 5. The recommendation: rename the flag, not the verb

**Spell the new invocation-layer flag `--wf-continue`, not `--wf-resume`.**

This satisfies O1 exactly as decided — `resume` **and** `deposit` both survive as record
verbs — and removes the collision from the other side:

| | With `--wf-resume` | With `--wf-continue` |
|---|---|---|
| `resume` survives (O1) | yes | yes |
| `deposit` added (O1) | yes | yes |
| Meanings of "resume" | 2 (deposit + advance) | **1** (deposit) |
| Advance operation has a name | yes, a colliding one | yes, **`continue`** |
| Cost | — | **zero** — the flag does not exist yet |
| Existing hints/docs/skills touched | — | none |
| pi-workflows readers | still inverted | still inverted (C-6 is unavoidable) |

The decisive point is the **cost column**. `--wf-resume` has no users, no generated
hints, no docs and no skills referencing it. Renaming a flag that does not exist is free;
renaming `func builtin workflow resume` was not, which is precisely why O1 declined it.
Choosing `--wf-continue` gets the whole benefit of the rename at none of its cost.

It also makes the layer rule true *by construction* rather than by documentation:

> **record layer answers, invocation layer continues.** `resume`/`deposit` record an
> answer and never advance. `--wf-continue`/`--scope-id` advance.

And it gives §1.3's nameless operation a name, which fixes C-1's root cause instead of
papering over it — the blocked output can then say *"then continue the run"* and name a
flag that is actually spelled `continue`.

**Deviation flagged:** the handoff's decision 2 names the flag `--wf-resume`. That
decision was about the flag's *semantics* — complements `--scope-id`, newest-blocked
default, fuses input with continuation — all of which are unchanged. Only the spelling
moves.

### If you keep `--wf-resume` anyway

Then D1a is the entire mitigation and it must be enforced, not merely intended:

| # | Mitigation | Test |
|---|---|---|
| **M1** | Fix the blocked output per §2 — numbered steps, contract stated inline | a test asserting both the ordering and the phrase *"does not run the workflow"* appear |
| **M2** | Every record-layer verb's `--help` and docstring **opens** with *"Accepting input does not run the workflow."* | grep test over the declared surfaces |
| **M3** | Every invocation-layer surface **opens** with *"Continues the walk in this process."* | same test |
| **M4** | Fix C-2: group help → *"Inspect, answer, and cancel persisted workflow scopes"* | — |
| **M5** | Rename `_workflow_resume.py` → `_workflow_gate_input.py`; `resume_hint` → `continue_hint` | internal, free |
| **M6** | `resume`'s help states it is an alias for `deposit … --commit` | — |
| **M7** | One callout in `docs/cli/workflow.md`: the word appears on both layers, here is which is which | — |

M1 and M4 are worth doing **regardless of the naming outcome** — they are current
defects, not consequences of the decision.

---

## 6. What does not collide, and why that matters

The contract itself has never been ambiguous in code. Every declaration says the right
thing:

- `builtins.py:913-917` — *"Accepting input does not run the workflow — invoke the
  workflow job with the same scope_id to continue past the gate."*
- `_workflow_tools.py:241-245` — the same sentence on `resume_gate`.
- `docs/cli/workflow.md:12` — names the shared `deposit_gate_input` implementation and
  why both surfaces call it.

**The collision is entirely in the vocabulary and the guidance text, not in the
semantics.** That is why it is cheap to fix and why fixing it is worth doing before the
new surfaces multiply the sites. Nothing here requires an engine change; it is naming, one
stderr block, and a grep test.
