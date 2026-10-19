# plan.md — walk-recorded-route

**Phase:** Plan. `spec.md` and `contracts.md` (commit `24ac02d3`) were
confirmed by the member on 2026-10-19 ("Ok confirm as written", MCH-186
comment `01a15388`). This file was written before `tasks.md`. `tasks.md` waits
for member approval of this plan's surviving smells and tasks before Execute.

## Alignment

Shape: *Shape Intent — A Walk's Recorded Route, the Same on Every Store
(branches and failure routes in workflow show / get_workflow_state)*, SD page
18972707, **v2, `Authority: Approved`**, read live 2026-10-19. The selected
model is §9 candidate **B, split by kind, both stores**, with Q1 (a) and
Q2 (a).

In scope, in the page's own words (§5):

- **Command line, text**: two lines, always present, between `Steps:` and
  `Pending gates:`.
- **Command line and MCP, JSON** (`workflow show --format json`,
  `workflow list --format json`, `get_workflow_state`, `list_workflows`):
  `"branches"` and `"failure_routes"`, always present.
- **Library / port (store authors)**: `WorkflowReader.branches(scope_id)`,
  raw keys, one bulk read.
- **Errors and refusals**: UC-4, a store without the reader.
- **Documentation**: `docs/cli/workflow.md` § `workflow show`.

Out of scope, in the page's own words (§5, §8):

- **Configuration**, **Wire / file formats**, **UI (TUI)** and **Generated or
  observable artifacts**: *not touched*.
- *Not a change to what is recorded*.
- *Not a notifications surface*.

