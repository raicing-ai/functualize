# Spec-driven workflow

This repository specifies non-trivial work before building it. This file is the
single source of that contract; `CLAUDE.md`, the phase commands, and the hook
payloads reference it rather than restating it.

For project commands, architecture, and constraints see [AGENTS.md](../../AGENTS.md).
For the non-negotiables see [.spec/CONSTITUTION.md](../../.spec/CONSTITUTION.md).

## The contract

A feature lives in `.spec/features/<name>/`:

| File | Holds |
|---|---|
| `spec.md` | Behavior — what, not how. Acceptance criteria |
| `contracts.md` | External interfaces: signatures, payloads, declared surfaces |
| `plan.md` | BEFORE/AFTER architecture diagrams, the design skills consulted, a required `## Surviving smells` section, then technical approach, files to change, risks |
| `schema.md` | Internal types, tables (optional) |
| `research.md` | Findings (optional; never a gate) |
| `tasks.md` | Atomized tasks, ending in a `## Task Dependency Graph` JSON wave list |

Those are produced by `/agentic-specify` and `/agentic-plan`, and executed by
`/agentic-execute` against a fixed six-file context anchor. `/agentic-verify`
closes the feature.

Planning or executing non-trivial work here means producing those artifacts and
running the phases — not ad-hoc edits.

## What is mechanically enforced

**Modifying `src/functualize/**` or `plugins/*/src/**` requires an existing
`.spec/features/*/tasks.md` carrying a parseable `## Task Dependency Graph`.**
A `PreToolUse` hook denies the write otherwise.

Not gated, so the Specify and Plan phases work normally: `.spec/`, `tests/`,
`plugins/*/tests/`, `plugins/conftest.py`, every `pyproject.toml`, `docs/`,
`contributor/`, `.claude/`.

The gate fails open. If the validator cannot decide — malformed input, missing
interpreter, unreadable `.spec/` — the write proceeds. A broken validator
degrades to unenforced; it never bricks the repository.

### The exemption

For a change genuinely too small to spec, write `.spec/EXEMPT` containing:

```
Spec-exempt: <reason, at least 20 characters>
```

It is honoured for one hour. Using it appends a record to
`.spec/exemptions.log`, which **is committed** — that ledger is the entire
mitigation for the fact that an agent can exempt itself. Bypassing the workflow
is allowed; bypassing it invisibly is not.

### The shell boundary

The gate sees `Edit`, `Write`, and `NotebookEdit`. A write issued through the
shell — `echo >`, `sed -i`, `tee`, a heredoc — raises none of those and is **not
blocked**. It is instead *recorded*: a `PostToolUse` hook notices that shipped
code became dirty with no task list and no exemption, and appends a
`shell-write:` record to the same ledger.

This is deliberate. Reliably blocking arbitrary shell would mean parsing it,
which is fragile and easy to fool. The gate stops ad-hoc editing; it does not
stop a determined bypass, and does not claim to.

## Version control lifecycle

`.spec/features/` is **tracked on the branch** and **absent from master**.

The artifacts travel with the branch, so a reviewer sees the wave graph and the
acceptance gates the diff claims to satisfy, and they move across worktrees.
Before merge they are cleared: migrate the durable half to `.spec/STATUS.md` or
`contributor/adr/`, then `git rm -r .spec/features/<name>`. The required
`spec-artifacts-cleared` check blocks the merge until that lands.

### Recovering artifacts after merge

Master carries no trace, but squash commits carry `(#N)` and pull-request refs
are retained:

```
git log --oneline master --grep='<feature>'   # -> abc1234 ... (#N)
git fetch origin refs/pull/N/head
git show FETCH_HEAD:.spec/features/<name>/tasks.md
git log --oneline master..FETCH_HEAD          # the branch's real commits
```

Caveats: PR refs are not fetched by default, do not survive a repository mirror
or migration, and are long-standing GitHub behavior rather than a documented
guarantee. Treat this as archaeology, not an archive of record — that is what
the `STATUS.md` migration step is for.

