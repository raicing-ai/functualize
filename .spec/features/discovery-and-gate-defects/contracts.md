# Contracts — Discovery and gate defects

External interfaces only: exported signatures, dataclass fields users pass,
and observable result payloads. Internal types are in the implementation.

## 1. `functualize.app.JobSources`

The field under question, as it stands:

```python
@dataclass(frozen=True)
class JobSources:
    directories: list[str] | None = None
    functions: list[Callable[..., Any] | Job] | None = None
    job_providers: list[Any] | None = None   # read by nothing
    children: dict[str, str] | None = None
    children_glob: str | None = None
    lazy: bool = True
```

**If B1 resolves as "wire it"**, the field's declared type stops being `Any`:

```python
    job_providers: list[JobProvider | tuple[JobProvider, list[JobTransform]]] | None = None
```

…which is what the docstring already promises. `JobProvider` and
`JobTransform` are already public (`functualize.plugin`), so this adds no new
exported name.

**If B1 resolves as "delete it"**, both the field and its docstring line go.
This is a breaking change to a keyword argument that currently does nothing,
which the pre-release stance permits.

## 2. Result payload for a blocked gate (B4)

Unchanged in shape. What changes is that this payload is produced in one more
situation — an unregistered strategy name — where a `ValueError` propagated
before.

```python
JobResult(
    status=RunStatus.BLOCKED,
    metadata={
        "blocked_on": "<gate name>",
        "workflow_scope": "<scope id>",
        "workflow_status": "blocked",
        # new, and only present for this cause:
        "blocked_reason": "unregistered gate strategy 'ai_inbound' — "
                          "install functualize-ai to register it",
    },
)
```

`blocked_reason` is additive and optional. Consumers that read `blocked_on`
are unaffected.

The mapping from strategy name to the plugin that registers it is a fixed,
core-owned table — core must not import either plugin to build it:

| strategy | registered by |
|---|---|
| `resolve` | core, at boot |
| `prompt` | core, at boot |
| `ai_inbound` | `functualize-ai` |
| `ai_outbound` | `functualize-mcp` |

## 3. Import-failure reporting (B5)

A new entry in the `builtin info` report payload. Shape:

```python
{
    "import_failures": [
        {
            "module": "jobs",
            "path": "/abs/path/jobs.py",
            "error_type": "ModuleNotFoundError",
            "message": "No module named 'nonexistent_module_xyz'",
        }
    ]
}
```

Empty list when there are none — never absent, so a consumer need not guard.

Surfaced by whichever builtin the plan selects (`builtin info` full report, or
a `builtin doctor` row); the payload shape is the contract, the command
placement is a plan decision.

## 4. `Gate.strategy` — accepted values (B6, documentation only)

No code change. Recording the constraint the docs must state:

```python
_VALID_GATE_STRATEGIES = frozenset({"resolve", "prompt", "ai_inbound", "ai_outbound"})
```

`Gate(strategy=...)` validates against exactly this set in `__post_init__`.
Preset names registered via `app.register_gate_preset` — `"ai_inbound"`,
`"ai"`, `"ai_outbound"` — are **not** accepted here. They resolve only through:

```python
app.resolve_gate(model, gate_strategy="ai", gate_name="...")
rc.invoke(job, awaits_input=Model, force_gate=True, gate_strategy="ai")
```

Note also the axis collision to be described, not fixed, in this feature:
`docs/guides/ai.md` uses *outbound* to mean "the job calls an LLM" and
*inbound* to mean "an external agent drives the job", while the gate strategy
`ai_inbound` is the one implemented by calling an LLM. Both namings are
internally coherent — one names the scenario, the other the direction the
answer travels — and any prose touching both must say which axis it means.

## 5. Signatures that change

```python
# _app/impl.py — unchanged signature, changed behavior (B3)
def register_dynamic_job(
    app: Any,
    name: str,
    function: Callable[..., Any],
    config_class: Any | None = None,
    group: str | None = None,
) -> None: ...
```

The descriptor it appends gains a populated `parameters` list. No caller
changes.
