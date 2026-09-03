# Tasks: Boolean Flag Negation

Wave ordering is binding. **Every gate below is run before its task starts**,
and the task's `[F]` set to the command's actual hit set — RK5, the standing
lesson from `workflow-launch-validation`, where two gates were authored from
prose and neither observed what its task changed.

---

## Wave 0 — the separable half, and the blast radius

### [x] T1.1 — Cold and warm agree on a config field's short flag (B6, A4)

**[F]** `src/functualize/app/adapters/click_params.py`,
`tests/adapters/test_cold_warm_parity.py` *(new)*

`_config_field_option` takes `short_flag`; only the warm caller (`:278`) passes
it. The cold caller (`:490`) does not, so `-s` works on a warm boot and is
unknown on a cold one. The value is recoverable from the field's
`Option(short=...)` marker, read exactly as `_option_from_marker` (`:536`) does.

Separable from negation and lands first, so a cold/warm agreement test exists
*before* the pair changes what both builders emit.

**Gate — run red first, as RK5 requires.** Before the fix the cold builder
produced `('--region',)` and the warm one `('--region', '-s')`; both cells
failed. After: **2 passed**. Wider check `tests/adapters/ tests/group_options/`
→ 282 passed, 24 skipped.

The test carries a **control** asserting `-s` is actually present, because a
"fix" that dropped the short flag from *both* builders would satisfy agreement
perfectly while removing the capability.

**Sabotage** (cold call site stops passing `short_flag`): **2 failed** — the
agreement cell and the control. Restored clean.

### [x] T1.2 — Measure the help-output blast radius (RK1)

**[F]** `.spec/features/boolean-flag-negation/tasks.md` *(this file)*

Measured, not estimated:

| What | Command | Count |
|---|---|---|
| doc-verify scenarios mentioning `--no-` | `grep -rln -- "--no-" examples/docs/scenarios/` | **1** |
| boolean fields in `examples/` | `grep -rn ": bool" examples/*/*/jobs/*.py examples/*/*/*.py` | **11** |
| tests selected by `-k help` | `pytest -k help --collect-only` | **74** |
| tests referencing `secondary_opts` | `grep -rln secondary_opts tests/` | **3** |
| tests naming a boolean flag | `grep -rln -- "--dry-run\|--verbose\|--strict" tests/` | **23** |

The 74 and 23 are *candidate* sets, not predicted failures — most assert
behaviour rather than exact help text. The number that matters is how many
actually go red, and that is measured in T4.1 rather than guessed here.

#### RK3 resolved at the same time — click's pair behaves as needed

Run against the installed click, not read from the shape intent:

```
click.Option(["--dry-run/--no-dry-run", "-d"], default=None)
  opts=['--dry-run', '-d']   secondary=['--no-dry-run']   is_flag=True   default=None

  []                 -> None      (B7: "not provided" survives)
  ['--dry-run']      -> True
  ['--no-dry-run']   -> False
  ['-d']             -> True      (short flag binds the positive form)
  ['--dry-run=false']-> exit 2, "Option '--dry-run' does not take a value."
```

**Two consequences.** `default=None` is preserved by the pair, so the resolution
ladder is untouched (B7). And **click already refuses an inline value on a
flag** — so D4 needs no click-side work at all; only `func`'s pre-boot parser
(T3.1) accepts one today, and that is the whole of the parity defect.

---

## Wave 1 — the one rule

### [x] T2.1 — `negative_flag_for`, and the pair in `click_params` (B1, B3, B4; A3, A5)

**[F]** `src/functualize/_types/naming.py`, `src/functualize/app/utils.py`,
`src/functualize/app/adapters/click_params.py`,
`tests/adapters/test_boolean_negation.py` *(new)*

`negative_flag_for(name, siblings) -> str | None` returns `--no-x` unless a
sibling is literally named `no_x` (D2). Re-exported through `app/utils.py`
because `_cli/` may not import `_`-prefixed packages and reaches
`_types/naming.py` this way already.

Then `_config_field_option` emits the pair when `is_flag` and the rule allows,
keeping `default=None`; both callers pass sibling names; and the warm
signature-bool-with-short-flag branch (`:319-330`) gains a pair (B3).

**Verify before building (RK3):** that click parses `["--x/--no-x", "-s"]` with
`-s` as the positive form. If it does not, amend the spec rather than the test.

**Gate (A3, A5, A7):**
- every boolean shape in the spec's table emits a `--no-` secondary, derived by
  walking the builder's output rather than by a hand-written table;
- a model declaring `cache` **and** `no_cache` binds `--no-cache` to `no_cache`
  and gives `cache` no secondary — asserted with the fields declared in **both
  orders**, since order-dependence is the defect;
- a boolean neither set nor negated still resolves `None` from the builder, so
  the ladder is untouched.

**Result: 11 passed.** Wider check (adapters + group_options + cli + config +
tui_group_options) → **2121 passed, 453 skipped**.

**Sabotage, both variants:**
- `negative_flag_for` always `None` → **6 failed / 3 passed** (all four shape
  cells, the short-flag cell, the rule cell). The survivors are the
  absence-means-absence cell and the two order cells, which a
  nothing-has-a-negative world satisfies trivially.
