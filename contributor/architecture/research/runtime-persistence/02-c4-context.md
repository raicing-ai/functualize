# C4 level 1 — system context

This diagram fixes the system boundary. Functualize owns orchestration and
runtime truth. It integrates with delivery triggers, provider-owned storage,
workspaces/artifacts, and effect destinations.

```mermaid
C4Context
  title Functualize Runtime Persistence - System Context

  Person(operator, "Operator", "Runs, resumes, inspects, and repairs jobs/workflows")
  Person(author, "Job and Plugin Author", "Declares jobs and supplies persistence/workspace/effect providers")

  System(functualize, "Functualize Runtime", "Discovers and executes jobs; persists authoritative run/workflow state")
  System_Ext(trigger, "Delivery and Trigger Systems", "CLI, embedded app, HTTP, Lambda, MCP, schedulers")
  SystemDb_Ext(runtime_db, "Runtime Persistence", "Document compatibility store, SQLite, or network SQL")
  System_Ext(workspace, "Workspace and Artifact System", "Filesystem, blob store, or agent filesystem")
  System_Ext(effects, "Effect Destinations", "Notifiers, webhooks, queues, external services")

  Rel(operator, trigger, "Starts, resumes, and inspects work")
  Rel(author, functualize, "Declares jobs and provider plugins", "Python public API")
  Rel(trigger, functualize, "Submits RunRequest and control/query commands")
  Rel(functualize, runtime_db, "Commits and queries runtime truth", "Provider port")
  Rel(functualize, workspace, "Reads/writes artifacts by reference", "WorkspaceProvider")
  Rel(functualize, effects, "Dispatches committed effect intents", "Outbox + provider")
  Rel(functualize, trigger, "Returns outcomes, views, and live events")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Scope statements

- Runtime persistence contains execution causality: runs, workflow state,
  interactions, evidence metadata, leases, and outbox intent.
- Job code and delivery adapters are inside the Functualize runtime system but
  outside the persistence component boundary.
- Artifact bytes and the virtual/physical filesystem are external capabilities;
  runtime persistence records references.
- A concrete database is replaceable. The semantic model and query/control
  surfaces are part of Functualize.
