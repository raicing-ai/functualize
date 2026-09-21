# C4 level 3 — runtime host components

This view zooms into the `Runtime Host Process` container. It shows ownership,
not a proposed class-per-box implementation.

```mermaid
C4Component
  title Runtime Host Process - Persistence Components

  Container_Ext(trigger, "Delivery Adapter / App Caller", "Python/HTTP/MCP", "Starts runs and asks runtime questions")
  ContainerDb(runtime_db, "Runtime Database", "Selected provider", "Authoritative runtime data")
  Container_Ext(workspace, "Workspace Store", "WorkspaceProvider", "Artifact bytes and files")
  Container_Ext(dispatcher, "Outbox Dispatcher", "Python", "External effect delivery")

  Container_Boundary(host, "Runtime Host Process") {
    Component(app_facade, "Runtime Query/Control/Admin Facade", "functualize.app", "One public surface for every delivery")
    Component(composition, "Composition Root", "_app", "Registers factories; selects, migrates, health-checks, and binds one provider")
    Component(handle, "Runtime Persistence Handle", "_persistence + _types port", "Bind-once provider capability injected into the engine")
    Component(engine, "Execution Engine", "_engine", "Runs the lifecycle and requests semantic transitions")
    Component(transitions, "Runtime Transition Service", "_persistence", "Short fenced UoWs for starts, state, steps, outcomes, interactions, outbox")
    Component(queries, "Runtime Query Service", "provider implementation", "Purpose-built run/workflow/interaction projections")
    Component(event_bus, "EventBus", "_events", "Notifies live observers after commit")
    Component(workspace_bridge, "Workspace Bridge", "app/plugin port", "Stores artifact content and returns immutable references")
  }

  Rel(trigger, app_facade, "Executes commands and queries")
  Rel(composition, handle, "Binds exactly once after migration")
  Rel(app_facade, engine, "Submits RunRequest/control command")
  Rel(app_facade, queries, "Reads projected runtime views")
  Rel(engine, transitions, "Requests authoritative transitions")
  Rel(transitions, handle, "Opens provider UoW")
  Rel(handle, runtime_db, "Creates matched repositories/transactions")
  Rel(queries, runtime_db, "Runs indexed semantic queries")
  Rel(transitions, event_bus, "Emits committed events")
  Rel(transitions, workspace_bridge, "Records artifact references")
  Rel(workspace_bridge, workspace, "Stores/loads content")
  Rel(dispatcher, runtime_db, "Claims outbox work")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Dependency rule

The engine names only protocols/DTOs from `_types`. `_persistence` implements
backend-neutral orchestration without importing `_engine`. `_app` is the only
component that sees the engine, registry, config, and concrete provider together.
Public delivery code talks to `app_facade`; it never follows
`app.execution_engine.substrate`.
