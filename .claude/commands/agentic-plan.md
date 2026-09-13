Plan phase for: $ARGUMENTS

Prerequisite: verify `.spec/features/<name>/spec.md` exists and is user-confirmed.

1. Read `.spec/STATE.md` — if absent, treat as: no work in flight

**Steps 2–6 are the architecture gate.** Plan opens with architecture, not with
an approach: nothing below step 7 may name a file to change until the AFTER
shape is settled. Its two hard outputs are the BEFORE/AFTER diagrams and the
`## Surviving smells` section, both written in step 8 — the phase is not
complete without either. The contract and the reasoning are in
`.claude/rules/spec-workflow.md` → *The architecture gate*.

2. **Architecture pass — map the region with all three tools.** Not optional,
   and not the same as step 7's pass: this one asks *what shape is this*, before
   any approach exists to measure blast radius against.
   - *What does the surrounding prose say this is for?* — **zvec-grep**. The
     `zg` CLI is **installed but not on the default PATH** — it lives under
     mise's node install, so `command -v zg` returns nothing and the MCP server
     is frequently refused with a connection error. Neither means absent.
     Resolve it with `mise which zg` (observed here:
     `~/.local/share/mise/installs/node/24.14.1/bin/zg`, v0.2.2) and call it by
     that absolute path. The subcommand is `zg query "<question>"` — there is no
     `search` and no `--root` flag, so the workspace is resolved by **walking up
     from cwd**: run it with cwd at `git rev-parse --show-toplevel` and confirm
     with `zg status`, which prints the root and glob it bound to. Get this
     wrong in a worktree and you are silently told about the parent checkout. An
     index refresh costs ~20 s; budget it rather than skipping the pass.
   - *What is actually in these modules?* — **serena**
     `get_symbols_overview` / `find_symbol` for the real surface, not the
     remembered one. Activate by **absolute path** first:
     `mcp__serena__activate_project("<full worktree path>")`. Every checkout of
     this repo carries `project_name: functualize`, so a bare name is either
     ambiguous or binds to the wrong checkout.
   - *Which way do the dependencies point?* — **graphify** `get_neighbors`
     (an **MCP tool**; the CLI equivalent is `graphify explain "X"`, since
     `graphify get-neighbors` exits `unknown command`). Trust it for
     relationship *shape* and distrust it for line numbers and method lists:
     the committed `graphify-out/graph.json` goes stale between rebuilds. Check
     before relying on it —
     `git rev-list --count "$(python3 -c 'import json;print(json.load(open("graphify-out/graph.json"))["built_at_commit"])')"..HEAD`
     — measured 126 commits behind HEAD on 2026-09-11.
   - *What is already wrong here?* — **name the existing smells**, by catalogue
     name from the refactoring skills (step 5), with the file or symbol each
     lives on: *long method*, *feature envy*, *shotgun surgery*, *divergent
     change*, *middle man*, *primitive obsession*. Mapping the architecture
     means diagnosing it, not just drawing boxes, and a named smell usually
     names its own fix — 25 of `StateStore`'s 36 methods forwarding to a wrapped
     `ScopeStore` is **middle man**, whose standard answer is *remove the middle
     man*. Called "StateStore does too much" it suggests splitting the class;
     called middle man it points at deletion.

   (Routing table — which tool answers which shape of question:
   `.claude/skills/code-intel/SKILL.md`. Do not restate it here; read it.)

3. **Read the existing codemaps** — `contributor/architecture/codemaps/`:
   `overview.md`, `modules.md`, `dependencies.md`, `data-flow.md`,
   `entry-points.md`. They are the repo's own account of its shape, so a map you
   draw that contradicts one of them is a finding to resolve, not a drawing
   error. `overview.md` also carries the layer vocabulary step 4 needs.

4. **Draw BEFORE and AFTER, in `plan.md`.** ASCII — it survives in markdown and
   shows up in a diff. A diagram missing any of these four is decoration:
   - every module involved, named by its real path;
   - the **direction** of each dependency;
   - which **layer** each module sits in — both axes, because they are
     different contracts: the audience split (public `app/ job/ plugin/ types/
     testing/ workflow/` vs. the underscore-prefixed internals) and the internal
     layering (foundation `_types/`/`_primitives/`, then `_events/`, then the
     peer layers `_discovery/ _config/ _engine/ _plugins/`, with `_app/` as the
     only composition root). `overview.md` → *Audience-Separated Package
     Structure* and *Design Principles* are authoritative;
   - what **crosses a boundary** — the seven `[[tool.importlinter.contracts]]`
     entries in `pyproject.toml` decide whether the AFTER shape is legal at all,
     so check it against them (`uv run lint-imports`) rather than discovering it
     in Execute.

