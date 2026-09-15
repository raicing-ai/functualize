# Run Commands

Read the **run log**: every execution this project has performed, through any
door, with how it ended and what it set off.

```bash
func builtin run list
func builtin run show <run-id>
```

## Runs are not workflow scopes

Both have ids and both can be listed, so it is worth being precise about which
question each answers:

| | a **scope** (`func builtin workflow`) | a **run** (`func builtin run`) |
|---|---|---|
| is | a workflow's *position* | one *execution* |
| records | which steps completed, which gate waits, where the walk stopped | what was asked for, through which door, by which process, how it ended |
| exists to be | **resumed** | **read afterwards** |
| answers | "what is waiting on me?" | "why did last night's build fail?" |

A workflow that blocked and resumed three times is **one scope and four runs**.
Every run records the scope it executed in, so:

```bash
func builtin run list --scope wf-7a91c2e4      # the four runs of that one scope
```

A plain job that is not a workflow still produces a run. That is the point —
the run log covers everything, including jobs that never touch a graph.

## `func builtin run list`

```
func builtin run list [--job NAME] [--surface DOOR] [--state STATE]
                      [--scope SCOPE_ID] [--limit N] [--format table|json]
```

Newest first — the opposite of `workflow list`, and deliberately: a scope list
answers "what is waiting on me", where order is incidental; a run list answers
"what just happened", where it is the whole question.

```bash
func builtin run list                          # the 20 most recent
func builtin run list --job nightly-build      # only that job
func builtin run list --state failure          # only what went wrong
func builtin run list --surface http --limit 5 # only runs that arrived over HTTP
```

`--limit` is applied **after** filtering, so a narrow filter is never starved by
a flood of unrelated recent runs.

### Filtering by door

`--surface` is what makes "the same job behaves differently from the CLI and
from HTTP" an answerable question rather than a hunch. The origin is carried by
the request rather than reconstructed afterwards, so it is recorded exactly:

`app.cli` · `app.execute` · `app.parallel` · `engine.dependency` ·
`engine.step` · `event.job-submit` · `func.builtin` · `func.group` · `func.job` ·
`func.single-file` · `http` · `invoke` · `invoke.parallel` · `lambda` ·
`mcp.async` · `mcp.run-job` · `mcp.tool` · `tui.inline` · `tui.shell`

### Filtering by state

`--state` filters on the **derived** state, not the stored status, because the
question people actually have — *which runs never finished?* — is not expressible
in the stored one.

`blocked` · `cancelled` · `failure` · `refused` · `running` · `skipped` ·
`success` · `timeout` · `unknown` · **`abandoned`**

`abandoned` is the derived one: a run with no recorded end whose runner is not
this process.

> **`abandoned` currently over-reports.** A long-running job on *another*
> machine has no end recorded and is not this process, so it reads as abandoned
> even though it is alive and well. The over-report is deliberate: a misleading
> row is something you re-check, while a dead run reported as `running` is
> hidden for ever. A lease with renewal replaces the inference with a fact; until
> then, treat `abandoned` as "nothing has heard from this", not as "this is
> dead".

## `func builtin run show`

```
func builtin run show <run-id> [--events] [--tree] [--format table|json]
```

```bash
func builtin run show run-01M28FVYHE11SFJAA9BXNZ4HRQ
func builtin run show run-01M28... --tree      # and everything it set off
func builtin run show run-01M28... --events    # and its event log
```

`--tree` nests the runs this run started — a workflow step, a dependency, an
`rc.invoke` child — instead of listing their ids. This is the relationship the
old history ring dropped and the run log keeps.

`--events` appends the run's events in **sequence order**. Ordered by `seq`
rather than by timestamp, so a replay is correct even across processes on
machines whose clocks disagree.

Exits `1` with a message on stderr when there is no such run.

## JSON

`--format json` returns the projection verbatim — the same rows the MCP tools
`list_runs`, `get_run` and `get_run_events` return. That is not a coincidence
and not a promise made in prose: both surfaces render one projection, and a
test asserts the CLI's JSON equals it.

```bash
func builtin run list --format json | jq '.runs[] | select(.duration_ms > 1000)'
```

## MCP

Verb for verb, for an agent rather than a terminal:

| CLI | MCP tool |
|---|---|
| `run list` | `list_runs` |
| `run show` | `get_run` (`tree=true` for the nested form) |
| `run show --events` | `get_run_events` |
