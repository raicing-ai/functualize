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
