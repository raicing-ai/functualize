# Dependency Graph & Layer Rules

## The Strict Dependency Flow

```
                    _types/         ← Shared vocabulary (everyone imports)
                   /       \          NO LOGIC — only dataclasses, enums, protocols
          _primitives/   _events/   ← Foundation + cross-cutting concern
               |            |
         +-----+-----+-----+-----+----------+
         |     |     |     |     |          |
   _discovery/ _config/ _gate/ _engine/ _plugins/   ← PEER LAYERS (never import each other)
         |     |     |     |     |          |
         +-----+-----+-----+-----+----------+
                     |
                   _app/            ← COMPOSITION ROOT (imports all, wires together)
                     |
                   _cli/            ← DELIVERY (public API only — no _ imports)
```

## The Two Ports in `_types/`

`_types/` holds two host ports, and they are peers with different audiences.
Both exist so a dependent can name what it is handed without importing the
application.

| Port | File | Audience | Members |
|---|---|---|---|
| `EngineHost` | `_types/protocols.py` | the execution engine, inside this repo | job lookup, config/gate resolution, `fresh_root`, `substrate_override`, … |
| `PluginHost` | `_types/host.py` | **plugin authors, outside this repo** — reached as `functualize.plugin.PluginHost` | 11: the five facades as views, `get_jobs`/`get_job`, `execute`, `substrate`/`install_substrate`/`fresh_root` |

`_types/host.py` is its own module rather than another class in
`protocols.py`, which is 910 lines and fourteen protocols. It also carries the
five **view** protocols (`DependencyView`, `ExtensionsView`,
`ConfigurationView`, `GatesView`, `HooksView`): the concrete facades live in
`_app/`, which `_types/` may not name, so a view describes the part of one
facade that plugins call from the layer allowed to describe it.

**The `TYPE_CHECKING` escape is refused here, not merely unavailable.**
`exclude_type_checking_imports = true` means a deferred `_types → _app` import
passes `lint-imports` **with "7 kept, 0 broken"** — measured, by adding one.
`layer-contract-blind-spot.md` §7 forbids it in terms, and
`tests/types/test_plugin_host_port.py` reads the module's import lines to hold
the line where `lint-imports` cannot.

## The Lifecycle Vocabulary in `_types/`, and Its One Check

Three modules arrived with the runtime schema work, and they follow the same rule
as the ports above: `_types/` holds the words, one layer down holds the one thing
that can refuse.

| Module | Layer | What it holds |
|---|---|---|
| `_types/lifecycle.py` | `_types/` (stdlib only, no logic) | the four runtime machines as data — `SCOPE`, `RUN`, `ATTEMPT`, `INPUT_REQUEST`, each a frozen `Machine` carrying a closed state set, its legal `(current, target)` pairs, and its `absorbing` / `evictable` sets. The run machine adopts `RunStatus` from `_types/enums.py` rather than redefining it; the scope, attempt and input vocabularies are `StrEnum`s whose member *is* the text stored on disk |
| `_types/retention.py` | `_types/` (stdlib only, no logic) | `RetentionPolicy` — `max_records`, `evictable_only`, `max_age` — and `DEFAULT_RETENTION`. The three `500` caps that used to be spelled in `_primitives/scope_format.py` and `_primitives/run_format.py` read it |
| `_primitives/transitions.py` | `_primitives/` | `require_transition(machine, current, target)` — one membership test, no state of its own. It reads a `Machine` and raises `IllegalTransition` (`_types/errors.py`) |

**Why the check is not in `_types/`.** ADR-026 and `_types/__init__.py` say the
vocabulary layer holds no logic, and a `Machine` that could answer "is this
legal?" would be a second place to change a rule whose whole point is that it is
spelled once. A refusal is allowed to exist in `_primitives/`, so it lives there —
and the *meaning* stays in the tables, which the store reads without ever learning
why a move is legal (ADR-025).

Nothing above adds a layer, a peer edge, or a row to the matrix below: `_types/`
still imports stdlib only, `_primitives/` still imports `_types/` and stdlib, and
the two writers that call the check — `ScopeStore.set_scope_status`,
`RunStore.close_run` — are in `_primitives/`, where the tables were already being
written. `tests/types/test_lifecycle_tables.py` and
`tests/primitives/test_transitions.py` hold the two lines `lint-imports` cannot: a
table naming a state its vocabulary does not have, and a check whose verdict
differs from the table it reads.

## Allowed Imports Matrix

