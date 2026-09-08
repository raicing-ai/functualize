# Plan: workflow-state-durability

Technical approach for `spec.md`. Behaviour is settled there; this is *how*, plus
the four places the plan revises the spec artifacts and why.

Verified against `c0c921f`. Baseline green:
`pytest tests/test_state_store.py tests/test_state_format.py tests/test_explain_and_state_cmd.py`
→ **77 passed**.

---

## 1. The shape of the change

One idea carries the whole feature:

> **The scope file is always the sibling of the state file.** It is *derived* from
> the state path (`state.json` → `scopes.json` in the same directory), never
> resolved independently.

That is what keeps `contributor/reference/pitfalls.md` §5 from applying. The pitfall
was two stores that could disagree about *where they were*; here there is one upward
walk (`resolve_state_location`) and one answer, and the second path is a
`with_name()` away from the first. Two files, one location rule — the two can never
end up in different modes, so `show` and `clear` cannot report contradictory
answers about which project they are operating on.

It is also §22, *"A reader must not reconstruct a key the writer computed"*: five
readers once recomputed a fingerprint key the writer had computed differently, and
the divergence existed only *between* them. A `resolve_scopes_path` that repeated
the upward walk would be the same shape. It does not walk; it asks the state path.

```
_types/errors.py            ScopeStoreUnreadableError
   ↓
_primitives/scope_format.py  SCOPES_VERSION, SCOPES_FILENAME, resolve_scopes_path,
                             load_scopes (FAIL-CLOSED), save_scopes, scopes_lock,
                             update_scopes
   ↓
_primitives/scope_store.py   ScopeStore — the 16 scope accessors + batch()
   ↓
_primitives/state_store.py   StateStore — owns a ScopeStore, delegates to it
   ↓                         (no caller outside _primitives changes)
app/utils.py                 public door: + resolve_scopes_path,
                             + ScopeStoreUnreadableError
   ↓
_cli/builtins.py             state group · app/adapters · _engine · MCP plugin
```

### 1.1 Why a `ScopeStore` class, not just a second file handle

`StateStore` is 365 LOC. The scope accessors are ~160 of them. Moving them to their
own class leaves `StateStore` at roughly 265 with ~60 lines of explicit delegation,
keeps both classes well under the constitution's ~500 LOC decomposition threshold,
and — the real reason — gives the fail-closed read **one owner**. A reviewer asking
"who decides a scope file is unreadable?" gets exactly one answer.

`StateStore` keeps presenting one façade over both stores. Which file a section
lives in is not its callers' concern (`contracts.md` §1.1), so **no caller outside
`_primitives` changes** — that is the constraint that keeps this feature small and
leaves the verb surface to its own feature.

### 1.2 Fail-closed, and why nothing is renamed during a read

`spec.md` AC-4 asks for the file to be "preserved under a recoverable name". The
obvious implementation — rename it aside as the read refuses — has a defect that
defeats the whole feature:

> Refuse once, having renamed the file. The **next** run finds no `scopes.json`,
> reads it as "no scopes" per AC-5, and starts the workflow over. Silently.

So the read **refuses and leaves the file exactly where it is**. The refusal is a
*stable state*, not a one-shot: run it again, get the same exit 2 and the same
message. The file moves aside only when a human says so, at
`func builtin state clear --scopes`, which is the command the refusal names.

That is contract revision **R-a** (§5).

### 1.3 Where the refusal surfaces

The prelude runs before DI resolution and before any hook
(`.serena/memories/execution-ordering-contract.md`), so this cannot travel on the
event bus and cannot be a `JobResult`. It is an exception, caught at each delivery
boundary and turned into exit 2 / an MCP error envelope:

