# Decisions and external research

## Decision summary

| ID | Decision |
|---|---|
| RP-1 | Preserve ADR-022's one-choice invariant, but replace document-shaped runtime access with semantic ports. |
| RP-2 | Use an Abstract Factory/UoW provider family, selected and bound once at boot. |
| RP-3 | Keep derived/local/plugin/workspace data outside the runtime family unless it participates in the same correctness transaction. |
| RP-4 | Normalize operational fields; JSON is for opaque payloads only. |
| RP-5 | Persist domain events/effect intent in the transition; EventBus observes after commit. |
| RP-6 | SQLite is local/single-host; network SQL is required for multi-machine execution. |
| RP-7 | Migrate offline with backup/verification/cutover; reject indefinite dual write. |
| RP-8 | Expose query/control/admin facades to every delivery surface. |
| RP-9 | Artifact bytes belong to a workspace/blob capability; SQL stores references. |

## Celery: useful mechanisms and a warning

Celery selects a result backend from one application configuration/URL and
centralizes lifecycle behavior in a backend base (`store_result`, metadata,
retry, expiry, cleanup). Schemes select concrete implementations, and custom
overrides are registered by class path. That validates three mechanisms used
here: one bootstrap choice, a stable semantic client-facing interface, and
backend-specific retry/capability behavior.

Celery also demonstrates the ceiling of a broad result-backend interface. Its
base contains many optional behaviors and a KV subclass because Redis, RPC,
files, SQL, document databases, and caches do not share one natural data model.
Functualize should copy the selection/factory mechanism, not copy a universal
backend hierarchy. Runtime workflow queries are explicit ports, and workspace,
cache, and effects remain separate capabilities.

Sources:

- [Celery configuration and result backends](https://docs.celeryq.dev/en/main/userguide/configuration.html)
- [Celery backend base source](https://github.com/celery/celery/blob/main/celery/backends/base.py)

## Omnigent: schema and operational lessons

Omnigent uses the same SQLAlchemy schema/migration lineage for SQLite,
PostgreSQL, and CockroachDB while declaring different deployment capabilities:
SQLite is single-instance; PostgreSQL/CockroachDB serve multi-instance use.
Its live model provides several transferable lessons:

- workspace/tenant identity participates in primary keys and indexes rather
  than relying on callers to remember an unindexed filter;
- conversation/session identity is separate from ordered item/evidence rows;
- parent/root IDs and positions are normalized for traversal and ordering;
- operational state and searchable text are columns;
- opaque provider/session metadata may be compressed JSON/text;
- file rows contain metadata and a blob key so bytes can be shared and retained
  independently;
- migrations are first-class and startup refuses unsupported database states;
- transaction retries are limited to database-only callbacks, never constraint
  failures or external side effects.

Functualize adopts these modeling principles without adopting Omnigent's user,
conversation, or deployment domain.

Sources:

- [Omnigent database deployment](https://omnigent.ai/docs/deploy/database)
- [Omnigent SQL models](https://github.com/omnigent-ai/omnigent/blob/main/omnigent/db/db_models.py)

## Turso AgentFS: separate workspace capability

AgentFS uses one SQLite file but exposes three distinct interfaces and schemas:
POSIX-like filesystem (`inode`/`dentry`/chunk data), KV state, and an append-only
tool-call audit trail. The schema preserves filesystem meaning instead of
forcing file data through a generic payload table. Its tool-call table is
indexed by name/time and never mutates completed audit rows.

The transferable lesson is not “put everything in the runtime database.” It is
that a database-backed filesystem is its own abstraction with its own schema and
snapshot lifecycle. FUN-23 should provide that through `WorkspaceProvider` and
link runtime evidence to artifacts by reference. Implementations may place
runtime and workspace schemas in one physical SQLite file for local simplicity,
but the logical ownership and APIs remain separate.

Sources:

- [Turso: The Missing Abstraction for AI Agents](https://turso.tech/blog/agentfs)
- [AgentFS repository/specification](https://github.com/tursodatabase/agentfs)

## C4 method

The C4 model requires hierarchical abstractions—system, container, component,
and code—and supports dynamic/deployment views. It is notation/tool independent.
These documents use Mermaid's C4 annotations, treat the Python host process as a
container, and keep packages/classes at component/code level.

Source: [official C4 model](https://c4model.com/).

## Rejected alternatives

### Widen `StoreSubstrate` with query methods

Rejected because every domain query would widen every backend, recreate the
`hasattr`/least-common-denominator problem from ADR-022, and keep data semantics
inside a physical storage port.

### One repository per SQL table

Rejected because table boundaries are persistence details. Callers need atomic
workflow/run/interaction transitions and question-shaped queries.

### One giant `PersistenceBackend`

Rejected as a renamed god object. It would combine provider lifecycle, writes,
queries, migrations, admin, workspace, cache, and effects.

### Keep EventBus subscribers as the durable record

Rejected because the observer runs outside the authoritative transaction, can
fail independently, and cannot atomically persist the state transition and
effect intent it describes.

### Long transaction around a job

Rejected because user code may block, prompt, call a network, or run for hours.
It would hold locks/connections, make retries unsafe, and couple database
availability to arbitrary work duration.

### Silent fallback from configured SQL to files

Rejected because it makes a distributed runner write local truth while the
operator believes it is shared. Defaulting to documents when nothing is
configured remains valid; failing an explicit choice is mandatory.

### Indefinite dual write

Rejected because two authorities need reconciliation and every failure creates
an ambiguous winner. The migration uses compatibility first, then an exclusive
verified cutover.

### Store artifact bytes in runtime rows

Rejected because transaction size, retention, sharing, streaming, and workspace
semantics differ. Store immutable references and integrity metadata instead.

## Open decisions owned by implementation ADRs

1. Exact public names and whether configuration uses only a URL or a typed
   `PersistenceSources` plus URL.
2. First network SQL provider for FUN-22.
3. Whether the outbox dispatcher initially runs inline-after-commit, as a
   managed background component, or as a separately invoked worker.
4. Exact event table split (`run_events`/`scope_events`) versus a carefully
   constrained shared append table.
5. Retention defaults and whether audit export is a 1.0 or 2.0 requirement.
6. Whether local workspace and runtime providers share one physical SQLite file;
   logical capability separation is already decided.
