# Run middleware registration

## Behavior

Both `@app.hooks.run_middleware` forms and
`app.hooks.register_run_middleware(fn)` register a yield-based run middleware
in the chain consumed by the job execution engine. Registration is visible
through the existing `_middleware_registry` inspection attribute, which is an
alias of that chain.

The decorator continues to reject a function that is not a generator. The
function form keeps its current callable validation. The execution chain
orders middleware by ascending numeric priority and then registration order.

## Acceptance

1. Decorator registration wraps a real job run and produces an observable
   effect in the job.
2. Bare decorator, parameterized decorator, and function registration share
   the same execution and inspection store.
3. Mixed registration forms respect priority and stable ordering, with
   post-yield code running in reverse order.
4. Non-generator decorator validation remains intact.

Job middleware in `_engine/job_middleware.py` is outside this change.
