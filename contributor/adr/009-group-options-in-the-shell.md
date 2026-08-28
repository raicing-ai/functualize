# ADR-009: Rendering and Rebuilding Group Options in the Interactive Shell

**Status**: accepted
**Date**: 2026-08-28
**Deciders**: Hakim

## Context

A `GroupOptions` subclass declares flags at a *group* that every descendant job
inherits, typed **mid-path**:

```
func deploy --env prod web --region eu-west-1 run v1.2
```

The kernel for this shipped in S6a/S6b and works *for `func`*: trie
construction, the walk, inheritance, engine injection, and CLI/MCP/completion
parity are covered by `tests/group_options/`. Two things did not follow. The
shell is the subject of this ADR; an app's **own** entry point is the second,
and it was invisible because all six parity probes drove one CLI — see
decision 11. Its **read** paths were wired
to the mid-path resolver (`resolve_tui_command`); every **write-back** path
still took the bar's first token as the job name — and under a group, that
token is the *group*.

That one mistake produced nine defects, four reproduced against a running app:
the command path was truncated on any field edit; the bar was rewritten in the
dotted spelling its own resolver refuses; typed group flags vanished; a path
segment bound to the job's first positional (`image` silently became `"web"`);
Ctrl+S saved a shortcut naming a group, which is not invocable; no config panel
appeared for any grouped job; readiness was evaluated against the group node, so
the bar reported READY whatever the job was missing; missing-argument detection
returned "not a command"; and completion's argument slice under-cut by two per
mid-path flag, spilling path segments and a deeper group's flags into the job's
own.

None of it was reachable, because **no example project declared a
`GroupOptions` subclass** — `build_group_option_trie` returned `None` and every
defect stayed dormant. `examples/standalone/group_options_lab/` exists to arm
them; `tests/tui_group_options/` holds the regressions.

The defects were mechanical. What needed deciding was everything the shell has
to answer that the CLI never asks: a command line is *parsed* once, but the
shell must also **rebuild** one, and **render** the fields behind it.

## Decision

### 1. One emitter, and it is the shell's only way to write a command line

`build_command_line` (`_cli/tui/sync.py`) turns "which job, which values" back
into a line the user could have typed. Every producer routes through it — the
config-table sync, the pending sync, the pre-flight header, Ctrl+S — so the
fixed point

```
emit(resolve(text)) == text
```

holds by construction rather than by four implementations agreeing. It is sited
in `sync.py` because that module's docstring already claimed single-source-of-
truth status for bar reconstruction; this extends an existing contract rather
than opening a second one.

The property is enforced directly, over the canonical invocation table, in
`tests/tui_group_options/test_smartbar_roundtrip.py`.

**Amendment (2026-08-28, scrutiny pass).** One emitter is necessary and was not
sufficient. `sync_overrides_to_bar` routed *every* edited row into the
emitter's `job_overrides` argument, group rows included, so editing
`[deploy] --env` emitted `deploy web run v1.2 -e prod` — a **job** flag named
`env`, which the walk hands back as `{}`. The bar read READY (the check in
decision 7 inspects `--` tokens only) and the job ran on the group's unedited
value. The emitter places a flag correctly only if it is told which kind the
flag is, so the real invariant is the **partition**, not the funnel:
`sync_overrides_to_bar` now splits on `FieldDef.group_path` before it calls
`build_command_line`, and a field list carrying any group row is authoritative
for the group's values — which is also what makes `r` remove a flag rather than
leave it standing (see decision 9).

The quoting rule was the emitter's other half-truth. `_quoted` wrapped any
value containing whitespace in double quotes while every reader called
`str.split()`, so `deploy --env "us east" web run` resolved to *no job at all*.
`tokenize_bar_text` (`cli_arg_parser.py`) is now the one owner of the inverse
direction, shlex-based, and `_quoted` falls through to `shlex.quote` when the
value carries a quote of its own.

### 2. Group flags emit mid-path; a name declared twice emits at the **outermost** level

Each group flag is written beside the segment of the group that declared it,
because that is the only position the CLI reads it in. A flag written after the
job is the job's own — the docker/kubectl convention the walk already
implements — so emitting a group's flag there would produce a line that parses
as something else.

