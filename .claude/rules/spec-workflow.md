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
| `plan.md` | Technical approach, files to change, risks |
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

Retrieval is **three named passes**, one per phase — never a conditional "if
exploration is needed". Each asks a different question, so a finding that arrives
in the wrong phase arrives too late to act on.

| Phase | Question | Reach for |
|---|---|---|
| Specify | Has this been decided, or gotten wrong, here before? Are my claims true? | **zvec-grep** for prose (ADRs, guides, `pitfalls.md`); **rg** for every count and negative |
| Plan | What references this, and what breaks if I change it? | **serena** `find_referencing_symbols`; **graphify** `get_neighbors` |
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
- **Pass an absolute worktree path.** Without one, zvec-grep walks up and
  silently answers from the parent checkout's index — so a branch gets told about
  master.

Routing (which tool for which question) is
[`.claude/skills/code-intel/SKILL.md`](../skills/code-intel/SKILL.md); timing and
rationale are in `.claude/agents/spec-driven-developer.md` → *Retrieval Passes*.

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
