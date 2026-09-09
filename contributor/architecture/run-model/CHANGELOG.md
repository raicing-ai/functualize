# CHANGELOG — how this document set was produced

The numbered documents read as one specification. They did not arrive that way. This file
holds the iteration history, every reversal, and — most importantly — **the arguments that
are closed**. If you are about to re-open a question, check §3 first.

---

## 1. How this material was produced

| Pass | What it did |
|---|---|
| 1 | Read the audit synthesis (`.spec/shape-intents/entrypoint-encapsulation/shape-intent.md` @ `289e0b7`) and the pi-workflows roadmap (`~/code/raicing-ai/pi-workflow-parity/13-roadmap.md`) as two separate bodies of work |
| 2 | Extracted the two source audits and ADR-020 in full — 17 surfaces, 13 divergences, 14 leakage rows, 4 causes, 15 smells, 9 steps, 6 open decisions |
| 3 | **Re-verified every audit claim at `2a079de`**, by blob-hash comparison and by re-running each falsifying command. 15/17 held, 2 drifted, 0 false |
| 4 | Surveyed the branch landscape and found the assumed collision was already merged (§2 R1) |
| 5 | Independent evidence passes for the doors, the durable-run substrate, and the workflow declaration surface |
| 6 | Wrote 01–14 from that evidence. Every `file:line` in this set resolves at `e57f0c9` |

Retrieval routing per `.claude/skills/code-intel/SKILL.md`: `rg` for exact strings, graphify
for typed edges, zvec-grep for prose. **serena was unavailable** — its MCP handshake timed
out for the authoring session — so reference enumeration was delegated to subagents carrying
their own serena wiring, and every result they returned was re-run locally with `rg` before
being written down. Where this set says "the only", "zero", or a count, the command is named.

## 2. Reversals, in order

### R1 · "A branch collides with this work" → it was already merged

`feat/discovery-and-parameter-fixes` showed 10 commits not on master, touching
`_engine/executor.py` (+70), `app/utils.py`, `app/adapters/cli.py` and
`app/adapters/click_params.py` — the audit's primary targets. It was recorded as a
sequencing risk and offered to the maintainer as a decision.

**Wrong.** It had been squash-merged as PR #30 (`787035e`); the 10 commits were its
pre-squash history, which a squash merge never makes ancestors of master. Verified by
content: `_primitives/parameter_types.py`, `_types/discovery_report.py` and both its test
files are on master.

*The lesson is the general one: a commit count is not a merge state.* `git rev-list --count`
answers a different question than "is this work in master", and under squash merges the two
answers routinely disagree.

### R2 · "Freshness exposure is one acceptance criterion in F1" → it is its own feature

The maintainer's boundary — *artifact storage is the job's business; give the job its
fingerprint verdict and let it decide* — was initially costed as a small addition to F1, on
the assumption that the verdict merely needed surfacing.

Measured: `_engine/executor.py:1026` **returns before the body runs** when the pre-flight says
skip. So the job never gets the chance, and exposing the verdict alone changes nothing. A
second piece is required — a way for a job to declare it handles its own freshness — and that
is a change to the job-author declaration surface. It became **F9**.

### R3 · "Memoize `entry_points()` — the largest available boot win" → withdrawn, already shipped

Carried from the audit synthesis, which carried it from `tests/perf/test_startup_budget.py`.
It shipped on 2026-08-27 as `84ed555` (PR #4). The comment recommending it dates from
2026-08-20 (PR #3) — the previous PR — and was never deleted. See [12 §D](12-performance.md).

### R4 · "Four causes" → five

Both audits compressed to four and each dropped a different one, so "Cause 4" names two
different claims across the three source documents. Renumbered once to **C-I…C-V**, old
numbers never reused. See [Appendix A §A](appendix-a-audit-synthesis.md).

### R5 · "The urgent tranche lands first, separately" → folded into F1

The audit's D2 recommends it, and under its assumptions it is right. Those assumptions
included shipping it in days. Under one-branch-one-PR nothing ships early, so the recommendation
keeps its cost — writing D-1/D-2/D-3 twice, once as deposits and once as request fields — and
loses its benefit. Folded into F1, ordered first within it (decision **G7**).

## 3. Closed — do not re-litigate

| Question | Answer | Where |
|---|---|---|
| Should the inline TUI exit 0 or 5 when a gate blocks? | **5.** 0.3.0 already made `workflow resume` exit 5-when-blocked, breaking compatibility on purpose. The TUI is the last dissenter. The panel may still render `✓ Done` | [06 §C](06-outcome-authority.md), **J3** |
| Should functualize cache job artifacts? | **No — that is the job's business.** The framework owes the job its freshness verdict, not its storage | [11 §B](11-boundaries.md), **N1** |
| Should `RunContext`'s 58 delegations be derived from declarations? | **Not here.** Each `rc.` method is a deliberate public-API decision. F3 shrinks the facade; it does not derive it | **N2** |
| Should `execute(name, function, …)` get a deprecation shim? | **No.** Pre-release stance, and a shim preserves the door this work exists to close | **G3** |
| Should the two CLI parsers become one? | **No.** Pre-boot exists for a ~3 ms zero-import routing budget. They share a vocabulary, not a syntax | **J5**, **N7** |
| Should the door count be reduced? | **No — made irrelevant.** 0.3.0 added a tenth and was right to | [Appendix A §B](appendix-a-audit-synthesis.md), **N4** |
| Can the durable run layer be built before the entry consolidation? | **Yes, at the cost of nine instrumentation sites and a tenth authority.** That is the whole argument of this set | [03 §C](03-the-run-model.md) |
| Does `rc.invoke` lose workflow scope? | **No.** It propagates `parent_scope` (`invoke.py:398,406`). The audit matrix's cell is wrong. `parallel` passes `None` deliberately | [Appendix A §C](appendix-a-audit-synthesis.md) |
| Is `_execute_lifecycle` being redesigned? | **No.** Its 20-step order is a contract; `test_lifecycle_order.py` stays green at every commit, and that is the proof each move was pure | **H6**, **N5** |
| Should this be several PRs? | **No.** One branch, one PR, after every feature is executed and cleared | **M4** |

## 4. Still open

**Nothing in the design.** D1–D6 from the audit synthesis are all resolved or scoped out
([14 · Open](14-decisions.md)).

Two *execution* risks, recorded rather than solved because they are properties of the work
and not questions to answer:

- **F1's kwargs-split and stdin move is the riskiest single change in the codebase's near
  term.** Identical behaviour must survive across eager click, lazy click, group options and
  stdin markers, on both surfaces. It is defended by `TestWarmBootParity` and the dual-surface
  `cli_run` harness, and by nothing else.
- **F3 re-points the `_app` reads that live zones depend on.** They must move in the same
  commit, with `tests/tui_audit/` green.

## 5. Lifecycle of this document set

Mirrored to `~/code/raicing-ai/run-model/` and committed to
`contributor/architecture/run-model/`. Unlike the pi-workflows set — which lived in
`.spec/shape-intents/` and was removed from the branch before merge — this one lives in
`contributor/architecture/` **permanently**, beside the two audits it merges. It describes a
target the codebase moves toward over several releases, so it must outlive the branch.

Its `Status` line is updated as features land. It is not deleted when they do.

## 6. Document history

| Date | Change |
|---|---|
| 2026-09-09 | Set created. Audits and ADR-020 brought onto `feat/run-model` so citations resolve. Nine features specified and planned |
