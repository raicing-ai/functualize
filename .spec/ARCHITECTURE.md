# Architecture Details

Implementation-level architectural decisions extracted from pre-release ADRs.
For high-level rules and invariants, see `CONSTITUTION.md`.

## Runtime storage — five files, two discard rules

What a project keeps in `.functualize/`, and the rule that decides what happens
when each cannot be read. The rule is the architecture here: it is what says
whether a file may be silently discarded.

| file | holds | on unreadable |
|---|---|---|
| `fresh.json` | freshness verdicts (fingerprints) + the session precondition cache | **degrades to empty** |
| `scopes.json` | scope records: steps, branches, gate payloads, position, epilogue | **refuses**, file left in place |
| `scope-state/<id>.json` | one run's `rc.state` keys | **refuses**, file left in place |
| `runs.json` | the run log: every execution, its origin, parentage, outcome, and events | degrades to empty |
| `shell-history.json` | commands typed in the TUI's shell mode | degrades to empty |

**The asymmetry is the point.** Derived data is recomputable, so the worst case
of losing it is one extra run — correct for a cache. A *record* is recomputable
from nothing: a scope is the only trace of an in-flight run, and reading a
damaged one as empty would silently restart a workflow whose gate a human had
already approved. So records refuse, and the refusal never moves the file —
moving it would make the *next* run read "no scopes" and start over, which is
the failure the refusal exists to prevent.

### One upward walk

`fresh_format.resolve_fresh_location` walks up for a `.functualize/` directory
and returns `(path, mode, marker)`. Every other store derives its path from that
one answer rather than repeating the walk:

```
resolve_fresh_location(start) ──┬─→ fresh.json
                                ├─→ scopes.json          .with_name(...)
                                ├─→ scope-state/<id>.json
                                ├─→ runs.json
                                └─→ shell-history.json
```

Two walks can disagree about which project — or which of the two modes,
`project` vs `standalone` — they are in, and a reader must never reconstruct a
key the writer computed. The mode is *returned* rather than re-derived for the
same reason, and is reported by `func builtin data show`: a project could
otherwise spend its whole life in standalone mode and then go looking for a
`fresh.json` that was under a hashed cache directory.

### Locking

Per-file `.lock` sidecars via `fcntl.flock`, released on the fd rather than the
path so the lock survives the atomic replace of the file it guards. Every
read-modify-write **re-reads inside the lock**, so two runs touching different
records merge instead of clobbering: last-writer-wins per record, not per file.
A lock that cannot be taken within 10 s proceeds anyway and **logs a warning** —
degrading silently is what made a lost write invisible.

**Known limitation:** the scope lock and the state lock can be acquired in
either order by ordinary user code (a record write inside `state.batch()`, a
state write inside `store.batch()`), which is a lock-order inversion no store
can fix from the inside — the caller picks the order. Mitigated by taking the
record lock before the state lock on the common path and by the audible
timeout; removed properly only by one substrate with one lock.

### Bounds

Every store is capped, because an unbounded file is a cost that arrives on
someone else's machine:

| store | cap | eviction |
|---|---|---|
| `runs.json` | `RUNS_LIMIT = 500` runs, `EVENTS_PER_RUN_LIMIT = 200` events per run | oldest first, by ULID order |
| `scopes.json` | `SCOPES_LIMIT = 500` | oldest first, **terminal records only** |
| `shell-history.json` | 200 | oldest first |
| `fresh.json` | none needed — keyed by job, not by run | — |

The scope cap's restriction is load-bearing: a workflow parked at a gate must
survive any amount of unrelated traffic, so a file that is over the cap holding
nothing finished **stays over the cap**. An oversized file of live runs is
correct behaviour, not a defect to fix by deleting something resumable.

### Why a run's state is its own file

