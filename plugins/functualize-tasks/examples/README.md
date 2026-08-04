# functualize-tasks Examples

The task-management domain SDK: `Tasks` capability, `TaskStatus`, and the `MockTasks` testing double (a working in-memory provider that also records operations).

| Directory | Demonstrates |
|-----------|--------------|
| [`todo/`](todo/) | A job creating and completing tasks through the `Tasks` capability |

```bash
uv run pytest plugins/functualize-tasks/examples/ -v
```

For a persistent provider, see [`functualize-tasks-local/examples/`](../../functualize-tasks-local/examples/).
