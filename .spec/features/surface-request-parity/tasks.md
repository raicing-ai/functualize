# Tasks — surface-request-parity

Every gate was **run at authoring time** against `e57f0c9`; `now:` is what it returned then.
Run gates from the worktree root.

---

## Wave 0 — the nested call gets a channel

### [ ] T1 · `Invoke` gains `group_option_values`

**Files:** `src/functualize/_engine/capabilities/invoke.py`,
`tests/execution/test_invoke_group_options.py`

`None` means inherit — today's behaviour and the default. A mapping overrides for that call.
`invoke_parallel` is untouched. Spec AC-7, AC-8; STATUS #17.

**Gate**
```bash
rg -c 'group_option_values' src/functualize/_engine/capabilities/invoke.py
```
now: `0` · after: `≥1`

**Gate — parallel's independence survives**
```bash
rg -c 'parent_scope=None' src/functualize/_engine/capabilities/invoke.py
```
now: `1` · after: `1`

**Test:** write the inheritance test **first** — a bare `rc.invoke(job)` behaves identically
before and after (risk R-f) — then the override test.

---

## Wave 1 — MCP's three doors stop disagreeing

### [ ] T2 · `group_option_values` and `scope_id` on all three executing doors

**Files:** `plugins/functualize-mcp/src/functualize_mcp/_tools.py`,
`plugins/functualize-mcp/src/functualize_mcp/_translator.py`,
`plugins/functualize-mcp/tests/test_three_doors_agree.py`

Job parameters move into a nested `arguments` object so a job parameter named `scope_id`
cannot collide with the control input beside it. Spec AC-4, AC-9.

**Gate**
```bash
rg -c 'group_option_values' plugins/functualize-mcp/src/functualize_mcp/_tools.py
```
now: `0` *(only `_server.py:278` has it — that is D-5)* · after: `≥2` *(both doors)*

**Gate — no door splats a caller dict into the facade**
```bash
rg -c 'app\.execute\([a-z_]*name, \*\*' plugins/functualize-mcp/src/functualize_mcp/_tools.py
```
now: `2` · after: `0`

**Test:** one test asserts the **property** — a per-job tool, `run_job` and the async worker
produce the same result for the same inputs (risk R-b) — rather than three separate tests
that could each drift.

---

## Wave 2 — the wire doors get an envelope

### [ ] T3 · HTTP and Lambda accept `arguments`, `group_option_values`, `scope_id`, `force`

**Files:** `plugins/functualize-http/src/functualize_http/__init__.py`,
`plugins/functualize-lambda/src/functualize_lambda/__init__.py`,
`plugins/functualize-http/tests/test_request_envelope.py`,
`plugins/functualize-lambda/tests/test_request_envelope.py`

Spec AC-5, AC-6, AC-9. **Breaking**: job parameters move under `arguments`. That is the fix —
the flat shape is exactly what let a body key bind to a control parameter (risk R-a).

**Gate**
```bash
rg -c 'app\.execute[^)]*\*\*kwargs' plugins/functualize-http/src/functualize_http/__init__.py plugins/functualize-lambda/src/functualize_lambda/__init__.py
```
now: `functualize_http:1`, `functualize_lambda:2` · after: `0`, `0`

**Test:** a gated workflow **started** over Lambda is **resumed** over Lambda (AC-6). This is
the story D-6 says is impossible today.
**Test:** a body `{"arguments": {"scope_id": "x"}}` reaches the job as an argument named
`scope_id` and addresses nothing (AC-9).

---

## Wave 3 — the adapters let go of the kernel

### [ ] T4 · Five `_engine` imports leave `app/adapters/`

**Files:** `src/functualize/app/adapters/click_params.py`,
`src/functualize/app/adapters/lazy_command.py`,
`src/functualize/app/adapters/surface_gate.py`,
`src/functualize/types/__init__.py`,
`tests/adapters/test_adapters_do_not_import_engine.py`

Spec AC-1, AC-2. Note `terminal_available` is imported **twice**, in two adapters, to answer
one question — the TTY pre-flight is decided in two files. It gets one route on the way
through.

**Gate**
```bash
rg -n 'from functualize\._engine|import functualize\._engine' src/functualize/app/adapters/ | wc -l
```
now: `5` *(`lazy_command.py:87`, `surface_gate.py:37`, `click_params.py:1064,1069,1230`)* ·
after: `0`

**Gate — one TTY route**
```bash
rg -c 'terminal_available' src/functualize/app/adapters/
```
now: `lazy_command.py:1`, `click_params.py:1` · after: at most one file names it

---

## Wave 4 — the contract forbids the edge

### [ ] T5 · `app.adapters` must not import `_engine`

**Files:** `pyproject.toml`

Spec AC-3. **After** T4, so the contract lands green — a contract added first would land red,
and a red contract in CI teaches people to ignore it.

