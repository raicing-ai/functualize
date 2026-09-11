# Capability duality — one object behind `rc.X` and `x: X`

**Depends on:** — (independent; touches `_engine/capabilities/` and the
workflow orchestrator, neither of which F5 T3–T13 edit)

## A · Why

`.spec/CONSTITUTION.md` → *DI + RunContext Duality* already states the rule:

> The DI registry and RunContext resolve from the **same underlying capability
> map** — they are two access paths, not competing systems.

It was prose for its whole life and nothing enforced it. An audit of all twelve
capabilities found that of the six with both access paths, **one** (`Log`)
obeyed it. Three of the violations were live defects, fixed in `99dcaf2`:
`Invoke` fired every `INVOKE_*` hook with `parent=None` on the DI door, the
injected `Perf` raised `NotImplementedError` on every method for its entire
life, and `wiring.with_plugin_config` returned a context missing seven wiring
fields.

This feature closes the rest: the general resolution mechanism, and `State` —
the one remaining case where the two doors are not merely different objects but
different *classes*, with different lifetimes, behind names that read
identically at the call site.

## B · The `State` finding

Four paths, mapped by running each one — see `research.md` §2 for the cause.

| path | carried state before this feature? |
|---|---|
| `rc.invoke` parent ↔ children | yes |
| `@workflow` step → next step | **no** |
| `@workflow` step → epilogue | **no** |
| `state: State` (DI), anywhere | **no** |

`examples/standalone/composition_lab/jobs/pipeline.py` §8 documents the DI half
as *"the trap this job pins"* and opens §9 with *"Three things are called
state"*. That is a warning about a defect, not a design.

**Maintainer decisions, in the order they were taken.**

1. **One flat store per run.** No framework namespacing; a user who wants it
   writes `state.set("fetch.count", n)`.
2. **`keys()` matches by glob, not by prefix** — `keys("fetch.*")`. A bare
   prefix leaks the neighbouring namespace, and requiring a trailing dot to
   avoid that is worse DX than the leak. `research.md` §5.
3. **No in-memory state tier at all.** The in-memory store existed as a
   fallback for when no state plugin was installed, and a fallback that empties
   on resume is unusable: the case you most need state in is the case that
   loses it. `State` is backed by `ScopeStore`. `research.md` §6.
4. **One name per store.** Five things wear the word "state" and two unrelated
   classes are both `StateStore`. `research.md` §3, executed by T8.

## C · Acceptance criteria

- **AC-1** A `@workflow` step's `rc.state` is the scope's store, so a value set
  by one step is readable by every later step and by the epilogue.
- **AC-2** `state: State` and `rc.state` are the same object, in a workflow
  step and outside one.
- **AC-3** `State` names exactly one class, and it is **durable**. Both
  in-memory classes are deleted, not aliased (*Pre-Release Stance*: delete
  rather than shim).
- **AC-4** `state.keys(pattern)` matches by glob using the codebase's existing
  matcher, so `keys("fetch.*")` cannot reach `"fetchmeta.x"`.
- **AC-4b** A workflow that blocks at a gate and is resumed **in a new
  process** finds the state its earlier half wrote. This is the criterion the
  in-memory store could never meet and the reason it is gone.
- **AC-4c** The plugin seam survives: `WorkflowScope.replace_state_store` still
  swaps in a `StateStoreProtocol` implementation, and
  `functualize-state-sqlite` still works.
- **AC-5** `rc[T]` and `T in rc` answer from the per-invocation capability map
  before the DI registry, so a capability the job is holding is never reported
  missing.
- **AC-6** A test parametrized over `CAPABILITY_SPECS` fails when a capability
  gains an `rc` accessor that does not resolve through the shared map — the
  rule becomes executable rather than prose.
- **AC-7** The scope propagation is bounded to one run: two separate runs of
  the same workflow share nothing.
- **AC-8** `examples/.../pipeline.py` §8 no longer teaches the trap, because
  the trap is gone.
- **AC-9** **ADR-021 states the mechanism and its exemptions.** The rule is
  useless if the next person has to rediscover which capabilities may opt out
  and why, so the ADR names the resolution mechanism, each class of capability
  that legitimately cannot share, the reason, and the remedy in each case. The
  docstring at the mechanism's own implementation says the same thing in two
  sentences and points at the ADR — `.spec/CONSTITUTION.md`'s rule gains a
  pointer to it rather than restating it.

## D · Out of scope

- Renaming `_primitives/state_store.StateStore` (the on-disk one). T8 renames
  the *classes*, which is the collision a reader hits. Renaming the **file**
  `state.json` is held for `durable-run-layer`/T3b, written up there: it is
  only correct after `history` is derived from the run log, and that is decided
  in T3. Renaming first would leave a `history` key in a file called
  `fresh.json`.
- `copy_context()` for `trace_id` across `invoke_parallel`. A real defect found
  in the same audit, but it is an observability fix on a different axis — its
  own task list.
