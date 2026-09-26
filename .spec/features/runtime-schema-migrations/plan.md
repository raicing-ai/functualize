# Runtime schema — Plan

**Status:** architecture gate closed 2026-09-25 against `03fbb64`; decisions D1 = A, D2 = 1,
D3 = B and both smell dispositions answered by the maintainer 2026-09-26 (`spec.md` →
*Decisions*, *Surviving smells* below). Execute may start.

## Retrieval passes (gate step 1)

All three tools, each addressed by the absolute worktree path
`/home/ubuntu/orca/workspaces/functualize/rp-18-schema`.

| Pass | Tool and address | What it returned |
|---|---|---|
| Prose | zvec-grep, `root=/home/ubuntu/orca/workspaces/functualize/rp-18-schema` (index built for this worktree: 854 files, 13 527 entities, 1 m 15 s) | `contributor/reference/runtime-persistence-data-model.md` §1/§2/§6/§7 already on master; `_config/vault.py:727-783` `_upgrade` + `PRAGMA user_version` as the repo's only migration prior art; `scope_format._trim` "never evicts a live scope"; `_workflow_control.advanceable_scopes` docstring "a resumed walk reports `blocked` for its whole duration" |
| Symbols | serena, project activated at `/home/ubuntu/orca/workspaces/functualize/rp-18-schema` | `persistence.py`: 21 dataclasses + 10 protocols, no functions; `ScopeStore/set_scope_status` referenced from `FrontierWalk.start/complete/block`, `WorkflowWalker._run_walk ×2/_service_step/_fail`, `_DocumentTransaction._complete_step/_suspend/_resume/_cancel`, plus 38 test call sites in 18 files. **Misses** `executor.py:1065` and `_workflow_control.py:444` (duck-typed `store: Any`); `rg` found them — 13 production writers in total |
| Dependency direction | graphify, `project_path=/home/ubuntu/orca/workspaces/functualize/rp-18-schema` | **Stale**: the tracked `graphify-out/graph.json` predates #46/#49 (`set_scope_status` at L361, now L415; no `DocumentRuntimeStore` node). Not rebuilt — the output is tracked and would dirty the branch. Direction below is taken from an AST import walk of the 18 modules in the region instead, and `lint-imports` (7 kept, 0 broken) |
| Codemaps | `contributor/architecture/codemaps/dependencies.md` | `_types/` is "NO LOGIC — only dataclasses, enums, protocols"; confirmed by `_types/__init__.py` docstring. This moves the check function out of `_types` (below) |

### Smells the BEFORE already carries (catalogue names)

- **Shotgun surgery** — a scope's status is decided in 13 writers across `_engine/frontier.py`,
  `_engine/workflow_walker.py`, `_engine/executor.py`, `_primitives/document_store.py`,
  `app/_workflow_control.py`; a legality rule today would have to be repeated in each.
- **Primitive obsession** — status is `str` on `ScopeStore.set_scope_status`, on every command in
  `_types/persistence.py` (`CompleteStep.scope_status: str`, `FinishAttempt.status: str`, …) and in
  five parallel vocabularies (`spec.md` P4).
- **Large class** — `ScopeStore` is 930 lines (`_primitives/scope_store.py`); `_DocumentTransaction`
  442. Both are god-object-rule relevant: the first is already past ~500.
- **Duplicate code** — three ring caps as three unrelated constants (`RUNS_LIMIT`,
  `SCOPES_LIMIT`, `EVENTS_PER_SCOPE_LIMIT`) with "500 matches the run log" held in a comment.

## BEFORE

```
 layer            module (real path)                                   status it writes
 ───────────────  ───────────────────────────────────────────────────  ─────────────────────
 app/ (public)    app/_workflow_control.py  cancel_scope ───────────────┐ "cancelled"
                                                                        │
 _engine/ (peer)  _engine/frontier.py   FrontierWalk.start/complete/block┤ WalkState.*
                  _engine/workflow_walker.py _run_walk/_service_step/_fail┤ WalkState.*, _SCOPE_STATUS_FOR
                  _engine/executor.py   _close_scope ───────────────────┤ "completed"/"failed"
                  _engine/executor.py   _close_run_record(_failed) ──┐  │
                        │ commands (ADR-025)                         │  │
                        ▼                                            │  │
 _types/          _types/persistence.py  (700 lines, status: str) ◄──┼──┼── imported by _engine,
                  _types/enums.py        RunStatus (+ .terminal)     │  │   _primitives, _app
                  _types/errors.py                                   │  │
                        ▲                                            │  │
 _primitives/     _primitives/document_store.py _DocumentTransaction ┼──┤ literals "blocked"/"running"/"cancelled"
                  _primitives/run_store.py  RunStore.close_run ◄─────┘  │ any str  ── no check
                  _primitives/scope_store.py ScopeStore.set_scope_status◄┘ any str  ── no check
                        │ (930-line class)
                        ▼
                  _primitives/scope_format.py  _trim, SCOPES_LIMIT=500, EVENTS_PER_SCOPE_LIMIT=500
                  _primitives/run_format.py    _trim, RUNS_LIMIT=500      (write-time eviction)

 boundaries crossed: app→_primitives (legal: public→internal), _engine→_primitives, _engine→_types,
 _primitives→_types (all downward). No relational store, no migration runner, no schema version
 (DOCUMENT_PROFILE.versioned_migrations=False).
```