**Gate**
```bash
uv run lint-imports 2>&1 | tail -2
```
now: `Contracts: 6 kept, 0 broken.` · after: `Contracts: 7 kept, 0 broken.`

> The contract is the deliverable. Removing the imports without forbidding them leaves the
> door open and calls it closed.

---

## Wave 5 — the matrix becomes a suite

### [ ] T6 · Every coverage §B feature row, on both surfaces

**Files:** `tests/integration/test_surface_feature_matrix.py`

Spec AC-10, AC-12. Uses the dual-surface `cli_run` fixture (`tests/conftest.py:454`), already
parameterised over `func` | `app`. Rows needing a real PTY are marked `slow`.

The sixteen rows: `Deps` · `Fingerprint` freshness · `Guards` refusal · `Exec` retry ·
`GroupOptions` · `@workflow` + `Gate` · gate resume · `--prompt-gates` · capability injection ·
config precedence · `--force` · `--output` · exit-code contract · aliases · discovery filters ·
unknown-command explanation.

> **A row that cannot be expressed as a test is a row that was never true.** Any row that
> resists is recorded as a finding in `.spec/STATUS.md`, not quietly dropped (risk R-d).

**Gate**
```bash
uv run pytest tests/integration/test_surface_feature_matrix.py -q --co 2>/dev/null | tail -1
```
now: `no tests ran` · after: ≥ 16 rows × 2 surfaces collected

**Sabotage:** drop `group_option_values` from one door's request builder; the matrix must go
red for that door only — which is the whole point of a matrix over a convention.

---

## Wave 6 — say what moved

### [ ] T7 · Docs

**Files:** `docs/guides/group-options.md`,
`plugins/functualize-http/README.md`, `plugins/functualize-lambda/README.md`,
`contributor/architecture/surface-boundary.md`

Spec AC-11. `group-options.md` currently records #17's boundary as deliberate; it must now say
the boundary **moved**, and why — under `RunRequest`, withholding the field costs a deliberate
erasure, and a boundary that costs code needs a better reason than "it was free".

Both plugin READMEs get a before/after envelope example (risk R-a).

**Gate**
```bash
rg -c 'invoke' docs/guides/group-options.md
```
now: `≥1` *(recording the boundary as deliberate)* · after: `≥1`, describing the move

---

## Wave 7 — checkpoint

### [ ] T8 · Feature gate

- `uv run ruff check src/ tests/ plugins/`, `ruff format --check`
- `uv run mypy src/`
- **`uv run lint-imports` — 7 contracts kept** (the point of T5)
- `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto`
- each plugin's own suite: `functualize-http`, `functualize-lambda`, `functualize-mcp`
- `uv run pytest examples/`
- AC-1…AC-12 each named to a test, or to a recorded finding (AC-10 only)
- orphan scan over every symbol newly made public in `functualize.types`
- T6's sabotage, **committing before it**

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
| 0 | *(fill from the wave's task headings: T1)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 1 | *(fill from the wave's task headings: T2)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 2 | *(fill from the wave's task headings: T3)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 3 | *(fill from the wave's task headings: T4)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 4 | *(fill from the wave's task headings: T5)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 5 | *(fill from the wave's task headings: T6)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 6 | *(fill from the wave's task headings: T7)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |
| 7 | *(fill from the wave's task headings: T8)* | run each task's gate **and** one command the task did not choose — a different spelling of the same question | *(the wave's `**Sabotage:**` line, or the smallest edit that should break its named test)* |

> The middle column is deliberately not pre-filled with the task's own gate. Derive the
> falsifier from the **claim**, then check whether the task's gate asks the same question. If
> it asks a narrower one, that difference is the finding.


## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1"]},
    {"id": 1, "tasks": ["T2"]},
    {"id": 2, "tasks": ["T3"]},
    {"id": 3, "tasks": ["T4"]},
    {"id": 4, "tasks": ["T5"]},
    {"id": 5, "tasks": ["T6"]},
    {"id": 6, "tasks": ["T7"]},
    {"id": 7, "tasks": ["T8"]}
  ]
}
```

**Why these boundaries**

Every wave holds one task. T1, T2 and T3 are three independent doors and *could* share a
wave — they touch disjoint files — but each is a behaviour change to a different public
surface, and serializing them means a bisect lands on one door rather than three. **When in
doubt, serialize**; incorrect parallelism costs more than conservative ordering.

The two orderings that are not merely cautious:

- **T5 after T4.** A contract added before the imports are gone lands red.
- **T6 after T1–T3.** The matrix asserts channels those tasks create; run earlier it would
  assert absence and then need rewriting.

**File-disjointness**

Single-task waves make disjointness trivial. Across waves:
`app/adapters/click_params.py` is touched only by T4; each plugin's `__init__.py` only by T2
or T3; `pyproject.toml` only by T5.