| Boundary | Site | Count |
|---|---|---|
| CLI job invocation, cold | `app/adapters/click_params.py:1141` | 1 |
| CLI job invocation, warm | `app/adapters/lazy_command.py:141` | 1 |
| `builtin workflow list/state/cancel/resume` | `_cli/builtins.py` `_workflow_store()` | 1 helper |
| `builtin state show` / `builtin info` | `_cli/builtins.py` | 2 |
| MCP tools | `_workflow_tools.py`, 6 tool coroutines | 1 decorator |

**Both CLI invocation sites, or neither.** This is `pitfalls.md` §23 — *"Two
dispatch paths, one result-handling contract"* — and `deliver_job_result`'s own
docstring records what happened last time only one of them was fixed: *"Cold boot
exited 1, warm boot exited 0, for the same job and the same failure."* The two sites
share one context manager (`scope_store_refusal()`) rather than two copies of the
rule, and the test exercises both.

`builtin state show` is the diagnostic command, so it does **not** die on the first
line. It prints every other statistic, renders the scopes line as the problem, and
*then* exits 2 — a reader running `state show` to find out what is wrong should be
told, not stonewalled. That is contract revision **R-b**.

### 1.4 Coalescing the walk (AC-17)

Reading `frontier.py` settled the fork flagged during Specify. The seam is already
there — three methods, each a short burst of consecutive scope writes with no job
execution and no I/O between them:

| Method | Scope writes today | After |
|---|---|---|
| `start()` (`frontier.py:100-106`) | `ensure_scope`, `set_scope_status`, `set_position` | 1 |
| `complete()` (`:136-161`) | `record_step`, `record_branch`?, `set_position`, `set_scope_status`? | 1 |
| `block()` (`:189-191`) | `set_position`, `set_scope_status`, `put_gate` | 1 |
| `_fail()` (`workflow_walker.py:444-450`) | `record_step`, `set_position`, `set_scope_status` | 1 |

Each method body is wrapped in `with self._store.scope_batch():`. No restructuring,
four sites, and the lock is held for microseconds — `classify_return_value` and
`graph.successors()` are the only work inside, and neither touches disk.

Reads inside a batch see the batch (`_read()` returns it), so `complete()`'s
`_resolve_branch` — which reads `get_branch` and may write `record_branch` — keeps
its read-your-writes behaviour.

**One deliberate behaviour change.** `batch()` writes on clean exit only, so an
exception mid-method now discards that node's partial scope writes instead of
persisting some of them. This is all-or-nothing per node, which is *better* than
today's torn write, but it is a change and gets its own test.

### 1.5 AC-18 falls out

`StateStore.batch()` has **0 production call sites** and 5 test call sites
(`tests/test_state_store.py:158,191,199,204,210`). It is replaced by
`scope_batch()`, which the walk actually calls, and the module docstring's
instruction to use it becomes true. The five tests repoint to the scope side.

---

## 2. Files

### 2.1 New

| File | Contents |
|---|---|
| `src/functualize/_primitives/scope_format.py` | version, filename, sibling-path rule, fail-closed load, atomic save, lock, `update_scopes` |
| `src/functualize/_primitives/scope_store.py` | `ScopeStore` — the 16 scope accessors, `batch()`, `clear()` |
| `tests/test_scope_format.py` | AC-2, AC-4, AC-5, AC-6 |
| `tests/test_scope_store.py` | accessor parity + AC-16 |
| `tests/test_state_split_regression.py` | AC-3, AC-12 — the §1.1 experiment as a test |

### 2.2 Modified

