# Run middleware registration plan

## Architecture gate

BEFORE

```text
_app/hooks_facade.py [composition root; public HooksFacade surface]
  -> _app/impl.py (composition root)
      decorator -> _engine/job_middleware.py MiddlewareRegistry [peer engine; inert]
      function  -> _engine/job_middleware.py MiddlewareRegistry [peer engine; inert]
                -> _engine/middleware.py ExecutionMiddlewareChain [peer engine]
  -> _app/boot.py (composition root) -> _engine/executor.py [peer engine]
                                      reads ExecutionMiddlewareChain only
```

The existing shape has duplicated registration and dead code at the app's
middleware store. Its two stores can diverge. No peer layer imports another
peer layer in the proposed change.

AFTER

```text
_app/hooks_facade.py [composition root; public HooksFacade surface]
  -> _app/impl.py (composition root; one registration function)
      decorator ------+
      function --------+-> _engine/middleware.py ExecutionMiddlewareChain [peer engine]
  -> _app/boot.py (composition root)
      _middleware_registry ------ alias ------ _execution_middleware_chain
                                      -> _engine/executor.py [peer engine]
```

The app composition root remains the sole boundary crossing between public
registration and the engine. The alias keeps the inspection attribute useful
without a second mutable store. No new abstraction or cross-layer import is
introduced.

## Retrieval and design

The source search for `_middleware_registry` found writes in `_app/boot.py`
and `_app/impl.py`, and inspection in `tests/core/test_app_extensions.py`.
The engine construction in `_app/boot.py` passes
`_execution_middleware_chain`; graphify confirmed the engine's relationship to
`ExecutionMiddlewareChain`. The repository's `contributor/reference/pitfalls.md`
§6 argues for one registry serving dispatch and inspection. The local
`python-design-patterns` and `design-patterns-refactoring` skills favor
removing the duplicated mutable store over another layer of indirection.
Serena is unavailable in this runtime; source reference searches with `rg`
and graphify supplied the symbol and dependency checks.

## Implementation

Initialize one execution chain in both boot paths and alias the inspection
attribute to it. Route decorator registration through the same function used
by the function form. Preserve decorator generator validation in
`_app/decorators.py`. Update inspection tests for the alias and add a job run
test with mixed registration forms, priority order, and an observable value.

## Surviving smells

`_middleware_registry` remains a private compatibility name for the same
object. This is a duplicate reference, but no duplicated mutable state remains.
It needs no maintainer review because the attribute and inspection operations
were explicitly called out for preservation in the accepted task.

The dead-code delta reports both boot aliases as `TESTS_ONLY`. This is known:
the private alias exists for the inspection tests and refers to the production
chain. It also reports the nested `parameterized` test middleware as
`NEW_DEAD`; that callable is consumed dynamically by the decorator and the
job-run assertion proves it executed. These are advisory tool findings, not
unconnected production code.

## Risk

Code that checks the private attribute with `isinstance(...,
MiddlewareRegistry)` will see `ExecutionMiddlewareChain` instead. The
repository's own inspection test is migrated deliberately.
