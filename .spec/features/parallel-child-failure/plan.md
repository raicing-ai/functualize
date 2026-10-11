# Parallel child failures: implementation plan

Status: Plan, awaiting review of `tasks.md`. The specification and the
`_app/impl.py` caller extension were approved on 2026-10-11. No source change
has been made.

## Architecture gate (3a)

The five codemaps (`overview.md`, `modules.md`, `dependencies.md`,
`data-flow.md`, `entry-points.md`) describe `_engine` as the job-execution peer,
`_app` as composition root, and `_cli` as public-API-only delivery. Serena's
symbol overview and Graphify's `WiredInvoke`, `.parallel()` and
`execute_parallel()` neighbors confirm the live delegation. The prose retrieval
finds the old result-only contract in `docs/guides/run-context.md` and the
noninterruptible worker rule in
`contributor/architecture/run-model/08-durable-runs.md`. `uv run lint-imports`
at Plan authoring kept all seven contracts with zero broken.

BEFORE (arrows are call or import direction; labels name boundary payloads):

```text
job author
  -> src/functualize/job/_invoke.py [public job: Invoke export]
  -> src/functualize/_engine/capabilities/runcontext.py [engine peer: facade]
  -> src/functualize/_engine/capabilities/invoke.py [engine peer: WiredInvoke.parallel]
       -> src/functualize/_engine/executor.py [engine peer: child RunRequest]
          -> src/functualize/_types/descriptors.py [types: JobResult/status]
       -> parent job [boundary: ordered results; ignored failure is invisible]

CLI user -> src/functualize/_cli/builtins.py [cli: batch entry]
  -> src/functualize/app/core.py [public app: execute_parallel]
  -> src/functualize/_app/impl.py [app: constructs WiredInvoke]
  -> src/functualize/_engine/capabilities/invoke.py [engine: shared batch]
  -> src/functualize/_app/impl.py [boundary: all JobResults]
  -> src/functualize/_cli/builtins.py [cli: status/exit code]
  -> src/functualize/_cli/parallel_output.py [cli: observer status]
```

`invoke.py` also calls `nested_request` in
`src/functualize/_types/run_request.py` to make each child's run request.
The dependency direction is engine -> types. The `_cli` path reaches internals
only through the public `app/core.py` entry. The CLI observer is passed by the
composition root and receives a status rather than a failure verdict.

BEFORE smells: **Long Method** at `WiredInvoke.parallel` (272 lines) and
**Large Class** at `WiredInvoke` (658 lines, AST count at Plan authoring). The
class already exceeds the Constitution's approximate 500-line limit. Adding
the new policy there would cause forbidden god-object growth.

AFTER (same layers and call paths, changed boundary marked):

```text
job author
  -> src/functualize/job/_invoke.py [public job: Invoke export]
  -> src/functualize/_engine/capabilities/runcontext.py [engine: unchanged facade]
  -> src/functualize/_engine/capabilities/invoke.py [engine: WiredInvoke.parallel
       delegates batch execution to private _ParallelBatch]
       -> src/functualize/_types/run_request.py [types: child RunRequest]
       -> src/functualize/_engine/executor.py [engine: execute every child]
          -> src/functualize/_types/descriptors.py [types: ordered JobResults]
       -> src/functualize/_types/outcome.py [types: Family.TOOL is_failure]
       -> parent job [boundary: RuntimeError on failed child by default;
          ordered JobResults if raise_on_failure=False]

CLI user -> src/functualize/_cli/builtins.py [cli: batch entry]
  -> src/functualize/app/core.py [public app: same result contract]
  -> src/functualize/_app/impl.py [app: explicit raise_on_failure=False]
  -> src/functualize/_engine/capabilities/invoke.py [engine: shared batch]
  -> src/functualize/_app/impl.py [boundary: all JobResults]
  -> src/functualize/_cli/builtins.py [cli: unchanged status/exit code]
  -> src/functualize/_cli/parallel_output.py [cli: unchanged observer status]
```

