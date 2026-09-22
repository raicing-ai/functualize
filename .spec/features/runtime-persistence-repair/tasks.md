# FUN-24 — Tasks

**Status:** refined against the code (2026-09-22, Factory Designer). The scaffold's seven tasks
became nine, the wave order changed, and every file list below is the hit set of the query that
found it — not a list composed from prose. Sizes and line numbers were measured in this worktree
at `b82fc78`.

**Read `plan.md` §5 (AFTER) and §6 (rejected alternatives) before starting.** Two entries in
`plan.md` → *Surviving smells* are marked **needs maintainer review** and must be answered
before Execute begins: the AC-4 contract shape, and the per-write lease read cost.

Wave ordering is binding: never start a task in wave N+1 while wave N has unchecked tasks.
Tasks inside one wave touch **disjoint files** — that is what makes the wave a wave.

## What changed from the scaffold, and why

| Scaffold | Now | Why |
|---|---|---|
| `1.2` cited `plugins/functualize-state-sqlite/.../substrate.py` | `plugins/substrates/functualize-substrate-sqlite/…` | **That path does not exist.** The `plugin-taxonomy` reshuffle put every plugin two levels under `plugins/`. |
| `Stored.revision` was a wave-0 sibling of the state fence | its own wave-0 task, and the fence moved to wave 2 | `expect=` passes revisions around, so retyping after would touch the same lines twice. |
| `3.1` "install the substrate in a boot step that may raise" | 0.2 + 1.1, the error-exemption shape | A new boot step carries FUN-17's `RuntimeStoreFactory` with it. `plan.md` §6. |
| `4.1` one task for all four sabotage tests | each gate lands with the change it proves | *Reachability precedes `[x]`* — a task cannot be ticked on a gate that lands two waves later. |
| — | 0.4 (AC-6) moved to wave 0 | Its file list is disjoint from everything; nothing gains from serialising it. |

---

## Wave 0 — independent foundations

