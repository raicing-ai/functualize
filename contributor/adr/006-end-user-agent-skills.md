# ADR-006: End-User Agent Skills — Authoring Location and Distribution Strategy

**Status**: accepted — §2 amended by [ADR-009](009-shipping-skills-in-the-distribution.md)
**Date**: 2026-08-27
**Deciders**: Core team, with agent-assisted research

## Context

Functualize users write jobs in *their own* repositories. A coding agent helping
them gets several things wrong by default, because the contracts are invisible
from the file being edited:

- Capabilities are DI-injected by parameter type, not constructed or passed.
- A job is a plain function; `@job` is for declarations, not registration.
- Returning a value does not print it — output goes through `Stdout.emit()`.
- Discovery is convention plus filters, so valid code can be undiscoverable.
- `func` is frequently not on PATH, and the correct prefix depends on how the
  project composes its version and dependency managers.

Documentation does not fix this: docs are read by humans before the work, while
agents need the contract at the moment of writing. Agent Skills are the format
built for that, and the ecosystem has converged on it (Anthropic-authored, now
an open standard with broad client adoption).

The hard part is **delivery**, not authoring. Unlike a hosted service whose
skills describe a remote API, functualize's skills must land in *someone else's
repository*, alongside a specific installed version of the framework.

Three prior-art models were examined:

- **Supabase** — a dedicated `agent-skills` repo, installed globally via the
  skills CLI or as a Claude Code plugin marketplace. Fits a *service*, whose
  users call an API from any language.
- **Laravel Boost** — skills ship inside the composer package; an installer
  command (`boost:install` / `boost:update`) writes them into the user's project
  per detected agent, with guidelines keyed by the *installed* package version,
  and an extension point letting third-party packages contribute their own
  skills. Fits a *framework*, and is the structural analogue here.
- **The skills CLI** (`npx skills add`) — a general-purpose installer covering
  a large number of agents, recording project installs in `skills-lock.json`.

## Decision

### 1. Author in-repo at `skills/`, distribute via the skills CLI and a plugin marketplace

Skills live at `skills/<name>/SKILL.md` in this repository — the layout both the
skills CLI and a Claude Code marketplace consume. This is the single source of
truth regardless of which delivery path is used later.

### 2. Do not build `func builtin agents install` yet

An in-venv installer is the only thing that can resolve the *installed* version,
enumerate *installed plugins*, and write MCP config pointing at the right
interpreter. It is also code we would maintain forever against a churning
agent-path matrix.

At 0.1.0 with one version in the wild, version drift is hypothetical, and the
"living skill" design (defer to `func builtin info` / `why` rather than
describing the API in prose) degrades gracefully when a skill is stale. Build the
installer when one of these fires:

- the first functualize **plugin** wants to ship a skill — the only capability
  the skills CLI structurally cannot provide, since it resolves a git ref rather
  than Python entry points;
- a release with breaking job-authoring changes makes drift real;
- MCP setup friction appears in issues.

When built, it should shell out to the skills CLI for the agent-path matrix
(which accepts local directory sources) rather than reimplementing it, and live
as a sibling of `cache` / `state` / `config` in the `BUILTIN_COMMANDS` registry —
not under `scaffold`.

### 3. Scaffold is not the delivery mechanism

Scaffold output is *user-owned*: written once, hand-edited afterwards, committed.
Framework-authored skills are *framework-owned*: regenerated on every upgrade,
gitignore-able, and needing an `update` verb scaffold has no concept of. Teaching
scaffold idempotent-overwrite semantics would put dangerous semantics next to
`scaffold add job`.

Scaffold does own one skill-shaped thing: a future `scaffold add skill <name>`
emitting a conformant **user-authored** stub, which is exactly its stated intent —
a starting point conforming to standards, with real standards to conform to
(`name` matching the directory, lowercase/hyphen rules, the description's
activation burden).

### 4. Three skills, split by task rather than topic

- `functualize` — reference: editing jobs in an existing project.
- `functualize-app` — procedure: building a well-tested CLI/TUI from scratch.
- `functualize-skill` — procedure: authoring an agent skill whose scripts are
  functualize jobs.