`rc.state` was a section of the scope record, which put a per-run value in a
per-project file: one `set` parsed and rewrote every scope record the project
had ever made — measured at 116× the cost of the same write on an empty store,
at 2,000 accumulated runs. A per-run value belongs in a per-run file. The second
effect was worth as much: one file meant one lock, so two jobs sharing nothing
serialised on every write.

### Projections, not second records

Two read models sit over these files, and neither store is read directly by a
surface:

- `app/_workflow_view.py` — scopes. *Where is this workflow, and what is it
  waiting for?*
- `app/_run_view.py` — runs. *What executed here, and how did it end?*

The CLI renders these and the MCP tools return them, so `--format json` and the
matching tool cannot answer differently. Both expose **derived** fields
(`state`, `duration_ms`, `children`) that are computed on read rather than
stored, so no format version moves when the vocabulary grows.

`func builtin history` is the clearest case: it is a *view* over the run log and
shell history, not a third record. It was a ring in `fresh.json` until the run
log existed, at which point that ring was a poorer copy of a subset.

**A scope and a run are different things.** A scope is a workflow's *position*
and exists to be resumed; a run is one *execution* and exists to be read
afterwards. A workflow that blocked and resumed three times is one scope and
four runs.

## The event log — a subscriber, never a publisher

`EventBus` emits and forgets, and keeps no file I/O. Persistence is a
`"*"` subscriber installed at boot (`_events/run_log.py`), which means:

- **subscribing is what turns the log on.** With nothing subscribed the bus
  returns before it builds an event object, so a bare engine costs nothing.
- **no write lands on the emit path.** Events are buffered in memory and
  flushed once, when the run that owns them ends.

An event is attributed to **the innermost run active on the emitting thread**,
tracked by a thread-local stack that `engine.run()` pushes and pops.

> **Thread-local, deliberately not a `ContextVar`.** `invoke_parallel` runs
> batch items on worker threads, and a `ContextVar` set in the parent is not
> inherited by a thread it did not create — the item would read an empty
> context. The stack works because the push happens *on* the worker, since
> `engine.run()` is what pushes. The same reasoning is why `RunContext._run_id`
> is carried rather than looked up.

Events emitted outside any run — boot, discovery, CLI parsing — are dropped.
They belong to the process, not to a run, and inventing a run for them would
make the log claim something false.

## Capability duality — two doors, one object

The Constitution states it as a rule: *the DI registry and `RunContext` resolve
from the same underlying capability map — two access paths, not competing
systems.* This is the mechanism (ADR-021).

Every per-invocation capability lives in one `caps` dict for the run. Both doors
**look it up there**; neither constructs:

```python
def j(rc: RunContext, state: State) -> None:
    assert rc.state is state          # the same object, not two that agree
```

Three properties make that true, and each was a real defect before it was a
rule:

1. **Lazy lookup, never construction.** An `rc` accessor that built its own
   instance would hand out a second one. `rc.state` reads `caps[State]` and only
   builds when there is no map at all.
2. **Resolved at call time, not at construction.** DI runs *before* the
   `RunContext` exists, so a capability that captured it eagerly captured
   `None`. Every `Invoke` hook reached through a `inv:` parameter received
   `None` as its parent while the identical hook through `rc.invoke` got the
   context.
3. **One implementation.** Where both doors had logic, one class absorbs the
   other rather than delegating — `PromptFacade` was merged into `Prompt`.

**Enforced by a registry-driven test, not by prose.** The rule was written in
the Constitution and in `contributor/guides/wiring-discipline.md` for the
project's whole life, and five of six capabilities violated it anyway.
`tests/integration/test_capability_duality.py` is parametrized over
`CAPABILITY_SPECS`, so a capability added tomorrow is covered the day its spec
is written, and one that legitimately cannot share declares
`shared_with_rc=False` where a reader can see it.

**Identity is not enough, and that gap has bitten.** The tripwire compares
objects; it cannot see a capability that is *inert*. The injected `Prompt` was
built by a factory that bound no collector, so every call raised while
`rc.prompts` answered normally — one door bricked, not two drifting. Wiring
needs a round-trip test that asserts the **answer**, through a collector that
records being called.

