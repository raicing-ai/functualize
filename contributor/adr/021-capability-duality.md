# ADR-021: Capability Duality — `rc.X` and `x: X` Are Two Names for One Lookup

**Status**: accepted
**Date**: 2026-09-11
**Deciders**: maintainer, after an audit of all twelve capabilities

## Context

`.spec/CONSTITUTION.md` has always carried the rule:

> The DI registry and RunContext resolve from the **same underlying capability
> map** — they are two access paths, not competing systems.

It was prose, nothing enforced it, and an audit of every capability found that
of the six with both access paths, **one** obeyed it.

| capability | the `rc` path | shared the DI object? |
|---|---|---|
| `Log` | `rc.log()` | yes — read `_caps` |
| `Invoke` | `rc.invoke()` | no — built its own `WiredInvoke` |
| `State` | `rc.state` | no — a different *class* |
| `Perf` | `rc.events.perf_*` | no |
| `Prompt` | `rc.prompts.*` | no — reached `engine.host` |
| `Sources` | `rc.discovery.*` | no — reached `engine` |
| *any type* | `rc[T]` / `T in rc` | no — went to the registry |

Three were live defects. Every `INVOKE_START` / `INVOKE_END` /
`INVOKE_FAILURE` hook reached through an `inv: Invoke` parameter received
`None` as its parent while the identical hook via `rc.invoke` received the
context. The injected `Perf` raised `NotImplementedError` on **every** method,
for its entire life. `wiring.with_plugin_config` returned a context missing
seven wiring fields, including the engine — so `invoke` raised on it — and an
`_invoke_depth` reset to `0`, which defeats the recursion guard downstream.

None of this was caught by a green suite of 11,699 tests, and the reason is
worth recording: every capability had unit tests and they all passed. A unit
test constructs its subject directly, and a double answers whatever the test
wants to hear. Every test in the repository that called `perf.mark()` called it
on `NoopPerf` — the double that silently accepts everything — so nothing ever
called the real one.

## Decision

### The mechanism

**A per-invocation capability is resolved once per run into the capability map,
and `rc.X` and `x: X` are two names for one lookup in that map.**

`RunContext._cap(T)` is that lookup and the only one. Three properties make it
work, and each exists because its absence produced a defect:

1. **It resolves lazily, at call time, never at construction time.** A
   capability factory runs *during* parameter resolution, so for
   `def j(inv: Invoke, rc: RunContext)` there is no RunContext yet when `inv`
   is built. Capturing eagerly captures `None`. `TTY.ctx` had always done this
   correctly and was the model for the rest.

2. **It never constructs.** `Sources` and `Freshness` are injected *empty* and
   completed once the pre-flight decision exists. A resolver that helpfully
   built one on demand would hand back an empty map with no error — which is
   the failure `sources.py`'s own factory comment warns about.

3. **Where an `rc` path has real logic, the capability delegates to it rather
   than reimplementing it.** `WiredPerf` calls `rc.events.perf_mark*`. The
   alternative — two implementations of the prefixing and `enabled` rules that
   agree today — is how the doors drift apart again.

### Where this must be loosened, and what to do instead

The rule is about **per-invocation capabilities**. Five classes fall outside
it, and treating them as exceptions to be fixed would break working behaviour.
A future capability that fits one of these does not need a waiver; it needs the
remedy named here.

| class | why one object is wrong | remedy |
|---|---|---|
| **Qualified providers** — `Annotated[Conn, Qualifier("replica")]` | There is no "the" `Conn`. An `rc.conn` accessor cannot name which one, and inventing a default silently picks a database. | No `rc` accessor. `rc[Conn, "replica"]` is the only honest form; the registry raising `AmbiguousProviderError` is correct and stays. |
| **Factory-scoped providers** — `provide_factory` | A fresh instance per resolution *is* the contract. Caching one in the map silently converts it to a singleton. | Exclude by **scope**, not by type. The map holds per-invocation capabilities only. |
| **Exclusive resources** — `TTY` | Terminal ownership is granted at most once, pre-flight, and degrades to `None` when refused. A second handle is not a sharing bug, it is a correctness bug. | Read from the map, **never create**. An `rc` accessor that constructed one would hand out a handle that was refused. |
| **Pre-flight-bound capabilities** — `Sources`, `Freshness` | Complete only after a decision that has not been made when DI runs. | Read from the map, never create — property 2 above. The two-phase bind stays declared on the `CapabilitySpec`. |
| **App-scoped singletons** the user registered | Deliberately shared across *runs*, so a per-run map is the wrong home entirely. | `rc[T]` falls through to the DI registry. Correct, and unchanged. |

