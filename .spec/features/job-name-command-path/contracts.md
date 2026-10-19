# External contracts

Status: proposed concrete representation of the approved behavior. The member reviews this with `tasks.md` before Execute.

## Python API

`functualize.types.CommandPath` is an immutable value containing path segments. `JobDescriptor.command_path: CommandPath` is a public, derived read-only property. `str(descriptor.command_path)` is the shell spelling. Identity remains `descriptor.name`, and `JobDescriptor.to_dict()` / `from_dict()` keep their current serialized shape. A user-shaped example under `examples/` must exercise the new public type and property.

## Human-facing shell text

For a job with identity `suite.inventory` and group `suite`, the path is `suite inventory`. The same path is used in hints, help, usage, listings, resume text, TUI rows and pre-flight. The leaf help contract is `Usage: func suite inventory [OPTIONS]` or `Usage: <app> suite inventory [OPTIONS]`. A dotted group traversal such as `func suite.inventory` fails with the existing spaces hint. A literal-dot leaf may still be one valid token, as E6 requires. Group and plugin paths retain mid-path flag behavior.

A colliding command prints one physical stderr line before invocation, names both function names and source files, states which claimant runs, and says to rename one. Group help and TUI show the same finding next to the command. Multiple claimants produce one deterministic finding per displaced claimant. A clean command has no warning.

## Machine-readable output

The existing JSON `name` field remains the dotted identity, including in `func builtin info jobs --json` and the full report. The top-level jobs catalog remains an array. A colliding job row gains `collisions`, an ordered array of objects with `canonical_name`, `dropped_python_name`, `dropped_source_file`, `registered_python_name`, and `registered_source_file`. A clean row omits `collisions`. The same collision array appears on the job detail within the full report. The existing `discovery_failures` objects (`module`, `path`, `error_type`, `message`) remain byte-compatible in shape and keep the dropped claimant's path. The registered job's `source_file` remains the surviving claimant's path. Programmatic surfaces outside reporting retain their dotted job identifiers.

The two-file association must be proved before implementing the JSON join. If the existing findings and surviving descriptor cannot yield both real paths for every claimant, return to Specify for a contract decision; do not parse a prose message or silently change `discovery_failures`.
