# Changelog & retired arguments

The numbered documents read as one coherent specification. They did not arrive that way.
This file holds the iteration history, every reversal, and — most importantly — the
**arguments that are closed**, so none of them has to be made or answered again.

If you are about to re-open a question, check §3 first.

---

## 1. How this material was produced

| Pass | What it did |
|---|---|
| 1 | Audited the prior study at `~/code/raicing-ai/functualize-vs-pi-workflows/` against both codebases. Produced the corrections and the evidence index. |
| 2 | Built an independent model of pi-workflows @ `2b3cf35` rather than trusting the study's reading of it. |
| 3 | Inventoried the live surface (CLI / job flags / MCP) and the defects in it. |
| 4 | Assessed the MCP adapter for reach, naivety and context cost. |
| 5 | Designed the gate-answer, coordination, nesting and task-storage additions. |
| 6 | Placed everything on the core/plugin map and fixed the fallback story. |
| 7 | Critiqued the in-flight `--wf-status` handoff. |
| 8 | Four iterations on the surface design — see §2. Settled at three tiers. |

Everything was re-derived from source at `78d9ff4`. One claim (silent scope erasure) is
proven by a run experiment; the transcript is in
[evidence/scrutiny-report-2026-09-08.md](evidence/scrutiny-report-2026-09-08.md).

## 2. Reversals, in order

Recorded because each one was reached by evidence, and knowing *why* prevents a
well-meaning revert.

### R1 · "Keep the early-parse `--scope-id`" → remove it

**Claimed:** the pre-command global is the only spelling guaranteed on every dispatch
mode, because the per-command option's warm path depends on the discovery cache.
**Falsified by testing** all five invocation paths, cold and warm: the per-command option
is present in every one. And the cold-cache bug at `main.py:2075-2081` was a defect in
the **global's** own threading through UNKNOWN mode — evidence against keeping it, cited
as evidence for. The claim was inherited from the prior study's doc 07 and repeated
untested.

### R2 · "Remove it as a refusal" → plain deletion

Two grounds were given for keeping the flag recognised while rejecting it. Both reduce to
error-message quality once you notice the correct spelling is post-command, where
`detect_mode` stops before ever reaching the flag. Verified that a deleted flag fails
loud (`Unknown command 'scope-id'`, exit 1) and can never misexecute, because the scan
`break`s on an unrecognised `--flag` before examining its value.

### R3 · "Replace `--scope-id` with a verb and delete the job surface" → three tiers

An over-correction: it solved the flag problem by removing an affordance. The job command
knows *which workflow it is* — that is a real convenience nobody else can offer. Settled
as: rich `builtin workflow`, MCP at parity, `--wf-*` a convenience subset.

### R4 · `--wf-continue` → `--wf-resume`, and `deposit` → `answer`

Three intermediate positions, collapsed by the no-aliases constraint:

1. keep `resume` meaning deposit, add `deposit`, mitigate the collision with a docstring
   rule (D1a) and name the new flag `--wf-continue` to dodge the word (D1b);
2. then: delete `resume` entirely;
3. **settled:** `resume` takes its universal meaning — *advance* — and `answer` takes the
   record meaning. Two verbs, distinct contracts, no alias, and the collision is
   *removed* rather than managed, which retired D1a and D1b instead of implementing them.

The deciding evidence: **three doc sites already describe `resume_workflow` as advancing
the walk** (`docs/guides/mcp.md:55`, `:200`, `docs/guides/workflows.md:247`) while the
code only deposits. Two guides, written by people who knew the system, independently
reached for the universal meaning. The code moves to match the docs.

### R5 · Doc 02's closing conclusion

Said "keep the global" on the strength of R1's claim. Retracted in place — leaving it
standing was exactly the stale-conclusion drift this material exists to catch.

## 3. Closed — do not re-litigate

Each row is settled. The evidence is in the cited document.