5. **Load the design-pattern and refactoring skills before judging the AFTER
   shape.** The repo ships `.claude/skills/python-design-patterns` (a symlink to
   `.agents/skills/python-design-patterns`) — invoke the `python-design-patterns`
   skill. Then scan this session's available-skills listing for anything else
   matching *design patterns*, *refactoring*, or *architecture* and load that
   too; those are per-user and per-machine, so consult the listing rather than
   any fixed path. **Name in `plan.md` which skills you actually consulted** — a
   reader cannot otherwise tell what advice was on the table.

   They are also the **smell vocabulary** for steps 2, 6 and 8 — use their
   catalogue names rather than your own adjectives.

6. **Iterate with Specify until the AFTER shape is good, not merely drawn.**
   Where the architecture work shows `spec.md` was wrong — wrong premise, wrong
   scope, wrong decomposition — go back and revise `spec.md`, then redraw. Do
   not plan around a spec you have just disproved. The loop closes when the
   AFTER diagram is one you would defend in review; record what changed and why.

   **Check each candidate AFTER for the smells it introduces, not only the ones
   it removes.** This is what the loop is *for*. Dissolving a god class across
   six modules that all change together trades *middle man* for *shotgun
   surgery* and is not an improvement. And check the candidate against
   `.spec/CONSTITUTION.md` → *Forbidden Patterns*: if the AFTER carries a
   god-object past ~500 LOC, a peer-layer cross-import
   (`_discovery` ↔ `_config` ↔ `_engine` ↔ `_plugins`), global mutable state, an
   ABC used as a port, or any other entry on that list, **the AFTER is wrong** —
   iterate until it is gone. Those are blockers, never accepted compromises.

   This is the step that pays for the gate. Planning `store-substrate`, the
   AFTER diagram showed `RunStore` was *already* a peer and that 25 of
   `StateStore`'s 36 methods were pure pass-through — so they are **deleted, not
   moved**, and the feature shrank from a migration to a type change in five
   modules (`.spec/features/store-substrate/spec.md` §C–D). Neither finding is
   reachable from "what references `StateStore`".

7. **Retrieval pass — call sites and blast radius.** Now that the shape is
   settled. Not the same pass Specify ran, nor the same one step 2 ran. For
   every symbol the approach touches:
   - *What references this?* — **serena** `find_referencing_symbols`. LSP-accurate,
     so it is the only safe basis for a signature change. It also tells you which
     existing tests change meaning.
   - *What breaks if I change it?* — **graphify** `get_neighbors` for typed,
     directional dependents.
   - *Where is the seam, and is there a name collision?* — read the code the
     answers point at.

   **The task file lists in `tasks.md` are the hit sets of these queries**, not a
   list composed from memory. Anything that reshapes the approach goes in
   `research.md`. Pass an absolute worktree path — without one zvec-grep silently
   answers about the parent checkout.
   (Routing table: `.claude/skills/code-intel/SKILL.md`.)
8. Write `plan.md` — the BEFORE/AFTER diagrams and the skills consulted, then
   technical approach, files to change, dependencies, risks. **A
   `## Surviving smells` section is required**, on the same footing as the
   diagrams: for each smell the settled AFTER still carries, give the catalogue
   name, where it lives, why it was unavoidable or accepted, and whether it
   needs maintainer review. Nothing on the *Forbidden Patterns* list may appear
   here — those had to be removed in step 6. **If there are none, write the
   section anyway and say why you believe that**: an absent section is
   indistinguishable from an unexamined one, and this phase is not complete
   until the section exists as a list or as an explicit reasoned "none".

   Example of a legitimate entry, from `store-substrate`: the three stores keep
   their own per-file discard rules (`scopes.json` refuses, `state.json`
   discards) instead of pushing them into the substrate — duplication on the
   face of it, deliberate underneath, because they are "decisions about meaning,
   not about storage, and flattening them into the substrate would be the drift
   this feature exists to prevent" (`.spec/features/store-substrate/plan.md:43-45`).
   Accepted in writing, with the reason — not left for a reviewer to notice.
9. If implementation internals are complex: write `schema.md` — DB tables, internal types, aggregation schemas
10. Write `tasks.md` — atomic tasks, each ≈ 1–3 files, completable in one context window. End with a `## Task Dependency Graph` section grouping tasks into waves (see spec-driven-developer agent for format and rules).
11. Review task list with user before Execute — and **put the `## Surviving
    smells` entries to them explicitly**, not just the tasks. Every smell marked
    *needs maintainer review* is raised here by name, with its reason, and
    answered before Execute begins. A flag nobody is shown is not a review; if
    the section says "none", say that out loud too, so the user knows the
    question was asked rather than skipped.
