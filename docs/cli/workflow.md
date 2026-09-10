# Workflow Commands

The `func builtin workflow` (or `functualize builtin workflow`) sub-command
inspects, answers and **advances** persisted workflow scopes — the paused state
a `@workflow` leaves behind when it blocks at a gate awaiting input.

> **Note:** `func` and `functualize` are aliases for the same CLI. All examples
> below use `func` but `functualize` works identically.

## Two verbs, one meaning each

> **`answer` records. `resume` advances.**

`answer` fills a gate's input slot and runs nothing. `resume` walks the graph to
its next stopping point, in this process. There are no aliases for either.

This matters because it used to be untrue: every verb called *resume* on every
surface was a deposit, and nothing anywhere could continue a blocked walk except
re-invoking the job from a shell — which an agent driving the workflow over MCP
cannot do.

## The three tiers

| Tier | Surface | For |
|---|---|---|
| **1 — rich** | `func builtin workflow …` | anyone operating **any** run: a second actor, an operator, CI, a scheduler |
| **2 — parity** | MCP tools | an agent doing the same |
| **3 — convenience** | [`--wf-*` flags](#the-wf-flags) on the job itself | the invoker about to run **this** workflow |

Tier 1 is the superset; tier 2 matches it verb for verb, held by a parity test.
Tier 3 is a strict subset — every one of its flags exists here too.

## `func builtin workflow`

```
func builtin workflow COMMAND [ARGS]...
```

| Command | What it does |
|---------|--------------|
| `list` | Survey scopes, with filters |
| `show <id>` | One scope in full — graph, results, gates |
| `answer <id> <gate>` | Record input for a gate — partial, whole, or corrected |
| `resume <id>` | **Advance** the walk, optionally answering a gate first |
| `gate-tool <id> <tool>` | Run a tool a waiting gate offers |
| `cancel <id>` | Cancel a scope — terminal |
| `purge` | Delete finished scopes |

## Run states

`status` is what the walk last did. `state` is **derived** from it and from the
gates, and it is what you filter on:

| State | Means |
|---|---|
| `waiting` | blocked, with a gate needing an answer |
| `ready` | answered — needs `resume` |
| `running` | executing now |
| `completed` | done |
| `stalled` | the walk finished but the workflow body failed |
| `failed` | a step raised; `resume` re-runs it |
| `cancelled` | terminal — `resume` refuses |

`ready` is exactly the set `resume` can advance without input, which is what a
scheduler polls for. Without it, an answered scope read `blocked` with no
pending gates and looked stuck.

## `func builtin workflow list`

```
func builtin workflow list [--workflow NAME] [--state STATE] [--blocked-on GATE]
                           [--format table|json]
```

With no filters, lists the runs still running or blocked. **Naming `--state`
widens the search to finished runs**, because asking for `completed` and getting
nothing would be a silently empty answer to a well-formed question.

```bash
func builtin workflow list
# rel-1  release  waiting  gates: approval

func builtin workflow list --state ready          # answered, needs advancing
func builtin workflow list --blocked-on approval  # everything waiting at one gate
func builtin workflow list --format json          # the same rows MCP returns
```

`--format` is **domain-aware**: the command knows its items are workflow scopes,
so `json` emits structured scope objects rather than a serialized log line. This
is distinct from the global `--emit-format`, which only formats the dispatch layer's
return value.

## `func builtin workflow show`

```
func builtin workflow show <workflow_id> [--format table|json]
```

The declared graph, the walk position, every recorded branch choice, each step's
return value and resolved inputs, and every pending gate's schema and offered
tools.

`--format json` returns **exactly** what the MCP `get_workflow_state` tool
returns — asserted byte-identical by a test, not merely intended. This replaces
`state`, which emitted five fields over records that had held all of the above
all along.

## `func builtin workflow answer`

```
func builtin workflow answer <workflow_id> <gate> [OPTIONS]
```

| Option | Meaning |
|---|---|
| `--input JSON` | Merge a whole object into the draft |
| `--set KEY=VALUE` | Merge one field (repeatable). Values are JSON-typed; a bare word stays a string |
| `--unset KEY` | Remove a field from the draft (repeatable) |
| `--clear` | Discard the draft |
| `--replace` | With `--input`: replace the draft rather than merging |
| `--show` | Print the draft and what is still missing; change nothing |
| `--commit` / `--no-commit` | Validate and answer when complete (default: on) |
| `--reopen` | Move an already-recorded answer back into the draft to correct it |

**Auto-commit is the default**, so the one-shot flow is one command:

```bash
func builtin workflow answer rel-1 approval \
  --input '{"environment": "prod", "replicas": 3}'
```

Input accumulates in a **draft** until it validates whole, so two actors can
fill different fields of the same gate and neither has to hold the whole answer:

```bash
func builtin workflow answer rel-1 approval --set environment=prod
# Draft saved for 'approval'. Still missing: replicas (int).

func builtin workflow answer rel-1 approval --set replicas=3
# Gate 'approval' answered.
```

The gate stays blocked until the draft is complete and valid — the walk never
reads a draft, only a committed answer.

`--reopen` is refused once the walk has passed the gate: the answer produced the
results recorded after it, so correcting it in place would leave those results
downstream of an input that no longer exists.

## `func builtin workflow resume`

```
func builtin workflow resume <workflow_id> [--input '<json>'] [--gate NAME]
                             [--retry-epilogue] [--format table|json]
```

Advances the walk **in this process**. With `--input`, it answers a gate first,
through the same validation `answer` uses.

```bash
func builtin workflow resume rel-1 --input '{"environment": "prod", "replicas": 3}'
```

**The exit code is the walk's**, so a run that is still blocked exits 5 and a
completed one exits 0. A script resuming in a loop can act on that.

`--retry-epilogue` clears a stalled epilogue so the workflow body runs again.
It exists because the epilogue record is the one thing sticky on failure: a walk
that reached the end and whose body then failed is `stalled` and would never run
again. Failed *steps* need no equivalent — they already re-run on resume.

## `func builtin workflow gate-tool`

```
func builtin workflow gate-tool <workflow_id> <tool> [--args '<json>']
```

Runs a job a waiting gate offers, inside that gate's scope. Arguments the gate
fixes cannot be supplied — a bound argument is refused, never silently
overridden. The call is recorded on the scope but never memoized: calling twice
runs twice.

## `func builtin workflow cancel`

```
func builtin workflow cancel <workflow_id>
```

Terminal. A cancelled scope refuses to resume — the engine enforces it, so the
refusal holds on every surface rather than only where a tool remembered to check.

## `func builtin workflow purge`

```
func builtin workflow purge [--state STATE] [--older-than DAYS]
```

Deletes finished scopes. **Never touches a running, waiting or ready one**, and
`--state` cannot name a live state at all: this is a hard delete with no backup,
unlike `func builtin state clear --scopes`, which moves the whole scope file
aside.

`--older-than` measures the newest recorded result in the scope. A scope with no
timestamps is never matched — it cannot be aged, and treating it as infinitely
old would delete exactly the records whose history is least known.

## The `--wf-*` flags

A job that declares a `@workflow` carries seven flags of its own. They are a
convenience subset for the invoker who already knows *which workflow* — every
one has a fuller spelling above.

```
--wf-resume [ID]     Advance a scope of this workflow (the only advanceable one
                     if ID is omitted). Walks in this process.
--wf-input JSON      Gate input for --wf-resume: recorded, then the walk advances.
--wf-gate NAME       Which pending gate --wf-input answers, when there are several.
--wf-status          List this workflow's scopes, then exit 0.
--wf-show [ID]       Full projection of one scope, then exit 0.
--wf-retry-epilogue  With --wf-resume: clear a stalled epilogue and re-fire it.
--wf-run-id ID       Start under a caller-chosen scope id (idempotent start).
```

```bash
func release                      # blocks at the gate, exit 5
func release --wf-status          # rel-1  waiting  gates: approval
func release --wf-resume --wf-input '{"environment":"prod","replicas":3}'
```

**They are post-command options**, on the job, and a plain `@job` carries none
of them.

**Ambiguity never guesses.** Omitting the id works when exactly one scope of
this workflow can be advanced; with several it lists them and exits 2, and with
none it points at `--wf-status`. Never "newest wins" — a gate's `blocked_at`
resets every time it re-blocks, so recency is not computable.

`--wf-resume` requires the scope to **already exist**; an unknown id is an error
and creates nothing. Starting a run under an id you choose is `--wf-run-id`,
which is idempotent — running it twice resumes rather than restarting.

### Replacing `--scope-id`

`--scope-id` is **removed**, in both its pre-command and per-command spellings.

|  | `--scope-id X` | `--wf-resume [X]` |
|---|---|---|
| Advance a named scope | yes | yes |
| Omit the id when unambiguous | no | **yes** |
| Answer a gate in the same command | no | **yes** (`--wf-input`) |
| Unknown id | **silently started a new run under it** | **errors** |

That fourth row was a defect: `WorkflowRunner` does `scope_id or
new_scope_id()` and the walk creates the scope, so a typo'd id became a blocked
run under the typo — one the caller could not find, while the real run stayed
blocked. Splitting *start under an id* from *advance an id* fixes it.

An embedded host can still set `app._workflow_scope_id` programmatically. That
seam is deliberately kept and has no CLI spelling.

## See also

- [Workflows Guide](../guides/workflows.md) — declaring `@workflow` graphs and gates
- [MCP Guide](../guides/mcp.md) — the same verbs, for agents
