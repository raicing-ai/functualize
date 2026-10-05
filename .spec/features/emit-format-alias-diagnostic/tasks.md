# Tasks — `emit-format-alias-diagnostic`

**One arity per pre-boot flag.** The optional-value lookahead is withdrawn: `--emit-format`
and `--perf-report` join `GLOBAL_OPTIONS_ALWAYS_VALUE`, `GLOBAL_OPTIONS_OPTIONAL_VALUE` is
deleted, and every value-required flag reports a missing value at `ExitCode.USAGE (2)`.

Contracts: `.spec/features/emit-format-alias-diagnostic/spec.md` (AC1–AC9) and
`contracts.md`. Approach, smells and risks: `plan.md`. `schema.md` is not written — this
feature changes no table, type or aggregation shape; it deletes one frozenset and rewrites
three walks over an existing one.

Every gate below was **run at authoring time** and its hit set recorded; the counts are the
ids `pytest --collect-only -q -p no:randomly` returned at `3cb96a5`. A file list equal to a
gate's hit set is the point: an executor who does exactly what `[F]` says must land green.

---

## Wave 0

### T1.1 — One arity in the grammar and in the pre-boot parser `[ ]`

**Goal.** Delete the optional-value vocabulary from the grammar and from its two pre-boot
consumers, and make "a flag that takes a value requires one" the single rule in
`detect_mode`, `_extract_global_options` and the `--version` scan.

