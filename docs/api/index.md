# API Reference

The API reference documentation is auto-generated from Python docstrings using [mkdocstrings](https://mkdocstrings.github.io/). Each page displays class signatures, method signatures, function signatures, parameter types, return types, and docstring descriptions for all public symbols in the corresponding module.

When source code docstrings are updated, the API reference reflects those changes on the next documentation build — no manual editing of these pages is required.

## Public Modules

| Module | Import Path | Description |
|--------|-------------|-------------|
| [App](core.md) | `functualize.app` | Application construction: `FunctualizeApp`, config objects, preset factory functions. |
| [Job](context.md) | `functualize.job` | Job author API: `RunContext`, capability classes (`Log`, `Invoke`, `Prompt`, `Perf`, `State`, `Sources`, `Shell`, `Freshness`). |
| [Plugin](plugins.md) | `functualize.plugin` | Plugin author API: `EventBus`, `Surface`, `PromptCollector`, `LiveConstruct`, protocols. |
| [Types](discovery.md) | `functualize.types` | Shared types: `JobDescriptor`, `FieldDescriptor`, `JobResult`, `RunStatus`, enums. |
| [Types — Run Model](types.md) | `functualize.types` | The door a run entered through and its status translation: `RunSurface`, `RUN_SURFACES`, `request_from_envelope`, `wire_value`, `status_from_wire`, `report_line`. |
| [Workflow](workflow.md) | `functualize.workflow` | Graph-based job orchestration: `@workflow`, `Step`, `Gate`, `AgentStep`, `Edge`, `ConditionalEdge`, `OnFailure`, `Notify`, `Notification`, `END`. |
| [Testing](testing.md) | `functualize.testing` | Test doubles for job unit tests: `TestRunContext`, `FakeShell`, `FakeShellCall`, `FakeStdout`, and friends. |

## Internal Module References

These pages document where internal functionality has moved. Users should import from the public modules above.

| Module | Description |
|--------|-------------|
| [Config (Internal)](config.md) | Configuration resolution system — now in `_config/`. |
| [Discovery (Internal)](discovery.md) | Job auto-discovery — now in `_discovery/`. |
| [Events (Internal)](hooks.md) | Event system — now in `_events/`. |
| [Hierarchy (Internal)](hierarchy.md) | Child project composition — now in `_discovery/hierarchy.py`. |
| [Validation (Internal)](validation.md) | JobConfig validation — now in `_config/job_config.py`. |

!!! note "Scaffold and TUI"
    The scaffold system is now internal to the CLI (`_cli/scaffold/`). The TUI adapter is at `functualize.app.adapters.tui`. Neither has a separate API doc page — they are accessed through the `func builtin scaffold` CLI command and `TuiAdapter` class respectively.
