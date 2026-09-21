# Runtime Persistence Architecture

**Status:** target architecture; not yet implemented
**Canonical for:** FUN-16 through FUN-23
**Current-code baseline:** `b0148f8` (`v0.3.0`, 2026-09-20)
**Decision boundary:** supersedes neither ADR-022 nor shipped behavior until an
implementing ADR and acceptance tests land.

This folder is the canonical technical source for the runtime-persistence
initiative. Jira owns sequencing and delivery state. These documents own the
system boundary, invariants, target interfaces, data model, migration, and
acceptance architecture. A ticket may narrow this design, but it must link the
decision here rather than restating a competing architecture in its description.

## Why the substrate must change

`StoreSubstrate` solved the 0.3.0 problem: choose one place for five JSON
documents so a workflow record and its state cannot split across backends. Its
document-shaped contract is a poor final boundary for the Northstar 1.0/2.0
requirements, which need relational queries, atomic multi-aggregate state
transitions, durable interactions, an effects outbox, migrations, distributed
leases, and workspace/artifact references.

The redesign does **not** replace one generic storage abstraction with another.
It splits persistence by meaning:

1. **Runtime truth** — runs, workflows, steps, decisions, state, gates,
   evidence, leases, and effects. One `RuntimePersistenceProvider` produces one
   compatible family of repositories and one transaction boundary.
2. **Derived/local documents** — freshness fingerprints and shell history may
   remain lightweight documents because their discard rules and locality are
   different.
3. **Workspace/artifact content** — files and large blobs belong behind a
   `WorkspaceProvider`/artifact capability; runtime SQL stores references and
   integrity metadata, not an accidental virtual filesystem.
4. **Plugin-owned data** — tasks and other domains own explicit repositories or
   adapters. They do not reach through `app.execution_engine.substrate`.

## Non-negotiable invariants

- One provider selection per app/runtime namespace; no per-store backend choice.
- Related runtime repositories come from one provider and one unit of work.
- No database transaction spans arbitrary job code or a network effect.
- A scope claim uses a monotonically increasing fencing generation; expiry alone
  is not authority.
- Authoritative transitions and their audit/effect intent commit together.
- EventBus remains an observer after commit; it is not the durable record.
- Explicitly configured persistence fails boot if unavailable. Silent fallback
  is permitted only when no provider was explicitly requested.
- Backend capabilities are typed data checked at boot, never `hasattr` probes.
- SQL columns hold identities, ordering, status, time, ownership, and fields used
  in predicates. JSON holds genuinely opaque payloads only.
- CLI, MCP, HTTP, Lambda, `app.execute`, and `Invoke` read the same query ports.
- A local SQLite provider and a network SQL provider pass the same semantic
  contract suite; deployment-specific capability tests remain separate.
- Legacy data is imported under an exclusive cutover, verified, and backed up.
  There is no indefinite dual-write mode.

## Document map

| Document | Question answered |
|---|---|
| [00-tooling-health.md](00-tooling-health.md) | Which retrieval tools and evidence were available? |
| [01-current-state-and-blast-radius.md](01-current-state-and-blast-radius.md) | What exists and what changes when the substrate changes? |
| [02-c4-context.md](02-c4-context.md) | Who uses the system and what external systems surround it? |
| [03-c4-containers.md](03-c4-containers.md) | What deployable/runtime units exist? |
| [04-c4-components.md](04-c4-components.md) | Which in-process components own persistence behavior? |
| [05-c4-dynamic-boot.md](05-c4-dynamic-boot.md) | How is one provider selected, migrated, and bound? |
| [06-c4-dynamic-execution.md](06-c4-dynamic-execution.md) | How does a run commit truth without holding a long transaction? |
| [07-c4-dynamic-resume.md](07-c4-dynamic-resume.md) | How is a suspended workflow claimed and resumed safely? |
| [08-c4-deployment-local.md](08-c4-deployment-local.md) | What is the local SQLite topology? |
| [09-c4-deployment-distributed.md](09-c4-deployment-distributed.md) | What changes for multiple runners/machines? |
| [10-target-architecture.md](10-target-architecture.md) | What are the ports, patterns, ownership, and module boundaries? |
| [11-data-model-and-transactions.md](11-data-model-and-transactions.md) | What is normalized, what remains JSON, and where are transactions? |
| [12-migration-and-delivery.md](12-migration-and-delivery.md) | In what order does the feature land and how is it proven? |
| [13-decisions-and-research.md](13-decisions-and-research.md) | Which external designs informed the decision and what was rejected? |

## Jira ownership map

| Jira | Primary architecture |
|---|---|
| FUN-16 | this index; context, containers, and delivery sequence |
| FUN-17 | components, target ports/provider family, current blast radius |
| FUN-18 | data model, transaction boundaries, migrations |
| FUN-19 | local deployment, legacy import, SQLite contract suite |
| FUN-20 | execution/resume dynamics, leases, workflow/state repositories |
| FUN-21 | interaction/evidence/outbox schema and execution dynamic |
| FUN-22 | distributed deployment, capabilities, network SQL correctness |
| FUN-23 | system context, workspace/artifact boundary, artifact references |

## Reading and change policy

The C4 files describe the final system, not intermediate coexistence. Transitional
states belong in `12-migration-and-delivery.md` and must be marked `TRANSITIONAL`
in code/spec tasks. When implementation changes a box, relationship, invariant,
or schema ownership rule, the implementing ticket updates this folder in the same
PR. When implementation merely fills in a box, Jira status changes and this design
does not need to be rewritten as progress reporting.
