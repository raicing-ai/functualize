# Research — did-you-mean-spaced-invocation

Findings that changed the shape of the plan, measured at `d1c7e40`.

## R1 — Blind `.`→space substitution can print a line that does not run

The approved shape (SD/17104932, H1) assumed that every dot in a registered name
separates segments. That is false.

- `_types/naming.py:561-575` (`_job_segments`) derives the leaf by stripping
  the group prefix "rather than `name.rsplit(".", 1)`. The difference matters
  for any leaf carrying a dot of its own."
- `_discovery/providers.py:670-672` (`StaticProvider`): explicit
  `Job(name=…)` wiring keeps a dotted name with no group.
  `normalize_name("tools.lint")` → `tools.lint`, `group=None`.
- Measured through an app's own entry point (`StaticProvider` via
  `JobSources(functions=[Job(lint, name="tools.lint"), Job(build, name="pack", group="ci")])`):

```
registered: [('tools.lint', None), ('pack', 'ci')]
$ app.py tools.lint   -> ran lint, exit=0
$ app.py tools lint   -> Error: Unknown command 'tools'.  exit=1
$ app.py ci pack      -> ran build, exit=0
$ app.py ci.pack      -> Error: Unknown command 'ci.pack'.  exit=1
```

So `name.replace(".", " ")` would print `tools lint`, which fails, and `pack`,
which is not the job's path. That breaks the page's own must-not-change rule,
"each suggestion still exits 0 when pasted into a shell". The page anticipated
this case: "the printed form must come from the trie path, not from string
substitution". This plan does exactly that, through `job_segments`. For every
`JOB_GROUP` job, which covers every case the ticket measured, the output is
identical to substitution.

Not measured: these two names on the `func` door. There, `StaticProvider` jobs
arrive only through a plugin's `add_job_provider` (`docs/guides/subjects.md:125`).
The rendering rule is the same either way, and AC6 pins it at unit level.

## R2 — The app entry point carries the same defect, outside the approved scope

`app/adapters/cli.py:754-764` (`_show_command_not_found`) prints each hit
verbatim, with no program name:

```
$ python app.py suite.inventori
Did you mean:
  suite.inventory
$ python app.py suite inventory   -> exit 0
```

SD/17104932 scopes the fix to `_cli/main.py:1466-1471`, so this door is left
alone. The `cli_run` fixture runs every test on both doors
(`tests/conftest.py:831-836`). The new CLI regression test is therefore
restricted with `@surfaces("func")`, and the parity tests in
`tests/cli/test_unknown_command_parity.py` stay green because they check names,
not lines. The member decides whether this becomes a follow-up.

## R3 — Three derivations of "the spaced command" exist; this adds a fourth caller, not a fourth rule

| Site | Rule |
| --- | --- |
| `_cli/tui/app.py:2333` (`_format_preflight_job_header`) | `job_name.replace(".", " ")` — R1-unsafe |
| `_cli/tui/sync.py:177` (`build_command_line`) | `job_name.split(".")` — R1-unsafe |
| `_types/naming.py:561` (`_job_segments`) | group-prefix strip — the trie's rule |

The hint uses the third. The first two belong to the TUI, which SD/17170435
owns. They are a declared surviving smell, not part of this change.

## R4 — No test pins the dotted hint

`rg -n "func [a-z-]+\.[a-z-]+" tests/`, with file-argument matches removed,
returned 0 hits. `tests/cli/test_unknown_command_parity.py:119` checks
`"Did you mean" in combined` only.
