# Migration and delivery sequence

## Refactoring strategy

This is a branch-by-abstraction migration. The compatibility adapter lands
before the relational provider so production paths move once and backend
implementation changes behind them.

No stage is “done” because its components have unit tests. Each stage names the
cold and warm production paths that reach it and has a sabotage test that breaks
the wire.

## Delivery waves

### Wave 0 — architecture and characterization (FUN-16)

- Accept this folder and the implementing ADR boundary.
- Pin current JSON/SQLite behavior, discard/refusal rules, caps, views, CLI/MCP
  parity, crash/resume, fencing, and operator commands.
- Record legacy fixtures for filesystem documents and the SQLite `documents`
  table.
- Add architecture tests that prevent plugins/public surfaces from adding new
  private store reach-through.

Gate: current behavior is reproducible from fixtures and every current consumer
in the blast-radius table has an owning migration ticket.

### Wave 1 — ports, provider family, public facade (FUN-17)

- ADR: add `_persistence` peer layer and public plugin authoring surface.
- Introduce persistence DTOs/protocols, bind-once handle, registry, capability
  record, UoW, query/admin facades.
- Implement `DocumentRuntimePersistence` by adapting current stores.
- Select and bind it on both static and standard boot paths.
- Move CLI/MCP/public views to app query/control/admin facades.

`TRANSITIONAL`: semantic ports still delegate to document stores; on-disk data
and transaction limits are unchanged.

Gate: removing the binding or either boot-path selection fails dual-surface,
cold/warm, MCP, and workflow tests.

### Wave 2 — normalized schema and transition service (FUN-18)

- Land schema/migration catalogue and provider contract suite.
- Move engine/walker/state writes to short semantic transitions.
- Persist authoritative events and outbox intents inside those transitions.
- Emit EventBus notifications only after commit.
- Keep the document adapter passing the same contract where its capabilities
  permit; mark unsupported distributed capabilities explicitly.

Gate: fault injection between every write proves rollback leaves no partial
transition; stale fencing generation cannot update state or outcome.

### Wave 3 — relational SQLite and legacy import (FUN-19)

- Replace the plugin's opaque `documents` table as the runtime implementation
  with normalized tables.
- Plugin registers a provider factory during load; it imports public APIs only.
- Implement checksummed migrations, WAL/busy-timeout policy, transaction/UoW,
  indexed queries, health/admin, and close lifecycle.
- Implement offline import from JSON files and legacy SQLite documents.

Cutover procedure:

1. acquire exclusive project migration lock;
2. snapshot/backup source documents/database;
3. import into a new schema transaction;
4. verify counts, identities, terminal/live status, state keys, sequence order,
   and payload digests;
5. atomically persist provider selection/cutover marker;
6. reopen through target query ports and run semantic verification;
7. retain source backup until explicit cleanup.

There is no ongoing dual-write. A failed import leaves the source authoritative.

Gate: imports from every legacy fixture are repeatable; interruption at each
phase resumes or rolls back without choosing two authorities.

### Wave 4 — workflow/state/resume (FUN-20)

- Complete workflow/step/branch/state repositories and query/control facade.
- Move lease claim/renew/release to conditional row transitions.
- Prove two processes on SQLite cannot both commit the same generation.
- Preserve workflow graph digest, replay-skip, branch determinism, and
  non-eviction of live scopes.

Gate: start → block → crash → competing resume → terminal works through `func`,
embedded app, and MCP; exactly one runner commits each generation.

### Wave 5 — interactions, evidence, outbox (FUN-21)

- Normalize interaction requests/candidates/evaluations and tool/evidence links.
- Persist effect intent with the state transition.
- Add dispatcher claim/retry/idempotency policy and dead-letter/operator view.
- Remove `run_log`/`walk_log` as authorities; retain live EventBus behavior.

Gate: crash before commit sends nothing; crash after commit leaves dispatchable
intent; crash after provider acceptance follows the declared idempotency policy.

### Wave 6 — network SQL/distributed resume (FUN-22)

- Implement the first network provider only after its exact database is chosen.
- Validate connection pooling, isolation, row locking/CAS, retry classification,
  migration locking, clock assumptions, and notification/poll strategy.
- Refuse multi-machine mode when provider capabilities do not satisfy it.

Gate: two machines/processes contend on claims, migration, state, and outbox;
serialization/deadlock retries repeat database-only callbacks and never repeat
external effects.

### Wave 7 — workspace/artifact boundary (FUN-23)

- Define `WorkspaceProvider` and artifact reference model independently of
  runtime repositories.
- Keep artifact bytes/files in filesystem, blob store, AgentFS-like provider, or
  another explicit workspace implementation.
- Link runtime evidence by immutable reference/digest.

Gate: snapshot/restore and remote workspace cases preserve reference integrity;
runtime DB deletion does not silently delete shared blobs.

## Test architecture

### One semantic provider suite

Every provider factory is run against the same behavior contract:

- run tree and recent history queries;
- workflow transition and replay determinism;
- state batches and rollback;
- unreadable/corrupt data policy;
- fencing and stale writer refusal;
- event sequence monotonicity;
- outbox atomicity/claiming;
- admin describe/health/schema version;
- close/reopen durability.

### Capability-specific suites

- SQLite: multiple processes, WAL, busy timeout, crash recovery, file move/copy,
  no multi-machine claim.
- Network SQL: multiple hosts, pool exhaustion, transient retry, migration race,
  server clock/transaction isolation.
- Document adapter: compatibility/discard rules and clearly refused unsupported
  capabilities.

### Surface and wiring suite

The same runtime facts are asserted through:

- `func` cold and warm cache;
- an embedded `FunctualizeApp`;
- `Invoke` parent/child;
- MCP workflow and history tools;
- HTTP/Lambda request envelopes where relevant;
- `func builtin data/workflow/history` public facades.

Tests begin from real declarations and persisted legacy fixtures. Fakes are for
failure injection, not for replacing the production construction path.

## Documentation and removal

At final cutover:

- delete `EngineHost.substrate` and the public app substrate setter;
- remove direct `ScopeStore`/`RunStore` construction from surfaces/plugins;
- move or delete runtime stores from `_primitives`;
- retain `StoreSubstrate` only if local document services still need it, renamed
  to make that scope explicit;
- archive or amend ADR-022 with the semantic-port reopening decision;
- update examples and plugin development guidance;
- regenerate Graphify and the codemaps from the final committed graph.
