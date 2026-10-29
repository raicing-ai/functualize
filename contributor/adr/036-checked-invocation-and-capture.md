# ADR-036: Checked Invocation and Captured Child Output

**Status**: accepted
**Date**: 2026-10-26
**Deciders**: maintainer

## Context

An invoked child returns a `JobResult` even when it fails. A parent that forgets
to inspect that result can finish successfully after the child did not do its
work. A child's explicit `Stdout` emissions also go straight to the run's
output, so a parent cannot compose them into one document without an opt-in
recording path. The ordinary unchecked invocation and output behavior must
remain available.

## Decision

- `JobResult.raise_for_status()` returns the same result for `SUCCESS`,
  `SKIPPED`, and `BLOCKED`. For every other `RunStatus`, it raises one
  `JobFailedError(result) from result.exception`. The error carries the whole
  result, the job name, status, and child exception; its message names the
  child and includes the underlying error when present. The frozen result gains
  no field. The error is defined in `_types/errors.py` and exported beside
  `JobResult` from `functualize.types`, not from `functualize.job`.
- The `INVOKE_FAILURE` hook, `Invoke.parallel`, and the checked method use the
  same TOOL-family failure set. The hook therefore also fires for `TIMEOUT`,
  `CANCELLED`, and `UNKNOWN`, in addition to `FAILURE` and `REFUSED`. The old
  "Req 21.6" rule that excluded a timed-out child is retired.
- `inv("child", capture=True)` records the child's `Stdout.emit()` values and
  `Stdout.write()` payloads, diverting them from the output stream. The returned
  result carries `metadata["emitted"]` and `metadata["writes"]` as tuples,
  including empty tuples when nothing was emitted. Values are retained as
  passed, including `None` and custom objects, regardless of output format.
  Without `capture=True`, output and result metadata retain their old behavior.
  Capture is local to the requested child and does not pass to its nested runs.
- A live `EmissionRecord` sits on the public frozen `RunRequest` while a child
  runs. The maintainer accepted that coupling: `capture` is excluded from
  equality and the hand-written hash and is reset by `nested_request`. The
  recorder is defined beside its annotation in `_types/run_request.py` to keep
  that module's imports stdlib-only and its runtime type hints resolvable.
- The unused `InvokeResult` remains for this change. Removing its public
  re-exports is a separate change with its own review and removal note.

## Consequences

### Positive

- A parent can bind a child's value and assert its outcome in one expression.
- A parent can construct one output document from a child's emissions without
  writing the child's documents first.
- The hook and checked result agree about which child outcomes failed.

### Negative

- Subscribers to `INVOKE_FAILURE` observe more statuses than before.
- Captured values remain in memory and are not redacted by output formatting;
  callers must handle them as the child's original data.
- The request carries a mutable recorder during execution, despite its frozen
  value-object shape; the exclusion from equality and hashing is intentional.

### Neutral

- An unchecked `inv("child")` still returns its result for caller inspection.
- Removing `InvokeResult` is deferred to a separate public-surface change.

## Alternatives Considered

| Alternative | Why rejected |
|-------------|--------------|
| Re-raise the child's exception | It loses the child's name at the normal error boundary and mutates the traceback on the exception retained by the child result. |
| Keep the hook's narrower failure set | A timed-out child would raise on the checked lane while the failure hook stayed silent. |
| Tee captured output to the stream | The caller would still emit a child's document before its own composed document. |
| Redirect the process stream or write capture into the child's own result | Stream redirection misses custom values and output formats; mutating the child's result changes its recording semantics. |
