# Research: workflow-state-durability

Findings from the retrieval pass. Never a gate — but two of these change the plan.

Verified against `c0c921f` (branch rebased onto master; `state_format.py` and
`state_store.py` untouched by master's three new commits).

---

## 1. The pitfall this feature must not recreate

`contributor/reference/pitfalls.md` §5 — *"One piece of data, one cache"*:

> *"The framework once maintained two parallel persisted caches of the same job
> descriptors, with different validation rules and different invalidation triggers, so
> `cache show` and `cache clear` could operate on different files and report contradictory
> answers. There is now exactly one."*

**This is the closest thing in the repo to an argument against splitting a store.** It
does not block the design — the pitfall was two copies of *the same data* — but the plan
must show why scopes are different and must not reproduce the symptom:

| Pitfall condition | This feature |
|---|---|
| same data in two places | **different data**: derived (fingerprints/history/session) vs. authoritative (scopes) |
| different validation rules per copy | each store has **one** owner and **one** version check, stated in one module |
| different invalidation triggers | deliberate — that is the entire point (AC-3) |
| `show`/`clear` report contradictory answers | **AC-8, AC-11 forbid it**: `show` reports both stores; `clear` says what it kept |

The last row is the real risk. `state show` and `state clear` must be read together when
either is edited, or we land the pitfall's exact symptom.

## 2. A reference doc nobody cited, that this feature invalidates

`contributor/reference/state-store.md` — *"Runtime State Store Reference"*, status
**shipped**. Not referenced anywhere in the shape intent. It documents:

- §1 the deliberate separation from the discovery cache, and *"the two never invalidate
  each other"*;
- §2 the file format — `.functualize/state.json`, `STATE_VERSION`, advisory lock,
  last-writer-wins per job key, and *"versioned JSON to start. Migrate to sqlite only if
  history/pruning pressure demands it — measured, not assumed."*

**It is already drifted.** Its documented envelope shows `"scope_records"` and a top-level
`"version"`, plus `functualize_version` and `generated_at` keys:

```json
{ "version": 1, "functualize_version": "0.15.0", "generated_at": "…",
  "fingerprints": {…}, "scope_records": {…}, "history": [ … ] }
```

The code has `format_version`, `scopes`, and a `session` section, and no
`functualize_version` or `generated_at` (`state_format.py:59-67`,
`_SECTIONS` at `:56`). So this doc must be updated by this feature regardless of the
split, and its §2 is the natural home for the two-store description.

## 3. The precedent this feature deliberately breaks

`_discovery/cached_provider.py:285-367` — `_load_cache`:

> *"Load cache from disk. Silent recovery on any failure. Applies the format-version check
> and global invalidation checks; when any fires, the cache starts empty and the stale file
> is deleted."*

That is the right behaviour **for a cache**: derived data, cheap to rebuild, deleting the
stale file is a feature. `state_format.load_state` copied the shape
(`:162-175`) — and it is wrong for scopes, which are not derived.

Worth stating in the plan as the contrast: the scope store's fail-closed behaviour (AC-4,
AC-6) is a deliberate divergence from the cache pattern, not an inconsistency.

## 4. `StateStore.clear` has exactly three call sites

serena, LSP-accurate:

| Site | Effect of AC-7 |
|---|---|
| `_cli/builtins.py:805` (`state_clear`) | the production change |
| `tests/test_state_store.py:215-224` `TestClear/test_clear_resets_everything` | **will fail** — clear no longer resets scopes |
| `tests/test_state_store.py:226-231` `TestClear/test_clear_leaves_a_valid_envelope` | likely still passes; assert per store |
| `tests/test_explain_and_state_cmd.py:101-113` `test_clearing_state_does_not_touch_the_cache` | should still pass; it asserts the cache boundary |

`test_clear_resets_everything` is the one test whose *intent* changes: "everything" stops
including scopes. Rename it rather than loosening it, so the diff records the decision.

## 5. Layer constraints, from `.serena/memories/architecture-layer-contract.md`

- **Six** enforced import-linter contracts; baseline `uv run lint-imports` reports
  *318 files, 816 dependencies, 6 contracts*.
- `_primitives` may reach **`_types` and stdlib only**. A new scope-store module lives
  under that rule; `state_format.py` is stdlib-only today and the new one should stay so.
- The public surface is **six** packages: `app`, `job`, `plugin`, `types`, `testing`,
  `workflow`.
- **Blind spot:** `exclude_type_checking_imports = true`, so imports inside
  `if TYPE_CHECKING:` are invisible to every contract. Do not rely on a contract to catch
  a bad type-only import in the new module.

## 6. Execution-ordering constraint

From `.serena/memories/execution-ordering-contract.md`, the two lines that bear on this:

- *"Workflow prelude runs **before** DI resolution and **before any hook**."* So the scope
  store is read before hooks exist — a fail-closed refusal (AC-4) cannot be reported
  through the event bus, and must surface as an exception the CLI turns into exit 2.
- *"History is recorded only at `invoke_depth == 0`, and stores `args_hash` only — never
  argument values, which may be secrets."* The scope store holds gate payloads and step
  return values, which **are** potentially secret-bearing. The split must not add a new
  place those get copied to (e.g. do not echo payloads in the AC-4 refusal message —
  report a count, not content).

## 7. Retrieval state, for whoever picks this up

| Tool | State in this worktree |
|---|---|
| serena | activated on the worktree path; python LSP live; 3 committed memories |
| zvec-grep | index present, scoped to this worktree root (`rootPaths` verified), `possibly_stale` with a background refresh running after the rebase |
| graphify | `graphify-out/graph.json` committed — 8,608 nodes, 17,052 edges, 292 communities, 95% EXTRACTED |
| rg | for exact anchors; no index |

Routing per `.claude/skills/code-intel`: exact strings → `rg`; "what references X" →
serena; "why is it like this" → zvec-grep; "what breaks if I change X" → graphify
`get_neighbors`.

**Caveat found:** `mcp__serena__activate_project` on the worktree path re-registered the
name `functualize` to point at the worktree. A later session working in the main checkout
must re-activate it there, or serena will answer about this branch.
