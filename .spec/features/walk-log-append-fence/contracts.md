# External contracts

## Public plugin port

`functualize.plugin.EventWriter.append` retains its positional parameters and adds defaulted keyword parameters:

```python
def append(
    self,
    type: str,
    payload: Any = None,
    run_id: str | None = None,
    scope_id: str | None = None,
    generation: int = 0,
) -> None: ...
```

`run_id` and `scope_id` together raise `ValueError("an event names a run or a scope, not both")`. `scope_id=None` preserves existing inferred routing. With `scope_id`, a positive generation must still hold the scope when the write applies; a stale append lands nothing. A substrate may raise or write zero rows at commit. Generation 0 is unfenced.

## Workflow event bus

Every walker-emitted `workflow.*` event has `scope_id` and `generation` in its bus payload. The walk-log subscriber consumes both, passes them to `EventWriter.append`, and excludes them from the persisted payload. Scope-log row and reader response shapes remain unchanged.
