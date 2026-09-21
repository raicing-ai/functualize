# C4 level 2 — containers

“Container” uses the C4 meaning: an executable/runtime or data store. Python
packages and plugins loaded into the same process are components, not containers.

```mermaid
C4Container
  title Functualize Runtime Persistence - Containers

  Person(operator, "Operator", "Runs and controls work")
  System_Ext(trigger, "Trigger Client", "CLI shell, HTTP caller, Lambda event, MCP client")
  System_Ext(effects, "Effect Destinations", "Notifiers, webhooks, queues")

  System_Boundary(functualize, "Functualize Runtime") {
    Container(host, "Runtime Host Process", "Python + Functualize", "Boots plugins, executes jobs, commits transitions, serves queries")
    Container(dispatcher, "Outbox Dispatcher", "Python worker or managed in-process loop", "Claims committed effects and invokes providers")
    ContainerDb(runtime_db, "Runtime Database", "Document adapter / SQLite / network SQL", "Runs, workflows, state, interactions, evidence, outbox")
    Container(workspace, "Workspace and Artifact Store", "Filesystem / blob / AgentFS-like provider", "Job files and artifact bytes")
  }

  Rel(operator, trigger, "Uses")
  Rel(trigger, host, "Submits requests and queries", "Public adapter/app API")
  Rel(host, runtime_db, "Executes short transactions and queries", "RuntimePersistenceProvider")
  Rel(host, workspace, "Reads/writes artifacts", "WorkspaceProvider")
  Rel(dispatcher, runtime_db, "Claims and acknowledges outbox rows", "Provider transaction")
  Rel(dispatcher, effects, "Invokes with idempotency policy", "Provider-specific protocol")
  Rel(host, trigger, "Returns JobResult, views, and post-commit live events")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Container notes

- Local mode may run the dispatcher synchronously after commit in the host
  process. It remains a separate responsibility and can later become a worker
  without changing the outbox contract.
- The runtime database is one logical container even when the compatibility
  provider maps it to several files.
- The workspace store may share a physical SQLite file with runtime data in a
  local deployment, but it stays a separate logical container/capability.
- Delivery plugins embedded in the host do not own runtime persistence. They
  use the app facade.
