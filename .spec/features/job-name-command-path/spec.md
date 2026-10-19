# One job namespace across human and program surfaces

Status: behavior confirmed by the member's approval of SD/19595276 v2 on 2026-10-19. This specification carries that ruling, including N1-a, N2 and N3. It replaces the narrower proposals on the two retired branches.

## Problem and users

A person using `func`, an application's own CLI, or the TUI can see different spellings for the same job. A name collision can silently make one author's job unreachable. The user needs a command shown in a shell to run when copied, and a collision warning where that command is discovered or invoked. Programs still need the stable dotted job identity.

## Behavior

1. A job has one dotted identity for programmatic references and JSON. The existing normalization and deterministic collision winner stay intact.
2. A shell displays a job's command path using its actual group segments and leaf, including a literal dot inside a leaf when that is part of the name. Both `func` and an application's CLI show the full program and command path in leaf usage. Hints, root and group help, the non-TTY listing, resume hints, TUI browser, pre-flight header, SmartBar, bar text and presets agree on that path.
3. Shell input navigates groups with separate tokens. A dotted token that attempts to traverse a group is refused with the established “navigate groups with spaces” hint and a non-zero exit. A literal-dot leaf that is one path segment remains invocable. Programmatic references continue to use dotted identity: MCP tool names, `rc.invoke`, `deps=`, `FromJob`, state keys, `[aliases]` targets, and JSON.
4. The TUI navigates groups from discovered jobs even when the project declares no `GroupOptions`. Group flags still work at their declaring position in a path and remain job arguments after the leaf. Completion labels retain their provenance, including `(local)` and `(job)` where applicable.
5. A job-name collision remains a warning: one deterministic claimant runs. Each existing finding is visible on invocation as one stderr line, in group help, `info jobs` text and JSON, the full `info` report, and the TUI browser and pre-flight. Shell text names the command path; JSON names the dotted identity. The finding identifies both function names, both real source files where file-backed, the surviving claimant and the action to rename one. A clean job has no warning. Cold and warm discovery agree.
6. Root `func --help` lists top-level jobs and groups as shell command paths, alongside the reserved builtin subtree.

## Acceptance gates (SD/19595276 E1–E8)

| # | Run | Must hold | Falsifies |
| --- | --- | --- | --- |
| E1 | `func suite.inventori`, `func deploy.web.rnu`, `func versions` | spaced suggestions, each exits 0 when pasted | rules 2, 3 |
| E2 | `func suite inventory --help`, app `suite inventory --help` | `Usage: func suite inventory [OPTIONS]` / `Usage: <app> suite inventory [OPTIONS]` | rule 2 |
| E3 | `func suite.inventory` | refused with the spaces hint, exit non-zero | rule 3 |
| E4 | TUI, no `GroupOptions`: `audit` | `explain`, `notes` with `(local)` / `(job)`; no `builtin` | rule 4, H2 |
| E5 | `status` and `status_` in `tools` (one file, then two): run, group help, `info jobs` (text/JSON), TUI browser | the finding on each; shell text says `tools status`, JSON says `tools.status` | rule 5, N2 |
| E6 | `Job(name="tools.lint")`, `Job(name="pack", group="ci")`, nested `deploy.web.run` | every printed path runs | H1 |
| E7 | root `func --help` | lists `hello` and `suite` | N3 |
| E8 | ratchet test over `src/` | no `replace(".", " ")` / `split(".")` on a job name outside `_types/naming.py` | rule 2 |

## Boundaries

The in-scope and out-of-scope surfaces are the approved page's *Boundaries and non-goals* table. In scope: every shell surface that prints or accepts a job, the always-built TUI group trie, collision surfacing on CLI and TUI, and root `func --help`. Out of scope: `normalize_segment`, the naming rule, `GroupOptions` flag grammar, discovery refusal on collision, flag-name defects, `@job(name=)` override, and the unmeasured standalone `Usage: -c` report. The existing `discovery_failures` payload and its full-info rendering remain compatible. No programmatic dotted identity is replaced by a command path.

## Delivery

One spec package, branch and PR carry the three defects together before the 0.5.0 tag. Add one hand-written `CHANGELOG.md` entry under `## [Unreleased]`. Preserve the two retired branches as research records.