### Five classes that legitimately cannot share

Qualified providers (`rc[Conn, "replica"]` — there is no "the" `Conn`),
factory-scoped providers (a fresh instance per resolution *is* the contract),
exclusive resources (`TTY` — a second handle is a correctness bug, not a sharing
bug), pre-flight-bound capabilities (`Sources`, `Freshness` — incomplete when DI
runs), and app-scoped singletons the user registered.

A capability with **one** door is not an exemption but a non-case: it cannot
drift from itself, so the tripwire correctly skips it.

**The test for a real exemption:** can you state, in one sentence, what a user
gains from the two doors returning different objects? For those five the answer
is concrete. For `State` and `Prompt` it was never anything but "that is what
the code did".

## AdapterPlugin Protocol (Delivery Surfaces)

FunctualizeApp is a lean kernel (~300 LOC facade). All delivery concerns live in `AdapterPlugin` implementations.

```python
@runtime_checkable
class AdapterPlugin(Protocol):
    name: str
    version: str
    description: str
    adapter_type: str  # "cli", "http", "lambda", "mcp"

    def __call__(self, app: FunctualizeApp) -> None: ...  # setup
    def run(self, *args, **kwargs) -> Any: ...             # serve
    def shutdown(self) -> None: ...                         # cleanup
```

Design choices:
- Method is `run()` not `serve()` — more general (CLI "runs", Lambda "runs")
- The adapter owns async decisions internally (kernel stays synchronous)
- CLI is built-in (`[cli]` extras) because `func` needs it; HTTP/Lambda are separate plugin packages
- Capability plugins (e.g., `HttpServerPlugin`) register commands — adapters route them
- Multiple adapters can coexist (e.g., CLI adapter routes to HTTP plugin's `serve` command)
- `adapter_type` field enables introspection without isinstance checks
- Lifecycle: setup → boot → freeze → run → shutdown

## Presets as Factory Functions

Named configuration strategies are plain functions, not a class registry:

```python
def twelve_factor(*, dotenv: bool = False) -> ConfigSources:
    """CLI → Env → Defaults. No file discovery."""
    chain = ResolutionChain([CliSource({}), EnvSource(), DefaultSource({})])
    return ConfigSources(config_resolution_chain=chain, dotenv=dotenv)
```

Contract: any function with signature `(**kwargs) -> ConfigSources` is a valid preset.

- IDE autocompletion works (type the function name, see its kwargs)
- Type-safe: each factory exposes only relevant kwargs
- No registry lookup, no string-based selection, no `PresetNotFoundError`
- Custom presets from teams are just functions in their own modules
- Built-in presets: `classic()`, `twelve_factor()`, `env_only()`, `remote_first()`

## Monorepo Plugin Packaging

Official plugins are independently installable from PyPI, developed alongside core:

```
functualize/
├── src/functualize/          # Core (published as "functualize")
├── plugins/
│   ├── functualize-http/     # Published as "functualize-http"
│   ├── functualize-lambda/   # Published as "functualize-lambda"
│   ├── functualize-state-sqlite/
│   ├── functualize-inline/
│   ├── functualize-flow-viz/
│   └── functualize-fullscreen-tui/
├── pyproject.toml            # [tool.uv.workspace] members = ["plugins/*"]
└── uv.lock                   # Single lockfile for everything
```

Mechanics:
- Each plugin has its own `pyproject.toml` with `[project.entry-points."functualize.plugins"]`
- Entry-point auto-discovery: `pip install functualize-inline` just works — no user configuration
- `functualize[all]` meta-extra installs everything
- Single lockfile (`uv.lock`) via `[tool.uv.workspace]`
- Plugins depend on `functualize>=0.1.0` — version coupling is explicit
- Tests can cross plugin boundaries (integration testing in monorepo)
