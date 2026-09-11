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

Four paths, mapped by running each one:

| path | does state carry today? |
|---|---|
| `rc.invoke` parent ↔ children | **yes** |
| `@workflow` step → next step | **no** |
| `@workflow` step → epilogue | **no** |
| `state: State` (DI), anywhere | **no** |

`rc.state` returns the shared store only `if self._workflow_scope is not None`.
`workflow_orchestrator.py:122` passes `workflow_scope_id` — a **string** — and
never `parent_scope`, the **object**. So every step gets `_workflow_scope =
None`, lazily builds a private `StateStore`, and writes into a store nothing
reads. Silently, with no test and no doc describing the behaviour either way.

`examples/standalone/composition_lab/jobs/pipeline.py` §8 documents the DI half
as *"the trap this job pins"* and opens §9 with *"Three things are called
state"*. That is a warning about a defect, not a design: the isolation is an
artifact of `State` being a per-invocation dict that shares nothing, ever.

The three things are real: `_primitives/state_store.StateStore` (JSON, on
disk), `_engine/capabilities/state_store.StateStore` (in-memory, workflow
scope), and `_engine/capabilities/state.State` (per-invocation dict).

**Decision (maintainer, 2026-09-11): one flat store per run.** No framework
namespacing. A user who wants it writes `state.set("fetch.count", n)`, and that
convention is documented rather than built. `keys(prefix)` is what makes it pay
off, so the surviving class keeps that parameter.

## C · Acceptance criteria

- **AC-1** A `@workflow` step's `rc.state` is the scope's store, so a value set
  by one step is readable by every later step and by the epilogue.
- **AC-2** `state: State` and `rc.state` are the same object, in a workflow
  step and outside one.
- **AC-3** `State` names exactly one class. The per-invocation dict is deleted,
  not aliased (*Pre-Release Stance*: delete rather than shim).
- **AC-4** `state.keys(prefix)` filters, so the documented `"fetch.count"`
  convention is usable without a second API.
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

- Renaming `_primitives/state_store.StateStore` (the on-disk one). It is a
  different layer with a different job; the collision is a naming annoyance,
  not a correctness defect, and folding it in triples the blast radius.
- `copy_context()` for `trace_id` across `invoke_parallel`. A real defect found
  in the same audit, but it is an observability fix on a different axis — its
  own task list.