When two levels declare the same field name, the flag is emitted at the
**outermost** declaring level.

This is the non-obvious half, and it is worth stating why it is safe, because
the parsing side does the opposite. `_match_group_flag` (`_cli/dispatch.py`)
searches `reversed(specs)` — *nearest*-declaration-first — so a nested group
shadows an ancestor's flag on the way in. Emitting outermost on the way out is
not a contradiction, because the value being written back is not attributed to
a level at all. `_engine/executor.py` states the model outright:

> `cli_values` is the **flat** merge the dispatcher produced, nearest
> declaration already winning. Each class is handed only the keys it declares,
> so a job that injects two ancestor types sees one value for a field they
> share.

One value means one place to write it. Choosing the outermost makes that place
deterministic; choosing per-token would make the emitted text depend on where
the user last happened to type it, and the round trip would not close. The
`collision_tui` fixture in `tests/tui_group_options/conftest.py` builds the
two-levels-same-name project the example deliberately does not contain, and
asserts the round trip over it.

`PendingExecution.group_option_paths` carries the attribution the flat values
dict cannot, so the snapshot key and the diff row can name a group without
guessing. It must agree with the emitter: a value attributed to one level and
emitted at another would round-trip into a different command than the one
recorded.

### 3. Default-omission is **opt-in**, reversing the plan of record

The proposal specified that `build_command_line` omit any group value equal to
its declared default (shape-intent SBR.3). Implementation reversed this to
`omit_defaults=False`, a keyword the caller opts into.

`group_values` normally holds **what the user actually typed** — the walk does
not inject defaults. Omitting on equality would therefore delete a user's
explicit `--env staging` because `staging` happens to be the default, and the
fixed point would fail for that input. SBR.3's real intent — "do not fill the
bar with every default" — is satisfied one level up, by the caller: the
config-table path already filters on `edit_origin != NONE`, which is a better
mechanism because it distinguishes *chosen* from *merely equal*.

The option remains for a caller passing fully resolved values, where every
field is present and most are defaults nobody chose. Note it cannot fire for a
secret field at all: a credential's default is not written to the discovery
cache (`_serialize_default` returns `None` when `secret`), so the comparison
has nothing to compare against and the flag is always emitted.

### 4. Group rows render after job rows, outermost group first

This resolves shape-intent `CTD.3`, which left the ordering open on condition
it be consistent and documented. Consider it documented here.

A reader meets the job's own arguments before the path's, and within the group
block the order is the order the path is read in — `[deploy]` before
`[deploy.web]`, matching `group_options_on_path`. The rows are appended *after*
`sort_fields_by_priority` rather than folded into it: that function ranks a
job's arguments against each other, and a field belonging to an ancestor is not
competing in that ranking.

### 5. `[group]` is one convention across every renderer