| Layer | May Import From | Must NOT Import From |
|-------|----------------|---------------------|
| `_types/` | stdlib only | Any `_`-prefixed or public package |
| `_primitives/` | `_types/`, stdlib | `_events`, `_discovery`, `_config`, `_engine`, `_plugins`, `_app`, `_cli` |
| `_events/` | `_types/`, `_primitives/` | `_discovery`, `_config`, `_engine`, `_plugins`, `_app`, `_cli` |
| `_discovery/` | `_types/`, `_primitives/`, `_events/` | `_config`, `_gate`, `_engine`, `_plugins`, `_app`, `_cli` |
| `_config/` | `_types/`, `_primitives/`, `_events/` | `_discovery`, `_gate`, `_engine`, `_plugins`, `_app`, `_cli` |
| `_gate/` | `_types/`, `_primitives/`, `_events/` | `_discovery`, `_config`, `_engine`, `_plugins`, `_app`, `_cli` |
| `_engine/` | `_types/`, `_primitives/`, `_events/` | `_discovery`, `_config`, `_gate`, `_plugins`, `_app`, `_cli` |
| `_plugins/` | `_types/`, `_primitives/`, `_events/` | `_discovery`, `_config`, `_gate`, `_engine`, `_app`, `_cli` |
| `_app/` | ALL internal layers | `_cli`, public folders |
| `_cli/` | Public folders only (`app/`, `job/`, `plugin/`, `types/`, `testing/`, `ui/`, `workflow/`) | ANY `_`-prefixed package |
| Internal layers (all) | — | Public folders (`app/`, `job/`, `plugin/`, `types/`, `testing/`, `ui/`, `workflow/`) |

## import-linter Enforcement

These rules are enforced by `import-linter` in CI. Run locally:

```bash
uv run lint-imports
```

The contracts are defined in `pyproject.toml` under `[tool.importlinter]`:

1. **"Peer layers are independent"** — independence contract between `_discovery`, `_config`, `_gate`, `_engine`, `_plugins`
2. **"Primitives import nothing internal"** — forbidden contract
3. **"Types import nothing internal"** — forbidden contract
4. **"Internal never imports public"** — forbidden contract preventing `_app` etc from importing `functualize.app`
5. **"_cli uses public API only"** — forbidden contract preventing `_cli` from importing any `_`-prefixed package

## Why This Structure?

**Problem it solves**: Without these rules, changes cascade unpredictably. Editing `_config/` could break `_discovery/` which could break `_engine/`. With peer independence, each layer is a self-contained unit that can be modified without fear of cascading.

**How peer layers communicate**: They don't talk to each other directly. `_app/` (the composition root) imports from all peer layers and wires them together via dependency injection. If `_engine/` needs config resolution, `_app/` passes the resolved config as a parameter — `_engine/` never imports `_config/`.

**Why `_cli/` uses public API only**: This is the "dogfooding" constraint. If the framework's own CLI can't be built using the public API, then external tools (GUIs, CI runners, web dashboards) can't either. Any functionality `_cli/` needs that requires internal access → add it to the public API instead.

## CLI Dependency Isolation

The CLI is **click-native**; Typer and Trogon are no longer dependencies.
Isolation (enforced by `tests/test_typer_isolation.py`) has two rules:

- **Public boundary**: `import functualize.app` / `functualize.job` pull in
  none of `typer`, `click`, `rich`, `textual`.
- **Kernel packages** (`_types/`, `_primitives/`, `_events/`, `_discovery/`,
  `_config/`, `_engine/`, `_plugins/`, `_app/`) have ZERO runtime imports of
  `textual`, `rich`, or `jinja2`. `click` is exempt — a kernel module may use
  it directly (`_config/cli_adapter.py` reads a `click.Context`); it still
  stays off the public boundary above.

Command trees are built in the delivery layer (`app/adapters/click_params.py`,
`cli.py`, `lazy_command.py`, `_cli/main.py`, `_cli/scaffold/cli.py`). This means:
- Lambda deployments don't pull in CLI dependencies
- `import functualize.app` and `import functualize.job` never trigger a CLI import
- The `[cli]` extras group in pyproject.toml contains all optional CLI deps

## Adding a New Dependency Between Layers

If you need Layer A to know about something in Layer B (where A and B are peers):

1. **Don't import B from A** — the import-linter will catch this
2. **Define the interface in `_types/`** — add a Protocol or dataclass
3. **Have `_app/` wire them together** — pass the concrete from B to A via constructor or method call

Example: `_engine/` needs to look up job metadata at execution time.

```python
# _types/protocols.py — the shared interface
class JobLookup(Protocol):
    def get_job(self, name: str) -> JobDescriptor | None: ...

# _engine/executor.py — depends only on the protocol
class JobExecutionEngine:
    def __init__(self, job_lookup: JobLookup, ...): ...

# _app/boot.py — wires the concrete implementation
from functualize._discovery.pipeline import ResolutionPipeline
from functualize._engine.executor import JobExecutionEngine

pipeline = ResolutionPipeline(providers)  # satisfies JobLookup protocol
engine = JobExecutionEngine(job_lookup=pipeline, ...)
```
