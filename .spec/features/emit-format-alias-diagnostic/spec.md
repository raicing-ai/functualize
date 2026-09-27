# emit-format-alias-diagnostic

## Problem

`func`'s early (pre-boot) parse lets two of its flags take a value **optionally**.
`--emit-format` and `--perf-report` are listed in `GLOBAL_OPTIONS_OPTIONAL_VALUE`
with their accepted values in `OPTIONAL_VALUE_VALID_SET`
(`src/functualize/_types/flag_grammar.py:68,76`), and every reader of that table
decides what the token after a bare flag means by asking whether it belongs to
the flag's accepted set. A token outside the set is left standing as a *command
candidate*: today `func --emit-format greet` runs `greet` with the default format.

That lookahead makes one token mean two things at once, and the two meanings are
resolved by different code at different times:

- **pre-boot** — `_cli/dispatch.py::detect_mode` (`:159-167`) consumes the flag
  alone and classifies the token as the command; `_cli/dispatch.py::_extract_global_options`
  (`:357-368`) assigns the flag's *default* value and leaves the token at
  `first_positional_index`.
- **post-boot** — `_cli/main.py::_handle_job` (`:1489-1494`) re-walks the same
  prefix through `_cli/dispatch.py::refused_optional_value` (`:572`, whose
  re-decision is `:595-600`), which
  asks the opposite question and re-decides the same token as the value the flag
  refused.

