# C4 dynamic — execution and durable effects

The flow uses multiple short transactions. The job body and external effects do
not run inside one.

```mermaid
C4Dynamic
  title Execute - Commit Runtime Truth Before Publishing or Dispatching

  Container(adapter, "Delivery Adapter", "CLI/HTTP/Lambda/MCP", "Builds RunRequest")
  Component(engine, "Execution Engine", "_engine", "Owns one execution path")
  Component(transitions, "Runtime Transition Service", "_persistence", "Performs short fenced transitions")
  Component(job, "Job / Workflow Step", "User Python", "Performs arbitrary work")
  Component(event_bus, "EventBus", "_events", "Live post-commit observation")
  ContainerDb(db, "Runtime Database", "Provider", "Runs, workflow, state, events, outbox")
  Container(dispatcher, "Outbox Dispatcher", "Python", "Claims committed effects")
  System_Ext(effect, "Effect Destination", "Notifier/webhook/service")

  Rel(adapter, engine, "1. Submit RunRequest")
  Rel(engine, transitions, "2. Start run and claim/ensure scope")
  Rel(transitions, db, "3. Commit run + scope fence + start events")
  Rel(transitions, event_bus, "4. Publish start after commit")
  Rel(engine, job, "5. Execute body outside transaction")
  Rel(job, engine, "6. Return outcome or raise")
  Rel(engine, transitions, "7. Commit state/step/run outcome and effect intents")
  Rel(transitions, db, "8. Atomic rows + events + outbox commit")
  Rel(transitions, event_bus, "9. Publish committed outcome")
  Rel(engine, adapter, "10. Return JobResult")
  Rel(dispatcher, db, "11. Claim available outbox row")
  Rel(dispatcher, effect, "12. Invoke with idempotency policy")
  Rel(dispatcher, db, "13. Acknowledge or schedule retry")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Consequences

- A database failure while committing authoritative outcome is visible; it is
  not swallowed as optional observation.
- A live-rendering subscriber may fail without changing committed truth.
- A process crash after step commit cannot lose the effect intent.
- A process crash during the job leaves a started run/lease that recovery can
  classify and reclaim.
- Database retry wraps only a transition callback. It never repeats the job body
  or an external effect.
