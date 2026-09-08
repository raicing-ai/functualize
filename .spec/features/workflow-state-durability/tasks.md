# Tasks: workflow-state-durability

Approach: `plan.md`. Formats: `schema.md`. Behaviour: `spec.md`.

Every `Gate` below was **run at authoring time** against `c0c921f`; the "now"
figure is what it returned then, so drift between authoring and execution is
visible (`CONSTITUTION.md` → *Acceptance Gates*).

Baseline: `pytest tests/test_state_store.py tests/test_state_format.py
tests/test_explain_and_state_cmd.py` → **77 passed**.
`lint-imports` → *318 files, 816 dependencies, 6 contracts*, zero violations.

---

## Wave 0 — the error type

### [x] T1 · `ScopeStoreUnreadableError`

`[F]` `src/functualize/_types/errors.py`, `src/functualize/_types/__init__.py`

Add the exception per `schema.md` §4: `path`, `scope_count`, `found_version`,
`expected_version`, `Error`-suffixed. Its `__str__` names the count and the
discard command — **a count, never scope content** (`plan.md` R3). Export from
`_types/__init__.py`.

**Gate** `grep -c ScopeStoreUnreadableError src/functualize/_types/errors.py
src/functualize/_types/__init__.py` → `1+` each *(was: 0, 0 — now 1, 2)* ✓

**Reachability:** nothing raises it yet; `scope_format.load_scopes` (T2) is the
production raiser, and T2's tests are what prove it. Disclosed here rather than
claimed — a type with no raiser is the *expected* state at the end of wave 0.
**Covers** AC-4, AC-6

---

## Wave 1 — the derived store gives up its scopes

### [x] T3a · one atomic writer for the two runtime-state formats

`[F]` `src/functualize/_primitives/state_format.py`

Extract `atomic_write_json(path, payload)` from `save_state`'s body; `save_state`
stamps `STATE_VERSION` and calls it. Behaviour identical — no envelope change here.