| Question | Answer | Where |
|---|---|---|
| Rename `builtin workflow resume`? | **No rename.** Both verbs survive with **distinct contracts**: `answer` records, `resume` advances. No aliases. | [14 A1-A2](14-decisions.md) |
| `--wf-continue` or `--wf-resume`? | **`--wf-resume`.** Once `resume` means advance the word collides with nothing. | [CHANGELOG §2 R4](CHANGELOG.md) |
| A standing docstring rule to keep the two contracts straight? | **Not needed** — there is no collision left to mitigate. | [CHANGELOG §2 R4](CHANGELOG.md) |
| `answer` or `deposit` for the record verb? | **`answer`** — pi-workflows' word for the same operation; `deposit` is overloaded three ways internally. `deposit_gate_input` stays as the internal name. | [14 A1-A2](14-decisions.md) |
| Keep the early-parse `--scope-id`? | **Delete it outright.** | [12](12-scope-id.md) |
| Keep the per-command `--scope-id`? | **No** — `--wf-resume [id]` replaces it and is strictly more capable. | [05 §2.2](05-target-surface.md) |
| Should the job command lose its control flags? | **No.** Nine `--wf-*` flags, chosen by the inclusion test. | [05 §1](05-target-surface.md) |
| Which surface is richest? | **`builtin workflow`**, with MCP at verb-and-contract parity and `--wf-*` a subset. | [05](05-target-surface.md) |
| Does `--wf-show` render a summary or the full projection? | **Full projection** — the flag saves naming the workflow, it does not reduce output. | [05 §2.1](05-target-surface.md) |
| Co-address tasks to workflows, or delete the link kind? | **Co-address.** | [14 D6](14-decisions.md) |
| Peer multi-master task merge? | **Not buildable** — no `updated_at`, and the status enum is not a monotonic lattice. Architecture A only. | [10 §3](10-task-storage.md) |
| A message bus for agent coordination? | **No.** Scope-scoped append-only notes, no routing, no inboxes. | [08 §3](08-coordination.md) |
| Two nesting models? | **No.** Keep child scopes; fix their five defects. | [14 C7](14-decisions.md) |
| `--wf-retry-failed`? | **Not needed** — failed steps already re-run on resume. Only the epilogue is sticky. | [02 §9](02-prior-study-corrections.md) |
| `--fresh`? | **No** — absence of a resume flag already means a new scope. | [14 N8](14-decisions.md) |
| Time columns / `--actor` in the survey? | **Not yet** — scope records carry no timestamps, and the gate-level `blocked_at` resets on every re-block. | [01 §C.6-C.7](01-current-state.md) |
| Where should shared verb logic live? | **`app/`, re-exported through `functualize.app.utils`** — the only arrangement `_cli` may legally import. | [11 §1](11-boundaries.md) |
| Preserve caller-chosen run ids? | **Yes — `--wf-run-id`.** A *start* parameter, unconditional, separate from `--wf-resume` which errors on an unknown id. | [14 A8](14-decisions.md) |

## 4. Still open

None.

## 5. Lifecycle of this shape intent

**Decided:** before the PR merges, this folder is synced once to
`~/code/raicing-ai/pi-workflow-parity/` and then **removed from `.spec/shape-intents/`**.
The unversioned copy becomes the durable record.

Note the difference from the other shape intents, which live on `master` permanently
(`git ls-tree master .spec/shape-intents/` lists eight). This one is deliberately
branch-only, so the sync is the whole preservation step — if it is skipped, the material
is lost with the branch. Do it as the last commit before merge, alongside whatever
`.spec/features/` cleanup the required `spec-artifacts-cleared` check demands.

## 6. Document history

| Date | Change |
|---|---|
| 2026-09-08 | Initial set: audit, corrections, pi-workflows model, surface inventory, MCP assessment, gate design, coordination, task storage, boundaries, roadmap, decisions. |
| 2026-09-08 | Handoff critique added (four factual errors, six design blockers in the in-flight `--wf-status` handoff). |
| 2026-09-08 | Four surface-design iterations (R1–R4) collapsed into one target-surface document. |
| 2026-09-08 | **Realigned.** The superseded chain (old 09, 14, 16, 17, 18) merged into [05](05-target-surface.md) and [06](06-lifecycles.md); the `--scope-id` audits (old 15, 16) merged into [12](12-scope-id.md); old 05 (tasks↔workflows) folded into [08](08-coordination.md) and [10](10-task-storage.md); nesting split out to [09](09-nesting.md). Supersession notes and self-corrections removed from the documents and recorded here instead. |

## 7. Superseded file map

For anyone following a link from an older commit:

| Old | Now |
|---|---|
| `01-surface-inventory.md` | [01-current-state.md](01-current-state.md) |
| `02-corrections.md` | [02-prior-study-corrections.md](02-prior-study-corrections.md) |
| `03-mcp-assessment.md` | [04-mcp.md](04-mcp.md) |
| `04-gate-deposit.md` | [07-gate-answers.md](07-gate-answers.md) |
| `05-tasks-and-workflows.md` | folded into [08](08-coordination.md) §4 and [10](10-task-storage.md) |
| `06-pi-workflows-model.md` | [03-pi-workflows.md](03-pi-workflows.md) |
| `07-roadmap.md` | [13-roadmap.md](13-roadmap.md) |
| `08-handoff-critique.md` | [appendix-a-handoff-critique.md](appendix-a-handoff-critique.md) |
| `09-target-matrix-and-lifecycles.md` | [05](05-target-surface.md) + [06](06-lifecycles.md) |
| `10-coordination-and-nesting.md` | [08](08-coordination.md) + [09](09-nesting.md) |
| `11-core-plugin-boundaries.md` | [11-boundaries.md](11-boundaries.md) |
| `12-task-sinks.md` | [10-task-storage.md](10-task-storage.md) |
| `13-decisions.md` | [14-decisions.md](14-decisions.md) |
| `14-resume-deposit-collisions.md` | [05 §2.3](05-target-surface.md) + §2 R4 above |
| `15-scope-id-early-parse-removal.md` | [12-scope-id.md](12-scope-id.md) |
| `16-replacing-scope-id.md` | [12-scope-id.md](12-scope-id.md) + §2 R2-R3 above |
| `17-lifecycle-without-scope-id.md` | [05](05-target-surface.md) + [06](06-lifecycles.md) |
| `18-three-tier-surface.md` | [05-target-surface.md](05-target-surface.md) |
| `19-no-aliases.md` | [05 §2.3](05-target-surface.md) + §2 R4 above |
