# Run middleware contracts

## Public registration

- `app.hooks.run_middleware` accepts a generator function directly or a
  `priority=` parameter and returns the decorated function unchanged.
- `app.hooks.register_run_middleware(middleware, priority=0)` registers a
  callable and returns `None`.
- Lower priority executes before higher priority; equal priorities retain
  registration order. Post-yield execution reverses that order.
- Both forms wrap jobs through `JobExecutionEngine` and receive the same
  RunContext or dependency injection behavior as the existing function form.

## Inspection

`app._middleware_registry` remains available with `has_middleware` and
`get_sorted()`; it is the identical object as
`app._execution_middleware_chain`. A type assertion against the old
`MiddlewareRegistry` class is migrated to the execution chain type.