`scope_format` needs the same mkstemp → fsync → `os.replace` discipline with a
different version stamp, and a second copy is `pitfalls.md` §6 ("a list hardcoded
in five places has already drifted"). One writer, two callers.

*Scope of the claim, corrected at execution time:* `grep -rn mkstemp
src/functualize/` returns **6**, not the 1 this task was authored against — five
are in `_cli/` (`self_update`, `manifest`, `package_ops`, `config_snapshot_store`,
`toml_writer`), staging a binary, a registry and a TOML file, and `_primitives`
cannot import `_cli` anyway. This unifies the *runtime state* writers, not the
repo's. The docstring says exactly that rather than overclaiming.

**Gate** `grep -rc 'tempfile\.mkstemp' src/functualize/_primitives/*.py | grep -v ':0'`
→ exactly one file, `state_format.py:1` — `scope_format` must not add a second.
*(An earlier wording used bare `mkstemp`, which counts the docstring's mention of
the five `_cli/` writers and returns 2. Anchor on the call, not the word.)*;
`pytest tests/test_state_format.py tests/test_state_store.py` green *(77 passed —
this task must not turn the tree red)*
**Covers** — (enabling; AC-1/AC-3 move to T6)

*Split from the original T3 during execution. Dropping `scopes` from the envelope
turned out **not** to be separable from repointing `StateStore`: doing either
alone leaves the store reading a key that is gone, and it broke 14 tests for four
waves. The envelope change is now T6's, done in one step with the repoint. The
extraction is separable and stays here, because T2 consumes it.*

---

## Wave 2 — the fail-closed scope file

### [x] T2 · `scope_format.py` — the fail-closed file

`[F]` `src/functualize/_primitives/scope_format.py` *(new)*,
`tests/test_scope_format.py` *(new)*

`SCOPES_VERSION`, `SCOPES_FILENAME`, `resolve_scopes_path`, `empty_scopes`,
`load_scopes`, `save_scopes`, `scopes_lock`, `update_scopes`.

Two things distinguish it from `state_format.py`, and both are the point:

1. **The path is derived, never resolved.**
   `resolve_state_location(start)[0].with_name(SCOPES_FILENAME)` — one upward
   walk, so the two files cannot land in different modes (`plan.md` §1).
2. **`load_scopes` raises where `load_state` degrades**, per `schema.md` §3.
   Absent → empty. Unparseable, not-a-dict, wrong version, `scopes` not a dict →
   `ScopeStoreUnreadableError`, **file left exactly where it is** (`plan.md`
   §1.2 — renaming here makes the next run start over silently).

Call `state_format.atomic_write_json` (extracted in T3) and reuse `state_lock`'s
sidecar discipline rather than reinventing either. Intra-layer import, permitted,
and it is what keeps one atomic-write implementation in the repo.

Tests: one per row of `schema.md` §3; that a refused read is **repeatable** (call
twice, same error, file still present, byte-identical); and that the message
contains the count but **not** a payload value planted in the file.

**Gate** `pytest tests/test_scope_format.py -q` green, ≥ 8 tests *(23 passed)*;
`lint-imports` 6/6 *(the `_primitives → _types` import is contract-legal)* ✓

**Reachability:** `load_scopes` is T1's production raiser, so the error type is
now wired. `scope_format` itself is not yet reached from a production path —
`ScopeStore` (T4) is its first consumer. Disclosed, not claimed.

Two functions beyond the task's letter, both load-bearing:
`clear_scopes()` (the escape hatch — it must move a file `load_scopes` refuses,
so it never reads one, and it never clobbers an existing `.bak`) and
`update_scopes()` refusing to write over a file it could not read.
**Covers** AC-2, AC-4, AC-5, AC-6, AC-16

---

## Wave 3 — the store, and the public door

### [x] T4 · `ScopeStore`

`[F]` `src/functualize/_primitives/scope_store.py` *(new)*,
`tests/test_scope_store.py` *(new)*

**Check the path, not the class name.** There are two `StateStore` classes:
`_primitives/state_store.py` (this one) and `_engine/capabilities/state_store.py`
(an unrelated in-memory KV container for the `State` capability). The second is
never touched by any task in this feature.

Move the 16 scope accessors out of `state_store.py` **verbatim** — same names,
same signatures, same docstrings, same `_blank_scope()`. This is a move, not a
rewrite; behaviour changes belong to other tasks and a reviewer must be able to
see that at a glance.

Add `batch()` (the `state_store.py:98-114` contextmanager, retargeted) and
`clear()`, which moves an existing file aside to `scopes.json.bak` and returns
that path, or `None` if there was nothing. `clear()` must **not read** the file —
it is the escape hatch from an unreadable one (`plan.md` §1.2).

Tests: accessor parity against the current behaviour, `batch()` read-your-writes,
`batch()` discarding on exception, and AC-16 (two stores over one path, interleaved
writes on different scope ids, both survive).

**Gate** `pytest tests/test_scope_store.py -q` green, ≥ 16 tests *(32 passed)* ✓

*Executed as a **copy**, not a move.* `state_store.py` still holds its own
accessors until T6 repoints it; deleting them here would break every caller for
a wave. The duplication is deliberate, bounded to one wave, and T6's gate is what
proves it is gone. `ScopeStore.beside_state()` carries the sibling rule so
`StateStore` needs no path logic of its own in T6.

Three methods beyond the accessors: `batch()` (used by T8), `clear()` (the
escape hatch — never reads), and `is_readable()` for `state show`, which must
report the fault rather than propagate it (R-b).
**Covers** AC-1, AC-16

### [x] T5 · public door

`[F]` `src/functualize/app/utils.py`

Re-export `resolve_scopes_path` and `ScopeStoreUnreadableError`, both added to
`__all__`, beside the `StateStore` / `resolve_state_path` / `DIValidationError`
neighbours already there. **Not** `functualize.types` — it exports no error types
today, and `_cli` needs one import line, not two doors (`plan.md` R-c).

Also exports `SCOPES_VERSION` — AC-11 asks `show` to report the scope store's
version, and `_cli` cannot reach `_primitives` to read it.

**Gate** `uv run python -c "from functualize.app.utils import resolve_scopes_path,
ScopeStoreUnreadableError, SCOPES_VERSION"` → exit 0 *(was: `ImportError: cannot
import name 'resolve_scopes_path'`)*; `lint-imports` 6/6 ✓
**Covers** AC-11

---

## Wave 4 — the façade

### [x] T6 · `StateStore` delegates

`[F]` `src/functualize/_primitives/state_store.py`,
`src/functualize/_primitives/state_format.py`, `tests/test_state_store.py`,
`tests/test_state_format.py`

- **Drop `scopes` from `state_format._SECTIONS` and `empty_state()`**, and remove
  the two `TRANSITIONAL(workflow-state-durability/T6)` comments there. Done *here*,
  not in T3a: the envelope losing the key and `StateStore` no longer reading it are
  one atomic change (proved by doing it apart — 14 tests red). Do **not** bump
  `STATE_VERSION`; that would discard every fingerprint for nothing.
- Hold `self._scopes = ScopeStore(self._path.with_name(SCOPES_FILENAME))` — derived
  from its own path, so every existing `StateStore(tmp / "state.json")` in the test
  suite finds its sibling with no extra wiring.
- Delegate all 16 scope methods. Signatures **identical**: no caller outside
  `_primitives` may need editing (`contracts.md` §1.1).
- `clear(*, scopes: bool = False) -> Path | None` — always clears fingerprints,
  history and session; clears scopes only when asked; returns where the scope file
  was moved, for the CLI's message.
- Remove `batch()`; add `scope_batch()` forwarding to `self._scopes.batch()`.
  Repoint the 5 test sites (`:158, :191, :199, :204, :210`). Update the module
  docstring, whose *"should use `StateStore.batch`"* instruction had no production
  caller.
- Rename `test_clear_resets_everything` (`:215-224`) — its intent changes, and the
  rename is what records that. "Everything" stops including scopes.

**Gate** `grep -rn '\.batch(' src/ plugins/` → exactly **1**, and it is
`state_store.py`'s own `self._scopes.batch()` delegation *(authored as `0`, which
was wrong: AC-18 asks that no mechanism go uncalled, and `ScopeStore.batch` is
called — by `scope_batch`, which T8 calls from the walk. A literal 0 would mean
the replacement was unused too.)*;
`grep -c 'def batch' src/functualize/_primitives/state_store.py` → `0` *(now: 1)*;
`grep -c 'def scope_batch' src/functualize/_primitives/state_store.py` → `1`
*(now: 0)*; `grep -c '"scopes"' src/functualize/_primitives/state_format.py` → `0`
*(now: 2)*; `grep -rc 'TRANSITIONAL(workflow-state-durability' src/` → `0`;
`pytest tests/test_state_store.py tests/test_state_format.py -q` green
**Covers** AC-1, AC-3, AC-7, AC-9, AC-18

