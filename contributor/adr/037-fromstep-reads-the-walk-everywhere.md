# ADR-037: `FromStep` Reads the Walk Everywhere

**Status**: accepted
**Date**: 2026-10-20
**Deciders**: maintainer (the build-it option, D-1, D-2)

## Context

`FromStep`'s docstring said it was used for "a gate tool's bound argument, and
the epilogue body". Only the first was built. `from_job_refs` returns `FromJob`
references only, and it was the executor's sole injection source, so a
`FromStep` annotation on a step job's or the epilogue's parameter was silently
ignored — no value, no error, no warning. The guide said steps take no
arguments by design, and the walker reference said the injection was designed
but never built. Three documents disagreed and the code agreed with none of
them.

There were two ways out: build the read the docstring described, or correct
the docstring and refuse the annotation loudly. Either way the silent no-op had
to end.

## Decision

1. **One rule, three positions.** `FromStep("x")` reads *this walk's* record
   for node `x` — a `Step` or a `Gate`, whose record is its answer — wherever
   it is written: a step job's parameter, the epilogue body's parameter, or a
   gate tool's bound argument. All three go through one pure reader,
   `_primitives/walk_reads.read_node`; the executor injects through
   `_engine/walk_reads.inject_from_step`, and gate tools resolve through
   `resolve_bound_values`.
2. **A read never runs anything.** It is not a dependency edge, it orders
   nothing, and it never consults a fingerprint, so it cannot resurrect a value
   from an earlier walk. `FromJob` semantics do not change.
3. **Names are checked at boot.** A name that is not a node of the workflow is
   refused. A step or gate reader may name only a node ordered before it. The
   epilogue, which runs after `END`, may name any node. A parameter declaring
   both `FromJob` and `FromStep` is refused.
4. **D-1: a gate binding may read an earlier gate.** It resolves to that gate's
   answer. A binding that names its own gate, or a later node, is refused at
   boot.
5. **D-2: a skipped node yields the declared default.** When a conditional
   branch skipped the node, the parameter's default is used. With no default
   the run fails with `FromStepUnavailableError`, naming the node, the
   parameter and the reader. Unknown and unordered names still fail at boot,
   default or not.
6. **Outside a walk there is nothing to read.** A job run on its own, or
   invoked with `Invoke` from inside a step, is not part of the walk. Its
   `FromStep` parameter fails the same way. An argument passed explicitly wins
   over the read.

## Consequences

### Positive

- A gate's answer reaches a later step and the epilogue as a typed value, in
  a fresh process too, because it is read from the walk's record and not from
  memory.
- The annotation can no longer be silently ignored: every position resolves,
  is refused at boot, or fails the run with a message that names the read.
- The gate-tool binding and parameter injection share one reader, and the
  MCP plugin's duplicate resolver is gone.

### Negative

- A gate-tool binding whose node has no record used to resolve to `None`. It
  now fails with the named error. This is a deliberate behaviour change.
- The `FromJob[step]` / `FromStep[step]` subscript form is still not built.
  Only the call form reads the walk.

### Neutral

- No new persistence, no new gate lifecycle and no new graph node kind. The
  reader uses the step records the walk already writes, through the selected
  store, so it behaves the same on the document store and on SQLite.
- The epilogue is still not part of graph ordering.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Correct the docstring to the gate-tool binding and refuse `FromStep` on any parameter | Smallest change; no new engine path | A gate's answer still could not reach a later step or the epilogue as a typed read, which is what the docstring promised | The maintainer chose to build the read |
| Refuse a binding that names a gate (step values only) | Narrower surface | A gate's answer is a step record like any other, so refusing it is an arbitrary exception to the one rule | D-1 |
| Fail on a skipped node even when the parameter declares a default | One failure mode | A conditional graph could not give an optional read a fallback | D-2 |
