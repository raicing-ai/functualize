# Run tags from every settings file

## Problem

`[run] tags` in a project settings file currently has no effect on the tags
attached to a run. The existing run-tag path reads the global user file, the
environment variable, and CLI flags. A project owner cannot declare tags for
all runs in a checkout, and a non-CLI caller does not receive those defaults.

The declared `run.tags` setting is also exposed to the ordinary list resolver.
That resolver concatenates list items and accepts malformed tag strings; its
resolved value cannot be a run-tag input. The intended behavior below therefore
uses each settings file's raw `[run] tags` list through the one run-tag grammar,
not `settings.values["run.tags"]`.

## User stories

- As a project owner, I can put `[run] tags` in a selected project settings
  file and see those tags on every run started in that checkout.
- As a user with nested projects, I can override a tag key nearer to the
  invocation directory without losing unrelated keys from outer files.
- As an operator, I get an early, source-specific refusal for a malformed or
  repeated tag, before a served application imports jobs or plugins.
- As a host author, I get the same effective defaults through the app execution
  door, regardless of whether the run arrived through a delivery adapter.

## Behavior

### Sources and precedence

`[run] tags` participates in the existing settings-file walk. A selected
`.functualize.toml`, `.functualize/.functualize.toml`, or `pyproject.toml` may
contribute a list in each project directory. The existing one-file-per-directory
choice and inclusive `root = true` stop remain in force. The global user file
may also contribute a list. A syntactically unreadable settings file follows
the existing settings-layer behavior and contributes no values.

The effective map overlays keys in this order, lowest to highest:

1. Global user file.
2. Farthest selected project file through nearest selected project file.
3. `FUNCTUALIZE_RUN_TAGS`.
4. Repeated `--run-tag` flags, where the CLI surface offers them.

Each source is validated independently. A repeated key within one source is
an error; the same key across sources is an override. Keys that are not
overridden remain. The final map may contain at most 32 keys and is frozen
when the run opens. Existing tag grammar, value limits, and comma rules apply
equally to file, environment, and flag sources. No tag comes from a job config
file.

`FUNCTUALIZE_RUN_TAGS` is the schema-derived environment name for `run.tags`.
It is consumed only by the run-tag grammar, alongside `--run-tag`. The ordinary
list resolver does not parse either source as a generic list. A resolved
settings snapshot must not supply the run-tag map from
`settings.values["run.tags"]`; the selected file layers are the source.

### Execution surfaces

The effective checkout and environment defaults reach `func <job>`, TUI and
inline TUI, HTTP, Lambda, MCP run tools, direct `app.execute`, event submit,
and workflow control. A direct request's `RunRequest.run_tags` overlays the
defaults per key. Child runs (`Invoke`, steps, dependencies, parallel) inherit
the parent's already frozen map exactly; they do not reread settings or
environment. Delivery wires do not gain a new tag-input field.

Standard application boot, including `func builtin serve http`, validates tags
explicitly before job or plugin import. A malformed or repeated file item
refuses that boot even if no run is requested. The CLI job path validates before
discovery. Explicit static boot retains its zero-filesystem-I/O promise; it
resolves and validates defaults on the first `execute` instead, before that
run opens, and caches the result for later runs.

### Refusals

A `[run] tags` value that is not a list of strings, a malformed item, or a
repeated key within one file is refused. A CLI command projects a
`RunTagError` as `Error: <source-specific detail>` on stderr and exits 2. For
file errors, the detail names the actual path and offending item or positions;
for `pyproject.toml`, it names `[tool.functualize.run] tags`. A standard served
application refuses at boot before job or plugin import. A static app raises
the same typed error at its first `execute`. A value exceeding the 32-key
effective limit is likewise refused.

Examples of the diagnostic shape:

```text
Error: [run] tags in /checkout/.functualize.toml item 2 ':x': a run tag needs a key before ':'.
Error: [run] tags in /checkout/.functualize.toml gives run tag key 's' twice (items 1 and 2).
Error: [tool.functualize.run] tags in /checkout/pyproject.toml must be a list of strings.
Error: a run may have at most 32 run tags.
```

The sample paths are illustrative; diagnostics use the selected file's real
path. `FUNCTUALIZE_RUN_TAGS` and `--run-tag` keep their source names in errors.

## Acceptance criteria

1. A project-file tag appears on a recorded CLI run; a nearer file overrides
   the same key from a farther file while unrelated keys remain.
2. Global, every selected project file, environment, and CLI flag precedence
   is observable per key. A `root = true` file and the existing winner per
   directory delimit the same walk as other settings.
3. An invalid or repeated project-file item causes `func <job>` and
   `func builtin serve http` to exit 2 with file and item detail before job or
   plugin import; malformed environment or flag input uses the same grammar.
4. Non-CLI execution through TUI, inline TUI, HTTP, Lambda, MCP run tools,
   direct `app.execute`, event submit, and workflow control receives the map
   without each surface implementing its own parser. An explicit request map
   overrides defaults and child runs copy that map exactly.
5. Static boot performs no new settings-file I/O; the first `execute` validates
   and freezes the defaults. Standard boot validates before the exception-
   swallowing plugin strictness helper can run.
6. The generic settings snapshot does not concatenate, deduplicate, or accept
   `run.tags` as an ordinary list value. The setting remains declared, and a
   tag-only selected file still counts as used by the config-path surface.
7. Store schema, tag-filter behavior, and run identity/hash behavior remain as
   they are. No delivery request envelope gains a tag field.

## Outside this feature

Store schema or tag-filter changes; job config tags; wire tag input; per-step
tags; reopening the one-file-per-directory choice; and preview or inspection
surface additions are outside this feature.
