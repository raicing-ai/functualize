# ADR-009: Shipping agent skills inside the distribution

**Status**: accepted
**Date**: 2026-08-31
**Deciders**: Core team, with agent-assisted research
**Amends**: [ADR-006](006-end-user-agent-skills.md) §2

## Context

ADR-006 authored the skills at `skills/` and deferred any in-venv installer,
accepting one explicit cost:

> **No version locking until the installer exists**: a user can install skills
> from `master` while running an older release.

That cost is real and it is the one that bites first, because the skills
describe an API surface (`func builtin why`, the capability set, the `--output`
vocabulary) that moves faster than the prose does.

Three things were also true when this was revisited:

1. **`skills/` was in neither artifact.** The wheel packaged `src/functualize`
   only; the sdist's `only-include` did not list `skills`. Nothing an installed
   functualize could reach.
2. **No document referenced the directory.** `grep -rl "skills/functualize"`
   over every markdown file in the repo returned nothing — not README, not
   AGENTS.md, not CLAUDE.md. A skill directory nothing points at is one nobody
   loads.
3. **The prose had already drifted**, at a repo with exactly one release. The
   capability table described the per-invocation `State` capability as
   "persistence across runs", documented `TestRunContext()` when the type is a
   builder reached through `.create()`, asserted on a `CapturingLog.messages`
   attribute that does not exist, enumerated `--output` without its default
   `auto`, and pointed users at `uv add functualize` when `click` lives behind
   the `[cli]` extra and a bare install produces a `func` that cannot run.