| File | Change | AC |
|---|---|---|
| `_types/errors.py`, `_types/__init__.py` | `ScopeStoreUnreadableError` | AC-4, AC-6 |
| `_primitives/state_format.py` | drop `scopes` from `_SECTIONS` + `empty_state()`; rewrite the version-discard comment (`:41-48`) so it claims only what is now true | AC-1, AC-3 |
| `_primitives/state_store.py` | own a `ScopeStore`, delegate 16 methods, `clear(*, scopes=False)`, `batch()` → `scope_batch()` | AC-1, AC-7, AC-9, AC-17, AC-18 |
| `app/utils.py` | export `resolve_scopes_path`, `ScopeStoreUnreadableError` | AC-11 |
| `_cli/builtins.py` | group help `:780`, registry `:90-96`, `clear --scopes`, `show` +2 lines, `info` +1 line, refusal in `_workflow_store()` | AC-7..AC-11 |
| `app/adapters/click_params.py`, `app/adapters/lazy_command.py` | `scope_store_refusal()` at both execute sites | AC-4, AC-6 |
| `_engine/frontier.py`, `_engine/workflow_walker.py` | `scope_batch()` at 4 sites | AC-17 |
| `plugins/functualize-mcp/.../_workflow_tools.py` | refusal decorator on 6 tools | AC-4, AC-6 |
| `tests/test_state_format.py` | 3 sites assert `scopes` in the envelope (`:30`, `:154`, `:156`) | — |
| `tests/test_state_store.py` | `test_clear_resets_everything` + 5 `batch()` sites | AC-7 |
| `contributor/reference/state-store.md` | drift + the two-store description | — |
| `docs/guides/task-runner.md` | `state clear` line at `:205` | AC-10 |
| `CHANGELOG.md` | `## [Unreleased]` — the new file, the `--scopes` flag, and the one-time loss (§6) | AC-10 |

### 2.3 Two hazards an executor will otherwise hit

**There are two `StateStore` classes and two `state_store.py` files.** graphify
resolves the name to three nodes:

| Path | What it is |
|---|---|
| `_primitives/state_store.py` | **this feature's subject** — the persisted store |
| `_engine/capabilities/state_store.py` | the in-memory `State` capability: a typed KV container with `__slots__`, closed by `WorkflowScope`. Imports nothing from `_primitives`, persists nothing. |
| `functualize_mcp/_workflow_tools.py` | an import of the first |

They are unrelated. The second is never edited by any task here. Check the path
before editing, not the class name.

**`state_format.py` has exactly two inbound importers** — `app/utils.py:42` and
`_primitives/state_store.py:31` (graphify `get_neighbors`, EXTRACTED edges), and
`empty_state` is referenced only within `_primitives` plus two test files (serena,
LSP-accurate). The file list in §2.2 is complete on that axis; nothing else reads
the envelope directly.

### 2.4 Untouched, deliberately

`functualize-state` / `functualize-state-sqlite` (AC-15 — the scope store is core and
unconditional), the scope **record** shape, every caller of `StateStore` outside
`_primitives`, and the `{str: record}` section layout that keeps the `StateBackend`
seam open.

---

## 3. Layer compliance

- `_primitives/scope_format.py` imports `_types.errors` — permitted by the contract
  table (`_primitives` → `_types`, stdlib). It diverges from `state_format.py`'s
  own *"stdlib-only: no `_types`"* docstring convention, which is a module
  preference, not a contract. Noted here so it reads as a decision.
- `scope_format.py` imports `state_format.resolve_state_location` — intra-layer,
  permitted, and it is what makes the sibling rule structural (§1).
- `_cli/builtins.py` reaches the new error through `functualize.app.utils`, which
  already re-exports `DIValidationError`, `JobMaterializationError` and
  `VaultKeyUnavailableError`. `_cli` still imports public folders only.
- `exclude_type_checking_imports = true`, so no contract will catch a bad
  `if TYPE_CHECKING:` import in the new modules. Check them by eye.
- Baseline to hold: `uv run lint-imports` → *318 files, 816 dependencies,
  6 contracts*, zero violations.

---

## 4. Risks

