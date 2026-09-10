# T12-REPORT — Round-trip and consumer-count

Task: F2 T12 in `.spec/features/run-outcome-authority/tasks.md`. Tests only; no
`src/` file touched except the sabotage edit (made and restored by editing, per
the sabotage-proof protocol). No git command was run. Only the two mandated
test files were created.

## Files delivered

### `tests/types/test_flag_grammar_roundtrip.py` — 350 lines

Spec's "round-trip" acceptance, as the task's File 1 describes it: what the
click builders render is what the pre-boot dispatch parser accepts. Every
expectation is derived from the grammar tables, never a second hand-written
list. Test groups:

1. **The tables are internally consistent** — `GLOBAL_OPTIONS_ALWAYS_VALUE` and
   `GLOBAL_OPTIONS_OPTIONAL_VALUE` are disjoint and their union is exactly
   `GLOBAL_OPTIONS_WITH_VALUE`; `GLOBAL_BOOL_FLAGS` is disjoint from
   `GLOBAL_OPTIONS_WITH_VALUE`; `OPTIONAL_VALUE_VALID_SET`'s keys equal the
   optional-value table, every valid set is non-empty, and each flag's default
   is a member of its own valid set (the bare-flag fallback is fed back through
   validation).
2. **Every value flag is accepted by the dispatch parser** — parametrized over
   the whole tables: `is_known_global_flag` knows every `GLOBAL_OPTIONS_WITH_VALUE`
   member in both spellings; `detect_mode` routes `func <flag> <value> <job>`
   to `Mode.JOB` with the value consumed; every `GLOBAL_BOOL_FLAGS` member
   stands alone (the job name stays the first positional); `_extract_global_options`
   consumes `--flag value` (always-value members) and `--flag=value` (every
   with-value member, asserting the value was stored, not skipped); the
   optional-value lookahead follows the grammar valid set — a token inside is
   consumed, a token outside is left as the first positional and the default is
   assigned.
3. **The click builder's pair agrees with `negative_flag_for`** —
   `build_click_params_from_fields` puts the positive spelling in `param.opts`
   and `negative_flag_for`'s answer in `param.secondary_opts` (plain bools,
   underscore names, short-flag bools, config-model/group bools); a sibling
   literally named `no_x` collapses the pair to the positive half; a str field
   renders no negative half.
4. **Alias round-trip through `match_group_flag`** — every positive alias
   `flag_aliases` produces for a field (including the `--dry_run` and `-n`
   spellings) matches back to that same field un-negated; every negative alias
   matches back negated; the full partition a group's params render resolves to
   the one field that owns each spelling per the grammar's own alias sets.

### `tests/types/test_flag_grammar_consumer_count.py` — 114 lines

The consumer-count pin (risk R-e): scans `src/functualize` in Python
(`pathlib` + regex — no `rg` shell-out, so it runs anywhere), asserting the
sorted list of files that name any of the nine public grammar spellings.
Hidden paths, `__pycache__` and binary files are skipped, mirroring the gate's
`rg -l` defaults. The four publishers are excluded by exact path with a reason
comment each (`_types/flag_grammar.py` defines the names; `_types/naming.py`,
`app/utils.py`, `types/__init__.py` re-export). On failure the assertion
message prints the files actually found, not just a number. Adding a consumer
is one obvious line in `EXPECTED_CONSUMERS`.

## Consumer scan

**First result** — the tasks.md command, run literally:

```bash
rg -l 'GLOBAL_OPTIONS_ALWAYS_VALUE|GLOBAL_OPTIONS_OPTIONAL_VALUE|OPTIONAL_VALUE_VALID_SET' \
   -e 'GLOBAL_OPTIONS_WITH_VALUE|GLOBAL_BOOL_FLAGS|flag_aliases|negative_aliases' \
   -e 'match_group_flag|negative_flag_for' src/functualize/ \
  | grep -vE '_types/flag_grammar.py|_types/naming.py|app/utils.py|types/__init__.py' | sort
```

produces `rg: GLOBAL_OPTIONS_ALWAYS_VALUE|…: No such file or directory` on
stderr, then lists **5 files**: `_cli/completions/data.py`, `_cli/dispatch.py`,
`_cli/tui/bar.py`, `_cli/tui/sync.py`, `app/adapters/click_params.py`.

**Finding — the tasks.md gate command drops its first pattern group.** With
`-e` patterns present, rg treats the leading positional pattern as a file path
(error above) and runs only the two `-e` groups. That is why the literal run
misses `_cli/main.py` (a real consumer: 2× `GLOBAL_OPTIONS_ALWAYS_VALUE`, 2×
`GLOBAL_OPTIONS_OPTIONAL_VALUE`) and instead shows `_cli/completions/data.py`.
The tasks.md "expected 5" note therefore matches **no** actual run: the literal
command gives data.py-in/main.py-out; the intended union (all three groups,
`-e` on each) gives seven.