Splitting by topic (jobs / config / workflows) dilutes activation, because every
description competes on the same trigger surface and all begin "functualize…".
Splitting by task does not — the triggers are disjoint. The two procedure skills
compose the reference skill rather than restating it.

### 5. Frontmatter stays on the portable six fields

`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`.
There is no `version`, `triggers`, or `args_schema` in the spec; a version goes
in `metadata.version` and is inert. Claude Code's extra fields are rejected by
claude.ai upload and the Skills API with `Unexpected key(s) in SKILL.md
frontmatter`, so anything published stays on the six.

### 6. Secrets never live in a config file

Credentials come from the environment or `.env`, declared `Secret[str]`. The XDG
config directory is plain TOML at default umask with no encryption, keyring, or
restrictive-permission write path, and is shared by every project on the machine.
Skills must state the *variable name* and let the user choose its home; the value
must never enter the conversation.

For a distributed plugin, the verified bridge from Claude Code's `userConfig` to
functualize's env convention is an `env` mapping in an `mcpServers` block, which
renames the value without it reaching the transcript.

## Consequences

### Positive

- Ships immediately: a directory and a marketplace manifest, no CLI surface, no
  new public API, no tests to maintain.
- One source of truth serves every delivery path, so npx-first is not throwaway
  work — a future installer reads the same directory.
- Skills that defer to runtime introspection cannot go stale in the way prose
  documentation does.
- Skills are installable by people evaluating functualize before adopting it.

### Negative

- ~~No version locking until the installer exists: a user can install skills
  from `master` while running an older release.~~ **Resolved by
  [ADR-009](009-shipping-skills-in-the-distribution.md)**: the skills ship
  inside the wheel and `func builtin skills install` sources them from the local
  directory, so what lands is pinned to the installed release.
- Plugin-provided skills are impossible until then; plugin authors must publish
  separate repositories in the interim.
- Requires Node (`npx`) for the primary install path, which is a real cost for a
  Python framework. Softened by ADR-009: `cp -R "$(func builtin skills path)"/*`
  is a documented, Node-free alternative.

### Neutral

- Third-party skills already vendored under `.agents/skills/` (e.g. `improve`,
  MIT, authored by shadcn; `auditing-python-security`, pinned from
  `wdm0006/python-skills`) must be *referenced*, not redistributed.
- ~~`skills/` is a new top-level directory that is neither packaged nor tested
  by the existing suites.~~ **Resolved by ADR-009**: force-included into the
  wheel and sdist, and covered by `tests/skills/`.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| `func builtin agents install` now | Exact version lock; plugin skills; MCP wiring | Permanent maintenance of a churning agent-path matrix; speculative at 0.1.0 | Deferred, with explicit trigger conditions, not rejected |
| Deliver via `scaffold add skills` | Reuses an existing command | Lifecycle mismatch: scaffold output is written once and owned by the user | Rejected on semantics |
| Separate `functualize-skills` repository | Clean workspace; independent release cadence | Second repo to keep in sync with a framework whose API it describes | Rejected: in-repo authoring costs nothing and cannot drift |
| Five skills split by topic | Smaller files | Five competing descriptions all beginning "functualize…" dilute activation | Rejected for activation, not size |
| Secrets in the XDG config directory | Single location across projects | Plaintext at default umask; shared across all projects; no keyring | Rejected on security |

## Open Questions

- Whether `scaffold init` should invoke the agents installer behind a flag, or
  print the command for the user to run (Laravel Boost does the latter).
- Whether skills installed into a user's project should be committed or
  gitignored (Boost says gitignored, since they are regenerable).
- Two env-var naming conventions coexist — `EnvSource` builds `SECTION_KEY`
  (single underscore) while `_config/job_config.py` builds `JOB__FIELD` (double
  underscore) with a bare `FIELD` fallback. Only the first is documented. Worth
  a separate look; until then, skills must direct users to `func builtin env
  <job>` rather than deriving names by hand. Taken up in ADR-008.
- Config format narrowing (INI removal) is decided separately in ADR-007;
  secret discoverability and detection drift in ADR-008. Both affect what the
  `functualize` skill must teach about config and credentials.
