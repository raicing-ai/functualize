# Tasks — run-outcome-authority

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

---

## Wave 0 — the module exists and nothing uses it

### [x] T1 · `_types/outcome.py`, with the two tables re-exported through it

**Files:** `src/functualize/_types/outcome.py`, `src/functualize/_types/exit_codes.py`,
`src/functualize/_types/http_status.py`, `src/functualize/types/__init__.py`,
`src/functualize/app/utils.py`

`Family`, and the two existing functions re-homed. **No consumer changes** — the suite must
pass with the module present and unused, which is what proves the move is behaviour-free.

Spec AC-1.

**Gate**
```bash
test -f src/functualize/_types/outcome.py && rg -c 'class Family' src/functualize/_types/outcome.py
```
now: `file absent` · after: `1`

**Gate — stdlib only**
```bash
rg -c '^from functualize\.(app|_app|_engine|_cli)' src/functualize/_types/outcome.py
```
now: `n/a` · after: `0`

---

## Wave 1 — the rules join the tables

### [x] T2 · `is_failure`, `report_line`, `status_from_wire`, `wire_value`

**Files:** `src/functualize/_types/outcome.py`, `tests/types/test_outcome_families.py`

`is_failure(status, *, family)` is the rule spelled three times today. `report_line` is the
BLOCKED/REFUSED text currently living only in `click_params.py:1244-1256`. The two string
functions kill `_resume_exit`'s hand-rolled fallback. Still **no consumer changes**.

**Gate**
```bash
rg -c 'def is_failure|def report_line|def status_from_wire|def wire_value' src/functualize/_types/outcome.py
```
now: `0` · after: `4`

**Test:** `is_failure(BLOCKED, family=PROCESS)` is `True`; `is_failure(BLOCKED,
family=PANEL)` is `False`. The difference that lives in a comment becomes an assertion.

---

## Wave 2 — five consumers stop deciding

### [x] T3 · `deliver_job_result` declares `PROCESS` and loses its rules

**Files:** `src/functualize/app/adapters/click_params.py`

The failure set and the report line move out; the family choice moves in.

**Gate**
```bash
rg -c 'Family.PROCESS' src/functualize/app/adapters/click_params.py
```
now: `0` · after: `≥1`

### [x] T4 · `func builtin parallel` and `_resume_exit` read the module

**Files:** `src/functualize/_cli/builtins.py`

Spec AC-4. Two sites: the success tuple at `:598` and the reverse-lookup fallback at `:1367`.

**Gate — the hand-rolled fallback is gone**
```bash
rg -c 'answered.*drafted|drafted.*answered' src/functualize/_cli/builtins.py
```
now: `1` *(`:1367`)* · after: `0`

**Gate — parallel's own success tuple is gone**
```bash
rg -c 'RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED' src/functualize/_cli/builtins.py
```
now: `1` *(`:598`)* · after: `0`

### [x] T5 · `wire_status()` reads the module

**Files:** `plugins/functualize-mcp/src/functualize_mcp/_tools.py`

Spec AC-5. Its docstring records that three doors disagreed; keep that history and point the
implementation at the authority.

**Gate**
```bash
rg -c 'status_from_wire|wire_value|Family.TOOL' plugins/functualize-mcp/src/functualize_mcp/_tools.py
```
now: `0` · after: `≥1`

### [x] T6 · HTTP and Lambda declare `WIRE`

**Files:** `plugins/functualize-http/src/functualize_http/__init__.py`,
`plugins/functualize-lambda/src/functualize_lambda/__init__.py`

These two were already correct — they choose a family and render. The change makes the choice
explicit rather than implied by which function they imported.

**Gate**
```bash
rg -c 'Family.WIRE' plugins/functualize-http/src/functualize_http/__init__.py plugins/functualize-lambda/src/functualize_lambda/__init__.py
```
now: `0`, `0` · after: `≥1`, `≥1`

**Test:** the three plugin `test_status_codes.py` suites — already parametrized over every
terminal `RunStatus` — pass unchanged. Spec AC-8.