- [x] **0.1** Make `Stored.revision` an opaque token — **AC-5**
      *Files:* `src/functualize/_types/protocols.py`, `src/functualize/_primitives/substrate.py`,
      `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/substrate.py`,
      `plugins/domains/functualize-tasks-local/src/functualize_tasks_local/_provider.py`
      *Four files, deliberately:* this is AC-5's exact grep hit set (`contracts.md` §1.1), and
      `uv run mypy src/` is **red at every intermediate point** — splitting it creates a wave
      boundary where the repo does not typecheck.
      *Do:* add `Revision = NewType("Revision", str)` in `_types/protocols.py`; change
      `revision: int` → `revision: Revision` at `:784`; `_revision_of` returns `Revision`
      (`substrate.py:60-67`, and `Stored(...)` at `:132`); the SQLite substrate stringifies its
      row version at `:112` (the `documents.revision INTEGER` column does **not** change, and
      `:130`'s `revision = documents.revision + 1` stays — it is the minter);
      `_provider.py:106`'s return annotation `int | None` → `Revision | None`.
      *While in `protocols.py`:* fix `:790` "Three members, deliberately" → six. `:812` already
      says "Six members, not three"; the class docstring contradicts itself. Not an AC.
      *Invariants:* no call site does arithmetic on a revision outside the SQLite substrate;
      `StoreSubstrate`'s six members unchanged.
      *Gate:* `spec.md` → AC-5 parts (a) and (b), plus `uv run mypy src/` clean and
      `uv run pytest plugins/substrates/functualize-substrate-sqlite/tests/`.
      *Call path:* `ScopeStore._load` → `substrate.read` → `Stored`. Every store read.
      *Done when:* the AC-5 greps return what AC-5 requires and mypy is clean.

- [x] **0.2** Add `SubstrateInstallError` and export it from `functualize.plugin` — **AC-4 (part 1/2)**
      *Files:* `src/functualize/_types/errors.py`, `src/functualize/plugin/__init__.py`,
      `tests/test_public_api_surface.py`
      *Do:* new `SubstrateInstallError(Exception)` beside `SubstrateUnreadableError`
      (`_types/errors.py:525`); re-export from `functualize.plugin` — required because the
      plugin raises it and a plugin may not import `_types`; add the name to
      `EXPECTED_EXPORTS["functualize.plugin"]` (`tests/test_public_api_surface.py:108`).
      *Note:* this is the **first** error class in `functualize.plugin.__all__`
      (`grep -n 'Error' src/functualize/plugin/__init__.py` → nothing today). A deliberate
      widening of the plugin-author API, with its reasoning in `contracts.md` §1.2.
      *Behaviour change:* none. Nothing raises or catches it yet.
      *Gate:* `uv run pytest tests/test_public_api_surface.py` green; `uv run lint-imports`
      still 7 kept / 0 broken.
      *Done when:* the surface test passes with the name added, not by removing the assertion.

- [x] **0.3** Delete the dead `"state": {}` field and its now-wrong docstring
      *Files:* `src/functualize/_primitives/scope_store.py`, `tests/test_scope_store.py`
      *Scope amended 2026-09-22 (leader).* The first file list was `scope_store.py` alone, and the
      task's own gate could not pass with it: `test_blank_scope_has_every_section` (`:74-90`)
      asserts the created record's key set contains `"state"` — the field this task deletes.
      That expectation is stale and goes with the field. Dropping it is **not** re-pinning it,
      and re-pinning it elsewhere is forbidden: the field is the deliverable.
      *Do:* remove `"state": {}` (`:102`) and the ten-line docstring above it (`:92-101`) that
      describes behaviour `durable-run-layer`/T3 moved to `scope-state/<id>.json`; drop the
      `"state"` entry and its four comment lines from the expected set in
      `test_blank_scope_has_every_section`.
      *Verified dead before writing this:* `grep -rn 'get("state"' src/functualize plugins`
      returns **one** hit, `scope_state_store.py:125`, which reads a *different document*.
      `normalize_scopes` (`_primitives/scope_format.py:88-122`) passes scope records through
      verbatim and rejects no unknown key, so records already on disk keep an inert extra key.
      *Re-confirmed 2026-09-22 (leader), when the scope amendment below was made:* two tests
      state the migration in their own comments — `tests/integration/test_scope_lifecycle.py:328`
      ("`record["state"]` is no longer where it lives") and
      `tests/test_state_root_isolation.py:105-107` (it reads `scope-state/*.json`, "not in the
      record"). No reader of the record's `"state"` key exists anywhere in `src/`, `plugins/` or
      `tests/`.
      *Gate:* `uv run pytest tests/test_scope_store.py` green;
      `grep -n '"state": {}' src/functualize/_primitives/scope_store.py` empty.
      *Done when:* no scope record is created with the field, no reader looked for it, and the
      stale expectation in `tests/test_scope_store.py` is gone.

- [x] **0.4** Route the TUI's shell-history write through the installed substrate — **AC-6**
      *Files:* `src/functualize/_cli/tui/shell_mode.py`, `tests/_cli/test_shell_mode.py`
      *Do:* `_record_history_quietly(command, code)` (`:295`) takes `app`; `:243` passes the
      `app` that `execute_shell_handoff` (`:217`) already receives; `:312` becomes
      `ShellHistoryStore(app.substrate)`, falling back to `.for_project(Path.cwd())` when `app`
      is `None`. `app.substrate` is the **same public accessor the CLI reader uses**
      (`app/core.py:333-335`, read by `_cli/builtins.py:691`) — one derivation for writer and
      reader, per `contributor/reference/pitfalls.md` §22.
      *Invariants:* `_cli` imports no `_`-prefixed package (`app.substrate` and
      `functualize.app.utils` are both public); the existing narrow `except (OSError,
      ValueError, KeyError)` at `:325` stays narrow — history is still best-effort.
      *Gate:* `spec.md` → AC-6: with `SQLiteSubstratePlugin` installed, a `!` command written
      through the handoff path is visible to `func builtin history`. Assert **through both
      surfaces**, not by comparing paths — `tests/primitives/test_one_substrate_choice.py`
      passes today while this bug exists.
      *Call path:* inline-TUI handoff loop → `_cli/inline_tui.py:169` →
      `execute_shell_handoff` → `:243`. Break the `app` argument and the new test must fail.
      *Done when:* the two-surface test is green and `uv run lint-imports` still passes.

## Wave 1 — compare-and-swap, and the boot raise

- [ ] **1.1** Let a substrate install failure escape `APP_READY` — **AC-4 (part 2/2)**
      *Files:* `src/functualize/_app/boot.py`,
      `plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/_plugin.py`,
      `tests/` (the AC-4 gate; pick the file that already owns boot-failure tests)
      *Depends on:* 0.2.
      *Do:* in **both** hook loops — `boot_standard` at `:879-882` and `boot_static` at
      `:467-473` — add `except SubstrateInstallError: raise` **before** `except Exception`.
      In `_plugin.py:86`, wrap the `SQLiteSubstrate(self._db_path(app))` construction failure in
      `SubstrateInstallError`, imported from `functualize.plugin`.
      *Do not:* widen the loop to re-raise everything, and do not add a boot step. `plan.md` §6
      records both rejections; the research rejects the first in its own words.
      *Invariants:* what an `APP_READY` hook means is unchanged for every other plugin. The
      three documents that teach `install_substrate` from `on_ready` stay correct
      (`docs/guides/workflows.md:391`, `docs/examples/plugins/custom-state-backend.md:61`,
      `examples/plugins/custom_state_backend/README.md:65`).
      *Gate:* `spec.md` → AC-4, **both assertions**: (i) `defect_b2.py`'s shape now prints
      `BOOT FAILED as intended: SubstrateInstallError`, on `boot_standard` **and**
      `boot_static`; (ii) an unrelated `APP_READY` hook that raises is still logged and
      swallowed. Assertion (ii) is what proves the fix did not change the hook contract.
      *Call path:* `FunctualizeApp(...)` → `boot_standard` → `:870` hook loop → the plugin's
      `_on_app_ready`. Remove the `raise` and gate (i) must fail.
      *Done when:* both assertions pass on both boot paths.

- [ ] **1.2** Compare-and-swap the `scopes.json` write, which makes the claim atomic — **AC-1, AC-3 (records)**
      *Files:* `src/functualize/_primitives/scope_store.py`,
      `tests/primitives/test_lease_fencing.py`
      *Depends on:* 0.1 (the `Revision` type), 0.3 (same file).
      *Do:* in `_mutate` (`:235-266`) capture the revision from the read and pass
      `expect=` on the write at `:266`, inside a bounded retry loop. **Copy the shape at**
      `plugins/domains/functualize-tasks-local/src/functualize_tasks_local/_provider.py:139-158`
      — lock *and* CAS, belt and braces, because the lock is real on both shipped substrates and
      the CAS is what survives a backend whose lock is a no-op. Same treatment for `batch`'s
      exit write (`:292-311`). The fence check at `:249` **does not move**.
      *Carry the precedent's recorded limitation, in a comment:* `write(..., expect=None)` on a
      never-written document is unconditional, so the first write to `scopes.json` cannot be
      compare-and-swapped. Mitigated because `ensure_scope` creates the document before any
      claim (`_engine/frontier.py:177` → `:183`) — state the mitigation, do not assume it.
      *Why this is AC-1:* `claim_scope` routes through `_mutate` (`:749-750`), so CAS-ing
      `_mutate` makes the claim atomic. **`lease.py` is not touched** — owner-blindness at
      `:302` can only bite when two runners share a generation, which the CAS makes
      unreachable. Recorded in `plan.md` → *Surviving smells* rather than fixed.
      *Gate:* `spec.md` → AC-1 — a **two-process** claim race with locking disabled yields
      `distinct generations: 2 of 2`. Reuse `_no_locking` at
      `tests/primitives/test_lease_fencing.py:194-220`; add the second process, because that
      harness is single-process today and one process hides this class of bug entirely
      (`pitfalls.md` §22). Plus `spec.md` → AC-3 for `scope_store.py`'s writes.
      *Call path:* `_engine/frontier.py:183` `claim_scope` → `_mutate` → `substrate.write`.
      Remove `expect=` and the two-process gate must fail.
      *Done when:* `2 of 2`, and `uv run pytest tests/primitives/test_fenced_writes.py
      tests/primitives/test_lease_fencing.py` is green.

- [ ] **1.3** Compare-and-swap the `scope-state/<id>` writes — **AC-3 (state)**
      *Files:* `src/functualize/_primitives/scope_state_store.py`,
      `tests/primitives/test_scope_state_store.py`
      *Depends on:* 0.1.
      *Do:* `expect=` on the `_mutate` write (`:152`) and on the `batch` exit write (`:169`),
      same bounded-retry shape as 1.2. **The scaffold missed `batch`** — it writes the whole
      accumulated state at `:169` under the same unfenced, unconditional `write`.
      *Invariant, and it is load-bearing:* `ScopeStateStore` still knows **nothing** about
      generations. `grep -c generation src/functualize/_primitives/scope_state_store.py` must
      stay **0** after this task. It owns one document and must not read `scopes.json` —
      that cross-document read is FUN-17's `RuntimeTransaction`, not this wave's
      (`plan.md` §6).
      *Gate:* `spec.md` → AC-3 for this file; `grep -c generation` still 0;
      `uv run pytest tests/primitives/test_scope_state_store.py` green.
      *Call path:* `rc.state.set()` → `_engine/capabilities/state.py:123` →
      `scope_store.py:520` → `ScopeStateStore.set` → `_mutate` → `substrate.write`.
      *Done when:* both writes carry `expect=` and the generation count is still zero.

## Wave 2 — the fence reaches `rc.state`

- [ ] **2.1** Fence every `rc.state` write behind one seam in `ScopeStore` — **AC-2**
      *Files:* `src/functualize/_primitives/scope_store.py`,
      `tests/primitives/test_scope_state_store.py`
      *Depends on:* 1.2 (same file, and the fence reads a document 1.2 made CAS-correct).
      *Do:* add one private `_fenced_state(scope_id)` that, when `self._generations` holds a
      generation for `scope_id`, calls `check_generation(scope_id, read_lease(...), held)`
      against the lease freshly read from `scopes.json`, then returns
      `self._state_store(scope_id)`.
      *The number is SEVEN, not five — the scaffold and an earlier draft of this task both said
      five.* Measured: `grep -n '_state_store(' src/functualize/_primitives/scope_store.py`
      returns the definition at `:471` plus **seven** call sites:

      | Method | `def` | `_state_store` call | Fence it? |
      |---|---|---|---|
      | `get_state` | `:516` | `:518` | **no** — a read, and `_mutate` fences writes only |
      | `set_state` | `:520` | `:527` | **yes** |
      | `delete_state` | `:529` | `:531` | **yes** |
      | `state_snapshot` | `:533` | `:535` | **no** — a read |
      | `clear_state` | `:537` | `:539` | **yes** |
      | `state_batch` | `:541` | `:548` | **yes**, at entry **and** at the exit write — the stale window is the whole block, not its first instant |
      | `discard_state` | `:550` | `:562` | **yes** — destructive |

      Route the five write paths through `_fenced_state`; leave the two reads on
      `_state_store`. Fencing a read is a wider change than AC-2 asks for and than
      `_mutate:249` does for records.
      *Do not:* pass a generation into `ScopeStateStore.__init__`. `_state_store()` (`:471`) memoizes at
      `:512-514`, so a `hold()` afterwards would never be seen — the
      fence must be read at write time. Do not put the check on each method either; that is the
      design `:239-244` and `tests/primitives/test_fenced_writes.py:10-15` argue against by
      name. Full alternatives table: `plan.md` §6.
      *Blast radius, measured:* no signature changes, so **no caller is edited**.
      `_engine/capabilities/state.py` is the sole production caller of `set_state` (`:123`),
      `get_state` (`:106`), `delete_state` (`:127`), `state_snapshot` (`:130`, `:133`) and
      `state_batch` (`:147`). `clear_state` has **two**: `state.py:137` and
      `_cli/tui/panel_host.py:449` — the `_cli` one holds no generation, so no fence fires
      there, but a reviewer will look for it. The `ast` census is in `plan.md` §4.
      *New behaviour a reviewer must see:* `rc.state.set()` can now raise
      `StaleGenerationError`. Nothing in `_engine/` catches it today. `contracts.md` §3 records
      this as the ticket's largest behavioural break and recommends *refused loudly* for this
      wave.
      *Gate:* `spec.md` → AC-2 — `defect_b1.py`'s shape prints `state write : REFUSED` and B
      reads back `'written-by-A-while-holder'`. Assert with locking disabled too.
      *Call path:* as 1.3. Break `_fenced_state`'s call to `check_generation` and the AC-2 test
      must fail.
      *Done when:* AC-2's gate is green and `test_a_nested_workflow_still_owns_its_own_scope`
      still passes — a nested workflow claims its own scope through the *same* store object, and
      `hold` is per-scope for exactly that reason (`:268-285`, rationale at `:276-280`).
      That test lives in `tests/integration/test_workflow_as_job_e2e.py:509`, so it is outside
      the targeted selection — name it in the evidence, and run it as the second pytest
      invocation if the first is green.

## Wave 3 — verification sweep and the evidence bar

- [ ] **3.1** Run all five repository checks and every acceptance gate on one commit
      *Files:* `CHANGELOG.md`, `.spec/STATE.md`, this file
      *Depends on:* every task above.
      *Do:* `uv run ruff check --fix src/ tests/ plugins/ examples/`,
      `uv run ruff format src/ tests/ plugins/ examples/`, `uv run mypy src/`,
      `uv run lint-imports` (must still be 7 kept / 0 broken), then pytest — **smallest
      relevant scope, at most two invocations** (`AGENTS.md` command discipline). The targeted
      selection Mika measured green on `b82fc78` is the right first invocation:
      `tests/primitives/test_scope_state_store.py tests/primitives/test_fenced_writes.py
      tests/primitives/test_store_concurrency.py tests/primitives/test_lease_fencing.py
      tests/primitives/test_shell_history.py tests/primitives/test_run_store.py
      tests/test_scope_store.py tests/test_public_api_surface.py` (baseline 207 passed,
      3 skipped, 31 s). Add `tests/_cli/test_shell_mode.py`,
      `tests/primitives/test_one_substrate_choice.py` and the new boot-failure test.
      **Do not run the full fast suite** — it needs well over an hour on this host.
      *Then:* paste each of the six gates with its exact command and raw output; write
      `CHANGELOG.md` by hand (it is prose, never generated); update `.spec/STATE.md` (gitignored
      and currently **absent**, which reads as "no work in flight"); tick the boxes above only
      where the gate is green against the code as it actually stands.
      *Done when:* all five checks pass, six gates have pasted raw output, and residual risk is
      stated honestly — including the two `plan.md` review items and whether they were answered.

## Out of scope on this branch — report, do not build

Verified while planning; each belongs to a later wave. Full detail in `spec.md` → *Out of scope*.

1. Cross-document atomicity (B3's headline) — FUN-17 `RuntimeTransaction`.
2. `StoreSubstrate` made public / `Stored` exported from `functualize.plugin` — later wave.
   It is public **nowhere** today while `docs/guides/workflows.md:385-386` names a private path.
3. Deprecating `ScopeStore` / `RunStore` — **impossible here**: `.spec/CONSTITUTION.md` forbids
   compat shims under *Pre-Release Stance*. A contradiction in the design document.
4. Regenerating `contributor/architecture/codemaps/`, which never absorbed `store-substrate`.
5. Deciding whether `src/functualize/ui/` is a seventh public package.
6. Correcting the line-citation drift in `05-the-design.md`, `06-s3.md`, `07-the-design.md`.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": [
        "0.1",
        "0.2",
        "0.3",
        "0.4"
      ]
    },
    {
      "id": 1,
      "tasks": [
        "1.1",
        "1.2",
        "1.3"
      ]
    },
    {
      "id": 2,
      "tasks": [
        "2.1"
      ]
    },
    {
      "id": 3,
      "tasks": [
        "3.1"
      ]
    }
  ]
}
```