- Grammar: add `--perf-report`, `--emit-format` to `GLOBAL_OPTIONS_ALWAYS_VALUE` (14 → 16);
  delete `GLOBAL_OPTIONS_OPTIONAL_VALUE` and its `__all__` entry; set
  `GLOBAL_OPTIONS_WITH_VALUE` to the same 16-member frozenset (it is the global-flag
  detector's table and must not lose the two); keep `OPTIONAL_VALUE_VALID_SET` verbatim in
  name and shape (`(frozenset, default)`) with a `# TRANSITIONAL(emit-format-alias-diagnostic)`
  note that the name and the duplicate value-set name are pending a separate rename.
- `app/utils.py`, `types/__init__.py`: drop the name from the import block and `__all__`.
- `_cli/dispatch.py`: drop the name from the `functualize.app.utils` import; add
  `ExitCode` to it (`_cli/builtins.py:23` is the precedent for taking it through
  `functualize.app.utils` — contract 6 forbids `_cli` → `functualize._types` directly).
  Add three pure helpers and one scan:
  - `is_reserved_pre_boot_token(token)` → `is_known_global_flag(token) or
    token.split("=", 1)[0] == "--version"`.
  - `value_required_takes_next(flag_token, next_token)` → `next_token is not None and not
    is_reserved_pre_boot_token(next_token)`.
  - `missing_value_message(flag)` → `Error: {flag} requires a value.`, or
    `Error: {flag} requires a value: one of {values}.` when `flag in OPTIONAL_VALUE_VALID_SET`.
  - `version_requested(argv_tail)` — the position-aware prefix scan, extracted from
    `_cli/main.py:2050-2051` so the AC8 parity test can reach it.
  Rewrite the `GLOBAL_OPTIONS_ALWAYS_VALUE` branch of `detect_mode` to `i += 2 if
  value_required_takes_next(arg, nxt) else 1` and delete the lookahead branch beside it;
  in `_extract_global_options` replace the ALWAYS missing-value `break` with
  `print(missing_value_message(arg), file=sys.stderr); raise SystemExit(ExitCode.USAGE)`
  and delete its lookahead branch; change **all four** `_assign_option`-family
  invalid-value exits from the literal `1` to `ExitCode.USAGE` — `--emit-format` (`:554`)
  and `--perf-report` (`:547`), plus the two the first draft left alone, `--log-level`'s
  validation (`:389`) and `--discovery-depth`'s non-integer parse (`:523`) — so that after
  this task `_cli/dispatch.py` contains no `SystemExit(1)`; delete
  `refused_optional_value` and its callers; correct the `invalid_value_message` docstring,
  which currently describes optional values. Leave the `--flag=value` path, the
  positional break, `GLOBAL_BOOL_FLAGS` and `is_known_global_flag` untouched.
- `_cli/main.py`: delete the `refused_optional_value` consumer block
  (`_handle_unknown_command:1478-1500`) and its local import; replace the version scan
  (`:2012-2058`) with `version_requested(sys.argv)`; render the help row
  (`_format_options`:79-96) as `--emit-format TEXT` with the accepted values and the
  absent default moved into the description prose, still built from
  `OPTIONAL_VALUE_VALID_SET`.

**Files (5).** `src/functualize/_types/flag_grammar.py`,
`src/functualize/app/utils.py`, `src/functualize/types/__init__.py`,
`src/functualize/_cli/dispatch.py`, `src/functualize/_cli/main.py`.

**Gate (acceptance, run at authoring time).**
`rg -n "GLOBAL_OPTIONS_OPTIONAL_VALUE|refused_optional_value" src/ functualize 2>/dev/null` →
**no matches** (0 at authoring); plus `uv run python -c "import functualize.types,
functualize._cli.main, functualize._cli.dispatch"` → exit 0. Hit set = the two files the
first command's pattern lives in, both listed above, plus the import graph of the second.
Second command, for the Q1 half: `rg -n "SystemExit\(1\)" src/functualize/_cli/dispatch.py`
→ **no matches** (4 at authoring, at `:389`, `:523`, `:547`, `:554`).

**Invariants.**
- No module is added and no `_types → _cli` edge is created; `lint-imports` stays 7/7.
- `GLOBAL_OPTIONS_WITH_VALUE` and `GLOBAL_OPTIONS_ALWAYS_VALUE` have identical members
  after this task; `is_known_global_flag`'s answer for `--version` does not change.
- `--emit-format=json` (equals form) and every `=`-style path consume exactly as before.
- Every invalid value among the 16 value-required flags exits 2 through
  `ExitCode.USAGE` — including `--discovery-depth abc` and `--log-level bogus`, which exit
  2 after this task (Q1, answered 2026-10-05). Command-position errors keep their existing
  codes (`func shortcut` 1, `func bogus` 1).

**Call path / reachability.** `main.py::_run_cli` → `dispatch.detect_mode` (routing) and
`main.py` → `dispatch._extract_global_options` (option values) are the production paths; the
second caller is `_cli/builtins.py:778-781`. Reachability is proved by sabotage in
`[verify-e2e:TARGETED]` (T5.1): revert `value_required_takes_next` to `return True` and
watch `tests/cli/test_emit_format_discoverability.py` and
`tests/_cli/test_pre_boot_arity_parity.py` fail.

**Atomicity note.** Five files, not the usual 1–3, deliberately: deleting the name from the
three `__all__`s turns any smaller split red at import, because `_cli/dispatch.py` and
`_cli/main.py` import it. This is the smallest set whose diff is import-green.

---

## Wave 1

### T2.1 — The grammar's own tests follow the collapsed table `[ ]`

**Goal.** Repoint the three tests that read the tables at the one-table-with-valid-sets
shape, and invert the lookahead assertion.

- `tests/types/test_flag_grammar_roundtrip.py`: the partition test becomes "every
  value-required flag is in `GLOBAL_OPTIONS_ALWAYS_VALUE` and the two frozensets agree";
  `test_optional_valid_set_covers_exactly_the_optional_table` becomes "`OPTIONAL_VALUE_VALID_SET`'s
  keys are a subset of `GLOBAL_OPTIONS_ALWAYS_VALUE` and include both flags";
  `test_optional_lookahead_follows_the_grammar_valid_set` (the withdrawn-lookahead pin)
  becomes "no member of `GLOBAL_OPTIONS_ALWAYS_VALUE` is spellable as a bare flag" — its
  cross-scan replacement is T3.1, and this file must be honest on its own rather than
  forward-reference a test that does not exist yet.
- `tests/types/test_flag_grammar_consumer_count.py`: re-run the recensus command written
  at the top of the file and update its expected count and pattern if the pattern names the
  deleted set; the documented consumers must still be the ones that exist.
- `tests/test_public_api_surface.py`: drop `GLOBAL_OPTIONS_OPTIONAL_VALUE` from the
  expected export list; keep `OPTIONAL_VALUE_VALID_SET`.

**Files (3).** `tests/types/test_flag_grammar_roundtrip.py`,
`tests/types/test_flag_grammar_consumer_count.py`, `tests/test_public_api_surface.py`.

**Gate.** `uv run pytest -q -p no:randomly tests/types/test_flag_grammar_roundtrip.py
tests/types/test_flag_grammar_consumer_count.py tests/test_public_api_surface.py` —
hit set **130 ids** (84 + 3 + 43 at authoring). All green.

**Invariants.** The consumer-count test's number is produced by its own command, not
adjusted to fit.

### T2.2 — The app's own surface requires its argument `[ ]`

**Goal.** Stop supplying a default to a present-but-bare `--emit-format` on the `app`
adapter, so Click's own arity rule answers.

- `src/functualize/app/adapters/cli.py`: drop `flag_value=_OUTPUT_DEFAULT` from the
  `--emit-format` declaration (`:1113-1132`); keep `is_flag=False`,
  `type=click.Choice(sorted(_OUTPUT_VALUES))`, `default=None`, the `_OUTPUT_VALUES` /
  `_OUTPUT_DEFAULT` unpack (`:49`) and the help prose; rewrite the comment at `:1107-1110`.
  `--perf-report` is not declared on this surface and does not move.
- `tests/cli/test_app_surface_output_format.py`: add the bare-flag case — on `func` the
  sentence is `Error: --emit-format requires a value: one of {auto, json, ndjson, none, raw}.`,
  on `app` it is Click's `Error: Option '--emit-format' requires an argument.`; both exit 2
  and neither prints a traceback (AC9). Update the module docstring's parity claim.

**Files (2).** `src/functualize/app/adapters/cli.py`,
`tests/cli/test_app_surface_output_format.py`.

**Gate.** `uv run pytest -q -p no:randomly tests/cli/test_app_surface_output_format.py` —
hit set **16 ids** at authoring, plus the added case(s); all green on both surfaces.

**Invariants.** `--emit-format json emit` on the app surface renders exactly as today;
`OPTIONAL_VALUE_VALID_SET` remains the single vocabulary both surfaces read.

---

## Wave 2

### T3.1 — The arity parity instrument `[ ]`

**Goal.** Add the AC8 test and the AC6 version-position cases.

- **New** `tests/_cli/test_pre_boot_arity_parity.py`, parametrised over
  `sorted(GLOBAL_OPTIONS_ALWAYS_VALUE)` (16 members): for each flag `F` and token `T`,
  `detect_mode` consumes `T` as `F`'s value **iff** `_extract_global_options` assigns `T`
  to `F` **iff** `version_requested` skips `T` as `F`'s value; a missing value — no token,
  `--version`, or a known global flag — makes `_extract_global_options` exit 2 with the
  missing-value sentence and makes `version_requested` reject the prefix. Also the two
  sentence shapes: a selection-table flag names its values, every other flag gets the plain
  sentence, and both agree with `OPTIONAL_VALUE_VALID_SET` / the tables.
- `tests/cli/test_version_flag_position.py`: add `func --emit-format --version` → exit 2
  and no version on stdout (AC6); `func --version` and `func --log-level DEBUG --version`
  keep printing it.

**Files (2).** `tests/_cli/test_pre_boot_arity_parity.py` (new),
`tests/cli/test_version_flag_position.py`.

**Gate.** `uv run pytest -q -p no:randomly tests/_cli/test_pre_boot_arity_parity.py
tests/cli/test_version_flag_position.py` — the existing file's hit set is **8 ids**; the
new file's count is its own (48 parametrised + 6 standalone ≈ **54** as designed — record
the observed number). All green.

