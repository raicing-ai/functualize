# External contracts

Status: proposed; confirm with `spec.md` before Plan. These are user-facing outputs, not implementation types.

## Command invocation and group help

For each existing `JobNameCollision` associated with the invoked or listed address, emit one physical stderr line before execution or beside the help listing. The line contains the collision type, canonical command, both Python function names and unambiguous source file paths, the registered function, and the action “rename one.” Example for the two-file fixture (paths abbreviated here for readability):

```text
JobNameCollision: 'status' (…/jobs/a.py) and 'status_' (…/jobs/b.py) both claim 'tools.status'; 'status_' runs; rename one.
```

No new stdout text is emitted for an invocation. A colliding job's exit status still follows the job result. Normal jobs emit no collision line. `func tools --help` retains its normal stdout listing and writes the diagnostic to stderr.

## `func builtin info jobs`

Text output retains its existing job rows and prints each matching collision below the affected row, with the same information as the stderr line. The JSON output retains its top-level array and all existing row keys; a colliding row adds `collisions`, an array of objects in deterministic finding order. A clean row has no `collisions` key. Proposed new object shape:

```json
{
  "canonical_name": "tools.status",
  "dropped_python_name": "status",
  "dropped_source_file": "…/jobs/a.py",
  "registered_python_name": "status_",
  "registered_source_file": "…/jobs/b.py"
}
```

Paths must identify the files unambiguously; when a file-backed claimant exists, use its actual source file rather than only its module label. A command with multiple recorded collisions lists every relevant finding, without conflating intermediate claimants with the final survivor. If Plan proves this last association impossible without changing the published `discovery_failures` payload, return to Specify and ask for a contract decision before proceeding.

## Full report

`func builtin info --json` retains `discovery_failures: [{module, path, error_type, message}]` exactly as today. `path` continues to identify the dropped claimant. The full report's existing `jobs[*].source_file` continues to identify the registered claimant. A colliding `jobs[*]` entry adds the same `collisions` array specified above, so the two paths are paired in a machine-readable object. A clean job entry gains no field. Text `func builtin info` retains its existing discovery-failures rendering and adds a companion collision detail below the affected job row, naming both files. No new public Python API is requested.