- `negative_flag_for` ignores siblings → **3 failed / 6 passed**, exactly the
  collision cells. Restored clean.

#### Two findings this task produced

1. **There are five flag-rendering sites, not four.** `_option_from_marker`
   (`click_params.py:589`) was missed by the plan and found by the test: a bool
   declaring a short form routed down that path and silently lost its pair.
2. **The TUI readiness evaluator had the same bug shape** — `bar.py:290` added
   `no_<name>` only for a bool *without* a short flag, mirroring the builder
   defect. `TestReadinessAgreesWithClick` caught it immediately because it
   derives its expected set from the param builder rather than a table. Fixed
   here rather than deferred to T3.2, since T2.1 is what turned it red.

**T4.2 was pulled forward from wave 3** for the same reason — the frozen typer
snapshot goes red the moment the builder changes, and leaving the branch red
across two waves would hide a real regression behind an expected one. Its stated
reason for landing late (update from *observed* output) was satisfied: the
observed rows were in hand before it was touched.

### T2.2 — The config boolean, end to end (A1, A7)

**[F]** `tests/config/test_boolean_negation_e2e.py` *(new)*

A project whose config file sets `verbose = true`, driven through the **public
entry point**: `--no-verbose` gives `verbose=False`, `--verbose` gives `True`,
and neither gives `True` from the file. Capability coverage, per
`CONSTITUTION.md` — a test that calls the builder directly does not count.

**Gate:** the three cells above, on the app entry point.
**Sabotage:** revert T2.1's `_config_field_option` change; the negative cell fails.

---

## Wave 2 — the `func` surface

### T3.1 — Negation and the `--flag=value` refusal in dispatch (B2, B5; A2, A6)

**[F]** `src/functualize/_cli/dispatch.py`,
`src/functualize/_cli/tui/cli_arg_parser.py`,
`src/functualize/_cli/tui/job_execution.py`,
`tests/group_options/test_boolean_negation_dispatch.py` *(new)*

**Enumerate `_match_group_flag`'s callers with a grep first (RK2)** and make the
hit set this task's `[F]`; the list above is a prediction until that grep runs.

- `_flag_aliases` gains the negative spelling from `negative_flag_for`.
- `_match_group_flag` returns whether the match was negative — a 3-tuple, not a
  synthesised `inline="false"`, because D4 needs `--no-strict` and
  `--strict=false` to be distinguishable.
- The boolean branch sets `not negated` and **refuses an inline value**, with a
  hint naming the negative spelling.
- `_coerce_bool` loses its only caller and is deleted.

**Gate (A2, A6):** both surfaces, over one declaration —
`func deploy --no-strict run` and `python main.py deploy --no-strict run` both
observe `strict=False`; `--strict=false` exits non-zero on both, and the `func`
message names `--no-strict`. Modelled on
`tests/group_options/test_adapter_entry_point_parity.py` (RK4).

**Sabotage:** remove the negative alias; the `func` cell fails while the app
cell still passes — that asymmetry is the evidence the test drives two surfaces.

### T3.2 — Completion and TUI write-back (B8, A8)

**[F]** `src/functualize/_cli/tui/smart_bar_autocomplete.py`,
`src/functualize/_cli/tui/sync.py`,
`tests/tui_group_options/test_smartbar_roundtrip.py`

Completion offers `--no-x`; `_group_flag_tokens` emits `--no-x` for an explicit
`False`. The tripwire `test_a_groups_negative_boolean_spelling_is_not` (`:393`)
is **inverted, not deleted** — its docstring says it is the test that will say
so if group booleans ever gain the pair.

**Gate (A8):** `emit(resolve(text)) == text` for a line containing `--no-strict`.
**Sabotage:** revert the `sync.py` change; the round-trip cell fails.

---

## Wave 3 — the pinned snapshot, and verification

### T4.2 — The frozen typer snapshot (D3)

**[F]** `tests/adapters/test_click_params_parity.py`

Rows `:204` and `:216` gain their `--no-` secondaries, and the file's docstring
gains a note recording that booleans deliberately diverge from typer as of this
feature — a decision, not an edit. Landing it **after** the behaviour means the
snapshot is updated to match observed output rather than predicted output.

**Gate:** the parity suite green, and the docstring note present.

### T4.1 — Full regression and STATUS entry (A10)

**[F]** `.spec/STATUS.md`, plus whatever T1.2's measurement turned up

| Check | Command |
|---|---|
| Full suite | `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto` |
| Examples | `uv run pytest examples/` |
| Plugin suites | all 11, one at a time (they collide on `conftest` basenames) |
| Lint | `uv run ruff check` + `format --check` |
| Types | `uv run mypy src/` |
| Imports | `uv run lint-imports` |
| Docs | doc-verify shell tier, since help text changed |

Then the `STATUS.md` entry: what shipped, the four decisions and who made them,
and any gate that had to be corrected mid-flight — disclosed, not disguised.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["4.2", "4.1"] }
  ]
}
```
