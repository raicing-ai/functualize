# C4 dynamic — suspend, claim, and resume

```mermaid
C4Dynamic
  title Workflow Resume - Candidate, Fenced Claim, and Deterministic Replay

  Person(actor, "Human or Agent", "Supplies a candidate and requests resume")
  Container(surface, "Workflow Control Surface", "App/CLI/MCP", "Uses one public command/query facade")
  Component(queries, "Runtime Queries", "Provider", "Reads pending interaction and workflow view")
  Component(control, "Workflow Control Service", "app/_persistence", "Validates candidate and requests transition")
  Component(engine, "Execution Engine", "_engine", "Replays recorded decisions and executes remaining steps")
  ContainerDb(db, "Runtime Database", "Provider", "Interaction, scope, steps, state, lease generation")

  Rel(actor, surface, "1. Inspect pending interaction")
  Rel(surface, queries, "2. Query workflow and accepted input schema")
  Rel(queries, db, "3. Read indexed view")
  Rel(actor, surface, "4. Submit candidate and resume command")
  Rel(surface, control, "5. Validate command through public facade")
  Rel(control, db, "6. Commit candidate/evaluation if required")
  Rel(control, db, "7. Conditionally claim scope; increment fencing generation")
  Rel(control, engine, "8. Submit RunRequest with scope and held generation")
  Rel(engine, db, "9. Read recorded steps, branches, state, and accepted interaction")
  Rel(engine, db, "10. Commit only remaining transitions with generation predicate")
  Rel(engine, surface, "11. Return blocked/terminal JobResult and updated view")
  Rel(surface, actor, "12. Present outcome")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Race rule

Two runners may both believe an expired scope is claimable. Only the conditional
claim returns a new generation. Every later write includes that generation, so
the loser—and a previously suspended old owner—cannot commit. Determinism comes
from persisted branch/step/interaction decisions, not re-evaluating them on
resume.