## Plan mode

`permissions.defaultMode: "plan"` is set in project settings, but **the VS Code
extension ignores it**: conversations it starts do not read project settings for
the starting permission mode. VS Code users must set

```
claudeCode.initialPermissionMode: "plan"
```

in their own **VS Code user settings**. No file in this repository can do it for
them.

Plan mode is a convenience, not part of the enforcement. Nothing above depends
on it. Note that plan mode is read-only, so `/agentic-specify` and
`/agentic-plan` — which write `spec.md` and `tasks.md` — cannot run inside it.

## Retrieval discipline

Retrieval is **four named passes across three phases** — never a conditional "if
exploration is needed". Each asks a different question, so a finding that arrives
in the wrong phase arrives too late to act on. Plan carries two, in order: the
architecture gate runs *before* any approach exists to blast-radius.

| Phase | Question | Reach for |
|---|---|---|
| Specify | Has this been decided, or gotten wrong, here before? Are my claims true? | **zvec-grep** for prose (ADRs, guides, `pitfalls.md`); **rg** for every count and negative |
| Plan · 3a — architecture | What shape is the system now, what is wrong with that shape, and what shape should it be after? | **all three**: zvec-grep for a module's prose, serena `get_symbols_overview` for its real surface, graphify `get_neighbors` for dependency direction; plus `contributor/architecture/codemaps/` and the refactoring skills for smell names |
| Plan · 3b — approach | What references this, and what breaks if I change it? | **serena** `find_referencing_symbols`; **graphify** `get_neighbors` |
| Verify | Is anything unreachable? | **serena** — the orphan scan *is* a reference query |

- **Every count, "the only", and "nothing does X" in a spec artifact is verified
  by running the command that would falsify it**, before it is written. A
  negative is a claim about the whole repository; reading a file cannot establish
  one. This is the acceptance-gate rule applied to premises
  (`.spec/CONSTITUTION.md` → *Retrieval Before Assertion*).
- **A task's file list is the hit set of the query that found it**, not a list
  composed from memory.
- **Prior art outranks a fresh argument.** Contradicting an ADR, a guide, or a
  recorded pitfall is allowed; doing it silently is not.
- **Address every tool by absolute path.** Both fail silently, in different
  ways: zvec-grep walks up and adopts the parent checkout's index, and serena's
  registry is path-keyed while every checkout of this repo shares the name
  `functualize` — so a bare name either errors as ambiguous or binds to whichever
  checkout happens to be registered. Either way a branch gets told about master.
- **A tool you cannot reach is not a tool that is absent.** `zg` is installed
  but not on the default PATH, and the zvec-grep MCP server is frequently
  refused; an agent that reads "command not found" as "unavailable" silently
  drops a required pass. Locate the binary before concluding anything — the
  Plan command carries the paths.

Routing (which tool for which question) is
[`.claude/skills/code-intel/SKILL.md`](../skills/code-intel/SKILL.md); timing and
rationale are in `.claude/agents/spec-driven-developer.md` → *Retrieval Passes*.

## The architecture gate

**Plan opens with architecture, not with an approach.** Before `plan.md` names a
file to change, the phase produces a **BEFORE and an AFTER system diagram** of
the region the feature touches, and iterates against `spec.md` until the AFTER
shape is defensible. Only then does 3b (call sites, blast radius, tasks) begin.

This exists because a diagram is the cheapest instrument that finds a
*simplification*. Tracing call sites tells you where a change lands; drawing the
two shapes side by side tells you whether the change is the right one.

### What the gate requires

1. **Map the region with all three retrieval tools** — zvec-grep, serena,
   graphify. Not "if needed": each answers a shape of question the others
   cannot, and the routing table is
   [`.claude/skills/code-intel/SKILL.md`](../skills/code-intel/SKILL.md).
   **Name the smells the BEFORE already carries** while mapping it — by their
   catalogue names, never by invented adjectives (below).
