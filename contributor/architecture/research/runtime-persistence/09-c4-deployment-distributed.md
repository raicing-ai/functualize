# C4 deployment — distributed runners

```mermaid
C4Deployment
  title Multi-Runner / Multi-Machine Deployment

  Deployment_Node(clients, "Clients and Delivery Systems", "CLI, web, MCP, schedulers") {
    Container(trigger, "Trigger Client", "Protocol client", "Submits requests and controls workflows")
  }

  Deployment_Node(compute, "Runner Fleet", "Containers, VMs, or functions") {
    Deployment_Node(node_a, "Runner A", "Python") {
      Container(host_a, "Functualize Runtime", "Python", "Executes jobs using fenced transitions")
    }
    Deployment_Node(node_b, "Runner B", "Python") {
      Container(host_b, "Functualize Runtime", "Python", "Resumes/executes jobs using the same provider")
    }
    Container(dispatcher, "Outbox Dispatcher", "Python worker", "Claims effects across the fleet")
  }

  Deployment_Node(data, "Shared Data Plane", "Managed services") {
    ContainerDb(sql, "Network Runtime Database", "Selected SQL provider", "Transactions, row claims, migrations, outbox")
    Container(blob, "Workspace/Artifact Store", "Object/blob or remote workspace", "Artifact content")
  }

  System_Ext(effects, "Effect Destinations", "Notifier/webhook/queue/service")

  Rel(trigger, host_a, "Submits RunRequest/control command", "Adapter protocol")
  Rel(trigger, host_b, "Submits or retries")
  Rel(host_a, sql, "Claims and commits with fencing", "TLS SQL protocol")
  Rel(host_b, sql, "Claims and commits with fencing", "TLS SQL protocol")
  Rel(host_a, blob, "Reads/writes artifact references and content", "Workspace API")
  Rel(host_b, blob, "Reads/writes artifact references and content", "Workspace API")
  Rel(dispatcher, sql, "Claims/acknowledges outbox", "SQL transaction")
  Rel(dispatcher, effects, "Invokes with idempotency key", "Provider protocol")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Required provider properties

- server-coordinated transactions/row claims or equivalent compare-and-swap;
- fencing generation enforced in every authoritative write;
- migration lock safe across hosts;
- transient-error classification with bounded retry around database-only work;
- explicit isolation-level validation;
- shared time semantics for lease expiry, or conservative expiry plus fencing;
- connection pool sizing and shutdown lifecycle;
- outbox claim visibility/recovery after worker death.

The first implementation must name its database and test these properties.
“SQL compatible” is not a sufficient capability statement.