**Invariants.** `func infra --version` still does not print a version (the
"must come before the group name" message is unchanged); `func greet --emit-format json`
is still `No such option`.

### T3.2 — The discoverability file pins the new sentence `[ ]`

**Goal.** `tests/cli/test_emit_format_discoverability.py` stops pinning the console
sentence the six `--help` rows were added beside.

- The five `exit_code == 1` assertions (`:74`, `:82`, `:91`, `:100`, `:117`) become 2.
- The help row assertion (`:53`) becomes `--emit-format TEXT`, with the accepted values
  asserted in the description prose instead of the bracket (AC7).
- `TestTheLookaheadIsUnchanged` is rewritten: a bare flag before a job is now a
  missing-value error, not a run; an unknown command is still exit 1; `func builtin` still
  rejects the run options.
- The module docstring (`:15-16`) and the class docstring (`:106-111`) drop the withdrawn
  lookahead as the explanation.

**Files (1).** `tests/cli/test_emit_format_discoverability.py`.

**Gate.** `uv run pytest -q -p no:randomly tests/cli/test_emit_format_discoverability.py`
— hit set **18 ids** (9 names × 2 surfaces). All green.

### T3.3 — The early-parse and global-options files follow the new routing and exits `[ ]`

**Goal.** Two integration files pin argvs and exit codes the change moves: the lookahead
routing in the early-parse file, and the two invalid-value exits Q1 unifies.

