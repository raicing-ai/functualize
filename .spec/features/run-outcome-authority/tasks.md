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

### [ ] T8 · `_types/flag_grammar.py`, and the vocabulary moves out of `dispatch.py`

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

### [ ] T9 · The click builders read the grammar

**Files:** `src/functualize/app/adapters/click_params.py`

Four `negative_flag_for` call sites (`:322`, `:608`, `:675`, `:876`) plus the flag tables.

**Gate**
```bash
rg -c 'negative_flag_for' src/functualize/app/adapters/click_params.py
```
now: `5` *(1 import + 4 calls)* · after: `5` — **the count is not the gate**; the import path
is. `rg -n 'from functualize.types import.*negative_flag_for' src/functualize/app/adapters/click_params.py` after: `1`

### [ ] T10 · The TUI bar and sync read the grammar

**Files:** `src/functualize/_cli/tui/bar.py`, `src/functualize/_cli/tui/sync.py`

**Gate**
```bash
rg -c 'negative_flag_for' src/functualize/_cli/tui/bar.py src/functualize/_cli/tui/sync.py
```
now: `bar.py:3`, `sync.py:2` · after: unchanged counts, resolved through `app.utils`

### [ ] T11 · Completions read the grammar

**Files:** `src/functualize/_cli/completions/data.py`

The fourth consumer group. It computes flag partitions independently today.

---

## Wave 6 — the tests that keep it collapsed

### [ ] T12 · Round-trip and consumer-count

**Files:** `tests/types/test_flag_grammar_roundtrip.py`,
`tests/types/test_flag_grammar_consumer_count.py`

Spec AC-10, AC-11. The count test **asserts the count and prints the list**, so adding a
legitimate consumer is one obvious line and the diff shows a reviewer what changed (risk R-e).

**Gate — the consumer set as it stands**
```bash
rg -l 'negative_flag_for' src/functualize/ | grep -v '_types/' | grep -v 'app/utils.py' | sort
```
now: `_cli/dispatch.py`, `_cli/tui/bar.py`, `_cli/tui/sync.py`,
`app/adapters/click_params.py` *(4 files, 7 call sites)* · after: same 4 files, pinned by the
test

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