Item 3 is the important one. It is the same failure the
[rise-of-taskfile](https://github.com/viltohmyst/rise-of-taskfile) framework
shipped at a larger scale — a repository whose entire purpose is validating
taskfiles against a schema, in which every one of eleven agent skills
under-reported that schema's type system and the Copilot instruction file
actively taught the error its own skill listed as mistake #1. The cause was not
carelessness; it was that nothing bound the prose to the code.

## Decision

### 1. `skills/` is a build input

```toml
[tool.hatch.build.targets.wheel.force-include]
"skills" = "functualize/_skills"
```

plus `"skills"` in the sdist's `only-include`. Authored at the repo root, where
the skills CLI and a Claude Code marketplace look for it; carried into the
distribution, where an installed functualize can reach it. One source of truth,
two consumers, no symlink.

The rejected alternative was a symlink from the package into the repo root.
rise-of-taskfile does exactly that (`templates/project/.rise/skills ->
../../../skills/project`) and it silently breaks their installer, whose `find .
-type f` does not traverse symlinked directories — the template ships without
its skills whenever installed from a clone rather than a release tarball.

### 2. `func builtin skills`, a sibling of `cache` and `state`

Four subcommands, all thin:

| | |
|---|---|
| `path` | one bare path, so it composes: `npx skills add "$(func builtin skills path)"` |
| `list` | name, description and path, read from the files |
| `materialize` | copy to `$XDG_DATA_HOME/functualize/skills/func-<version>/` |
| `install` | shell out to `npx skills add <local dir>` |

`install` shelling out is ADR-006 §2's own position — do not reimplement the
agent-path matrix — and it now gets version-locking for free, because the
*source* is the local directory. **This is a smaller change than the installer
ADR-006 deferred, and it retires that ADR's stated Negative.** The remaining
trigger conditions in ADR-006 §2 (plugin-provided skills, MCP wiring) are
untouched and still gate the full installer.

`skills` is not a `scaffold` template. ADR-006 §3 settled that on semantics —
scaffold output is user-owned and hand-edited, these are framework-owned and
replaced wholesale — and the `materialize` verb, which deletes and rewrites,
would be dangerous sitting next to `scaffold add job`.

### 3. Package data is the source; XDG is a version-stamped cache

There is no install-time hook to write to. `pip install` and `uv add` run no
code, wheels have no post-install step, and PEP 517 provides nothing — so
"write the skills when func is set up on the host" does not exist as a moment.
What exists is *first run*, which makes materialization an explicit command
rather than a side effect.

For most callers the copy is unnecessary: `func builtin skills path` points at
the wheel's own directory, which is exactly the running version and can never be
stale. `materialize` earns its place when the environment holding the wheel is
disposable (`uvx`, a PEP 723 script env, a rebuilt venv) or when a project that
does not depend on functualize still needs a stable path.

**The version stamps the parent directory, never the skill directory.** The
Agent Skills spec requires a skill's `name` to equal its directory name, so
`…/func-0.1.0/functualize/SKILL.md` is conformant and
`…/functualize-0.1.0/SKILL.md` is rejected on upload. Old version trees are
kept by default — one may still be referenced by a project's agent config —
and removed with `--prune`.

### 4. The location is surfaced, and computed

One line in the `func --help` epilog, and a section in `func builtin info`.
`--help` prints on every mistyped command, so it gets the pointer and nothing
more; `builtin info` gets the answer, because that is where all four skills
already instruct an agent to look first.

Both render a resolved path. rise-of-taskfile's README, `CLAUDE.md` and
`.github/agents/README.md` name three different skill locations, and the one
`CLAUDE.md` gives Claude is a directory Claude does not read.

### 5. Four skills, split by task

`functualize-cli` joins the three from ADR-006 §4, covering the operator
surface: installing, upgrading, which environment `func` lives in, the XDG
layout, settings precedence, the TUI, cache and state, completions, and where
the skills themselves come from.

It passes ADR-006's own trigger-disjointness test — "func: command not found",
"configure the TUI", "clear the cache" do not compete with "editing jobs.py" —
which is why it is a skill rather than a reference. The two smaller requests
that arrived with it did **not** clear that bar and became references instead:
single-file scripts (`functualize-app/references/standalone-scripts.md`, shared
with `functualize-skill`, whose §3 was already teaching it inline) and the
intent→mechanism index (`functualize/references/idiomatic.md`).

### 6. `tests/skills/` binds the prose to the code

Every API name in a shipped skill is a claim, and the suite checks it:

- **frontmatter** — portable six only, `name` equal to the directory, the
  description within its cap, `metadata.version` equal to the package version;
- **capability table against the executor's own injection dispatch**, read by
  regex from `_create_capability` so a restructure fails the test — which is
  exactly when the table needs a human;
- **every backticked CamelCase name** against `__all__` of the five public
  modules, with a short explicit allowlist for third-party and placeholder
  names, so an unknown name fails rather than passing silently;
- **`func builtin …` strings** against `BUILTIN_COMMANDS`, **exit codes**
  against `ExitCode`, **template names** against the scaffold registry,
  **`--output` values** against the dispatch table;
- **packaging** — the force-include mapping, the resolver's ordering, and the
  materialize semantics.

Five of the drifts listed in Context were found by writing these tests, not by
reading.

## Consequences

### Positive

- Skills are version-locked to the installed functualize with no new
  maintenance surface: the pinning falls out of using a local directory.
- The distribution can answer "what do you teach an agent, and where is it"
  without network access or Node.
- Documentation drift in the skills is now a build failure. This is the
  property the framework already enforces for taskfile-shaped things and did
  not enforce for the documents describing itself.
- `npx` becomes optional rather than required: `cp -R "$(func builtin skills
  path)"/*` is a documented path.

### Negative

- `skills/` is now load-bearing for the build. Deleting or moving it breaks
  packaging, which is what `tests/skills/test_packaging.py` exists to catch.
- The frontmatter parser in `_cli/skills.py` is a deliberate YAML subset. It is
  bound to the shipped files by test, so it cannot silently under-read them, but
  a contributor authoring exotic YAML will be told to stop.
- Four skills is one more description competing on the "functualize…" trigger
  surface than ADR-006 planned for. Mitigated by leading each description with
  distinguishing tokens, not by the word functualize.

### Neutral

- `metadata.version` is inert to every client and now pinned to the package
  version by test. It exists so a materialized skill self-identifies.
- The materialized tree is disposable. Nothing reads it back; it is a
  convenience for pointing an agent at a stable path.

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| Symlink `functualize/_skills` → `../../skills` | Breaks on any consumer that does not traverse symlinks; the exact defect rise-of-taskfile ships |
| Move the canonical directory into `src/functualize/_skills/` | Loses repo-root discoverability for the skills CLI and a marketplace, for no gain over `force-include` |
| A custom hatch build hook | More machinery than a declarative `force-include` mapping, and a second place to keep correct |
| Write skills to XDG at install time | No such moment exists — wheels run no code on install |
| `func builtin agents install` (the full ADR-006 installer) | Still deferred, on its original reasoning. This ADR takes the version-locking benefit without the agent-path matrix |
| Version-stamp the skill directory (`functualize-0.1.0/`) | Violates the spec's `name` == directory rule; rejected on upload |
| Leave conformance to review | The thing that already failed. Five drifts existed at one release, all of them review-invisible |