`_ParallelBatch` stays private in `invoke.py` and owns worker submission,
collection, timeout sweep, nonblocking shutdown, and final result decision.
`WiredInvoke.parallel` remains the public capability method and passes the
per-invocation context to the private collaborator. This extraction lowers
`WiredInvoke` below the forbidden growth threshold without adding an import
edge, alternate execution path, global state, or policy copy. The class may
hold the engine and request context it needs; it must not import another peer
layer. No change to `_engine/executor.py` or worker lifecycle is planned.

The first candidate, adding the result check to the 272-line method, failed
the god-object rule. Extracting only an error-formatting helper still leaves
the oversized class. The settled shape extracts the batch responsibility,
leaves the one public delegate, and reuses `Family.TOOL` from the types layer.
It does not introduce a peer import or a second failure set. This changes the
implementation shape within the authorized `invoke.py` file, not the external
contract beyond the approved specification.

Design resources consulted: repository-local `python-design-patterns` (KISS,
single responsibility, composition, god-class decomposition) and
`design-patterns-refactoring` (Long Method, Large Class, Feature Envy, Middle
Man, Extract Class). The AFTER check finds no Constitution-forbidden pattern.

## Surviving smells

- **Middle Man**, `WiredInvoke.parallel`: the stable capability method delegates
  to its private batch collaborator. Accepted because public callers already
  use this method, and removing it would break the API. Needs maintainer review:
  **no**; it is a required API seam.
- **Long Method**, `_ParallelBatch` orchestration: thread submission, deadline
  sweep, and `shutdown(wait=False)` remain together to preserve the existing
  timeout ordering. The extraction should split independent result formatting
  from worker scheduling, but a short orchestration method may remain. Needs
  maintainer review: **yes**, because that tradeoff should be approved with the
  task graph before Execute.

## Call-site and blast-radius pass (3b)

Serena `find_referencing_symbols` found `WiredInvoke.parallel` referenced by
`_app/impl.py:execute_parallel` and the direct tests in
`tests/test_invoke_expanded.py`. `Invoke.parallel` is also reached through
`runcontext.py:invoke_parallel` and the `job/_invoke.py` public export.
`execute_parallel` is referenced by `app/core.py:FunctualizeApp.execute_parallel`;
`_cli/builtins.py` calls that public method. Graphify confirmed both constructor
doors (`_engine/capabilities/runcontext.py:_get_invoke` and
`_app/impl.py:execute_parallel`), the latter's app facade, and the nested
`_collect` helper; source search filled the graph's method-call gaps.

The source/test/docs `rg` hit set includes failing-result assumptions in
`tests/context/test_invoke_parallel_and_schema.py:196-255`, a top-level mixed
batch assertion in `tests/pipeline/test_history_producer.py:144-163`, and
the CLI reporter tests in `tests/pipeline/test_builtin_parallel.py`. The
composition-lab example and the other RunContext caller tests use successful
children and need verification, not a behavior edit. `docs/api/context.md`
and `docs/guides/run-context.md` describe the old always-return behavior and
need correction. The `rc.invoke_parallel` facade signature stays unchanged;
partial recovery uses the injected `Invoke` capability directly.

## Technical approach and risk

1. Extract current batch scheduling into `_ParallelBatch` while preserving
   signatures and old results. Verify structural equivalence before policy
   changes. Keep observer claim/release and deadline sweep exactly as before.
2. Add keyword-only `raise_on_failure=True` to stub and wired methods. After
   collection, classify each ordered result with
   `is_failure(status, family=Family.TOOL)`. Include every failing index, name,
   and status in the error. Chain the first failed result's exception only when
   it exists. The option must never enter a child kwargs dict.
3. Make `_app/impl.py:execute_parallel` pass `raise_on_failure=False`. Existing
   `FunctualizeApp.execute_parallel` and CLI reporting then keep returning
   mixed results. No CLI flag or exit-code change.
4. Add regression coverage at the public application entry point and at the
   capability seam. Repair old result-oriented tests to assert the new default.
   Document the canonical contract in `docs/api/context.md` and link the guide.

The main risk is an accidental wait on a running timed-out thread. Tests must
assert prompt return/raise with a release event in `finally`, so no worker is
orphaned by the test. The other risk is a shared caller regressing to fail-fast
rendering; preserve the mixed-result CLI and history tests. A third risk is an
unintentional gate-pause policy change; use the existing `Family.TOOL` decision
and assert `BLOCKED` remains a returned result.
