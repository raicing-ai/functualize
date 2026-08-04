# functualize-flow-viz

> **Status: Published** — Independently installable from PyPI.

Inline execution tree visualization plugin for functualize. Renders a live job execution tree in the terminal showing step status, durations, and nested invocations updating in real time. Automatically detects TTY capabilities and falls back to structured plain-text output for non-interactive terminals.

## Installation

```bash
pip install functualize-flow-viz
```

## Quick Start

```python
from functualize_flow_viz import FlowVizPlugin

# Register the plugin with your functualize app
plugin = FlowVizPlugin()
plugin.on_job_start("deploy", {"env": "production"})
plugin.on_log("info", "Starting deployment...")
plugin.on_invoke_start("migrate", {"target": "latest"})
plugin.on_invoke_end("migrate", None)
plugin.on_job_end("deploy", None)
```

## Features

- **Live execution tree** — Renders a real-time tree of job execution with status icons (⏳ running, ✓ success, ✗ failure, ○ pending, ⊘ timeout)
- **Nested invocation tracking** — Shows `rc.invoke()` calls as indented children in the tree, preserving parent-child relationships
- **Real-time duration refresh** — Background thread updates elapsed durations at ≤1s intervals for running nodes
- **TTY auto-detection** — Uses ANSI inline rendering on interactive terminals; falls back to plain-text output for piped/CI environments
- **Custom event handling** — Renders domain-specific visualizations including progress bars for events with progress payloads
- **Log streaming** — Buffers log messages and prints them above the inline tree widget to avoid visual corruption

## API Reference

Public classes and functions exported by this plugin:

- `FlowVizPlugin` — Main plugin class implementing the OutputRenderer protocol. Auto-selects between TTY and plain-text rendering. Methods:
  - `on_job_start(job_name, metadata)` — Initialize the execution tree for a job
  - `on_log(level, message)` — Render a log message
  - `on_status_change(old_status, new_status, message)` — Handle status transitions
  - `on_phase_change(step, action)` — Add or update a job phase node
  - `on_invoke_start(child_job_name, kwargs)` — Begin tracking a nested invocation
  - `on_invoke_end(child_job_name, result)` — Complete a nested invocation
  - `on_job_end(job_name, result)` — Finalize the tree and render final state
  - `on_event(event)` — Handle custom structured events
  - `render_log(message, level)` — OutputRenderer protocol: render log
  - `render_phase(phase, status)` — OutputRenderer protocol: render phase update
  - `render_progress(current, total, label)` — OutputRenderer protocol: render progress

Internal (non-public) classes used by `FlowVizPlugin`:

- `TreeNode` — Dataclass representing a node in the execution tree with label, status, timing, and children
- `InlineTTYRenderer` — ANSI-based renderer for interactive terminals with background refresh
- `PlainTextRenderer` — Fallback renderer producing structured plain-text without escape sequences

## Development

Run plugin tests:

```bash
uv run pytest plugins/functualize-flow-viz/tests/ -v
```
