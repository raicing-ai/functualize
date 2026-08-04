# functualize-flow-viz Examples

Live inline execution tree — zero code changes to your jobs. The plugin subscribes to `invoke_start`, `invoke_end`, and `phase_change` events and renders phase status, durations, and nested invocations.

| Directory | Demonstrates |
|-----------|--------------|
| [`pipeline/`](pipeline/) | A job invoking sub-jobs with phase tracking — the shape flow-viz visualizes |

## See it live

```bash
cd plugins/functualize-flow-viz/examples/pipeline
func jobs.py morning_report --city Tokyo
```

With `functualize-flow-viz` installed, the run renders as a live tree:

```
⏳ morning_report
├─ ✓ forecast — Forecast retrieved (0.1s)
├─ ✓ alerts — Alerts checked (0.1s)
└─ ✓ morning_report (0.3s)
```

Uninstall the plugin and the same command prints plain logs — jobs never know the difference.

## Tests

```bash
uv run pytest plugins/functualize-flow-viz/examples/ -v
```
