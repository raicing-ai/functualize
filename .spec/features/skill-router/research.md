# Skill Router — research (Explore phase)

Phase 4 of the decision-layer experiment: select `none` or one or more skills
from a bounded catalog **before** an agent's context is assembled, load only the
chosen definitions, and compare context size, routing correctness, latency, cost
and downstream task success against "load everything" and generative routing.
Scope guard: **bounded catalog**.

This file is findings only. `spec.md` is not written: the change's Shape intent
has not been settled (see *Gate* at the end). Every count below was taken with
the command named next to it, on `master` at `36eaeabf`.

## Findings

### F1 — The bounded catalog already exists: four shipped skills

`find skills -name SKILL.md | wc -l` → **4**: `functualize`, `functualize-app`,
`functualize-cli`, `functualize-skill`. With `none`, a selection has five
single-skill outcomes.

What "load everything" costs, by bytes on disk (`find skills/<name> -type f`):

| skill | files | bytes |
|---|---|---|
| `functualize` | 8 (SKILL.md + 7 references) | 59 285 |
| `functualize-app` | 2 | 17 250 |
| `functualize-cli` | 1 | 15 438 |
| `functualize-skill` | 2 | 18 882 |
| **total** | **13** | **110 855** |

The four `SKILL.md` bodies alone are 46 596 bytes. Token counts are not measured
here; bytes are the only number this file asserts.

The catalog is fixed by the repository, not grown by the router, so the scope
guard holds by construction as long as the catalog is *read* from `skills/` and
never written.

### F2 — A labelled routing set already exists, and every label is single

`evals/suites/triggering.yaml` holds **21** cases (`grep -E '^\s+expect:'`):
`functualize` 7, `functualize-cli` 6, `functualize-app` 3, `functualize-skill`
2, `none` 3. Each case has exactly one `expect`. No case expects two skills.

The skills are written to be disjoint: `functualize`'s description ends "Not
for installing, upgrading, or configuring the `func` tool itself — use
functualize-cli", and `evals/README.md` § *The tool/jobs boundary* records that
an overlap between two descriptions was removed on purpose.

### F3 — The decision seam proposes exactly one option

`DecisionProvider.choose(ChoiceRequest) -> DecisionResult[str]`
(`src/functualize/_types/decision.py:143`) — one value, 2–32 options.
ADR-030 §1 fixes this: "a `Protocol` with one method". `rg -i
'multi|subset|powerset'` over the seam and the Jev plugin returns nothing. So
"one or more skills" cannot pass through the seam as it is. The ways to carry it:

- **one option per skill subset** — 4 skills give 2⁴ = 16 subsets including
  `none`, inside the 32-option cap; the seam does not move, but probability mass
  is split across overlapping subsets, which works against `accept_at`;
- **one yes/no decision per skill** — four `ChoiceRequest`s, four round trips
  through the current seam (Jev batches questions per request, matrix row D2,
  but the seam sends one question per call);
- **primary skill or `none`** — five options, matches every label in F2;
- **widen the seam** — a change to `src/functualize/**`, against ADR-030 §1, and
  close to the "no new authority primitive" guard.

### F4 — "Load everything" is not how the shipped skills are consumed today

`skills/functualize-skill/SKILL.md:84-93`: "The description is the whole
activation surface. It is the only part always in context, and it alone
decides whether the skill ever loads." Agent harnesses already load a skill's
body only after choosing it from the descriptions. So the realistic comparison
is three-way:

| arm | in context before the task | who chooses |
|---|---|---|
| load everything | all bodies (F1) | nobody |
| native routing | the four descriptions | the working agent itself, inside its first turn |
| pre-context router | only what the router chose | a bounded decision provider, before the agent starts |

Against native routing the saving is not skill bodies; it is the
description listing plus the agent's own routing turn on a frontier model. That
changes what the experiment can claim, and the spec has to say which baseline
the headline number is measured against.

### F5 — Generative routing is already measured, by a different harness

`evals/providers/claude_router.py` runs the agent with only the `Skill` tool on
a pinned model (`claude-sonnet-5`) and records which skill fired;
`evals/asserts/skill_selected.py` grades it. It is promptfoo, on demand, not
pytest, and it costs cents per run (`evals/README.md` § *Quickstart*). Phase 3's
generative comparator is a different thing: `tests/hermetic_eval/comparators.py`
`FrontierRouter` answers a `ChoiceRequest` through one CLI call on the
maintainer's subscription (`gpt-6-astra`, effort `medium`).

### F6 — Downstream task success is measured only by the expensive suites

`evals/suites/functualize*.yaml` run the agent to completion in a container:
16 cases across three suites, dollars and ~30 minutes for `functualize` alone
(`evals/README.md` § *The suites*). Nothing cheaper measures whether the right
skill changed the outcome.

### F7 — The Phase 3 instrument is coupled to the four routes

`rg -c 'ROUTES|human_review|cheap_model|frontier_agent|"deterministic"'` over
`tests/hermetic_eval/*.py` → **34** lines across the five non-test modules,
per file below. The generic parts are the ones that speak `ChoiceRequest`:
`FrontierRouter`, `hermetic()`, `identity_sha256`, and the gate-rule arithmetic
in `metrics.accepts`.

| module | route-coupled lines |
|---|---|
| `corpus.py` | 9 |
| `metrics.py` | 12 |
| `comparators.py` | 6 |
| `report.py` | 5 |
| `replay.py` | 2 |

### F8 — Phase 3's result is the premise this phase inherits

Confluence `SD/13959170` v1 (*Hermetic Evaluation — Corpus v1 Results*): verdict
**continue research**; routed accuracy hermetic 0.6650, deterministic 0.6500,
frontier 0.8950; hermetic unsafe-continue 8 cells; availability 0.9950. Jev
routed only marginally better than a regular-expression table on that corpus.
The member chose to continue the plan on 2026-10-10.

### F9 — Frontmatter cannot carry catalog metadata

ADR-006 §5 keeps shipped skills on the portable six frontmatter fields; the
research plan's *Skill packaging* row ("machine-readable metadata: intent,
applicability, … version/hash") therefore cannot land in `SKILL.md` without
changing a shipped, user-visible surface. A catalog declaration has to live in
the instrument and be *derived* from `skills/` (name + description + content
digest).

## Gate — why `spec.md` is not written

The workspace rule: before `spec.md` or `plan.md` for a change, read the
issue's `Shape intent` property and that page's `Authority`; with no value, and
`Shape state` not `not-required`, the spec is not written. The issue carries no
properties at all, and no Confluence page in space `SD` titled for this phase
exists (CQL `space = SD AND title ~ "Skill Router"` → none). Whether this phase
has a user-visible surface depends on where it lives (F9, and the choice of
`tests/` versus `examples/` that Phase 3 also faced), which is the member's
decision.
