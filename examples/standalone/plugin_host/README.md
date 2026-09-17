# Plugin Host — annotating a plugin against the port

A plugin is handed the application at boot. The question this example answers is
what it should *call that thing* in its own signature.

```
plugin_host/
├── annotated_plugin.py       # BudgetPlugin — `def __call__(self, app: PluginHost)`
└── tests/
    └── test_annotated_plugin.py
```

## The problem, measured

Before `PluginHost` existed, **40 of the 44 `app` parameters** across the twelve
shipped plugins were annotated `Any`. Under `Any` every attribute access
type-checks, whether or not the member exists — and three of them did not:

| Plugin | Reached for | `hasattr` on a real app |
|---|---|---|
| `functualize-ai-pydantic` | `app._di_registry.resolve(...)` | the registry is private; the guarding import was of a retired package |
| `functualize-mcp` | `app.resolve(...)`, `app._tasks` | **False**, both |
| `functualize-ai` | `app.resolve_model(...)` | **False** — it lives on `app.configuration` |

Each sat inside a `try/except Exception`, so nothing failed at runtime either.
The first two were permanently dead code; the third means the `[ai]` config
section has never been read through `resolve_ai_provider`.

That is the shape `Any` produces: a reach that is wrong, silent, and invisible
to every test you could write.

## The answer

```python
from functualize.plugin import PluginHost

def __call__(self, app: PluginHost) -> None:
    app.di.provide(JobBudget, self._budget)
    app.extensions.register_plugin_command("budget", self._report_command)
    app.hooks.on_ready(self._on_app_ready)
```

`PluginHost` is the **eleven members a plugin is meant to use** — the five
facades as narrow views, plus `get_jobs`, `get_job`, `execute`, `substrate`,
`install_substrate` and `fresh_root`. Every one of them earned its place with a
measured client count across `plugins/*/*/src`.

Annotate with it and each of the six lines below is a `mypy --strict` error at
the line you wrote, instead of an `AttributeError` in someone else's release:

```python
app._di_registry.resolve(JobBudget)   # the private reach, shipped twice
app.resolve(JobBudget)                # the `hasattr` probe, as a call
app.hook_registry.invoke_start(...)   # firing lifecycle events is not yours
app.execution_engine.materialize_job  # one client; not worth the seat
app.dii.provide(JobBudget, budget)    # a typo in a facade name
app.di.provdie(JobBudget, budget)     # a typo one level down, inside a view
```

## Registration, then readiness

`__call__` **registers and reads nothing**. `on_ready` is where the project is
readable, because by then every plugin has loaded, jobs are discoverable and
storage is decided:

```python
def _on_app_ready(self, app: PluginHost) -> None:
    state = app.extensions.extension_state.setdefault("budget", {})
    state["jobs_at_boot"] = len(app.get_jobs())
```

`app.hooks.on_ready` is typed `Callable[[OnReadyHandler], OnReadyHandler]`, so a
handler with the wrong arity, a non-callable, or one that returns a value — the
return is discarded — fails at the registration line. It is also the only
lifecycle member on the port: registering is a plugin's business, firing is not.

## What a plugin cannot do, and why that is right

`app.di` is **write-only** — `provide`, `provide_factory`, `provide_named`, no
reader. That asymmetry is what drove two plugins into `app._di_registry`, so
`di.resolve` was considered for this port and **dropped**: both reaches were
dead, leaving zero surviving callers, and a port lists what is needed.

The consumer is a *job*, through `RunContext`:

```python
def spend(rc: RunContext, amount: int = 3) -> str:
    budget = rc[JobBudget]
    return "charged" if budget.charge(amount) else "refused"
```

`tests/test_annotated_plugin.py` drives exactly that — a real `FunctualizeApp`,
the plugin handed to it through `PluginSources(explicit_plugins=[...])`, and the
job run with `app.execute(...)`. Not a mock: a mock answers every attribute, so
it would pass whether the port existed or not.

## Run it

```console
$ uv run pytest examples/standalone/plugin_host -q
8 passed

$ uv run mypy --strict examples/standalone/plugin_host/annotated_plugin.py
Success: no issues found in 1 source file
```

## See also

- `contributor/guides/plugin-development.md` — writing a plugin
- `contributor/architecture/dependency-graph.md` → *The Two Ports in `_types/`* —
  why `PluginHost` lives where it does, and its peer `EngineHost`
- `tests/spec/test_the_plugin_host_cannot_be_bypassed.py` — the six refusals
  above, asserted
- `contributor/reference/public-api-example-coverage.md` — why this example is
  required rather than nice to have