---

## Wave 3 — the TUI's two families, and the only behaviour change

### [x] T7 · The inline TUI renders `PANEL` and exits `PROCESS` — **D3**

**Files:** `src/functualize/_cli/tui/job_execution.py`,
`tests/tui_audit/test_panel_agrees_with_table.py`

Spec AC-2, AC-6, AC-7. The panel keeps `✓ Done` for a blocked run; the **process** exit
becomes 5, matching every other surface and matching the decision 0.3.0 already took for
`workflow resume`.

**Gate — no surface owns a success set any more**
```bash
rg -c 'RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED' src/functualize/ --glob '!**/outcome.py'
```
now: `_cli/tui/job_execution.py:1`, `_cli/builtins.py:1` *(builtins cleared at T4)* ·
after: `0` outside the authority

*(Narrowed during execution: `_types/outcome.py` holds this set three times — it is the
`_NOT_A_FAILURE` table for PANEL, TOOL and WIRE, i.e. the one place the set is **supposed**
to live. A tree-wide `after: 0` would have been unreachable without deleting the authority
the task exists to create.)*

**Test:** the parity test derives expectations **from `outcome.py`**, never from a second
list — the `TestReadinessAgreesWithClick` pattern. One test body asserts both families for the
same status, so a swap fails loudly (risk R-b).

**Sabotage:** change the TUI's family locally; the parity test must fail.

---

## Wave 4 — the vocabulary gets a home

### [x] T8 · `_types/flag_grammar.py`, and the vocabulary moves out of `dispatch.py`

**Files:** `src/functualize/_types/flag_grammar.py`, `src/functualize/_types/naming.py`,
`src/functualize/_cli/dispatch.py`, `src/functualize/types/__init__.py`,
`src/functualize/app/utils.py`

Value / optional-value / bool tables (`dispatch.py:81-121`), the alias matchers (`:703-767`),
and `negative_flag_for` (re-homed from `naming.py:100`, keeping its public name and import
paths). Spec AC-9, AC-12.

**Gate — the grammar exists**
```bash
test -f src/functualize/_types/flag_grammar.py && rg -c 'def negative_flag_for' src/functualize/_types/flag_grammar.py
```
now: `file absent` · after: `1`

**Gate — the lookahead deliberately stays behind**
```bash
rg -c 'perf-report|perf_report' src/functualize/_cli/dispatch.py
```
now: `≥1` · after: `≥1` **plus** a comment in `flag_grammar.py` naming the exclusion

---

## Wave 5 — four grammar consumers

### [x] T9 · The click builders read the grammar

**Files:** `src/functualize/app/adapters/click_params.py`

Four `negative_flag_for` call sites (`:322`, `:608`, `:675`, `:876`) plus the flag tables.

**Gate**
```bash
rg -c 'negative_flag_for' src/functualize/app/adapters/click_params.py
```
now: `5` *(1 import + 4 calls)* · after: `5` — **the count is not the gate**; the import path
is. `rg -n 'from functualize.types import.*negative_flag_for' src/functualize/app/adapters/click_params.py` after: `1`

### [x] T10 · The TUI bar and sync read the grammar

**Files:** `src/functualize/_cli/tui/bar.py`, `src/functualize/_cli/tui/sync.py`

**Gate**
```bash
rg -c 'negative_flag_for' src/functualize/_cli/tui/bar.py src/functualize/_cli/tui/sync.py
```
now: `bar.py:3`, `sync.py:2` · after: unchanged counts, resolved through `app.utils`

### [x] T11 · Completions read the grammar

**Files:** `src/functualize/_cli/completions/data.py`,
`tests/_cli/test_completion_flag_pairs.py`

The fourth consumer group. It computes flag partitions independently today.

*(Authored without a gate, which cost an agent an hour of guessing — it read
"reads the grammar" as "must mention `negative_flag_for`" and came within one
step of adding an unused import to make a grep non-zero. It stopped instead and
wrote `T11-HANDOFF.md`. What the terse description actually names, measured:
`_flag_opts` loops `param.opts` only, while the builder renders a boolean as the
click pair `--x/--no-x` and click puts the negative half in
`param.secondary_opts` — so **shell completion offered no `--no-` flag at all**,
though the CLI accepts it and the SmartBar offers it.)*