**Last result** — the corrected union command (all three pattern groups as
`-e`; what the Python test implements):

```bash
rg -l -e 'GLOBAL_OPTIONS_ALWAYS_VALUE|GLOBAL_OPTIONS_OPTIONAL_VALUE|OPTIONAL_VALUE_VALID_SET' \
   -e 'GLOBAL_OPTIONS_WITH_VALUE|GLOBAL_BOOL_FLAGS|flag_aliases|negative_aliases' \
   -e 'match_group_flag|negative_flag_for' src/functualize/ \
  | grep -vE '_types/flag_grammar.py|_types/naming.py|app/utils.py|types/__init__.py' | sort
```

```
src/functualize/_cli/completions/data.py
src/functualize/_cli/dispatch.py
src/functualize/_cli/main.py
src/functualize/_cli/tui/bar.py
src/functualize/_cli/tui/sync.py
src/functualize/app/adapters/cli.py
src/functualize/app/adapters/click_params.py
```

**7 files** — the same set at first and last scan (the concurrent `main.py` /
`adapters/cli.py` edits had not landed or did not move the grammar reads by the
time of the final scan). The test pins these 7.

Two of the seven are not in tasks.md's expected five, and the delta is
instructive:

- `app/adapters/cli.py` — a **true** consumer the note missed: imports
  `OPTIONAL_VALUE_VALID_SET` from `functualize.types` and reads `["--output"]`
  for its own `--output` declaration.
- `_cli/completions/data.py` — a **mention only**: `negative_flag_for` appears
  once, in a docstring added by T11 explaining the builder rule. The scan is a
  mention scan (so is `rg -l`); the test docstring says so rather than carving
  out an extra exclusion, which would be a gate of my own devising.

## Verify commands (real output)

```bash
uv run ruff check tests/ && uv run ruff format --check tests/
```
```
All checks passed!
exit=0
767 files already formatted
```

```bash
uv run pytest tests/types -q -p no:randomly
```
```
........................................................................ [ 85%]
........................                                                 [100%]
168 passed in 0.91s
```
(168 = 84 round-trip + 1 consumer-count + 83 pre-existing `tests/types` tests;
the two new files also each passed on their own before the combined run.)

## Properties found FALSE

None — every listed idea was verified true and asserted as such. Two
documented discrepancies, neither a false property:

1. **tasks.md's gate command** (above) drops its first pattern group when run
   literally — a shell/rg quirk, not a code property. The Python test
   implements the union the gate intends.
2. **tasks.md's expected-five consumer set** is stale/incomplete relative to the
   actual union scan: it omits `app/adapters/cli.py` (true reader) and
   `_cli/completions/data.py` (docstring mention), and the literal command it
   ships cannot even see `_cli/main.py`. The test pins the true 7.
3. **AC numbering**: the task instructions map File 1 → AC-10 and File 2 →
   AC-11, while `spec.md` §4 has AC-10 = the consumer-count pin and AC-11 =
   round-trip. Content matches either way; numbering in tasks.md/spec.md is
   swapped relative to each other. Not blocking.

## Sabotage proof (File 1)

Broke: added `"--exclude"` (an always-value flag) to `GLOBAL_BOOL_FLAGS` in
`_types/flag_grammar.py` — the two sides then disagreed: the parser's bool
branch skips only the flag and reads its value as the command.

Ran `uv run pytest tests/types/test_flag_grammar_roundtrip.py -q -p no:randomly`:

```
>       assert GLOBAL_BOOL_FLAGS.isdisjoint(GLOBAL_OPTIONS_WITH_VALUE)
E       AssertionError: assert False
>       assert mode is Mode.JOB, f"{argv}: expected JOB, got {mode}"
E       assert <Mode.UNKNOWN: 'unknown'> is <Mode.JOB: 'job'>
E       AssertionError: ['func', '--exclude', 'some-value', 'job']: expected JOB, got Mode.UNKNOWN
2 failed, 82 passed in 0.30s
```

The failures are exactly the round-trip defect: `func --exclude some-value job`
would misroute to UNKNOWN because the grammar told the parser the value flag was
a bool.

Restored `_types/flag_grammar.py` by editing the entry back out (never git).
Re-ran:

```
168 passed in 1.06s
```

And verified the module is intact:
```
rg -c 'GLOBAL_BOOL_FLAGS' src/functualize/_types/flag_grammar.py  →  2
```

## What I could not do

Nothing. One question (do not block on it): whether the consumer-count
expectation should eventually distinguish mention hits (`completions/data.py`
docstring) from import hits — today the scan counts both, faithfully to the
gate; the docstring records which current hit is prose-only.