2. **Read the existing codemaps** in `contributor/architecture/codemaps/` —
   `overview.md`, `modules.md`, `dependencies.md`, `data-flow.md`,
   `entry-points.md`. They are the repo's own account of its shape; a diagram
   that contradicts one of them is a finding, not a drawing error.
3. **Draw BEFORE and AFTER.** ASCII, in `plan.md` — it survives in markdown and
   shows up in a diff. A diagram that does not carry all four of the following
   is decoration:
   - every module involved, named by its real path;
   - the **direction** of each dependency between them;
   - which **layer** each module sits in (`_types/`, `_primitives/`, `_events/`
     and the peer layers — `overview.md` → *Audience-Separated Package
     Structure*);
   - what **crosses a boundary**, since seven import-linter contracts in
     `pyproject.toml` decide whether the AFTER shape is even legal.
4. **Iterate between Specify and Plan.** Where the architecture work shows
   `spec.md` was wrong, revise `spec.md` — do not plan around it. Consult design
   pattern and refactoring skills while doing so (below) and name in `plan.md`
   which ones were consulted. **Check each candidate AFTER for the smells it
   *introduces*, not only the ones it removes** — that check is the reason this
   is a loop rather than one drawing.
5. **Declare the surviving smells in `plan.md`**, under their own heading. A
   hard requirement of the phase, on the same footing as the diagrams.
6. **Settle the architecture, then continue.** 3b and `tasks.md` come after.

### The skills to consult

- **This repo ships one:** `.claude/skills/python-design-patterns` (a symlink to
  `.agents/skills/python-design-patterns`), invoked as the
  `python-design-patterns` skill. It covers KISS, separation of concerns, single
  responsibility, God-class decomposition, and composition over inheritance.
- **Then look wider.** Scan the session's available-skills listing for anything
  matching *design patterns*, *refactoring*, or *architecture* and load those
  too. These are per-user and per-machine — one contributor's environment will
  offer skills another's does not, so the instruction is to consult the listing,
  never to follow a hardcoded path. Record the names you actually loaded in
  `plan.md`; a reader must be able to tell which advice was available.

Those skills are also the **vocabulary** for the smell work below. Use their
catalogue names — *long method*, *feature envy*, *shotgun surgery*, *divergent
change*, *middle man*, *primitive obsession* — rather than describing a problem
in your own adjectives. A named smell is one two readers of the same diagram
agree about; "this feels tangled" is not.

**The catalogue is not in this repository.** Measured: none of those six names
appears anywhere in `.claude/skills/python-design-patterns/`, which covers KISS,
separation of concerns, single responsibility, God-class decomposition and
composition over inheritance — principles, not a smell catalogue. All six come
from a **user-level** skill (here, `coding__design-patterns-refactoring`, which
carries the Refactoring.Guru catalogue).

So if the available-skills listing offers no refactoring catalogue, say so in
`plan.md` and name the smells as precisely as you can from the principles the
in-repo skill does cover. Do **not** silently invent names that look
catalogue-shaped — a fabricated term is worse than a plain description, because
it reads as agreed vocabulary when nobody else uses it.

### Code smells: three points, not one

The gate touches smells at three distinct moments, and skipping any one of them
turns the diagrams back into decoration.

| When | What is required |
|---|---|
| **BEFORE pass** (gate step 1) | Name the smells the current design *already* carries, by catalogue name, with the file or symbol each one lives on. Mapping the architecture means diagnosing it, not just drawing boxes. |
| **Each candidate AFTER** (gate step 4) | Check the smells the proposal *introduces*. A god class dissolved across six modules that all change together has traded *middle man* for *shotgun surgery* and is not an improvement. This check is what the iteration is for. |
| **Settled AFTER** (gate step 5) | Declare every smell that survives, in `plan.md`, under its own heading. |

