# Dependency Graph

See `contributor/architecture/dependency-graph.md` for the authoritative, human-maintained version of the layer rules — this file adds the measured fan-in data and the CI/config wiring.

## Layer Dependency Flow

```
                    _types/         <- Shared vocabulary (everyone imports)
                   /       \          NO LOGIC -- only dataclasses, enums, protocols
          _primitives/   _events/   <- Foundation + cross-cutting concern
               |            |
         +-----+------------+----------+
         |     |            |          |
   _discovery/ _config/  _engine/ _plugins/   <- PEER LAYERS (never import each other at runtime)
         |     |            |          |
         +-----+------------+----------+
                     |
                   _gate/           <- Gate resolution (composed into FunctualizeApp)
                     |
                   _app/            <- COMPOSITION ROOT (imports all, wires together)
                     |
                   _cli/            <- DELIVERY (public API only -- no `_` imports)
```

Enforced in CI by `import-linter` (`uv run lint-imports`), five contracts defined in `pyproject.toml` `[tool.importlinter]`:

1. "Peer layers are independent" — independence contract over `_discovery`, `_config`, `_engine`, `_plugins`.
2. "Primitives import nothing internal" — forbidden contract.
3. "Types import nothing internal" — forbidden contract.
4. "Internal never imports public" — forbidden contract (blocks `_app` etc. from importing `functualize.app`).
5. "`_cli` uses public API only" — forbidden contract (blocks `_cli` from importing any `_`-prefixed package).

`exclude_type_checking_imports = true` — imports inside `if TYPE_CHECKING:` blocks are not evaluated by the contracts.

**Verified compliant**: a grep across `_discovery/`, `_config/`, `_engine/`, `_plugins/` found exactly one cross-peer reference — `_engine/capabilities/runcontext.py:31` imports `functualize._config.job_config.JobConfigView`, but it's inside `TYPE_CHECKING` and therefore excluded by contract 1. No runtime peer-layer violation exists.

## Highest Fan-In Modules (measured)

Ranked by raw import-statement count across `src/functualize/**/*.py`:

| Rank | Module | Importers | Why it's a hub |
|---|---|---|---|
| 1 | `functualize._app.impl` | 30 | Internal `FunctualizeApp` implementation — the composition root's core |
| 2 | `functualize._types.descriptors` | 21 | `JobDescriptor` and friends — shared vocabulary used everywhere |
| 3 | `functualize._events.hooks` | 19 | `HookRegistry` — lifecycle interception used by every layer that fires hooks |
| 4 | `functualize.app` (public facade) | 17 | Re-export surface for `app/` symbols |
| 5 | `functualize._engine.capabilities.runcontext` | 15 | Concrete `RunContext` capability wiring |
| 5 | `functualize.app.core` | 15 | `FunctualizeApp` public class definition |
| 6 | `functualize._config.job_config` | 13 | `JobConfigView` — scoped config access |
| 6 | `functualize._app.decorators` | 13 | Boot-time decorator wiring |
| 6 | `functualize.app.config` | 13 | `JobSources`/`ConfigSources`/`PluginSources`/`ExecutionConfig` dataclasses |
| 7 | `functualize.app.utils` | 12 | `coerce_kwargs`, `import_job`, `auto_discover` |
| 8 | `functualize._types` | 10 | Package-level re-export |
| 8 | `functualize.job` | 10 | Public job-author facade |
| 8 | `functualize._config.errors` | 10 | Config resolution error types |
| 8 | `functualize._cli.tui.panels.config_table` | 10 | TUI panel — unusually high fan-in for a leaf UI widget, worth watching |
| 8 | `functualize._cli.data.pending_execution` | 10 | Shared pending-execution state for the TUI |

**Highest-risk hubs** (change with extra care, keep tests green): `_app.impl`, `_types.descriptors`, and `_events.hooks` sit at the composition root and shared-vocabulary layers — a breaking change there ripples through the entire codebase.

## Cross-Layer Communication Pattern

Peer layers never import each other directly. When Layer A (peer) needs something from Layer B (peer):

1. Define a `Protocol` in `_types/protocols.py`.
2. Layer B implements it (often structurally, with no explicit inheritance).
3. `_app/boot.py` wires the concrete B instance into A via constructor injection.

Example already in the codebase: `_engine/executor.py`'s `JobExecutionEngine` depends on a `JobLookup`-shaped protocol; `_app/boot.py` passes the concrete `_discovery.pipeline.ResolutionPipeline` in.

## CLI/Textual Dependency Isolation

The CLI is **click-native**; `typer` and `trogon` are no longer dependencies.
Runtime `click`/`textual`/`rich` imports live in the delivery layer:

1. `app/adapters/click_params.py` — schema → `click.Parameter` builder
2. `app/adapters/cli.py` — `CliAdapter` → `click.Group`
3. `app/adapters/lazy_command.py` — warm-boot command reconstruction from cached metadata
4. `_cli/main.py` — the `func` entry point
5. `_cli/scaffold/cli.py` — scaffold sub-command
6. `_cli/tui/**` — the full-screen TUI subsystem itself

Kernel packages have zero runtime `textual`/`rich`/`jinja2` imports (and no
`typer`, which is gone); `click` is exempt and may be used directly by a kernel
module (`_config/cli_adapter.py`). `import functualize.app` / `functualize.job`
never pulls in any CLI dependency. This keeps Lambda/HTTP deployments lean — the
`[cli]` extras group in `pyproject.toml` holds all optional CLI/TUI deps.

## External Dependency Graph

```
functualize (core)
├── pydantic>=2.0.0            # config/descriptor validation
├── python-dotenv>=1.0.0       # .env loading
└── jinja2>=3.1.0              # scaffold/config templating
# The interactivity contract (Surface/PromptCollector/prompt types, the stdin
# fallback) now lives IN core; functualize.ui (TextualApp/StdoutSurface) is in
# the [cli] extra below.

functualize[cli] (optional, needed for `func`/TUI)
├── click>=8.0.0                     # CLI framework (command/param construction)
├── rich>=13.0.0                     # terminal rendering
├── textual>=8.0                     # TUI framework
├── textual[syntax]>=8.0             # syntax highlighting for the TUI
└── textual-autocomplete>=4.0.0      # SmartBar autocomplete widget

functualize[all] = [cli] + 13 workspace plugins (see modules.md)
```

## Build & CI Wiring

- **Build backend**: `hatchling.build`; wheel packages `src/functualize`.
- **Workspace**: `[tool.uv.workspace] members = ["plugins/*"]` — all 13 plugins auto-included, single `uv.lock`.
- **CI** (`.github/workflows/ci.yml`, triggers on `push`/`pull_request`): `lint` → `lint-imports` → `typecheck` (mypy) → `test-fast` → `test-full` (matrix, Python 3.11/3.12/3.13).
- **Security** (`security.yml`): gitleaks secret scan, on push/PR to `main` plus a weekly Monday 06:00 UTC cron.
- **Release** (`release.yml`, on tag `v*`): `build` → `publish` (PyPI Trusted Publishing/OIDC) → `github-release`.
- **Docs** (`docs.yml`, on push to `main`): `mkdocs build --strict` → `mkdocs gh-deploy`.