- `tests/cli/test_early_parse_integration.py`:
  - `test_perf_report_followed_by_job_name_routes_to_job` (`:35-50`), its `--emit-format`
    twin (`:52-69`) and `test_multiple_flags_with_job` (`:76-95`) become missing-value usage
    errors, keeping the routing half that still holds.
  - `test_invalid_perf_format` (`:157`) goes 1 → 2.
  - `test_invalid_discovery_depth` (`:137`) also goes **1 → 2** (Q1: the non-integer
    `--discovery-depth` value is now `ExitCode.USAGE`).
  - The module docstring (`:8`) no longer attributes the routing to a lookahead.
- `tests/cli/test_global_options.py`:
  - `test_invalid_log_level_raises_system_exit` (`:38`) asserts `exc_info.value.code == 1`;
    that becomes `2` (Q1: the invalid `--log-level` value is now `ExitCode.USAGE`).
  - The neighbouring message case (`:40-48`) and every other case in the file
    (`:16-32`, `:91+`) are unchanged — only the code moves.

**Files (2).** `tests/cli/test_early_parse_integration.py`,
`tests/cli/test_global_options.py`.

**Gate.** `uv run pytest -q -p no:randomly tests/cli/test_early_parse_integration.py
tests/cli/test_global_options.py` — hit set **37 ids** (16 + 21 at authoring). All green.

### T3.4 — The perf-report integration file, and the bug-condition file it replaces `[ ]`

**Goal.** `--perf-report` has one arity, so the bug-condition instrument for the old one
goes and the integration cases move.

- `tests/_cli/test_perf_report_integration.py`: the module docstring (`:16-22`) drops the
  lookahead claim; `TestPerfReportDefaultWithJob` and `TestPerfReportBareMode` become
  missing-value usage errors; `--perf-report json hello` and `--perf-report text hello`
  are unchanged.
- **Delete** `tests/_cli/test_dispatch_bug_condition.py` (7 ids) — it asserts the behaviour
  of the branch this feature removes, and its replacement is the parity instrument (T3.1).

**Files (2).** `tests/_cli/test_perf_report_integration.py`;
`tests/_cli/test_dispatch_bug_condition.py` (deleted).

**Gate.** `uv run pytest -q -p no:randomly tests/_cli/test_perf_report_integration.py` —
hit set **12 ids**; `rg -n "test_dispatch_bug_condition" tests/ .github/` → no matches.

### T3.5 — The rename, characterization and preservation files `[ ]`

**Goal.** The three remaining files that mention the old arity.