The page's §6 AFTER is kept. This plan adds one placement the page left open
(where the engine's decoder lives, below) and nothing it ruled out.

## Retrieval and skills

- **zvec-grep** (`/usr/local/bin/zg`, index built in this worktree at Specify;
  14 412 entities). The prior art is in `spec.md` § *The defect*: ADR-033's
  rejected *blind operator surfaces*, and `ScopeStoreUnreadableError`'s
  *refusal, not an empty list*.
- **serena**, activated on this worktree by absolute path.
  `find_referencing_symbols` was run for:
  - `_port_record`: 2 refs, `_scopes` and `_read_scope`.
  - `_failure_branch`: 2 refs, in `WorkflowWalker._failure_route`.
  - `_notify_key`: 1 ref, `WorkflowWalker._notify`.
  - `WorkflowReader`: declared in `_types/persistence.py`; implemented by
    `_DocumentWorkflowReader` and `SqlWorkflowReader`; typed in
    `_engine/loop_state.py`; re-exported by `plugin/__init__.py`.
- **graphify**: `get_neighbors("_workflow_view.py")` gives importers
  `app/utils.py` and `app/_workflow_control.py`, plus imports from
  `app/_workflow_resume.py` and no `_engine`. The graph is **70 commits behind
  HEAD** and has no `_port_record` node, so it was used for dependency shape
  only.
- **Codemaps.** `contributor/architecture/codemaps/data-flow.md:237` lists
  `WorkflowReader`'s readers (`workflow, step, steps, branch, state`). The
  AFTER adds `branches`, so that line is updated (task 4.1). Nothing in
  `overview.md`, `modules.md`, `dependencies.md` or `entry-points.md`
  contradicts the BEFORE below.
- **Skills consulted:**
  - `python-design-patterns` (in-repo; KISS, single responsibility).
  - `design-patterns-refactoring` (user-level; Refactoring.Guru smell
    catalogue, `cheatsheet.md`). The smell names below come from it.

## BEFORE (`91947bb`)

```
 layer: delivery (_cli, public-only)        public adapters (plugins/)
 ┌───────────────────────────────┐   ┌──────────────────────────────────────────┐
 │ _cli/builtins.py              │   │ functualize_mcp/_workflow_tools.py        │
 │  show/list/resume ─ _render_scope  │  get_workflow_state / list_workflows /    │
 │  "Branches:" only if non-empty│   │  resume_workflow  (@_refuse_unreadable…)  │
 └──────────────┬────────────────┘   └──────────────────┬───────────────────────┘
                │ import (public)                        │ import (public)
                ▼                                        ▼
 layer: public app/ ─────────────────────────────────────────────────────────────
 │ app/utils.py  selected_workflow_store(): documents → ScopeStore (legacy)      │
 │                                          otherwise → RuntimeStore (port)      │
 │ app/_workflow_view.py                                                         │
 │   _read_scope / _scopes ── isinstance(store, RuntimeStore)? ──┐               │
 │        │ no (documents)                                        │ yes (sqlite)  │
 │        ▼                                                       ▼               │
 │   ScopeStore.get_scope() → raw dict             _port_record(): "branches": {} │
 │   (branches = every decision record,              (constant — never reads)     │
 │    NUL keys, markers)                                                          │
 │        └──────────────► _describe(): "branches": dict(raw)  ◄────────┘          │
 └───────────────────────────────────────────────────────────────────────────────┘
                │ import                                  │ import
                ▼                                         ▼
 layer: _primitives/  _primitives/scope_store.py   _types/persistence.py (port, public via plugin/)
                      (scope["branches"])           WorkflowReader.branch(scope, key)  — per key only
 layer: _engine/      _engine/workflow_walker.py  writes keys: <node>, <node>\x00onfailure,
                      \x00notify\x00<key>; value "\x00end"  ── no reader of its own encoding
 plugin (sqlite)      SqlWorkflowReader.branch()  (one row, by key)
```

Smells the BEFORE already carries (catalogue names):

| Smell | Where | Note |
| --- | --- | --- |
| **Primitive Obsession** | `_engine/workflow_walker.py:1098,1114-1133` (`_ROUTED_TO_END`, `_notify_key`, `_failure_branch`); `RecordBranch.decision_key: str` | the record's *kind* is encoded inside a `str` with NUL separators, and nothing decodes it, so every reader sees the encoding |
| **Switch Statements** | `app/_workflow_view.py:365-381` (`_scopes`, `_read_scope`: `isinstance(store, RuntimeStore)`) | two read paths chosen by type; ADR-033's TRANSITIONAL documents path (`app/utils.py:156` docstring) |
| **Alternative Classes with Different Interfaces** | `ScopeStore` vs `RuntimeStore` as the operator store | the same questions answered through two interfaces; the root of the switch above |

## AFTER

```
 _cli/builtins.py  _render_scope: "Branches:" + "Failure routes:" always, "-" when empty   (delivery)
 functualize_mcp   unchanged — returns the projection; refusal via existing @_refuse_unreadable_scopes
                │                                        │
                ▼                                        ▼
 app/_workflow_view.py   (public app/)
   _read_scope / _scopes  — unchanged switch; each path yields a RAW decision map:
        documents: scope["branches"]          port: store.workflows.branches(id)   ← NEW bulk read
                                                    (no `branches` → ScopeStoreUnreadableError)
   _describe(): route = recorded_route(raw)  ──────────────────────────────┐
                "branches": route.branches, "failure_routes": route.failure_routes
                                                                            │ import (app → _engine,
                                                                            ▼  precedent: _engine.recording)
 _engine/decision_keys.py   NEW — the single owner of the decision-key encoding
   failure_key(node) · notify_key(declared) · ROUTED_TO_END · recorded_route(raw) → RecordedRoute
        ▲ import (same layer)
 _engine/workflow_walker.py  encodes via decision_keys (no local encoders)

 _types/persistence.py   WorkflowReader.branches(scope_id) -> Mapping[str, str]   (public via plugin/)
   ▲ implements                      ▲ implements
 _primitives/document_store.py      plugins/…sqlite/_readers.py  SELECT … ORDER BY rowid
 _types/workflow.py      Step / Gate / AgentStep refuse "\x00" in a node name
 testing/conformance/baseline.py   "record branch and branches"  (public testing/)
```

**Boundary check.**

- `app` → `_engine.decision_keys` is legal: `app/` is a public folder, and
  public may import internal (`app/_workflow_resume.py:18` already imports
  `_engine.recording`).
- The forbidden contract *Delivery adapters go through the request, not the
  engine* (`app.adapters` ↛ `_engine`) is not crossed. `_workflow_view` is
  not in `app.adapters`, and `workflow_flags.py` reaches it only through
  `app.utils`, which is an indirect import that the contract allows.
- `_engine/decision_keys.py` imports `_types` only.
- `_types/workflow.py` gains no import.
- `uv run lint-imports` is the Execute gate on this (tasks 1.1, 2.1).

**Candidate AFTERs checked for introduced smells.**

1. **Decode in `app/_workflow_view.py` (rejected).** This is **Feature Envy**:
   the view would parse `\x00onfailure` and `\x00notify\x00`, an encoding it
   does not own. It would also make a future encoding change into **Shotgun
   Surgery** across `_engine` and `app`. The page's §8 owner table forbids it.
2. **Decoder as module functions inside `workflow_walker.py` (rejected).**
   It is legal, but `app` would then import the walker module (1 138 lines)
   for four lines of decoding. Encoders and decoder would sit together, but
   in the file of the **Large Class** `WorkflowWalker` (lines 264–1029, past
   the constitution's ~500-LOC line, pre-existing).
3. **New `_engine/decision_keys.py` with the encoders *moved* into it
   (selected).** Encoding and decoding change together, so they live
   together. The walker's three call sites switch import (serena hit set
   above).
   - It introduces no Middle Man: the module owns behaviour, not delegation.
   - It introduces no Speculative Generality: one decoder, three existing
     encoders.
4. **Route documents through the port too, and delete the switch
   (rejected).** It would remove **Switch Statements**, but
   `selected_workflow_store` also serves `cancel`, `reclaim`, `purge` and
   `resume` on documents through `ScopeStore` methods. That is ADR-033's open
   migration, and the spec's non-goals exclude it. The switch survives.

**Forbidden-pattern check** (`.spec/CONSTITUTION.md`): there is no
peer-layer cross-import, no ABC port (`branches` joins a `@runtime_checkable
Protocol`), no global state, no class growth past ~500 LOC
(`_DocumentWorkflowReader` and `SqlWorkflowReader` gain one method each), no
deprecation shim, and no hard-coded path. Nothing on the list is present.

## Approach

1. **Port** (`_types/persistence.py`). Add `branches(scope_id: str) ->
   Mapping[str, str]` to `WorkflowReader`. Docstring: raw records, recording
   order, `{}` for unknown scopes (contracts §4).
2. **Stores.**
   - Documents (`_DocumentWorkflowReader`, `_primitives/document_store.py`,
     beside `branch` at `:342`) returns `dict(scope["branches"])`. The JSON
     object keeps insertion order across a `scopes.json` round trip.
   - SQLite (`SqlWorkflowReader`, `_readers.py`, beside `branch` at `:220`)
     runs `SELECT decision_key, chosen_target FROM workflow_branches WHERE
     namespace_id = ? AND scope_id = ? ORDER BY rowid`. The table is a rowid
     table (`_schema/0001_runtime_schema.sql`), and rowid order is insert
     order.
3. **Engine owner** (`_engine/decision_keys.py`, new). Move `_failure_branch`,
   `_notify_key` and `_ROUTED_TO_END` out of `workflow_walker.py` as
   `failure_key`, `notify_key` and `ROUTED_TO_END`. Add `recorded_route(raw:
   Mapping[str, str]) -> RecordedRoute`, a frozen dataclass of two dicts. It
   classifies one record at a time:
   - a key with no NUL is a **conditional choice**;
   - `<node>\x00onfailure` is a **failure route** to `<node>`, with value
     `ROUTED_TO_END` mapped to `"END"` (D4);
   - anything else containing NUL is a **marker** and is dropped.

   It preserves input order. The walker imports the encoders from here.
   Records stay byte-identical, which task 2.1's walker-test gate pin.
4. **Projection** (`app/_workflow_view.py`).
   - `_port_record` sets `"branches": dict(reader.branches(id))`, raw. When
     the store's `workflows` has no callable `branches`, it raises
     `ScopeStoreUnreadableError` with the contracts §6 message, naming the
     store's `profile.name`.
   - `_describe` replaces `"branches": dict(scope.get("branches", {}))` with
     `recorded_route(scope.get("branches", {}))` and emits `branches` and
     `failure_routes` in that order (contracts §2.7).

   Every surface in contracts §3 gets the change through `_describe`, with no
   surface edit.
5. **Refusal mapping already exists on every surface.** That is
   `_workflow_refusal` (`_cli/builtins.py:1141-1156`, around show, list and
   resume), `@_refuse_unreadable_scopes` (MCP `get_workflow_state`,
   `list_workflows`, `resume_workflow`), and `click_params.py:1170`
   (`--wf-show`). Task 3.2 asserts this; it does not edit it.
6. **Text** (`_cli/builtins.py` `_render_scope`, `:1201-1204`). Print both
   lines unconditionally, with `-` when empty (contracts §1).
7. **Declaration** (`_types/workflow.py`). `Step`, `Gate` and `AgentStep`
   `__post_init__` refuse `"\x00"` in the canonical name with `ValueError`,
   beside each existing empty-name refusal (contracts §7). `Edge` endpoints
   are not changed: an endpoint naming a NUL node can name no node.
8. **Conformance** (`testing/conformance/baseline.py`). Add `record branch and
   branches` after `record branch and branch` (`BASELINE`, `:470-484`).
   Reopen, then assert the order. A store without the reader fails with an
   `AssertionError` that names it (contracts §5).
9. **Example** (`examples/standalone/workflow_store_read/test_workflow_store_read.py`).
   Extend it with `runtime.workflows.branches("…") == {}` from a booted app.
   This is the public-member caller that D7 requires.
10. **ADR — new `contributor/adr/034-operator-surfaces-read-decision-records-in-bulk.md`**,
    not an amendment to ADR-033. ADR-033 is accepted and decides where a
    walk's scope I/O goes. This decision is different: a public port member,
    engine-owned decoding of decision keys, and a visible documents-path
    change. Rewriting an accepted ADR would hide that. ADR-034 links ADR-033
    and ADR-025 (the engine owns transition meaning).
11. **Docs and changelog**: `docs/cli/workflow.md` § `workflow show` (contracts
    §9.1), the `CHANGELOG.md` `[Unreleased]` entry (§9.2), and
    `codemaps/data-flow.md:237` (reader list).

## Files to change (hit sets)

| File | Why (hit set) |
| --- | --- |
| `src/functualize/_types/persistence.py` | `WorkflowReader` declaration (serena) |
| `src/functualize/_primitives/document_store.py` | `_DocumentWorkflowReader` implements it (serena) |
| `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_readers.py` | `SqlWorkflowReader` implements it (serena) |
| `src/functualize/_engine/decision_keys.py` (new) | owner of the encoding |
| `src/functualize/_engine/workflow_walker.py` | 3 encoder call sites (serena: `_failure_route` ×2, `_notify` ×1) + definitions `:1098-1133` |
| `src/functualize/app/_workflow_view.py` | `_port_record` (`:384-447`), `_describe` (`:484`) |
| `src/functualize/_cli/builtins.py` | `_render_scope` (`:1201-1204`) |
| `src/functualize/_types/workflow.py` | `Step`, `Gate`, `AgentStep` `__post_init__` |
| `src/functualize/testing/conformance/baseline.py` | `BASELINE` (`:470-484`) |
| `examples/standalone/workflow_store_read/test_workflow_store_read.py` | D7 example |
| `contributor/adr/034-…md` (new), `docs/cli/workflow.md`, `CHANGELOG.md`, `contributor/architecture/codemaps/data-flow.md` | records |
| tests: `tests/engine/test_decision_keys.py` (new), `tests/workflow/test_recorded_route_on_both_stores.py` (new; pattern of `tests/engine/test_the_walk_on_both_stores.py`), `tests/integration/test_cli_workflow_parity.py` (extend), `tests/conformance/test_baseline.py` (runs the new check; no edit expected), `tests/test_workflow_declaration.py` (NUL refusal) | — |

`_engine/loop_state.py` types against `WorkflowReader` but calls `steps`
only, so it needs no change. Every `WorkflowReader` implementation in the
tree is in the serena hit set above. `rg -n "def branch\(self" src plugins
tests` returns exactly the two stores, the Protocol, and `FrontierWalk`
(which is not a `WorkflowReader`).

## Risks

| Risk | Mitigation |
| --- | --- |
| A third-party store without `branches` breaks on `show` | contracts §6 refusal (exit 2, `scope_store_unreadable`); `run_baseline` fails loudly first; CHANGELOG names it |
| Documents scripts reading `branches["publish\u0000onfailure"]` | undocumented key; replacement `failure_routes["publish"]`; CHANGELOG (spec R2) |
| Moving the encoders silently changes stored keys | Task 2.1's gate: the existing failure-routing and notify walker tests pass unchanged, and `test_notify.py:339` still reads the marker in the raw record |
| A rowid order that differs from write order after a legacy import | `_legacy_import.py` inserts in source order; AC-11 runs on both stores with a fresh walk |
| `--wf-show` refusal path untested today | Task 3.2 adds the assertion through the app flag, not just the builtin |

## Surviving smells

| Smell | Where | Why it survives | Maintainer review |
| --- | --- | --- | --- |
| **Primitive Obsession** | the NUL-delimited `decision_key` / `"\x00end"` encoding, now in `_engine/decision_keys.py` | Replacing it with a typed record kind would change what is recorded and need a migration of `workflow_branches` and `scopes.json`, which the page's §8 (*not a change to what is recorded*) rules out. This change **confines** it: one module encodes and decodes, and no other module parses NUL. | **Yes** — accept confinement instead of removal |
| **Switch Statements** | `app/_workflow_view.py` `_scopes` / `_read_scope` (`isinstance(store, RuntimeStore)`) | Removing it means moving the documents operator path onto the port for `cancel`, `reclaim`, `purge` and `resume` too: ADR-033's open migration, out of this scope. This change keeps the switch to "where the raw map comes from" and adds no new branch on it. | No — pre-existing, owned by ADR-033 |
| **Alternative Classes with Different Interfaces** | `ScopeStore` vs `RuntimeStore` as operator store | Same root as the switch; same owner | No |

No forbidden pattern survives (see *Forbidden-pattern check*).