## AFTER

```
 layer            module (real path)                                     change
 ───────────────  ─────────────────────────────────────────────────────  ─────────────────────────
 app/, _engine/   13 writers — UNCHANGED call shape                        still pass a str
 _engine/         _engine/frontier.py FrontierWalk.start  resumed branch also stamps RUNNING (D2 = 1)
                        │
                        ▼
 _primitives/     _primitives/scope_store.py  ScopeStore.set_scope_status   the assignment expression
                        │                     (net 0 lines in the class)    becomes a call ─┐
                  _primitives/run_store.py    RunStore.close_run  ──────────────────────────┤
                                                                                            ▼
                  _primitives/transitions.py  NEW  require_transition(machine, cur, to) -> to
                        │                     pure; raises IllegalTransition; no I/O, no state
                        ▼
 _types/          _types/lifecycle.py         NEW  ScopeStatus, AttemptStatus,
                                                   InputRequestStatus (StrEnum); Machine =
                                                   (name, states, transitions: frozenset[pair],
                                                   terminal); SCOPE / RUN / ATTEMPT /
                                                   INPUT_REQUEST instances. Data only.
                  _types/retention.py         NEW  RetentionPolicy (frozen dataclass), DEFAULT
                  _types/errors.py            + IllegalTransition(machine, current, target)
                  _types/enums.py             RunStatus — read by lifecycle.RUN, unchanged
                  _types/persistence.py       UNCHANGED (ADR-026 not reopened)
                        ▲
 _primitives/     _primitives/scope_format.py / run_format.py  caps read DEFAULT policy
                  (migration runner + 0001 + relational retention: moved to
                   sqlite-runtime-provider, D3 = B — not in this AFTER)

 dependency direction: _primitives/transitions → _types/lifecycle, _types/errors, _types/enums;
 _primitives/{scope,run}_store → _primitives/transitions; _primitives/{scope,run}_format →
 _types/retention. All downward or intra-layer. No peer edge, no new layer, no contract edit.
```

### Why this AFTER and not the others (gate step 4)

| Candidate | Rejected because |
|---|---|
| Table + check in `_types/persistence.py` (the scaffold) | Reopens ADR-026 on both of its stated triggers (feature growth, executable logic) and breaks the codemap's "`_types` has no logic" |
| Check at each of the 13 writers | Keeps the **shotgun surgery**; a 14th writer silently skips it |
| Check inside `ScopeStore` as new methods | **Large class** growth on a 930-line class — a Forbidden Pattern, so a blocker, not a compromise |
| State pattern (a class per status) | Five tiny classes for a lookup table; **speculative generality** for a machine with no per-state behaviour. The table is data; a `frozenset` of pairs is the whole machine |
| Check in `_engine` (ADR-025: engine owns meaning) | 4 of 13 writers are in `_primitives`/`app` and cannot import `_engine`. The table *is* the engine's meaning, written as vocabulary; the store only refuses what the vocabulary rules out — it never learns *why* (ADR-025's test: no `resume` in a store conditional holds) |

Smells the settled AFTER **introduces**: none new by catalogue name; it adds one call inside the
930-line class with zero net lines (see *Surviving smells*).

## Design skills consulted

- [x] `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns/SKILL.md`) — KISS,
      separation of concerns (logic out of `_types`), God-class rule.