**Reachability:** `clear(scopes=True)` has no production caller until T7 adds
`--scopes`; `scope_batch()` has none until T8. Both are disclosed, not claimed.
Everything else in this task is on the live path — every existing `StateStore`
scope call now runs through `ScopeStore`, proven by 9295 passing tests that were
never edited.

Two test sites deferred from T3a landed here with the envelope change
(`tests/test_state_format.py` — `scopes` assertions), plus a unit-level version
of the §1.1 experiment: bump the derived store's version, do one unrelated
write, and watch the fingerprint vanish while the gate payload survives.

---

## Wave 5 — the four delivery surfaces, in parallel

### [x] T7 · the `state` command group

`[F]` `src/functualize/_cli/builtins.py`, `tests/test_explain_and_state_cmd.py`

Four edits, one task **because `show` and `clear` must never be edited apart** —
that is the pitfalls.md §5 symptom this feature is most at risk of reproducing
(`plan.md` R4).

- Group help `:780` and the `BuiltinCommand` registry `:90-96` — make them agree
  and name every section each command touches. They disagree today: `c0c921f`
  half-landed this, so the registry says *"fingerprints, history, scopes"* while
  the click group still says *"fingerprints, history"*.
- `clear` gains `--scopes`, and reports what it kept or cleared, per
  `contracts.md` §2.1. With `--scopes` it says where the old file went.
- `show` gains `Scopes path:` and the scope store's version; on an unreadable
  store it prints every other line, renders the scopes line as the fault, then
  exits 2 (`plan.md` R-b).
- `builtin info`'s "Runtime State" block gains `Scopes path:` — its own comment
  explains why hiding a file's location is a defect (`plan.md` R7).
- `_workflow_store()` (`:826`) catches the refusal for all four
  `builtin workflow` subcommands in one place.

**Gate** `grep -rn 'fingerprints, history)' src/` → `0` *(now: 1, at
`builtins.py:780`)*; `func builtin state clear --help` contains `--scopes`
*(now: `grep -c '\-\-scopes' src/functualize/_cli/builtins.py` = 0)*;
`pytest tests/test_explain_and_state_cmd.py -q` green
**Covers** AC-7, AC-8, AC-9, AC-10, AC-11

