# ADR-010: One job-schema renderer, in core, under `builtin info`

**Status**: accepted
**Date**: 2026-08-31
**Deciders**: Core team, with agent-assisted research

## Context

A coding agent's first question in an unfamiliar functualize project is *what
can I call, and with what arguments*. Before this change there were four
answers and none of them was both complete and machine-readable:

| Surface | Shape |
|---|---|
| bare `func`, piped | `name — first docstring line` — prose, em-dash separated |
| `func builtin info` | rich panels; 331 box-drawing characters through a pipe |
| `func <job> --help` | click help, one job at a time |
| `app.get_jobs()` | complete and structured, but Python-only |
| `func mcp schema` | complete JSON Schema — **behind the `functualize-mcp` plugin** |

So an agent without the MCP plugin either parsed prose or opened each group's
`--help` in turn, which costs turns and silently misses any group it did not
think to guess.

Two defects surfaced while measuring this against
[DataDog/pup](https://github.com/DataDog/pup)'s "Why Your Agent Will Love It"
claims — *self-discoverable* and *structured output*:

**1. Capabilities were published as required arguments.** A job declaring
`out: Stdout, sh: Shell` advertised `out` and `sh` as required *string* inputs
on every descriptor-driven surface, live MCP tools included. `_discovery` kept a
hand-written exclusion frozenset assembled from `_engine/capabilities/*`, and
`Stdout` and `Shell` are the two capabilities that live in `_types` instead. The
CLI filtered them correctly because it tests the live annotation on a separate
path — so the only surface that leaked was the one with no test comparing it to
another. The existing property test could not have caught it: it builds its stub
types *from* the same list.

**2. `[cli] output` was inert.** It resolved, validated against
`{rich, plain, json}`, warned on invalid values — and was read by nothing except
`config show` printing it back. `FUNCTUALIZE_CLI_OUTPUT=json func builtin info`
still drew boxes. The "resolves but does nothing" shape catalogued in
`contributor/reference/pitfalls.md`.

## Decision

### 1. The JSON Schema renderer lives in core

`_primitives/job_schema.py` owns `TYPE_MAP`, `field_property`, `input_schema`
and `job_input_schema`, re-exported through `functualize.app.utils`. The MCP
plugin's translator now calls it instead of carrying its own copy.

The alternative — core builds its own and a test asserts the two agree — was
rejected. Parity by assertion still permits two implementations to drift between
test runs, and the surfaces that must agree will keep growing (a TUI argument
form is the obvious next one). One renderer is a stronger guarantee than one
test.

### 2. Capability exclusion has one source of truth

`_primitives/capability_names.py` holds `INJECTED_PARAM_TYPE_NAMES` (ADR-014),
and `_engine/capabilities/registry.py` refuses to start when the declared
`CapabilitySpec` names disagree with it. Names rather than types because
`_discovery` may not import `_engine` — they are peer layers — and because
extraction must handle string (PEP 563) annotations, where a name is all there
is.

That invariant is structural, so `tests/discovery/test_capability_parity.py`
covers what it cannot: the *behaviour* — that extraction actually drops those
parameters, on the live public types and under deferred annotations.

This ADR originally proposed a second list in `_types/capabilities.py` checked
against the executor's dispatch by regex. It was collapsed onto the
`_primitives` list on merge: two canonical lists is the bug this section exists
to prevent, and the registry's import-time check is stronger than a regex over
source.

`Stdin` is deliberately excluded from the set: it is an `Annotated[...]` marker
on a real user-supplied parameter, and treating it as a capability would delete
a flag the caller is supposed to pass.

### 3. Subcommands on `builtin info`, not a new `builtin jobs`

```
func builtin info                  # the overview — unchanged
func builtin info jobs [<name>]    # the catalogue, or one job in detail
func builtin info schema [<name>]  # input contracts as JSON Schema
func builtin info all              # everything, as one document
```

`info` was already the documented first stop — every shipped skill, AGENTS.md
and the README point at it — so the structured views belong under the noun
people already reach for rather than beside it. `requires_subcommand=False` and
`invoke_without_command=True` keep bare `func builtin info` working, which is
non-negotiable: breaking it would invalidate four skills and every habit.

A separate `builtin jobs` noun was the other serious candidate. It matches the
`cache`/`state`/`config` pattern more cleanly, but it would have split "what is
here" across two commands with no rule for which to use.

`info schema` always emits JSON regardless of `[cli] output`: it is a contract,
not a display. It uses the MCP tool shape (`name`/`description`/`inputSchema`)
because that is what agent tooling already reads, and a second spelling of one
contract is the drift this ADR exists to end. Asking for a single command
returns an object, not a one-element list — a caller should not have to index.

### 3a. `info schema` walks the command tree, not `app.get_jobs()`

The first cut read `app.get_jobs()`, which left builtins undiscoverable — an
agent still had to walk `func builtin --help` down through ~30 subcommands, the
exact friction the job half had just removed. It also quietly reinstated the
job/builtin split the convergence work removed, where `needs_terminal` was left
as the *only* seam and no `builtin` special-cases remain.

The repo had already decided this. `CommandNode`:

> "Nothing here distinguishes a job from a builtin; that is the point."

and `params()`:

> "Deliberately the **existing** `FieldDescriptor` … There is one description of
> a job's parameters and every surface reads it."

`build_command_tree(app)` already composed `JobCommandProvider` and
`ClickCommandProvider` into one tree. What it lacked was a *consumer*:
`params()` was called only from `tests/core/` — built, tested and unreached,
the shape `contributor/guides/wiring-discipline.md` exists to catch.
`info schema` is its first production caller.

Three defects had to be fixed before that tree could be published as a
contract, all of them invisible while nothing read it:

1. **Two type vocabularies.** Job params carry Python annotations (`int`,
   `bool`); click params carry `ParamType.name` (`integer`, `boolean`,
   `choice`). `TYPE_MAP` knew only the former, so every builtin flag published
   as `"type": "string"` — `--prune` advertised as text. One map now knows
   both, matching the rule the protocol states for the descriptor itself.

2. **The published name was the Python identifier, not the flag.** Across the
   tree the invariant is "the flag is derivable from the name" — a job
   parameter `rows` is passed as `--rows`. Click breaks it whenever a command
   spells the two differently: `@click.option("--json", "json_out")` binds
   `json_out` while the flag is `--json`, so publishing the identifier would
   tell an agent to type `--json-out`. `ClickCommandNode.params()` now reports
   an option's longest declared flag with dashes stripped, restoring the
   invariant; a positional still reports its identifier, having no flag to
   disagree with.

3. **Unrepresentable defaults were serialized.** Click marks "no default" with
   its own `Sentinel.UNSET`, which is not `None`, so it passed the
   `is not None` guard and emerged as the literal string `"Sentinel.UNSET"` — a
   value no caller could pass. `field_property` now publishes a default only
   when it is JSON-native. Fixed in the renderer rather than at the call site,
   so it protects every consumer.

**What counts as runnable.** A leaf is. A node with children is only if it takes
parameters of its own: `builtin info` does (`--json`), `builtin cache` does not
and merely prints usage. Publishing a pure namespace as a command with an empty
schema would tell an agent it can run something that exits 2.

**Shape.** Each entry keeps the MCP fields and adds `kind` (`"job"` /
`"builtin"`, the filter an MCP surface applies) and `path` — the segments to
type, as an array. Structured over opaque, matching the rule the MCP translator
already applies to group namespaces: a dotted string would have to be re-split,
and the split is not obvious. `--kind job` narrows to the previous behaviour.
Jobs sort before builtins: a caller's own jobs are what they came for.

### 4. `[cli] output` drives the renderer

`json` emits structure with no flag, `plain` drops box-drawing, `rich` stays the
default; an explicit `--json` overrides. Scope is the commands that have a
structured form — today the `info` family. `plain` is a real rendering there,
not a fallback to rich, so all three values mean something.

This is what lets an agent `export FUNCTUALIZE_CLI_OUTPUT=json` once instead of
passing a flag on every call — the ergonomics pup gets from sniffing
`CLAUDECODE`/`CURSOR_AGENT` environment variables, without functualize having to
maintain a list of agent vendors.

### 5. `--help` names it — on both entry points

The epilog is a labelled block at the left margin:

```
For AI agents:
  func builtin info schema                 all commands, as JSON
  func builtin info schema --kind job      jobs only
  func builtin info schema --kind builtin  builtin commands only
  func builtin skills list                 skills for this version
  export FUNCTUALIZE_CLI_OUTPUT=json       make JSON the default
```

Three rendering decisions, all of them corrections to click's defaults:

- **The heading sits level with `Commands:`.** Click renders `epilog` inside
  `formatter.indentation()`, which put it two columns in — reading as another
  command rather than a new section. Both root groups override `format_epilog`
  to emit at the margin.
- **It is never re-wrapped.** Click puts the epilog through `wrap_text`, which
  reflows a hand-aligned table into prose. Emitting verbatim makes source width
  the only thing between a narrow terminal and a mangled table, so lines are
  pinned to `MAX_EPILOG_COLUMNS` (72) rather than to 80.
- **Command first, description second**, so the left column is copy-pasteable.

**Spelled for the program that was invoked, and on both root groups.** The
block first shipped on `func` alone with a hardcoded `func` prefix — which is
the wrong entry point to have it on, since the skills tell an agent that `func`
is often not on PATH and to use the project's own `main.py`. So the surface an
agent actually runs was the surface with no pointer, and the advice it would
have printed there was un-followable anyway.

The text now comes from `_primitives/agent_epilog.py`, built at render time
from `ctx.find_root().info_name`, and both root groups render it through one
helper. Two consequences worth naming:

- The 72-column budget was previously satisfied by hand-alignment at *exactly*
  72, so a longer program name silently overflowed into the mangled table the
  cap exists to prevent. The renderer now drops the description column instead
  when the aligned table would not fit — the commands are the part an agent
  needs.
- `NormalizingGroup` is every *sub*group in the trie, not just the root, so the
  block is opt-in (`emit_agent_epilog`) rather than inherited; otherwise it
  repeats on `builtin --help` and on every job group.

This gap was found by the dual-surface `cli_run` harness landing on `master`
in parallel with this work — the epilog tests passed on a single surface and
failed the moment the second one existed. Worth recording as evidence for the
harness rather than as a footnote: it is the same class of defect as the
capability leak in §2, caught the same way.

`--help` prints on every mistyped command, so it is not the place for a
paragraph — but each line answers a question an agent otherwise resolves the
hard way: by walking every group's `--help` in turn, by parsing panelled
output, or by never learning the skills shipped with the install. A setting
nobody can discover is worth as little as one that does nothing, which is what
`[cli] output` was until this change.

`test_help_epilog_stays_short` caps the block, because "one more useful line" is
how a help epilog becomes a manual. It has already earned one deliberate raise
(4 → 6, when the `--kind` filters were added) — which is the cap working: the
growth was a decision someone took rather than one that landed by default.

## Consequences

### Positive

- The complete command surface is available in one call, without the MCP
  plugin, without Node, and without walking `--help`.
- An MCP tool definition and `func builtin info schema` cannot disagree about a
  job, because they are the same function.
- A capability can no longer be added without either updating the exclusion set
  or failing a test.
- `[cli] output` means something, so the config-show row stops being a lie.

### Negative

- `builtin info` is now a click group. Anything that assumed it was a leaf
  command (a completion table, a TUI shortcut) has to handle subcommands —
  though both derive from `BUILTIN_COMMANDS`, which was updated.
- `info all` embeds every job's full detail, so it grows linearly with the
  project. Fine at the scale of a CLI's job count; not a streaming API.
- The MCP plugin now depends on a `functualize.app.utils` export. That is the
  documented public seam for plugins, but it is a new coupling.
- `info schema` now boots the click tree as well as discovery, so it is
  marginally more expensive than a jobs-only listing. `--kind job` skips
  nothing today; if it ever matters, the walk can be pruned by kind.
- `ClickCommandNode.params()` changed what it puts in `FieldDescriptor.name`.
  Nothing read it, so there is no regression — but a future TUI argument form
  will now get the flag spelling, which is the point.

### Neutral

- `func mcp schema` still exists and is unchanged in output. It is the right
  command inside an MCP context; `info schema` is the right one outside.

## Alternatives Considered

| Alternative | Why rejected |
|---|---|
| `info schema` covers jobs only | Leaves ~30 builtin subcommands discoverable only by walking `--help`, and reinstates the job/builtin split the command tree removed |
| A parallel param model for builtins | `CommandNode.params()` already returns `FieldDescriptor`; a second model is what the protocol's docstring forbids |
| Publish namespaces with empty schemas | Advertises `builtin cache` as runnable when it exits 2 |
| New `builtin jobs` noun | Splits "what is here" across two commands with no rule for choosing |
| `builtin info --json` only, no subcommands | Forces a JSON shape onto config resolution, dotenv and skills when callers want jobs |
| `builtin schema` at top level | "Schema" alone does not say *of what*, and leaves nowhere for `list`/`show` |
| Global `--output json` across all builtins | A fourth meaning of "output", and every builtin would need a JSON shape designed at once |
| Core renders its own schema, test asserts parity with MCP | Two implementations can drift between runs; one renderer is the stronger guarantee |
| Agent-mode env detection (pup's approach) | Requires tracking a list of agent vendors. `FUNCTUALIZE_CLI_OUTPUT=json` gets the same result with no vendor list. Revisit if it proves insufficient |
