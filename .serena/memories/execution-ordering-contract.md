# Execution ordering contract (JobExecutionEngine)

`_engine/executor.py` is the single execution path for the CLI, `rc.invoke()`
and the standalone binary. The ordering is load-bearing and the source comments
are emphatic about it:

1. Materialize lazy function **before** any signature introspection.
2. Workflow prelude runs **before** DI resolution and **before any hook**.
3. Config resolution and argument validation complete **before** `PRE_EXECUTE`.
4. A validation or dependency failure exits through `_failure_before_execution`:
   `AFTER_FAILURE` fires, `PRE_EXECUTE` does **not**, and the body never runs.
5. A skipped job must not fire hooks that assume it ran.
6. History is recorded only at `invoke_depth == 0`, and stores `args_hash`
   only — never argument values, which may be secrets.

`execute()` is a thin wrapper whose only job is to record history on *every*
exit path from `_execute_lifecycle`, rather than at five separate return points.

Drawn as a diagram: `docs/diagrams/job-execution-lifecycle.html`