### [x] T8 · the walk stops rewriting the file

`[F]` `src/functualize/_engine/frontier.py`,
`src/functualize/_engine/workflow_walker.py`

Wrap four method bodies in `with self._store.scope_batch():` —
`FrontierWalk.start`, `.complete`, `.block`, and `WorkflowWalker._fail`
(`plan.md` §1.4). Bodies otherwise unchanged.

Test with a counting `save_scopes` spy: a graph of N nodes performs **one** scope
write per node transition, not three, and the resulting scope record is
byte-identical to the uncoalesced path. Plus the deliberate change: an exception
raised mid-`complete()` leaves that node's writes **unapplied**, not torn.

**Gate** `grep -c scope_batch src/functualize/_engine/frontier.py` → `3`
*(now: 0)*; `grep -c scope_batch src/functualize/_engine/workflow_walker.py` → `1`
*(now: 0)*; `pytest tests/test_workflow_walker.py tests/test_workflow_as_job.py
tests/test_d7_graph_probes.py -q` green
**Covers** AC-17

### [x] T9 · the CLI refuses, cold and warm

`[F]` `src/functualize/app/adapters/click_params.py`,
`src/functualize/app/adapters/lazy_command.py`

One `scope_store_refusal()` contextmanager, applied at **both**
`engine.execute(...)` sites (`click_params.py:1141`, `lazy_command.py:141`):
echo the message, `SystemExit(ExitCode.USAGE)`.

Both, or the bug returns. `deliver_job_result`'s docstring records what happened
when only one path was fixed: *"Cold boot exited 1, warm boot exited 0, for the
same job and the same failure."* So the test runs the same workflow against a
poisoned scope file **twice** — cold cache and warm — and asserts exit 2 both
times.

This is `contributor/reference/pitfalls.md` §23, *"Two dispatch paths, one
result-handling contract"* — the entry that exists because of this exact pair.

**Gate** `grep -c scope_store_refusal src/functualize/app/adapters/click_params.py
src/functualize/app/adapters/lazy_command.py` → `1+` each *(now: 0, 0)*
**Covers** AC-4, AC-6, AC-13

### [x] T10 · MCP parity

`[F]` `plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py`,
`tests/plugins/test_mcp_workflow_tools.py`

A `functools.wraps` decorator on the 6 tool coroutines
(`register_tools`, `:168-175`) turning the refusal into
`_error("scope_store_unreadable", …)`. `wraps` preserves `__name__`/`__doc__`, and
the explicit assignments after each definition still apply to the wrapper.

Flat `{error, message}` — `_error(code, message)` (`:716`) is flat by design and
widening it for one case is the worse trade (`plan.md` R-d). No tool signature
changes (`contracts.md` §3).

**Gate** `grep -c scope_store_unreadable
plugins/functualize-mcp/src/functualize_mcp/_workflow_tools.py` → `1+` *(now: 0)*;
`pytest tests/plugins/test_mcp_workflow_tools.py -q` green
**Covers** AC-4, AC-6

---

## Wave 6 — the regression that started this

### [ ] T11 · the experiment becomes a test

`[F]` `tests/test_state_split_regression.py` *(new)*

The transcript in
`.spec/shape-intents/pi-workflows-parity/evidence/scrutiny-report-2026-09-08.md`,
executable:

1. block a workflow, recording a gate payload;
2. bump the **derived** store's `format_version`;
3. perform one unrelated fingerprint write;
4. assert the scope still exists **and its payload is intact**.

Before this feature that sequence returned `scopes: []` and
`gate payload survived? False`, with no error and no warning.

Plus AC-12 end-to-end: block a real workflow through `cli_run`, deposit input,
resume, and assert completed steps replay, the recorded branch holds, and the exit
code is 5 then 0 — the same walk across the split.

**Gate** `pytest tests/test_state_split_regression.py -q` green, ≥ 3 tests
**Covers** AC-3, AC-12, AC-13, AC-14

---

## Wave 7 — collateral

### [ ] T12 · the docs that are already wrong

`[F]` `contributor/reference/state-store.md`, `docs/guides/task-runner.md`,
`CHANGELOG.md`

