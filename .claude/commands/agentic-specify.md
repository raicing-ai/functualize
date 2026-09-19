Specify phase for: $ARGUMENTS

1. Read `.spec/STATE.md` — if absent, treat as: no work in flight
2. Create `.spec/features/<name>/` if it does not exist
3. **Retrieval pass — prior art and premises.** Two questions, before any spec
   prose exists:
   - *Has this already been decided, or gotten wrong, here before?* Search the
     repo's **prose** — `contributor/adr/`, `contributor/guides/`,
     `contributor/reference/pitfalls.md`, `docs/`. Use **zvec-grep**; `rg` does
     not find an argument. A design contradicting one of these must say so and
     why.

     **If there is no index, build one — this is not a blocker and not a
     question to ask.** A fresh checkout or worktree returns
     `[INDEX_MISSING] … requires explicit user authorization`; that
     authorization is standing (maintainer, 2026-09-16). Locate the binary
     (`command -v zg`, else `mise which zg`), then:

     ```bash
     nohup zg index "$(git rev-parse --show-toplevel)" \
       -g 'src/**' -g 'docs/**' -g 'contributor/**' -g 'plugins/**' -g '*.md' \
       --embedding local/potion-code-16m-v2 > /tmp/zg-index.log 2>&1 &
     ```

     Measured 780 files / 12 627 entities / **1 m 17 s** / 81 MB (gitignored).
     Background it and do the second question's `rg` work while it builds.
   - *Are the claims I am about to write true?* Run the command behind every
     count, every "the only", every "nothing does X" — negatives are claims about
     the whole repo and reading cannot establish one. Write the number the
     command returned.

   Findings that change the shape of the feature go in `research.md`; findings
   that are simply true go straight into `spec.md`.
   (`.spec/CONSTITUTION.md` → *Retrieval Before Assertion*; routing table in
   `.claude/skills/code-intel/SKILL.md`.)
4. Write `spec.md` — problem statement, user stories, behavior, acceptance criteria (behavior only, no implementation)
5. Write `contracts.md` — external interfaces only: component props, API response types, event payloads, exported function signatures. NOT database schemas or internal types.
6. Get user confirmation before proceeding to Plan

**Confirmation here is not the last word.** `/agentic-plan` opens with an
architecture gate that draws the BEFORE and AFTER shapes of the region, and that
pass is expected to send work back to this phase: where the diagrams show the
premise, scope or decomposition in `spec.md` is wrong, `spec.md` is **revised**,
not planned around. Re-confirm with the user when it moves. The loop closes when
Plan's AFTER shape holds; from Plan's blast-radius pass onward the spec is fixed.
(`.claude/rules/spec-workflow.md` → *The architecture gate*.)

**A code smell is one of the things that sends work back here.** The gate names
the smells the current design already carries, and checks every candidate AFTER
for the ones it would *introduce*. Either can indict the spec rather than the
approach — a spec whose only clean implementation trades *middle man* for
*shotgun surgery* is a spec asking for the wrong decomposition, and the fix
belongs in `spec.md`. Expect to be handed that finding, and revise rather than
absorb it downstream.
