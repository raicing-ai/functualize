# contracts.md — freshness-key-group-options

All surfaces are internal. No public symbol changes, and nothing in `__all__`
of a public package is added or removed.

## `_primitives/fingerprint.py`

```python
def compute_args_hash(
    resolved_config: Any = None,
    call_args: Any = None,
    group_options: Mapping[str, Any] | None = None,
) -> str
```

- The payload is `{"config": resolved_config, "args": call_args}` when
  `group_options` is empty or `None`. This is byte-identical to the previous
  payload, so existing records keep their keys.
- Otherwise the payload is
  `{"config": ..., "args": ..., "group_options": group_options}`.
- `group_options` maps the parameter name to the option's plain-data dump
  (`config_payload(instance)`). For a reader that could not resolve the
  option, the value is `None` instead. A writer never produces `None`.

## `_engine/executor.py` — `JobExecutionEngine`

```python
def fingerprint_args_hash_for(
    self, job_name: str, group_option_values: Mapping[str, Any] | None = None
) -> str

def fingerprint_key_for(
    self,
    job_name: str,
    method: str,
    group_option_values: Mapping[str, Any] | None = None,
) -> str
```

- `group_option_values` is the flat group-CLI layer: the same map
  `RunRequest.group_option_values` carries, and the same map
  `_resolve_group_options` receives. `None` means no CLI layer. Group options
  then resolve from file, env and default.
- Both methods are read paths. They never prompt and never raise for an
  unresolvable config or option.
- `fingerprint_key_for(name, method)` with no layer behaves as before for a
  job without group options.

Callers whose signatures change, and the layer each passes:

| Caller | Layer passed |
|---|---|
| `JobExecutionEngine._from_job_value(ref, scope_id, expected_type, group_option_values)` | the consumer's `context.request.group_option_values` |
| `DependencyRunner._unreusable_upstreams(function, group_option_values)` | the dependent's `context.request.group_option_values` |
| `_app/impl.py` explain (`func builtin why`) → `Preflight.check(..., args_hash=engine.fingerprint_args_hash_for(name))` | none |