| # | Risk | Handling |
|---|---|---|
| R1 | **Upgrading erases the runs this feature exists to protect.** Dropping `scopes` from `_SECTIONS` makes `normalize_state` discard any existing section, and `scopes.json` does not exist yet. | **Accepted, not mitigated** — see §6. |
| R2 | The refusal reaches only one of the two CLI execute sites, reproducing the cold/warm split `deliver_job_result` documents. | One shared context manager; a test per site, cold and warm. |
| R3 | Secret leakage. Scope records hold gate payloads and step return values. | The refusal reports **a count, never content** (`.serena/memories/execution-ordering-contract.md`). Asserted in the test, not just intended. |
| R4 | `show` and `clear` drift apart — the exact symptom of pitfalls.md §5. | They are one task (T7), and their tests sit in one file. Neither is edited without the other. |
| R5 | Coalescing drops writes on an exception mid-node. | Intended (§1.4), and tested rather than discovered. |
| R6 | 41 test files touch state or scopes. | Only 4 sites reach into the envelope directly (`test_state_format.py:30,154,156`, `test_state_store.py:232`); everything else goes through accessors that do not change. Verified by grep, not assumed. |
| R7 | `builtin info`'s "Runtime State" block would name `state.json` and hide `scopes.json`, recreating the discoverability problem its own comment describes. | One line added in T7. Beyond AC-11's letter; within its intent. |

---

## 5. Contract revisions

`contracts.md` was written before the code was read. Four claims in it are wrong or
worse than the alternative. Each is corrected in `contracts.md` as part of this
plan:

| | Was | Now | Why |
|---|---|---|---|
| **R-a** | the refusal renames the file aside and reports `preserved_path` | the refusal leaves the file; `clear --scopes` moves it aside and reports where | renaming during a read makes the *next* run start over silently — the defect this feature exists to remove (§1.2) |
| **R-b** | `state show` fails closed like everything else | `state show` prints every other line, renders the scopes line as the fault, then exits 2 | it is the diagnostic command; stonewalling the reader who is trying to diagnose is backwards |
| **R-c** | `ScopeStoreUnreadableError` exported from `functualize.types` | exported from `functualize.app.utils` | `functualize.types` exports **no** error types today; `app.utils` exports three, plus `StateStore` and `resolve_state_path`. One door, beside its neighbours. |
| **R-d** | MCP error envelope gains `preserved_path` and `scope_count` keys | flat `{error, message}`, detail in the message | `_error(code, message)` (`_workflow_tools.py:716`) is flat by design; widening it for one case is a worse trade than a longer string |

And one correction to `spec.md` §1.3, which is factually wrong as written:

> *"**It has zero call sites** in `src/`, `plugins/` or `tests/`."*

`grep -rn '\.batch(' src/ tests/ plugins/` returns **5 hits, all in
`tests/test_state_store.py`** (`:158, :191, :199, :204, :210`). Zero in `src/` and
`plugins/`. The claim is corrected in place to "zero production call sites"; the
argument it supports is unaffected, and the five tests are repointed in T6.

---

## 6. The one thing this feature does not do

**There is no migration.** A project holding in-flight scopes in `state.json` loses
them once, on the upgrade that adds `scopes.json`.

This is uncomfortable — the feature's whole subject is not losing runs — so it is
stated rather than buried. The reasoning:

- `CONSTITUTION.md` → *Pre-Release Stance*: "No backward compatibility obligation.
  Breaking changes are free." and *Forbidden Patterns*: "backward-compat shims —
  reason: pre-release, no users to deprecate toward."
- A read-time fallback that adopts a legacy `scopes` section is permanent code
  serving a one-time transition, and it is the second-store-with-different-rules
  shape that pitfalls.md §5 warns about.
- The cost is bounded and knowable: a developer with a blocked run restarts it.

Because there is no migration, the `CHANGELOG.md` `[Unreleased]` entry is the **only**
warning anyone gets. It is a required part of T12, not a nicety.

**If that trade is wrong, it is a ~20-line task** (`load_scopes` adopts
`state.json`'s `scopes` section when `scopes.json` is absent, writes it out, and is
never consulted again) and it slots in as T2a without disturbing any other wave.
Say so and it goes in.