- `tests/cli/test_emit_format_rename.py`: `TestTheOldNameIsSimplyGone::test_a_bare_flag_still_falls_back_to_the_default` (`:87-96`) — the reason the delete site exists — becomes a
  missing-value assertion (a bare flag is no longer a spelling of the default).
- `tests/cli/test_dispatch_characterization.py`: the lookahead characterization
  (`:71-73`) is repointed at the single rule.
- `tests/_cli/test_dispatch_preservation.py`: **prose only.** Every use
  (`:333`, `:354`, `:374`, `:395`, `:514`, `:630`, `:637`) is `=`-style or an explicit
  valid value, so no behaviour changes; the module docstring (`:11-12`) and `:419` drop
  "optional-value" / "explicit valid format value".

**Files (3).** `tests/cli/test_emit_format_rename.py`,
`tests/cli/test_dispatch_characterization.py`, `tests/_cli/test_dispatch_preservation.py`.

**Gate.** `uv run pytest -q -p no:randomly tests/cli/test_emit_format_rename.py
tests/cli/test_dispatch_characterization.py tests/_cli/test_dispatch_preservation.py` —
hit set **60 ids** (11 + 27 + 22 at authoring). All green.

**Invariants.** No assertion in the preservation file is weakened: it characterizes
`=`-style and explicit-value parsing, which this feature does not change.

---

## Wave 3

### T4.1 — The live account of the four tables, and the parity docs `[ ]`

**Goal.**
- `docs/api/types.md`: `GLOBAL_OPTIONS_OPTIONAL_VALUE`'s row (`:157`) goes; the paragraph
  that explains a table of optional-value flags (`:164`) and the one that says a bare
  `--emit-format` falls back through the lookahead (`:178`) are rewritten for the
  one-table-with-valid-sets shape.
- `contributor/architecture/surface-boundary.md`: the
  `--perf-report with no value | optional-value lookahead` row (`:197`) becomes the neutral
  statement the contract asks for — the flag requires a value; the `func`-only divergence
  is about *when* the flag is recognized, not about its arity.
- `contributor/architecture/run-model/07-surface-parity.md`: the
  "pre-boot-only flags … `--perf-report`'s optional-value lookahead" cell (`:90`) keeps
  `--perf-report` in the pre-boot-only set and drops the arity claim.

**Files (3).** `docs/api/types.md`, `contributor/architecture/surface-boundary.md`,
`contributor/architecture/run-model/07-surface-parity.md`.

**Gate.** `rg -n "optional-value|optional value" docs/ contributor/` → the only remaining
matches are in `.spec/features/emit-format-alias-diagnostic/` (the artifacts) and
`CHANGELOG.md`'s released entry, which are history and stay.

### T4.2 — The run-model and ADR claims `[ ]`

**Goal.**
- `contributor/architecture/run-model/06-outcome-authority.md:136,142-144` and
  `14-decisions.md:48` (J4): the vocabulary still moves to `_types/flag_grammar.py` whole —
  but it now takes one arity, and the two flags are value-required. Name the remaining
  `func`-only distinction honestly.
- `contributor/adr/020-engine-entrypoint-encapsulation.md:146`: same correction; the ADR's
  decision is unchanged, only the example arity.

**Files (3).** `contributor/architecture/run-model/06-outcome-authority.md`,
`contributor/architecture/run-model/14-decisions.md`,
`contributor/adr/020-engine-entrypoint-encapsulation.md`.

**Gate.** `rg -n "optional-value|optional value" contributor/architecture/run-model/
contributor/adr/` → no matches.

### T4.3 — The encapsulation audit, and the changelog entry `[ ]`