`contributor/reference/state-store.md` is marked **shipped**, is cited by nothing,
and had already drifted before this feature touched it (`research.md` §2): it
documents `scope_records`, a top-level `version`, `functualize_version` and
`generated_at`; the code has `format_version`, `scopes`, `session`, and neither of
the other two. Fix the drift **and** add the two-store description — its §2 is the
natural home.

`docs/guides/task-runner.md:205` says `state clear` clears "fingerprints, history,
preconditions", which becomes accurate for the first time; add `--scopes` beside
it. `:97` and `:202` describe `state show`.

`CHANGELOG.md` `## [Unreleased]` gains a `### Changed` section: the new
`scopes.json`, the `--scopes` flag, and — because there is **no migration**
(`plan.md` §6) — the one-time loss of any scope already in `state.json`. This entry
is the only warning anyone gets, so it is required, not optional.

`skills/functualize/references/workflows.md:98-105` teaches the four
`builtin workflow` verbs and does **not** mention `state clear`, so it needs no
edit — checked, not assumed.

`examples/docs/scenarios/o-state-store-modes.toml` asserts with `stdout_contains`
only, so the added lines do not break it — confirmed by reading it, and re-run
here anyway.

**Gate** `PATH="$PWD/.venv/bin:$PATH" python
.agents/skills/doc-verify/scripts/run-scenario examples/docs/scenarios/ --engine
shell` green *(run `a-core-builtins` first to prove the harness works before
believing any failure — `TESTING.md`)*
**Covers** AC-10

---

## Wave 8 — checkpoint

### [ ] T13 · full verification

`[F]` — none; this task changes nothing.

0. **AC-15** — the scope store is core and unconditional. `git diff --name-only
   master...` names **no** file under `plugins/functualize-state*/`, and
   `git diff master... -- pyproject.toml` adds no dependency. Reading and writing
   scopes must require no optional package.
1. `uv run ruff check src/ tests/ plugins/` · `uv run ruff format --check`
2. `uv run mypy src/`
3. `uv run lint-imports` — **6** contracts, zero violations, ~318 files
4. `HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q` (~10 min)
5. `uv run pytest plugins/functualize-mcp/tests/`
6. Walk all 18 acceptance criteria in `spec.md` against real behaviour
7. **Reachability** (`CONSTITUTION.md`): name the production call path for each
   new capability and prove it by removing the call and watching a test fail —
   `scope_batch` (walk), `scope_store_refusal` (both CLI execute sites), the MCP
   decorator, `clear(scopes=True)`. *Commit first, sabotage second, restore
   third* — the restore reverts everything uncommitted in the file, and skipping
   this has discarded finished work twice.
8. Confirm no comment or docstring still claims runtime state is safe to discard
   without distinguishing derived state from scopes (`spec.md` §5).

**Gate** 0 and 1–5 green; 6–8 walked item by item, not inferred from a green suite
**Covers** every AC

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1"] },
    { "id": 1, "tasks": ["T3a"] },
    { "id": 2, "tasks": ["T2"] },
    { "id": 3, "tasks": ["T4", "T5"] },
    { "id": 4, "tasks": ["T6"] },
    { "id": 5, "tasks": ["T7", "T8", "T9", "T10"] },
    { "id": 6, "tasks": ["T11"] },
    { "id": 7, "tasks": ["T12"] },
    { "id": 8, "tasks": ["T13"] }
  ]
}
```

**Why the waves fall here.** T1 produces the error every later module imports.
T3a comes next alone: it owns `state_format.py`, and T2 consumes the
`atomic_write_json` it extracts there. *(Revised twice during execution. T2 and T3
were originally parallel, on the assumption that `scope_format` could own its own
atomic writer — it cannot, `_primitives` has exactly one and a second would drift.
Then T3 was split: its envelope change is inseparable from T6's repoint, and doing
it early left 14 tests red across four waves. Waves are only a useful checkpoint if
each one ends green.)*
T4 consumes T2; T5 consumes T1 and T2; disjoint files, same wave. T6 is alone because it is the only
task touching `state_store.py`, and everything downstream depends on the façade
being settled. Wave 4's four tasks touch `_cli/`, `_engine/`, `app/adapters/` and
`plugins/` respectively — no file overlap. T11 needs every surface in place. T12
is documentation, T13 is a checkpoint, and checkpoints always get their own wave.

Within T7, `show` and `clear` are deliberately **not** split into parallel tasks:
they are the pair pitfalls.md §5 warns can drift into contradicting each other.