- [x] `design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) — smell names above;
      routing *primitive obsession → Replace Type Code with Class* (the `StrEnum`s),
      *shotgun surgery → Move Method* (13 writers → one check), State pattern considered and
      rejected.

## Files expected to change

Hit sets from `rg -n 'set_scope_status\(|close_run\(|RUNS_LIMIT|SCOPES_LIMIT|EVENTS_PER_SCOPE_LIMIT'`
and the serena reference query above. Sizes measured with `wc -l` at `03fbb64`.

| File | Lines now | Change |
|---|---|---|
| `src/functualize/_types/lifecycle.py` | new | four machines as data (~110) |
| `src/functualize/_types/retention.py` | new | `RetentionPolicy` (~30) |
| `src/functualize/_types/errors.py` | 663 | + `IllegalTransition` (~20) |
| `src/functualize/_primitives/transitions.py` | new | `require_transition` (~40) |
| `src/functualize/_primitives/scope_store.py` | 1038 (class 930) | one expression in `set_scope_status._apply`; net 0 |
| `src/functualize/_primitives/run_store.py` | 368 (class 236) | one expression in `close_run._apply` |
| `src/functualize/_primitives/scope_format.py` | 197 | caps read the policy; the eviction-set comment at `:125` ("values a scope can never leave") corrected — it is the evictable set, not an absorbing one |
| `src/functualize/_primitives/run_format.py` | 153 | cap reads the policy |
| `src/functualize/_engine/frontier.py` | 506 | resumed branch of `FrontierWalk.start` stamps `running` (D2) |
| `src/functualize/app/_workflow_view.py`, `src/functualize/app/_workflow_control.py` | 559, 785 | docstrings only: "a resumed walk reports `blocked` for its whole duration" (`_workflow_view.py:109,212-215`, `_workflow_control.py:218-220`) becomes false |
| `tests/types/`, `tests/primitives/`, `tests/test_state_store.py`, `tests/test_scope_store.py` | — | new gates; any test asserting a now-illegal move (listed in task T6) |
| `contributor/reference/runtime-persistence-data-model.md`, `contributor/architecture/dependency-graph.md`, `.spec/STATUS.md`, `CHANGELOG.md` | — | durable half (task T8) |

## Risks

- **A live transition not in the table** turns a working walk into an `IllegalTransition`. The
  table's Δ rows come from reading the writers, not from a census; task T6 therefore runs the
  whole workflow/integration suites with the check in **record** mode first and fails on any
  unlisted pair before switching to refuse.
- **Legacy records** with a status outside the set (a hand-edited or pre-T11 `scopes.json`) now
  refuse on their next write. The document backend's normalizer is the place to map them; if one
  is found, it is a finding against the decided table (D1 = A, D2 = 1), not a silent mapping.
- **Plugin substrate tests** call `set_scope_status` directly
  (`plugins/substrates/functualize-substrate-sqlite/tests/test_sqlite_substrate.py:298`); run
  `pytest plugins/substrates/functualize-substrate-sqlite/tests` in task T6.

## Surviving smells

Dispositions are the maintainer's, recorded 2026-09-26.

| Smell (catalogue) | Where | Disposition |
|---|---|---|
| **Large class** (pre-existing, not grown) | `ScopeStore`, `_primitives/scope_store.py`, 930 lines | **Accepted** by the maintainer, 2026-09-26. The one legality choke point stays inside the class; this wave adds one call inside one existing expression, net 0 lines, and task T6's gate asserts the class stays ≤ 930 lines. Splitting it is its own refactor (38 test sites, 9 production callers) |
| **Primitive obsession** | `status: str` on every command and view in `_types/persistence.py` (`CompleteStep.scope_status`, `FinishAttempt.status`, …) | **Declined** by the maintainer, 2026-09-26 — the port is to be typed. Not absorbed here (it reopens ADR-026's frozen surface): split into its own ticket, MCH-104 (*Type the persistence port's status fields with the lifecycle status types*), parked until this wave's `_types/lifecycle.py` vocabulary lands. Until then the writers stay `str`, the choke point parses `str → ScopeStatus`, and the relational schema carries `TEXT` + `CHECK (status IN …)` generated from the tables |
| **Temporary field / transitional edges** | Scope rows `failed → running`, `completed → running` (D1 = A) | Accepted by D1: both marked `# TRANSITIONAL(workflow-persistence-atomic)` in `_types/lifecycle.py`, which decides whether a retry mints a fresh attempt instead of re-entering the scope. D2 = 1 removed the other four transitional edges (`blocked → completed/failed`, `failed → completed/blocked`) |
| **Duplicate code** (kept) | write-time eviction in `scope_format._trim` and `run_format._trim` | Accepted by D3 = B: the document backend has no maintenance operation; the policy value removes the duplicated *numbers*, not the two trims, which carry different eviction rules (run log discards, scopes refuse). The relational statement and its caller live in `sqlite-runtime-provider` (0.2, 0.3) |

No Forbidden Pattern survives: no new layer, no peer edge, no ABC, no module-level mutable state
(the machines are immutable module constants), no `_types` logic, no `_types/persistence.py`
growth.