**Goal.**
- `contributor/architecture/audit-engine-encapsulation.md:169` — the flat claim that the
  grammar holds "optional values"; `:367` and `:370` sit inside §3.5's *proposal* and stay
  as written (they describe a proposed state, not today's).
- `CHANGELOG.md`: a `## [Unreleased]` entry — the removed lookahead, the missing-value
  sentence and its two shapes, the app-surface arity, the `--help` row, and **one exit
  code for a wrong value across the whole value-required table**: `--emit-format` and
  `--perf-report` keep exit 2, and `--log-level` / `--discovery-depth` move from 1 to 2
  (Q1, 2026-10-05) — an intentional breaking change for any script that tested for `1`
  there, so it is named rather than glossed. The released entry at `:174-197` is history and is not rewritten.

**Files (2).** `contributor/architecture/audit-engine-encapsulation.md`, `CHANGELOG.md`.

**Gate.** `rg -n "optional-value|optional value" contributor/ docs/` → no matches outside
`CHANGELOG.md`'s released entry; `rg -n "^## \[Unreleased\]" CHANGELOG.md` → one match.

---

## Wave 4

### T5.1 — Checkpoint `[verify-e2e:TARGETED]` `[ ]`

**Goal.** Prove the whole change against the code as it stands, not against the task
descriptions.

1. `uv run ruff check --fix src/ tests/ plugins/` and
   `uv run ruff format src/ tests/ plugins/`.
2. `uv run pytest -n auto -q --no-header $(.agents/skills/test-tiers/scripts/tests-for-diff)`
   — the step tier, then `uv run pytest -x -q --no-header` (fast tier). The full tier
   (`HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q --no-header`) is CI's gate
   and exceeds the tool-call cap; run it in the shapes `.spec/TESTING.md` § *Suite tiers*
   and `.agents/skills/test-tiers/SKILL.md` give, or hand it to CI with the PR.
3. `uv run lint-imports` → **7 contracts kept, 0 broken.**
4. The real binary, not `cli_run`: in a fixture project,
   `.venv/bin/func --emit-format` → exit 2 with the selection sentence;
   `.venv/bin/func --emit-format bogus greet` → exit 2, no `Unknown command`;
   `.venv/bin/func --emit-format json greet` → exit 0; `.venv/bin/func --help` shows
   `--emit-format TEXT`; `.venv/bin/func --emit-format --version` → exit 2, no version;
   `.venv/bin/func --log-level BOGUS greet` → exit 2 (was 1);
   `.venv/bin/func --discovery-depth abc greet` → exit 2 (was 1); and
   `.venv/bin/func bogus` → still exit 1, so the unify did not swallow command-position
   errors.
5. Walk `contracts.md` §3 and §4 as the behaviour table it is: each row observed, or the
   row rewritten with the reason.
6. Sabotage for reachability: with the tree committed, break
   `value_required_takes_next` and `version_requested` in turn, confirm the expected tests
   fail, and restore with `git checkout --`.
7. `.spec/STATE.md` (gitignored, currently absent — treat as no work in flight): record the
   completed waves and the `OPTIONAL_VALUE_VALID_SET` transitional state, so the next
   session's phase is unambiguous.
8. Confirm `.spec/features/emit-format-alias-diagnostic/` is on the branch and will be
   cleared before merge (`git rm -r` in a later push) — this task does not clear it.

**Files.** `.spec/STATE.md` (gitignored, local only).

**Gate.** Every command above green; the doc sweep commands from Wave 3 re-run and clean;
the transitional state disclosed in `STATE.md` and in the PR body, not disguised.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["5.1"] }
  ]
}
```

**Why the waves fall this way.**
- **0 → 1.** Deleting the name from the grammar's `__all__`s breaks `_cli` at import, so
  the grammar and both its pre-boot consumers are one task. Every test task after it needs
  the collapsed table to exist.
- **Wave 1 is parallel.** T2.1 touches `tests/types/` + `tests/test_public_api_surface.py`;
  T2.2 touches `app/adapters/cli.py` + `tests/cli/test_app_surface_output_format.py`.
  Disjoint.
- **Wave 2 is parallel.** Five test tasks over disjoint files. T3.1 (the parity
  instrument) depends on nothing but the parser, and is the replacement for the lookahead
  pins the other four rewrite.
- **Wave 3 after Wave 2.** Documentation describes delivered behaviour; writing it before
  the tests agree with the code would let prose lead.
- **Wave 4 alone.** A checkpoint depends on all prior work, so it owns its wave.
