# Run-tag contracts

## Settings file and environment

`run.tags` is the existing declared list setting. The file value is an array of
`key:value` strings under `[run]` in the global user file or a selected project
`.functualize.toml` / `.functualize/.functualize.toml`. In `pyproject.toml` the
same field is `[tool.functualize.run] tags`. This feature adds no declaration,
alias, or legacy setting.

```toml
[run]
tags = ["team:payments", "environment:staging"]
```

`FUNCTUALIZE_RUN_TAGS` is already derived from the setting name. Its value is
the existing comma-separated sequence of `key:value` items. Repeated
`--run-tag key:value` is the CLI-only top layer. The run-tag grammar owns both;
the generic settings list reader must leave `run.tags` alone. The selected
raw `SettingsLayer` values supply files to the run-tag resolver. An opaque
generic `ResolvedSettings.values["run.tags"]` is never a valid input to it.

## Request and run record

`RunRequest.run_tags: Mapping[str, str]` already carries explicit caller tags.
The app execution boundary overlays that map over the frozen checkout defaults
and passes the resulting immutable map to the existing engine. The direct CLI
job path passes its fully merged immutable map into its `RunRequest`. Child
requests retain the parent's effective map exactly. No public request
constructor, HTTP/MCP/Lambda envelope, or persistence schema gains a field.

## Resolution boundary

The one run-tag grammar and layer resolver live at
`functualize._config.run_tags`. They accept selected `SettingsLayer` objects in
their existing nearest-first order, then apply them global-first and
farthest-project-first. Their result is a frozen key/value map. The module is
the only parser of `FUNCTUALIZE_RUN_TAGS` and `--run-tag`; callers supply raw
inputs and do not parse them. `functualize.app.config` exposes the supported
forwarding seam used by `_cli`; `_cli` does not import an internal package.

The existing CLI `_merge_run_tags` boundary remains the place that maps a
`RunTagError` to stderr plus `ExitCode.USAGE` (2), before discovery. A
standard-boot caller validates before job/plugin import and presents the same
failure shape at a CLI service boundary. Static app execution raises
`RunTagError` on its first execute if defaults are invalid.

## Diagnostic shapes

```text
Error: [run] tags in <path> item <n> '<value>': <grammar reason>
Error: [run] tags in <path> gives run tag key '<key>' twice (items <first> and <second>).
Error: [tool.functualize.run] tags in <path> must be a list of strings.
Error: a run may have at most 32 run tags.
```

The exact grammar reason continues to come from `parse_tag`; the file context
uses the selected layer's path and table prefix. API callers receive the typed
`RunTagError` without a CLI exit code. Cross-source overrides are allowed;
within-source duplicates are refused.