There is also a case that looks like an exemption and is not. `State` was a
per-invocation dict while `rc.state` was a scope-aware store, and
`examples/standalone/composition_lab/jobs/pipeline.py` §8 documented the
divergence — but as *"the trap this job pins"*, alongside §9's *"Three things
are called state"*. A warning is not a design. The isolation was an artifact,
the two are now one class, and the example no longer teaches the trap.

`Prompt` was the same shape, found later and worse. `rc.prompts` was a
`PromptFacade` and a `prompt: Prompt` parameter was a `Prompt`, and the two
were not merely different objects — **the injected one was inert**. Its factory
was `lambda ctx: Prompt()`, so `_provider` was `None` forever and every call
raised `InputNotAvailable` while `rc.prompts`, reading the live surface stack,
answered. A job written `def j(p: Prompt)` could not prompt at all.

That is worth separating from drift, because the two fail differently. Drift is
two objects that agree today and stop agreeing later. This was a door that
never worked, shipped behind a class whose existence implied it did. The
registry-driven test does not catch it — identity held once the objects were
merged, because the caps map holds whatever the factory returned regardless of
whether it is wired. Catching it took a test that asserts *the answer*, through
a collector that records being called. Both sabotages were run and they fail
**different** tests: breaking the factory fails the round-trip tests, breaking
the caps lookup fails the tripwire. They are complementary, not redundant.

**The test for whether something is a real exemption**: can you state, in one
sentence, what a user gains from the two doors returning different objects? For
all five rows above the answer is concrete. For `State` and `Prompt` it was
never anything but "that is what the code did".

**And a capability with one door is not an exemption — it is a non-case.**
`Sources` was twice reported as a rule violation. It is not: it has no second
door. `rc.discovery` is `DiscoveryFacade` (`get_job_schema` / `list_jobs`,
registry introspection) and `RunContext` has no `sources` accessor at all.
Giving it an `rc_accessor` would *create* a door rather than consolidate one. A
capability reachable one way cannot drift from itself, so the tripwire skipping
it is correct rather than a gap — and the row above already covers it for the
separate reason that its value is not complete when DI runs.

### Why this is enforced by a registry-driven test, not by prose

The Constitution's rule and `contributor/guides/wiring-discipline.md` §1 both
already said the right thing, and `Perf` shipped unwired anyway — because
"every user-declarable capability has an end-to-end test" was read as
*decorator* declarations (`tests/integration/test_declared_capabilities_e2e.py`
covers `deps`, `guards`, `cache`, `retry`, `run_mode`, `from_job` — six
decorator arguments and zero injected capabilities), and because nothing
enumerated the capabilities to check coverage against.

A third prose rule would fail the same way. `tests/integration/test_capability_duality.py`
is therefore parametrized over `CAPABILITY_SPECS`, the registry that already
exists (ADR-014), so a capability added tomorrow is covered the day its spec is
written. That is the property prose lacked — the same reasoning that made
ADR-014's name agreement an import-time assertion rather than a test.

## Consequences

- Adding a capability with an `rc` accessor that bypasses the map fails a test
  rather than shipping.
- A capability in one of the five classes above is declared as such on its
  `CapabilitySpec` and the test skips it by that declaration — an exemption is
  visible in the registry, not implicit in an omission.
- `State` is one class. Workflow steps share one store per run; the
  `"fetch.count"` key convention is documented rather than built, because a
  framework namespace is a second concept for something a string prefix already
  does.
- **That decision was made twice, because the first time it missed the place
  the namespace API actually lived.** `get_job_state("fetch", "rows")` and
  `list_job_namespaces()` were on `StateStoreProtocol`, not on `State`, so they
  survived the paragraph above by sitting one file away from where anyone read
  it. Both are now deleted (`capability-duality`/T12). The lesson is narrower
  than "check harder": a decision phrased about a *class* does not reach the
  *protocol* that class implements, and a plugin contract is exactly where an
  unwanted concept goes to survive.
- The deletion cost `functualize-state-sqlite` a real capability, which is
  recorded rather than glossed: it scoped rows by a genuine `(scope_id,
  job_namespace)` pair and could answer a cross-namespace read that the default
  dotted-key store only simulates. The Pre-Release Stance is what pays for
  that; a released framework could not have made this trade so cheaply.
- `Prompt` is one class. Deleting `PromptFacade` fixed an injected capability
  that had never worked, which is why the duality rule earns its keep beyond
  tidiness: the audit that enforces it is what surfaced the dead door.