**A forbidden pattern is a blocker, not an accepted compromise.**
`.spec/CONSTITUTION.md` → *Forbidden Patterns* already names specific smells and
rules them out: god-object growth past ~500 LOC, peer-layer cross-imports
(`_discovery` ↔ `_config` ↔ `_engine` ↔ `_plugins`), global mutable state and
module-level singletons, ABC for ports, implicit `Callable` conventions for
ports, hard-coded config paths, `_cli/` importing internals, and others. If the
AFTER architecture carries one of those, **the AFTER is wrong** — remove it or
the plan does not proceed. Only smells *absent* from that list are eligible for
the accepted-compromise section.

**The `## Surviving smells` section in `plan.md` is required.** For each one:
which smell (catalogue name), where (file or symbol), why it is unavoidable or
accepted, and whether it needs maintainer review. **If there are none, say so
explicitly and say why you believe it** — an omitted section is
indistinguishable from an unexamined one, and the Plan phase is not complete
until the section exists in one of those two forms. Silence is the failure mode
this rule exists for: a clean-looking AFTER diagram that quietly keeps a
compromise is worse than one that names it.

**The review flag is raised with the user, not just recorded.** Every entry
marked *needs maintainer review* is put to them at the same point the task list
is reviewed, by name and with its reason, and answered before Execute begins — a
flag written into a file nobody is shown is not a review. Report an explicit
"none" aloud too, so the user can tell the question was asked rather than
skipped.

### Worked example — `store-substrate`

The AFTER diagram is what found the simplification. Mapping the stores produced
(`.spec/features/store-substrate/spec.md` §C–D):

```
BEFORE                                 AFTER

StateStore  (36 methods)               StoreSubstrate
  ├ 11 own                              ├── FreshStore   ~8
  └ 25 ─ pass-through ─┐                ├── ScopeStore    32
                       ▼                └── RunStore      13
                 ScopeStore (32)
RunStore (13) ← already a peer,        three peers, one floor
                inconsistently
```

Drawing it made two things visible that a call-site trace does not. First,
`RunStore` was *already* a peer constructed directly by the engine, so the
existing arrangement was not a design but two halves of one. Second, 25 of
`StateStore`'s 36 methods were pure delegation to the `ScopeStore` it held — so
they are **deleted, not moved**, and the feature shrank from a migration to a
type change in five modules. Neither finding is reachable from "what references
`StateStore`".

**Naming the smell is what made the fix obvious.** 25 of 36 methods forwarding
to a wrapped collaborator is textbook **middle man** — and the standard answer
to middle man is *remove the middle man*, i.e. let callers talk to `ScopeStore`
directly. Recorded as "StateStore is doing too much" it would have suggested
splitting the class; recorded by its catalogue name it pointed straight at
deletion.

**And the AFTER keeps one declared compromise**, which is what the required
section is for. The three stores keep their own per-file discard rules
(`scopes.json` refuses, `state.json` discards) rather than pushing them down
into the substrate — duplication on the face of it, deliberate underneath,
because those rules are "decisions about meaning, not about storage, and
flattening them into the substrate would be the drift this feature exists to
prevent" (`.spec/features/store-substrate/plan.md:43-45`). Not on the
*Forbidden Patterns* list, so it is eligible to be accepted — and it is
accepted **in writing**, with the reason, rather than left for a reviewer to
notice.

## Execution discipline

- **Wave ordering is binding.** Never start a task in wave N+1 while wave N has
  unchecked tasks.
- **Acceptance criteria are gates, run at authoring time**, with the task's file
  scope equal to the gate's hit set.
- **Reachability precedes `[x]`.** Name the production call path, verify it by
  breaking the call and watching a test fail. "A test calls it" is not a call
  path.
- **Commit before sabotaging.** `git checkout -- <file>` reverts everything
  uncommitted in that file.
- **Disclose transitional states**, never disguise them.
- **`.spec/STATE.md` is updated after each task.** It is gitignored and may be
  absent; if so, treat as: no work in flight.
