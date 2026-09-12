# Inline Dependencies — Standalone Job

Jobs that use Domain SDK packages (state, tasks) directly in a single script file. No project structure needed — just `pip install` and go.

## Source

[`examples/standalone/showcase/scripts/data_processor.py`](https://github.com/raicing-ai/functualize/blob/master/examples/standalone/showcase/scripts/data_processor.py)

## Running

```bash
pip install "functualize[cli]" functualize-tasks
cd examples/standalone/showcase
func scripts/data_processor.py process --input-path ./sample.csv --format json
func scripts/data_processor.py summarize --input-path ./sample.csv
```

## Key Concepts

- **Multiple jobs per file** — `func` discovers all job functions in a single script
- **A module-level dict** — script-local, and gone with the process. There
  was a `functualize-state` SDK offering this behind a protocol; it was retired
  (`contributor/adr/022`) because a backend-agnostic key-value protocol can only
  offer the intersection of every backend. Durable state belongs to a *run*
  (`rc.state`) or to a workflow scope.
- **`MockTasks`** — Track tasks within a script without a database
- **Shared module state** — Jobs in the same file can share state objects

## When to Use This Pattern

- Quick automation scripts that need state tracking
- Data processing pipelines in a single file
- Prototyping before moving to a full project structure
- CI/CD scripts that need structured logging and task management

## Related

- [State Persistence Guide](../../guides/configuration.md)
- [AI Outbound Example](ai-outbound.md) — Another standalone pattern with AI
