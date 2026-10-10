# Parallel child failures reach the parent

Status: draft; awaiting confirmation before Plan. This document describes the
proposed behavior, not behavior already implemented.

## Problem

A job can call `invoke.parallel(...)`, ignore its returned list, and finish
successfully even when a child failed. Monitoring and verification jobs then
report a false clean result.

## User stories

- As a job author, I want an unhandled child failure to fail my parent job even
  when I do not inspect the batch's return value.
- As a job author implementing partial recovery, I want to request every result
  explicitly and decide which failures to tolerate.
- As a caller setting a deadline, I want the batch to return control at that
  deadline without waiting for a worker it has already classified as timed out.

## Proposed behavior

### Safe default: raise after collection

`Invoke.parallel` gains the keyword-only option `raise_on_failure: bool = True`.
The batch retains its existing concurrent execution and collection behavior.
After collection, if any child has a failing outcome, the call raises
`RuntimeError`. The message identifies all failing inputs by position, job name,
and status in submission order. The first failing input's exception, if present,
is retained as the cause. A failure with no exception still raises.

Raising is the primary behavior because an ignored return value cannot make a
failure visible. An uncaught batch exception reaches the parent's existing
execution error handling. The caller can still catch it deliberately.

This is not early abort: one child failure does not cancel otherwise runnable
children. Collection ends when the batch completes or its existing deadline
expires. The change introduces no retry or new scheduling policy.

The failing outcomes are `FAILURE`, `TIMEOUT`, `CANCELLED`, `REFUSED`, and
`UNKNOWN`. `SUCCESS` and `SKIPPED` remain successful batch results. A gate pause
(`BLOCKED`) retains its existing result behavior; changing gate propagation is
outside this feature. These distinctions follow the existing result-oriented
`Family.TOOL` policy in `_types/outcome.py`.

### Explicit result handling

`invoke.parallel(jobs, raise_on_failure=False)` returns one `JobResult` per input,
including failed or timed-out children, in submission order. The caller owns
failure handling in this mode. The option belongs to the batch and is never
forwarded as a child job argument.

With no failing children, both values of the option return the same ordered
results. An empty batch continues to return `[]`; the maximum remains 32 jobs.

### Timeout contract

`timeout=None` retains the existing 300-second default; a nonpositive timeout
retains the existing indefinite wait. A deadline produces `TIMEOUT` results for
unfinished inputs. A child that completes during the deadline sweep retains its
real result. With the safe default, a timed-out child causes the batch to raise
at the deadline; with the escape hatch, its `TIMEOUT` result is returned.

Pool shutdown remains nonblocking. Queued futures may be cancelled, but Python
cannot interrupt running worker threads, which may continue after the caller
regains control. Raising must not introduce a pool context manager or another
wait for those workers.

## Documentation contract

The canonical explanation and example live in the `invoke.parallel` reference
section of `docs/api/context.md`. It must show the safe default and the escape
hatch, define failure and timeout behavior, and explain who handles failures
when the option is false. Related guide sections link to that reference.

The `Invoke` class/call documentation and both `parallel` docstrings describe
the default and the option. `Invoke.__call__` remains a single-job operation;
its documentation must distinguish its existing result contract from the batch
option rather than imply that `raise_on_failure` is a single-job keyword.

## Acceptance criteria

1. One failed child among three causes a default batch to raise after collecting
   the batch. A parent that ignores the call's return value fails through the
   public application entry point.
2. Three failed children cause a default batch to raise; its diagnostic names
   all failing positions, including repeated invocations of the same job.
3. Three successful children completing out of order return results in
   submission order, with their return values preserved.
4. Explicit `raise_on_failure=False` returns ordered mixed results and permits
   a parent to handle them deliberately. The option is not passed to children.
5. Failure results without an exception still cause a default batch to raise.
   When the first failed result has an exception, it is the raised error's cause.
6. Default and opt-out timeout cases regain control without waiting for a
   running worker, preserve completed results, and keep the existing deadline
   conventions. Tests release/join any worker they start.
7. Empty batches, the 32-job limit, skipped children, and gate pauses retain
   their specified behavior.
8. The canonical reference and required docstrings describe the chosen contract.
9. Existing top-level batch reporting retains per-job results and its existing
   exit-code/rendering behavior.

## Scope and prerequisites for planning

The dispatched production change is confined to
`src/functualize/_engine/capabilities/invoke.py`, with proportional tests and
reference documentation. Do not change `_engine/executor.py`, child metadata,
cache materialization, workflow walking, or the worker-pool lifecycle.

The shared caller `src/functualize/_app/impl.py:execute_parallel` explicitly
promises returned failures for top-level reporting and currently calls
`WiredInvoke.parallel` without a failure-handling option. A universal new default
would affect it too. Plan must resolve this against the dispatched file scope;
the proposed minimal extension is for that caller to pass
`raise_on_failure=False`. That additional production file needs scope approval
before implementation. Do not silently vary the default by delivery surface.

Confirmation of this specification precedes Plan. A reviewed native task graph
and a fresh six-file execution anchor precede implementation. Review,
verification, and the two-push artifact cleanup remain later gates.

## Observed premises and prior art

Read against base `4e816a0f4d7f9e8e75066d4f3979f6bb126cce15`:

- An AST read finds `timeout` on the stub's `parallel` signature and `timeout`
  plus `observer` on the wired signature. Neither has a failure-handling option.
- `rg -n 'raise_on_failure|ignore_errors|fail_on_error' src plugins docs`
  returns no matches (exit 1).
- `WiredInvoke.parallel` sorts results by input index and returns them at
  `invoke.py:806-807`. Its nonblocking shutdown explanation is at lines 745-753.
- `RunContext.invoke_parallel` delegates to `Invoke.parallel` in
  `_engine/capabilities/runcontext.py:520-524`.
- `execute_parallel` promises returned failures and shares the wired call at
  `_app/impl.py:1387-1444`.
- The Specify prose query in zvec-grep surfaced
  `docs/guides/run-context.md:439-484` and
  `contributor/architecture/run-model/08-durable-runs.md:148-176`.
  The former documents the existing list result contract; the latter records
  the deliberate limitation that an invocation timeout does not kill a thread.
  The proposed default changes the batch failure contract explicitly and
  preserves that timeout limitation.