**Gate — the whole partition is read** *(added during execution)*
```bash
rg -c 'secondary_opts' src/functualize/_cli/completions/data.py
```
now: `0` · after: `2`

**Gate — behaviour, not text**
```bash
uv run python -c "from functualize._cli.completions.data import _flag_opts; \
from functualize._types.descriptors import FieldDescriptor; \
print(_flag_opts([FieldDescriptor(name='cache', type_annotation='bool', \
default=True, description='', required=False)]))"
```
now: `['--cache']` · after: `['--cache', '--no-cache']`

**Verification:** `tests/_cli/test_completion_flag_pairs.py` — four tests, the
last of which pins `_flag_opts` output to the union of every param's `opts` and
`secondary_opts`, so completion cannot drift from what click parses.
**Sabotage:** restore the `opts`-only loop; 3 of the 4 fail (the non-boolean test
correctly does not).

---

## Wave 6 — the tests that keep it collapsed

### [ ] T12 · Round-trip and consumer-count

**Files:** `tests/types/test_flag_grammar_roundtrip.py`,
`tests/types/test_flag_grammar_consumer_count.py`

Spec AC-10, AC-11. The count test **asserts the count and prints the list**, so adding a
legitimate consumer is one obvious line and the diff shows a reviewer what changed (risk R-e).

**Gate — the consumer set as it stands** *(corrected during execution)*
```bash
rg -l 'GLOBAL_OPTIONS_ALWAYS_VALUE|GLOBAL_OPTIONS_OPTIONAL_VALUE|OPTIONAL_VALUE_VALID_SET' \
   -e 'GLOBAL_OPTIONS_WITH_VALUE|GLOBAL_BOOL_FLAGS|flag_aliases|negative_aliases' \
   -e 'match_group_flag|negative_flag_for' src/functualize/ \
  | grep -vE '_types/flag_grammar.py|_types/naming.py|app/utils.py|types/__init__.py' | sort
```
now: `_cli/dispatch.py`, `_cli/main.py`, `_cli/tui/bar.py`, `_cli/tui/sync.py`,
`app/adapters/click_params.py` *(5 files)* · after: the same 5, pinned by the test

*(The gate as authored counted only the name `negative_flag_for`, and after T8 that
under-counts in both directions. `_cli/dispatch.py` no longer says `negative_flag_for` — its
call moved **into** `flag_grammar.negative_aliases`, which dispatch now calls, so it is still
a consumer under a different spelling. `_cli/main.py` **became** one, reading
`GLOBAL_OPTIONS_ALWAYS_VALUE` directly once T11 removed the `_`-prefixed aliases T8 had left
in `dispatch.py`. And `types/__init__.py` would have matched the original pattern despite
being a re-export, because the exclusion said `_types/`, not `types/`. A consumer count that
tracks one function name measures a spelling, not a dependency.)*

**Sabotage:** diverge one alias in the click builder only; the round-trip test must fail.

---

## Wave 7 — checkpoint

### [ ] T13 · Feature gate

- `uv run ruff check src/ tests/ plugins/`, `ruff format --check`
- `uv run mypy src/`
- `uv run lint-imports` — 6 contracts kept
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- the three plugin `test_status_codes.py` suites, unchanged
- AC-1…AC-12 each named to a test
- orphan scan over every added symbol
- both sabotage checks, **committing before each**

---

---

## Wave Audit

Read `.spec/AUDIT.md` first — it says what this section is for and how to run it. In short:
an agent that did **not** execute this feature works down the table below, per wave, and
tries to show each claim is false. Running the task's own gate and stopping is not an audit:
the gate was written by whoever wrote the code.

For every wave, do all five:

| # | Check | How |
|---|---|---|
| 1 | **The claim is true** | Run the falsifier in the row. The row says what output means the claim is false. |
| 2 | **The gate can fail** | Make the smallest edit that should break it, confirm the gate turns red, restore. A gate that stays green under that edit is **Blocking**. |
| 3 | **The tests are wired** | Apply the wave's sabotage, confirm the named test fails, restore. **Commit before sabotaging** — `git checkout --` reverts everything uncommitted in the file. |
| 4 | **Scope held** | `git show --stat <commit>` against the wave's `**Files:**` lines. Anything extra must be named in the commit message with a reason. |
| 5 | **The answers** | A wave claiming to be behaviour-free must have changed none. A wave that changes one must name it, and a test must assert the *new* answer with the reason beside it. |

Known hazards on this branch, all observed at least once — check for them specifically:

- **A gate matching its own explanation.** `rg` for a removed literal also matches the comment
  saying why it is gone. Three gates here needed rewording or narrowing for this reason.
- **A gate whose `after:` is unreachable.** One counted docstrings that state the rule the
  task enforces; another counted the authority module the task creates.
- **A test that pins the defect.** Check that a changed assertion moved *toward* the spec, not
  toward whatever the code now does.
- **Scope widened into tests no task owns.** The wave graph guarantees source disjointness
  only; the tests pinned to those sources belong to nobody.

### Per-wave

| Wave | The claim | Falsify it | Sabotage |
|---|---|---|---|
| 0 | The outcome module exists and nothing imports it. | `rg -l 'from functualize._types.outcome|from functualize.types import.*is_failure' src/ | grep -v '_types/\|types/__init__\|app/utils'` — any hit at this commit falsifies the 'inert' claim. | n/a — the wave's whole point is that a green suite proves it changed nothing. Check the commit touched no consumer. |
| 1 | `is_failure` gives different answers per family, and the two code tables agree. | `is_failure(BLOCKED, family=PROCESS)` must be `True` and `family=PANEL` `False`. Then check `RUN` — every `RunStatus` must return a bool for every family with no `KeyError`. | Add `RunStatus.BLOCKED` to `_NOT_A_FAILURE[Family.PROCESS]`; `tests/types/test_outcome_families.py` must fail. |
| 2 | Four consumers stopped deciding, and only one answer changed. | `rg -c 'RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED' src/functualize/ --glob '!**/outcome.py'` must be 0. Then verify the **changed** answers are the two named in the T4 commit and no others — run the three plugin suites and confirm byte-identical outcomes. | Revert `_resume_exit`'s gate-vocabulary translation; `tests/integration/test_cli_workflow_parity.py::test_resume_with_incomplete_input_does_not_advance` must fail. |
| 3 | The TUI answers PANEL and PROCESS separately: panel says done, process exits 5. | Run a blocked workflow through the inline TUI. The panel showing `✗ Failed` falsifies the PANEL half; a process exit of 0 falsifies the PROCESS half. Both must be checked — one branch answering both is the defect this wave removes. | Change the panel's family from `PANEL` to `PROCESS`; the parity test must fail. |
| 4 | One flag grammar. The value / optional-value / bool tables, the alias matchers and `negative_flag_for` live in `_types/flag_grammar.py`; `dispatch.py` and `naming.py` read it and define none of it; `negative_flag_for` keeps every import path it had. | The task's gate only checks the new file *exists*. Ask the harder question — is the old copy gone? `rg -n '^_?GLOBAL_OPTIONS_ALWAYS_VALUE|^_?GLOBAL_BOOL_FLAGS|^_?OPTIONAL_VALUE_VALID_SET' src/functualize/_cli/dispatch.py` must be empty; a hit means the table was copied, not moved. Then `rg -n 'def negative_flag_for' src/functualize/` must show exactly **one** definition. Then check the corridor did not grow a private door: `rg -n 'from functualize\._types' src/functualize/_cli/dispatch.py` must be empty — `_cli` reads the grammar through `app/utils.py`, and a direct `_types` import would break the sixth contract while the tests still passed. Finally re-run the *old* import paths: `python3 -c 'from functualize._types.naming import negative_flag_for; from functualize.app.utils import negative_flag_for as b; print(negative_flag_for is b)'` — `False` falsifies AC-12. | Change one entry in the value-flag table (e.g. drop `--output`); `tests/skills/test_api_claims.py::test_documented_output_values_match_the_flag` must fail. **Watch for a shim:** the first execution left five `_`-prefixed aliases in `dispatch.py` so `_cli/main.py` would keep working without being edited. They were deleted and `main.py` re-pointed at the public names — pre-release stance forbids the shim. `rg -n '^_GLOBAL|^_OPTIONAL' src/functualize/_cli/dispatch.py` must be empty. |
| 5 | Four consumer groups read the one grammar and none keeps a private copy: the click builders, the TUI bar and sync, and completions. | Identity, not import text — a re-export and a *delegating wrapper* look identical to `rg`: `uv run python -c 'import functualize._types.flag_grammar as g, functualize._types.naming as n, functualize.app.utils as u, functualize.types as t; print(n.negative_flag_for is g.negative_flag_for, u.negative_flag_for is g.negative_flag_for, t.negative_flag_for is g.negative_flag_for)'` — any `False` falsifies it. **This actually happened:** T8's first execution left a wrapper in `naming.py` with a copied docstring, and the import-path grep the task specifies could not tell. Then `rg -n 'def negative_flag_for' src/functualize/` must be `1`. T10's own gate is a *count* that was unchanged before and after, so it proves nothing on its own. | Change one alias in `flag_grammar.py` and confirm the TUI bar renders the changed spelling — the consumers must move together. **Also confirm `_cli/tui` still imports at all:** `uv run python -c 'import functualize._cli.tui'`. A syntax error there is invisible to most of the suite and silently turns `tests/adapters/test_surface_gate.py::test_env_override_opens_the_gate` red for an unrelated-looking reason; the first T10 execution shipped exactly that while reporting "ruff check … All checks passed". |
| 6 | *(fill from the wave's task headings: T12)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 7 | *(fill from the wave's task headings: T13)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |

> The middle column is deliberately not pre-filled with the task's own gate. Derive the
> falsifier from the **claim**, then check whether the task's gate asks the same question. If
> it asks a narrower one, that difference is the finding.


## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1"]},
    {"id": 1, "tasks": ["T2"]},
    {"id": 2, "tasks": ["T3", "T4", "T5", "T6"]},
    {"id": 3, "tasks": ["T7"]},
    {"id": 4, "tasks": ["T8"]},
    {"id": 5, "tasks": ["T9", "T10", "T11"]},
    {"id": 6, "tasks": ["T12"]},
    {"id": 7, "tasks": ["T13"]}
  ]
}
```

**Why these boundaries**

- **W0 and W1 are deliberately inert.** The module exists and nothing imports it, so a green
  suite proves the move is behaviour-free before any consumer depends on it. A producer must
  precede its consumers, and here the producer lands twice — structure, then rules.
- **W2's four tasks are four disjoint consumers.** None reads another.
- **W3 is alone because it is the only behaviour change in the feature.** Isolating it means a
  bisect lands on it directly.
- **W4 before W5** — the grammar must exist before anything reads it.
- **W6 after W5** — the count test asserts the consumer set, so every consumer must already be
  re-pointed or the count is of the wrong thing.
- **W7 is a checkpoint** and checkpoints always get their own wave.

**File-disjointness within each wave**

| Wave | Tasks | Files |
|---|---|---|
| 2 | T3 / T4 / T5 / T6 | `adapters/click_params.py` / `_cli/builtins.py` / `mcp/_tools.py` / http + lambda `__init__.py` |
| 5 | T9 / T10 / T11 | `adapters/click_params.py` / `tui/bar.py`+`tui/sync.py` / `completions/data.py` |

`app/adapters/click_params.py` is touched by T3 (wave 2) and T9 (wave 5) — separated.
`_types/outcome.py` is touched by T1 and T2, which are waves 0 and 1.
`app/utils.py` and `types/__init__.py` are touched by T1 and T8, waves 0 and 4.
