# Spec — `Did you mean` prints the spaced invocation

## Problem

A grouped job has two spellings that both run: `func suite inventory` and
`func suite.inventory`. When a user mistypes one, the `func` error hint prints
the dotted spelling. Every other surface that shows a group to a person prints
the spaced spelling: the group help, the spaced-typo error, the plugin-namespace
line, the TUI pre-flight header (ADR-009 §6), and the docs. So the error is the
one place that teaches a notation nothing else uses.

The hint itself is right and its suggestion runs. That part is kept.

## Measured at base (`master` `d1c7e40a128f94fce40efa170cdc32ca5c043da8`, 2026-10-16)

Fresh project with an empty `XDG_DATA_HOME` / `XDG_CONFIG_HOME`.
`.functualize/jobs/suite.py` has `JOB_GROUP = "suite"` and the jobs
`inventory` and `versions`. `.functualize/jobs/deploy_web.py` has
`JOB_GROUP = "deploy.web"` and the job `run`. Plugin load-time warnings are
removed from the output.

```
$ func suite.inventori
Error: Unknown command 'suite.inventori'.

Did you mean:
  func suite
  func suite.inventory

Run 'func' to see all available commands.
exit=1

$ func deploy.web.rnu
Error: Unknown command 'deploy.web.rnu'.

Did you mean:
  func deploy
  func deploy.web.run

Run 'func' to see all available commands.
exit=1

$ func versions
Error: Unknown command 'versions'.

Did you mean:
  func suite.versions

Run 'func' to see all available commands.
exit=1

$ func suite
Usage: func suite <command> [options]

Commands:
  inventory  Inventory everything.
  versions   List versions.
exit=0

$ func deploy --help
Usage: func deploy <command> [options]

Sub-groups:
  web
exit=0

$ func suite inventory          -> ran inventory, exit=0
$ func deploy web run           -> ran deploy web run, exit=0

$ func | cat
deploy.web.run — Deploy the web app.
suite.inventory — Inventory everything.
suite.versions — List versions.
mcp — 6 commands (run 'func mcp' to list)
```

## User story

As someone who mistyped a grouped job, I get a suggestion I can copy, and it is
written the way the group help and the docs write it. Then the next thing I read
(`func suite`) agrees with what the error just taught me.

## Behaviour

- **B1.** Each `Did you mean` line on the `func` unknown-command path that names
  a **job** prints that job's command path, with one space between segments:
  the group's segments, then the job's leaf. `suite.inventory` prints as
  `func suite inventory`, and `deploy.web.run` prints as `func deploy web run`.
- **B2.** The leaf is the job's name with its group prefix removed. It is never
  produced by splitting on every dot. A job with no group prints its whole name,
  dots included. That name is one path segment, and the dotted form is the one
  that runs (see `research.md` R1).
- **B3.** A suggestion that is not a job, meaning a group first segment
  (`func suite`) or an ungrouped plugin command, prints exactly as it does
  today.
- **B4.** Which names are suggested, and in what order, does not change. Only
  how a job hit is printed changes.
- **B5.** Every printed suggestion, pasted into a shell from the project root,
  exits 0.
- **B6.** The hint still fires for a retired name (`func versions`, once
  `versions` sits under `suite`), and the suggestion is printed spaced.

## Must not change

- The dotted spelling still runs (`func suite.inventory`, exit 0). Retiring it,
  or warning about it, is the alias/deprecation surface FOSS-117 rejected.
- Registered names, MCP tool names, `rc.invoke`, `deps=`, and state keys stay
  dotted.
- The group help, the sub-group listing and the plugin-namespace line are
  byte-identical to base.
- The non-TTY `func` listing stays dotted. It is a parseable job list (D1(a)).
- The leaf usage line (`func suite.inventory --help` → `Usage: suite.inventory
  [OPTIONS]`) is untouched. It is a follow-up (D1(a)).
- The app entry point's hint (`app/adapters/cli.py:754-764`) is untouched. It
  is outside the approved scope (`research.md` R2).

## Acceptance criteria

| # | Gate | Must hold |
| --- | --- | --- |
| AC1 | `func suite.inventori` | stderr carries the line `  func suite inventory` and does not carry `func suite.inventory`; `  func suite` still present; exit 1 |
| AC2 | Each `func …` line from AC1, AC3 and AC4, run back through the CLI | exit 0 |
| AC3 | `func deploy.web.rnu` | stderr carries `  func deploy web run` |
| AC4 | `func versions` (retired name) | stderr carries `  func suite versions` |
| AC5 | `func suite`, `func deploy --help`, `func \| cat` | output identical to the base text above |
| AC6 | Job-path rendering for a job with no group whose name holds a dot (`tools.lint`), and for a job whose group is not a prefix of its name (`group="ci"`, `name="pack"`) | `tools.lint` and `ci pack`, each equal to the trie's own segments joined by one space |
| AC7 | The regression test for AC1, AC3 and AC4 at base `d1c7e40` | fails there (it checks the printed line, not just `"Did you mean"`), and passes with the fix |
| AC8 | `CHANGELOG.md` | one `### Fixed — <one sentence>` entry under `## [Unreleased]`, in the file's own style |
