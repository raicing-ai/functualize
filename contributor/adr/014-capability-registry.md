# ADR-014: A capability is declared once, beside itself

**Status**: accepted
**Date**: 2026-08-30
**Deciders**: Hakim (decision D-4, plus the follow-up question on where the
name set lives), agent

## Context

Adding one capability meant editing the same fact in four places, **two of which
failed silently**:

| # | Site | Missed ⇒ |
|---|---|---|
| 1 | `_engine/capabilities/<new>.py` | — |
| 2 | `executor._per_invocation_types()` | the parameter resolves to nothing, **no error** |
| 3 | `executor._create_per_invocation_cap()` — a 129-line `if/elif` ladder ending in `type_()` | falls through to a bare construction that may or may not work |
| 4 | `_primitives/capability_names.INJECTED_PARAM_TYPE_NAMES` | the parameter becomes a **CLI flag**; cold boot works, warm boot dies with `Error: Missing argument 'SH'` |
| 5 | a `_bind_*` method **and** its one call site inside `_execute_lifecycle` | the capability is injected and **inert** |

Sites 2 and 4 were a real defect — `Shell` and `Stdout` missing from one copy
of the list, so a warm boot turned them into CLI flags. Site 5 is the standing
risk in the `Sources` two-phase bind, mitigated with a cold-and-warm sabotage
test.

**That branch fixed three instances of the pattern without changing the
pattern.** An independent audit named this as the structural cause of D7, D8 and
its own finding A alike: *a rule stated in more than one place, in a system with
no mechanism for stating it once*.

Prior art: NestJS solves the same problem with custom providers
(`{provide, useClass | useFactory | useValue, scope}`) plus `Scope.REQUEST`.
One entry per provider, declared where the provider is, and the container
derives the rest.

## Decision

**One `CapabilitySpec` per capability, written beside the capability.**

```python
# _engine/capabilities/sources.py
CAPABILITY = CapabilitySpec(
    name="Sources",
    type=Sources,
    factory=lambda ctx: Sources(),
    preflight_bind=_bind_from_preflight,
)
```

`_engine/capabilities/registry.py` collects them, and three of the five sites
derive:

| Was | Is |
|---|---|
| `_per_invocation_types()`, a hand-written `set[type]` | `PER_INVOCATION_TYPES`, derived |
| the 129-line ladder with a `type_()` fallback | `SPEC_BY_TYPE[type_].factory(ctx)` — **no fallback**; an unregistered type raises |
| one hard-coded `_bind_sources(...)` line in `_execute_lifecycle` | a loop over the specs that declare a `preflight_bind` |

Every factory takes one `CapabilityContext(engine, context, caps)`. The
uniformity is load-bearing rather than tidy: a dispatch table cannot have
per-branch signatures, and that is exactly why the ladder was a ladder.

`preflight_bind` turns the second phase from *"remember to call `_bind_sources`"*
into a declared property. A capability that needs pre-flight data cannot be
finished when DI creates it — DI must run first, because the pre-flight's args
hash reads `context.injected` — so the two-phase shape is inherent. Declaring it
is what stops the second phase being forgotten.

### The name set stays in `_primitives`, and is checked at import

Site 4 is the one that **cannot** derive, and this was put to Hakim explicitly
with two alternatives before it was decided.

`_discovery/providers.py` consumes `INJECTED_PARAM_TYPE_NAMES` to strip injected
parameters from the CLI surface. `_discovery` and `_engine` are peer layers under
the *"Peer layers are independent"* import contract, so `_discovery` may never
import a capability module — matching on the **name** is the whole reason these
are strings rather than types. There is no location reachable by `_discovery`
where a derivation from the registry could run.

So the set stays, and it is made non-drifting instead: `registry.py` asserts at
**import time** that its spec names equal the set, and raises a `RuntimeError`
naming both differences when they disagree.

This is deliberately not the option D-4 rules out. D-4 rules out *a test*
asserting that two hand-maintained lists agree; a test runs when somebody runs
it, and both lists stay hand-maintained. The invariant fires on every process
that resolves a capability, including in production, and there is still exactly
one place a capability is declared.

## Consequences

### Positive

- Adding a capability is one declaration plus one string, and forgetting the
  string is a startup crash rather than a parameter that silently becomes a CLI
  flag and fails on the job's *second* invocation.
- The `type_()` fallback is gone. A missing registration raises with a message
  naming the registry and this ADR.
- `executor.py` lost ~100 lines and its largest type-switch.
- A second capability needing a two-phase bind declares it and is found; nobody
  has to notice that `_execute_lifecycle` has a line for it.

### Negative

- `Shell` and `Stdout` have their specs in `_engine/capabilities/{shell,stdout}.py`
  rather than beside their protocol types in `_types/`, because `_types` may
  import nothing internal and so cannot hold a factory. The nearest legal home,
  and noted in both files — but it is one hop from "beside the capability".
- `JobConfigView` keeps a special case in the resolver. It is the one type
  resolved by identity against a runtime value (`engine._config_view_type`,
  discovered at boot), so it cannot be a registry key written at import time. Its
  spec exists carrying `type=None` purely so the name invariant balances.
- The registry imports eleven capability modules, so it is imported lazily by
  the executor to preserve the warm-boot "zero imports until a job resolves"
  property. The invariant therefore fires on first capability resolution rather
  than at interpreter start — which is every real run, but not `--help`.

### Neutral

- Behaviour is unchanged for all eleven existing capabilities: same
  constructions, same arguments, same lifecycle positions. Every factory body
  was transcribed with its comments intact; the only difference is that it reads
  its inputs from `ctx.engine` instead of `self`.
- `_per_invocation_types()` survives as a function because it has callers; it
  now derives instead of restating.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| Move the whole registry into `_primitives` as pure data (name + flags), and bind factories by name from `_engine` | genuinely one list, reachable by every layer | the entry no longer sits beside the capability it describes, and adding one becomes two edits in two files | Put to Hakim; not chosen. D-4's shape — declared beside the capability, carrying its factory — is the half worth keeping |
| Let `_discovery` import the engine registry and delete the string set | literally one list, nothing to keep in sync | breaks *"Peer layers are independent"*; `lint-imports` goes from 5 kept / 0 broken to 4 kept / 1 broken | Put to Hakim; not chosen, and ruled out by the task brief. The layer rule is load-bearing |
| A test asserting the two lists agree | cheap; no new mechanism | a test runs when somebody runs it, and both lists stay hand-maintained | Ruled out by D-4 explicitly. Superseded by the import-time invariant, which is strictly stronger |
| Keep the ladder, add a completeness test over its branches | smallest diff | tests the branches that exist, not the ones that are missing; the `type_()` fallback makes "missing" unobservable | Does not address site 3 at all |

## References

- `examples/standalone/composition_lab/` — every capability in the registry
  used together, on both surfaces
- `src/functualize/_engine/capabilities/spec.py`, `registry.py`
- `src/functualize/_primitives/capability_names.py`
- `tests/engine/test_capability_registry.py`
