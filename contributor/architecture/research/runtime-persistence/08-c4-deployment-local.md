# C4 deployment — local SQLite

```mermaid
C4Deployment
  title Local Development / Single-Host Deployment

  Person(operator, "Operator", "Uses func or an embedded application")

  Deployment_Node(machine, "Developer or Runner Machine", "Linux/macOS/Windows host") {
    Deployment_Node(process, "Runtime Process", "Python") {
      Container(host, "Functualize Runtime Host", "Python", "Executes jobs and short UoWs")
      Container(dispatcher, "Inline/Managed Outbox Dispatcher", "Python", "Dispatches committed local effects")
    }
    Deployment_Node(local_disk, "Persistent Local Disk", "Filesystem") {
      ContainerDb(sqlite, "Runtime SQLite Database", "SQLite WAL", "Normalized runtime tables and migrations")
      Container(workspace, "Local Workspace/Artifacts", "Filesystem or AgentFS-like SQLite", "Job files and artifact bytes")
    }
  }

  System_Ext(effects, "Effect Destinations", "Local/network providers")

  Rel(operator, host, "Starts and controls jobs", "CLI/app API")
  Rel(host, sqlite, "Reads/writes short transactions", "SQLite connection per thread")
  Rel(host, workspace, "Reads/writes files and artifacts")
  Rel(dispatcher, sqlite, "Claims/acknowledges outbox")
  Rel(dispatcher, effects, "Invokes")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Supported envelope

- Multiple threads and processes on the same host/file are supported within
  SQLite's writer limits, with WAL, busy timeout, short transactions, and
  fencing.
- A persistent local volume is required.
- The file must not be placed on an eventually consistent/object-store mount.
- SQLite does **not** satisfy multi-machine runtime capability. Copying or
  syncing the file is backup/replication, not shared concurrent execution.
