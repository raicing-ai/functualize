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
                      [--scope SCOPE_ID] [--tag KEY:VALUE ...] [--limit N]
                      [--format table|json]
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

### Filtering by tag

A **run tag** is a `key:value` label attached to a run when it starts — which
harness launched it, which session, which bug it reproduces. `--tag` finds the
runs that carry it:

```bash
func builtin run list --tag repro:bug-412 --tag attempt:3
```

```
run-01M6316CWX94YJYNZZ5E0MG3WQ  nightly-build  success  func.job  16ms  attempt:3 repro:bug-412
```

- **Every `--tag` must match.** Two `--tag` options mean *and*: a run carrying
  only one of them is not listed.
- **Matching is exact and case-sensitive.** `--tag repro:Bug-412` does not match
  `repro:bug-412`; no match prints `No matching runs.` and exits `0`. A
  `--tag` that is not `key:value` is a usage error, exit `2`.
- **`--limit` still comes last**, after the tag filter, like every other filter.
- In the table, a run's tags come **last**, sorted by key and separated by
  spaces. An untagged run's line is exactly what it was before tags existed.
  `run show` prints them on a `run_tags:` line, `-` when there are none.

A run gets its tags from three places, merged per key, a later source winning:

1. `[run] tags = ["host:laptop"]` in your global config
   (`~/.config/functualize/config.toml`);
2. `FUNCTUALIZE_RUN_TAGS="harness:claude,model:opus"` in the environment —
   comma-separated, blank items skipped;
3. `--run-tag KEY:VALUE` before the job name, repeatable:
   `func --run-tag harness:claude nightly-build`. `builtin` commands start no
   run and refuse it: `Error: No such option '--run-tag'.`

A key given twice in one source is refused, naming that source; a malformed
tag stops the command with exit `2` before any job runs. A run started from
inside a job — a workflow step, a dependency, an `rc.invoke` child — carries an
exact copy of its parent's tags. Tags never reach the job itself: they are not
arguments, not part of the cache key, and not visible on `RunContext`.

> **Tags are stored in plain text — never put a secret in one.** They are
> written to the run log and shown by `run list`, `run show`, `--format json`
> and the MCP tools.

A run's tags are not its job's declared `@job(tags=[...])`: those describe the
job and are reported by `func builtin info jobs`; `--tag` never matches them.

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

Every row carries `run_tags`, the run's tags as an object — `{}` for a run with
none, including runs recorded before tags existed:

```bash
func builtin run list --format json | jq '.runs[] | select(.run_tags.harness == "claude")'
```

## MCP

Verb for verb, for an agent rather than a terminal:

| CLI | MCP tool |
|---|---|
| `run list` | `list_runs` |
| `run show` | `get_run` (`tree=true` for the nested form) |
| `run show --events` | `get_run_events` |

Each run the tools return carries `run_tags`, because they return the same
projection. They take no tag input: `list_runs` has no tag filter.