With `[aliases] shortcut = "absent"` and no `absent` job, the reported
consequence (PR #51 review, finding 1) is:

```
$ func --emit-format shortcut
Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'shortcut'.
```

Exit 1. The same token in command position reports the repair the operator
actually has to make:

```
$ func shortcut
Error: Alias 'shortcut' maps to job 'absent', which was not found.
```

The token was resolved as a command pre-boot — the alias error proves the run
reached `_handle_job` — and rejected as a flag value post-boot, so the alias
diagnostic the finding asks for is unreachable on exactly the spelling that
needs it. An operator is sent to repair a `--emit-format` value that is not the
setting at fault.

**The rule that replaces the lookahead** (member decision, 2026-09-27T10:54:24Z):
in `func`'s early (pre-boot) parse a flag is **either boolean, or its value is
mandatory** — never optional, never defaulted. With no optional-value flag there
is no position in which a token might be a command, so the misdiagnosis class
cannot exist rather than being re-ordered.

The earlier draft kept the optional value and moved the diagnostics (recognize
the command first, report the flag value only if command resolution misses).
That approach is **withdrawn**: it keeps the two-meaning token and would add a
third place that decides what the token means.

## Behavior

- **B1 — one arity per flag.** Every flag the pre-boot router reads is boolean
  or value-required, and the vocabulary says so in two tables.
  `GLOBAL_BOOL_FLAGS` (6 members) consumes no token; the value-required table
  (16 members) consumes exactly one. `--perf-report` and `--emit-format` move
  from the optional-value table into the value-required table. A boolean flag
  has no accepted-values set.
- **B2 — a value-required flag always takes the next token.** `func --emit-format json greet`
  and `func --emit-format=json greet` remain valid: a value, then the command.
  The spaced form takes the next argv token whatever it looks like — an accepted
  value, a job name, an alias key, another flag (`--force`, `--no-dotenv`), an
  unrecognized flag, or a bare `-`. There is no exception for a token that
  starts with `-`, and no exception for a token that names a job or an alias.
  This is the rule the always-value flags already have (`func --log-level --force`
  reports `Error: --log-level must be one of CRITICAL, DEBUG, ERROR, INFO, WARNING,
  got '--force'.`) and the rule Click applies to a value-required option on an
  app's own surface.
- **B3 — a value flag with no value is a usage error.** When a value-required
  pre-boot flag is the last token of argv, `func` exits `2` with
  `Error: <flag> requires a value: one of {<accepted values>}.` — the
  accepted-values clause for a flag that declares a selection table, and
  `Error: <flag> requires a value.` for one that does not. This is new behavior
  for **every** value-required flag, not only the two: `func --log-level`
  currently lists the jobs and exits 0, and `func --emit-format` currently runs
  bare mode.
- **B4 — no command or alias resolution in value position.** The value of a
  value-required flag is never looked up as a job, a group, a plugin command or
  a configured `[aliases]` key. `func --emit-format shortcut` now reports
  `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'shortcut'.`
  and mentions no alias; `--emit-format greet` no longer runs `greet`. The
  invalid-value diagnostic is exit `1`, unchanged
  (`_cli/dispatch.py::_assign_option`, `:545-555`).
- **B5 — command-position diagnostics are unchanged.** `func shortcut` still
  reports `Error: Alias 'shortcut' maps to job 'absent', which was not found.`
  (exit 1); `func bogus` still reports `Error: Unknown command 'bogus'.`;
  `func --emit-format json shortcut` and `func --emit-format=json shortcut` —
  explicit value, then command — report the alias error too. This is what makes
  the finding reachable rather than hidden: the alias diagnostic now appears on
  every spelling in which the token is a command.
- **B6 — this supersedes the earlier acceptance criterion AC1, deliberately.**
  The withdrawn draft required `func --emit-format shortcut` to print the alias
  error. Under the confirmed rule that spelling is not a command reference at
  all — the token is the flag's value, and it is invalid — so it reports the
  invalid-value sentence and never mentions `absent`. The finding's
  operator-facing requirement (the caller must be told which setting to repair)
  is met by B5: the alias error survives wherever the alias is in command
  position, unreachable from value position. **This is a behavior change to a
  documented spelling, and it is item (d) of the confirmation list below.**
- **B7 — explicit values, absent-flag defaults and boundaries stay as they
  are.** `--emit-format auto|json|ndjson|none|raw` and `--perf-report text|json`
  remain valid wherever they are valid today, including
  `func --emit-format auto greet` (the default is still typeable by name); an
  *absent* `--emit-format` still means `auto` and an absent `--perf-report`
  still means `text` for the run; `func greet --emit-format json` and
  `func --emit-format json builtin version` still fail as job-level
  `No such option '--emit-format'` (exit 2); `func bogus` is still an unknown
  command; the job-name/alias precedence documented in
  `contributor/architecture/codemaps/data-flow.md:57` is unchanged. The
  `--flag=value` split is unchanged; `--emit-format=` (empty value) is an
  invalid value, not a missing one.
- **B8 — the rendered and documented surfaces follow the grammar.** The
  `func --help` run-options row renders `--emit-format TEXT` with its accepted
  values in the prose (`Format: auto, json, ndjson, none or raw.`), matching the
  convention `--perf-report TEXT` already uses, instead of today's
  `--emit-format [auto|json|ndjson|none|raw]` bracket that advertises an
  optional value. The app's own entry point (`app/adapters/cli.py`) declares
  `--emit-format` without `flag_value`, so a value is required there too.
  Prose that reasons from the optional value (`docs/api/types.md:150-187`,
  `contributor/architecture/surface-boundary.md`,
  `contributor/architecture/run-model/06-outcome-authority.md:126-150`) is
  updated in the same change; the constitution's rule is that a code change owes
  the docs that describe it.

## Acceptance criteria

- **AC1.** With `[aliases] shortcut = "absent"` and no `absent` job,
  `func --emit-format shortcut` exits 1, stderr contains
  `Error: --emit-format must be one of {auto, json, ndjson, none, raw}, got 'shortcut'.`,
  and stderr contains no `Alias` and no `absent`. `func --perf-report shortcut`
  behaves the same with the `--perf-report` set.
- **AC2.** With the same configuration, `func shortcut` exits 1 with
  `Error: Alias 'shortcut' maps to job 'absent', which was not found.`;
  `func --emit-format json shortcut` and `func --emit-format=json shortcut`
  report the same alias error.
- **AC3.** `func --emit-format json greet` and `func --emit-format=json greet`
  run `greet` with `json`; `func --emit-format auto greet` runs it with `auto`;
  with an absent `--emit-format` the run still uses `auto`.
- **AC4.** `func --emit-format` (nothing after it) exits 2 and prints
  `Error: --emit-format requires a value: one of {auto, json, ndjson, none, raw}.`.
  The same holds for `func --perf-report`, and for a value-required flag with no
  selection table (`func --config-directory` exits 2 with
  `Error: --config-directory requires a value.`) — for every member of the
  value-required table, including the 14 that already require a value.
- **AC5.** A token that merely *starts with* `-` is a value:
  `func --emit-format --force greet` and `func --emit-format -x greet` exit 1
  with the invalid-value sentence for `--force` / `-x`, and `greet` does not run.
  `func --emit-format=` exits 1 with `got ''.`
- **AC6.** `func greet --emit-format json` and `func --emit-format json builtin version`
  exit 2 with `No such option '--emit-format'`; `func bogus` exits 1 with
  `Unknown command 'bogus'`; `func --version` still prints the version and
  `func --emit-format --version` exits 1 with the invalid-value sentence and
  prints no version.
- **AC7.** `func --help` shows `--emit-format TEXT` with the accepted values in
  its description and no `[auto|json|ndjson|none|raw]` bracket.
- **AC8.** The grammar publishes two arity tables and one selection table, and
  no spelling of "optional value" survives in `src/**`. A parity test asserts
  that for every flag in the value-required table, `_extract_global_options`
  and `detect_mode` treat the following token as a value and raise the usage
  error when there is none — the shape
  `contributor/reference/pitfalls.md:318-346` asks for a rule spelled in several
  places.
- **AC9.** The app's own surface requires a value for `--emit-format`:
  `main.py --emit-format emit` exits 2 with
  `Error: Option '--emit-format' requires an argument.` (Click's message), and
  `main.py --emit-format json emit` still renders as it does today. `--perf-report`
  on that surface is unchanged.

## Blast radius (verified)

Every count and every "only" below was produced by running the command that
would falsify it (`.spec/CONSTITUTION.md` → *Retrieval Before Assertion*).

**The four grammar names this replaces** — 118 occurrences, by `rg -c`:
`OPTIONAL_VALUE_VALID_SET` 49, `GLOBAL_OPTIONS_OPTIONAL_VALUE` 24,
`GLOBAL_OPTIONS_ALWAYS_VALUE` 23, `GLOBAL_OPTIONS_WITH_VALUE` 22. They live in 6
source files (`_types/flag_grammar.py`, `_cli/dispatch.py`, `_cli/main.py`,
`app/utils.py`, `types/__init__.py`, `app/adapters/cli.py`), 9 test files and 3
documentation files (`docs/api/types.md`, `CHANGELOG.md`,
`contributor/architecture/surface-boundary.md`).

**Behavior change is not limited to the two flags.** With 16 value-required
flags, every one of them gains the "requires a value" error, and a bare
optional-value flag no longer leaves the next token alone — so any script
relying on `func --perf-report --perf-filter=X job` or
`func --emit-format --force job` changes from exit 0 to exit 1. `--perf-filter`
is in `GLOBAL_OPTIONS_ALWAYS_VALUE`, so that pairing is a real, currently working
spelling.

**Tests that pin the optional-value spellings and must be inverted, rewritten or
deleted** — 6 files, 15 assertion sites (`rg` for a flag literal followed by a
token outside its accepted set, then read at each hit):

| File | Sites |
|---|---|
| `tests/_cli/test_dispatch_bug_condition.py` | `:109`, `:128`, `:154`, `:194`, `:214`, `:227`, `:249` (its whole premise is the release behavior) |
| `tests/cli/test_early_parse_integration.py` | `:42`, `:62`, `:85` (`--perf-report --no-dotenv forecast`) |
| `tests/_cli/test_perf_report_integration.py` | `:63`, `:79` (module docstring `:16-17` narrates the lookahead) |
| `tests/cli/test_emit_format_rename.py` | `:88-96` (`test_a_bare_flag_still_falls_back_to_the_default`) |
| `tests/cli/test_emit_format_discoverability.py` | `:106-111` (`TestTheLookaheadIsUnchanged::test_a_bare_flag_before_a_job_still_runs_it`), module docstring `:6-7,:15` |
| `tests/cli/test_dispatch_characterization.py` | `:71-73` (`test_optional_value_flag_releases_an_invalid_value`) |

**Tests that read the tables and need the rename only** — 5 files:
`tests/types/test_flag_grammar_roundtrip.py` (`:201-214` pins the release itself
and is rewritten, not renamed), `tests/types/test_flag_grammar_consumer_count.py`
(pins the spelling set in `_PATTERN` and the consumer list),
`tests/test_public_api_surface.py`, `tests/cli/test_app_surface_output_format.py`
(`:23`), `tests/skills/test_api_claims.py` (`:288`). Two further assertions move
with B8: `tests/cli/test_emit_format_discoverability.py:52` (the help row) and
`tests/cli/test_version_flag_position.py` (the `--version` scan's arity).

**Not affected**, checked rather than assumed: `tests/_cli/test_dispatch_preservation.py`
(its optional-value cases use explicit accepted values or `=` syntax),
`tests/perf/test_cli_perf_report.py` (app surface, explicit values),
`tests/_cli/test_dispatch_manifest.py`-style prose mentions, and
`app/adapters/workflow_flags.py:95,124` — that module's
`is_flag=False, flag_value=_OMITTED` is a job-level workflow flag parsed by Click
*after* the command, where no command candidate can follow, so the pre-boot rule
does not reach it.

## Scope boundary

This change is `func`'s pre-boot routing and the grammar it reads. It does not
extend `[aliases]` resolution to an app's own entry point (the deferred gap in
`.spec/STATUS.md` #40), does not touch alias configuration syntax, does not
change what an accepted value does at run time, and does not add a shim or alias
for any removed grammar name — this is pre-release, and the constitution says
delete rather than shim. `_cli/dispatch.py::ParsedGlobalOptions.first_positional_index`
has no consumer outside `dispatch.py`, so re-basing it on the new arity is
internal.

## Decision list carried into confirmation

1. **(a)** A valueless value flag exits **2** (usage). The invalid-value path
   stays **1**, so a missing value and a wrong value differ by exit code. The
   alternative — flatten both to 2 — is a one-line change plus four test
   updates, and is the doctrine `docs/cli/modes.md:144-148` and
   `contributor/reference/pitfalls.md:485-490` describe.
2. **(b)** The next token is the value even when it is another flag
   (`--force`, `-x`). This is what `--log-level` already does and what Click
   does; it is a behavior change for the two flags' users.
3. **(c)** The app's own entry point follows the same rule: `--emit-format` there
   loses `flag_value`, so a valueless `--emit-format` is an error on that surface
   too. The alternative is to leave it optional there and document the
   divergence.
4. **(d)** The re-draft supersedes the earlier AC1 (see B6): the alias error is
   no longer reachable from `func --emit-format shortcut`.