A group's field is shown with its declaring group as a dimmed prefix — `[deploy]
--env` — with the flag itself undimmed, because the flag is the part the user
types. The Config Table, the pre-flight summary and the diff view all use it, so
a reader learns it once. `FieldDef.group_path` (and `ConfigDiffEntry.group_path`)
is where the attribution lives; both default to `None`, which is what makes an
ungrouped project's rendering byte-identical **structurally** rather than by
discipline.

Rows filter on the group as well as the field name: `deploy` is what the prefix
shows, so it is what someone will type to find those rows.

### 6. The pre-flight header renders the CLI spelling

`_format_preflight_job_header` printed the canonical dotted name directly
beneath a bar showing the spaced one, and the dotted form is a spelling the
shell's own resolver refuses. It now renders `deploy web run`.

This was a pre-existing `X.1` violation affecting **ungrouped projects too**,
fixed here because the same header serves both.

### 7. An unknown job flag stops READY — for every project, grouped or not

Position is what separates a group's flag from the job's own, so
`deploy web run --env prod` asks for a *job* flag named `env` and there is none.
The shell showed READY and a full pre-flight panel listing `--env` one line
above under `[deploy]`, then failed at dispatch with an error the user had no
warning of and every reason to find baffling.

The check is general, so it also fires on ungrouped projects: `greet --nonsense
bob` now greys out. This is a deliberate widening beyond the group case
(maintainer decision), on the grounds that the command was never going to run.

One trap, found by comparing the shell's notion of a valid flag against real
`--help` output for every job in every example project: click renders a **job's**
boolean as a *pair*, so `--no-verbose` is a genuine flag even though no field is
named `no_verbose`, and a naive field-name check greys out a valid line. A
**group's** boolean has no pair — `_flag_aliases` builds only the long form, the
undecorated form, and any short flag — so `deploy --no-dry-run web run` really is
refused by dispatch. The shell now matches dispatch in both cases, and a test
pins each so the day the dispatch side changes, a test says so.

**Amendment (2026-08-28, scrutiny pass).** That comparison was made once, by
hand, over the field shapes the example projects happen to contain, and it
missed two:

- A **positional** is a `click.Argument` and has no flag spelling at all, so
  `deploy web run --image v1.2` was refused by click and reported READY by the
  bar — the exact failure this decision exists to close. (The example's own
  `main.py` docstring advertised that spelling.)
- A boolean's negative half exists only for a **plain** bool. With a short flag
  the param builder emits `["--verbose", "-v"], is_flag=True` and no
  `--no-verbose`, so allowing `no_<name>` unconditionally greenlit a line
  dispatch refuses.

`known` is now built from the same rules `build_click_params_from_fields`
applies, field shape by field shape, and short flags are validated too (with a
numeric guard, so `--count -1` stays a value). The rules are not restated in a
test: `TestReadinessAgreesWithClick`
(`tests/tui_group_options/test_write_back_contract.py`) derives the expected
set from the param builder itself, over a fixture carrying every shape it
branches on.

### 8. Two shape-intent assertions were void, not implemented

- **`SBP.1`** asked for `parse_cli_args_to_kwargs` to return group values as
  well as job kwargs. A trie-walking resolver already existed as its sibling —
  `resolve_tui_command` — so building a second would have violated the intent's
  own `X.2`. The parser stays job-level-only; its *callers* feed it
  `resolution.args`.
- **`PF.1`** attributed the command line to `build_preflight_lines`, which
  renders per-field lines only. Reattributed to the header (decision 6).

Both are recorded in the shape intent itself.

### 9. A group row is reset as the *path's*, not as the job's

**Added 2026-08-28 (scrutiny pass).** Shape-intent `CTE.3` — `r` on a
`[deploy] --env` row clears the override and removes the flag from the bar —
shipped unimplemented and untested, and it needed two things that were both
missing.

A group row built from a bar-typed value arrived with `edit_origin = NONE`, so
`action_reset_override` hit its own no-op guard (Req 5.7) and never fired: the
row *displayed* `source="cli"` while claiming nothing had been edited. It is
now marked `VALUE`, with `original_value` set to what the row falls back to —
the group's own resolved layer, else its declared default — exactly as the job
path does for a CLI-provided field.

And `on_config_table_panel_override_reset` cleared `PendingExecution.overrides`
for every row. For a group row that both misses the value (the flag stays
standing mid-path in the bar) and, where the job declares a field of the same
name, clears the **job's** instead. The attribution is on the row; the handler
now uses it, popping `group_option_values` / `group_option_paths`.

### 10. Every group section on the path contributes to the Config Files panel

**Added 2026-08-28 (scrutiny pass).** Shape-intent `CF.1–3` concluded "zero code
changes, verify by audit only", and the audit left no artifact. It was right
about the shape it reasoned over and wrong for two levels: the panel resolves
one section — the job's — so `deploy.web.run` read `[deploy.web]` and reported
`region`, while `[deploy]`'s `env` and `token`, in the same file two lines up,
did not appear at all.

`discover_config_files` now partitions its field list on `group_path` and reads
each declaring group's section as well as the job's, labelling what it finds
`[deploy] env`. Unescaped, unlike the other three renderers, because that column
is a plain DataTable cell rather than Rich markup — the section shown beside it
in the File column is written the same way.

### 11. Mid-path flags work on an app's own entry point, not only on `func`

**Added 2026-08-28 (scrutiny pass).** The Context above says the kernel "works",
citing `tests/group_options/` for CLI parity. Those six probes drive
`functualize._cli.main`. A standalone app does not go through it: `CliAdapter`
builds a real nested `click.Group` tree and click owns the parse, so
`walk_group_path` is never reached and the group answered `Error: No such
option '--env'` for the one spelling the feature exists for.

    func deploy --env prod web run v1.2   →  env = prod
    glab deploy --env prod web run v1.2   →  No such option '--env'

`group_options_lab`'s README says the two are interchangeable, and it now is.
Each group node carries its declared options as real click params, rendered by
`build_click_params_from_fields` — the same builder the job path uses, so a
group flag is spelled exactly as the identical job flag would be — and a
callback deposits them into one mutable dict shared with every job command
beneath. Mutable rather than baked in at construction, because click parses a
group's params before it resolves the sub-command.

Only values click reports as coming from `COMMANDLINE` are deposited.
`group_option_values` reaches the engine as the **CLI layer**, which outranks
the group's config file, so depositing click's defaults would silently replace
`[deploy] env = "from-file"` with `"staging"`. That is the one trap in giving a
group real params, and it is pinned in
`tests/group_options/test_adapter_entry_point_parity.py`.

## Consequences

### Positive

- The fixed point is a single testable property rather than an invariant spread
  across four writers, and it covers the two-levels-same-name case that was
  previously argued from a docstring rather than reproduced.
- Group options are visible where their values are decided, attributed to the
  group that declared them, in three panels that agree on how to say it.
- A group option declared `Secret[str]` masks by the same rule a job's
  credential does — see ADR-008's Addendum A5.
- The grep gate (`tokens[0]` → the sanctioned sites, `tokens[1:]` → those, and
  `panels/` → 0) makes the root-cause class of defect mechanically detectable
  rather than a matter of review attention. **It is a test**
  (`tests/tui_group_options/test_write_back_gate.py`), not a recipe: as
  originally written it was a bash snippet in a guide, which is exactly the
  "review attention" the sentence claims to have replaced, and the scrutiny
  pass that added the test found a further write-back defect behind a fourth,
  equally unenforced rule. The gate now also owns "one tokenizer" and "every
  `FieldDef` carries `secret=` and `group_path=`".

### Negative

- Decision 7 changes readiness behaviour for projects that have nothing to do
  with `GroupOptions`. Snapshot-bearing output moved for ungrouped projects
  under decision 6 as well.
- Two spellings of "which required arguments are missing" now coexist and agree
  (`SmartBar.evaluate` runs; `get_missing_required_args` does not). Kept
  deliberately — see `STATUS.md` follow-up 13 — at the cost that a reader must
  work out which one is live.
- `omit_defaults` is a parameter nothing currently passes as `True`. It is
  specified and tested, but it is API surface ahead of a caller.

### Neutral

- No cache-format change. `FieldDescriptor.secret`, `.default` and
  `.short_flag` were already cached; group options inherit them through
  `extract_group_options_fields`, which reuses the job path's extractor.
- `ConfigSnapshot` gains no field. Group values ride the existing flat `values`
  dict under a group-prefixed key, so old snapshots deserialize unchanged.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Teach `parse_cli_args_to_kwargs` to walk the trie (shape-intent `SBP.1` as written) | One entry point for callers | A second resolver beside `resolve_tui_command`, which the intent's own `X.2` forbids | Fix the callers, not the parser |
| Emit a repeated name at the **nearest** declaring level, matching `_match_group_flag` | Symmetric with parsing | The value carries no level; emitted text would depend on where the user last typed it, and the round trip would not close | Determinism beats symmetry when the data is flat |
| Keep group rows in a separate panel from the job's fields | No ordering question at all | A user asking "what will this run with?" would have to check two places for one answer | Ordering is cheaper to document than a second panel is to justify |
| Route the TUI panel path through `resolve_job_fields` for one resolver everywhere | True single answer | Needs a live Pydantic class; would import a job module on every panel refresh | Already settled — ADR-008 Addendum A1 |
| Reject unknown flags only when they are known group options in the wrong position | No behaviour change for ungrouped projects | Silent on genuine typos; more code for a narrower fix | Maintainer chose the general rule |
