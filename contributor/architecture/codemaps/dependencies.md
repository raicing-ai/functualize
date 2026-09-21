# Dependency Graph

See `contributor/architecture/dependency-graph.md` for the authoritative, human-maintained version of the layer rules — this file adds the measured fan-in data and the CI/config wiring.

## Layer Dependency Flow

```
                    _types/         <- Shared vocabulary and vocabulary rules
                   /       \          no imports from another internal layer
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

Enforced in CI by `import-linter` (`uv run lint-imports`), seven contracts defined in `pyproject.toml` `[tool.importlinter]`:

1. "Peer layers are independent" — independence contract over `_discovery`, `_config`, `_engine`, `_plugins`, and `_gate`.
2. "Events depends on foundation only" — `_events` may depend on `_types` and `_primitives`, not a peer or composition/delivery layer.
3. "Primitives import nothing internal" — forbidden contract.
4. "Types import nothing internal" — forbidden contract.
5. "Internal never imports public" — forbidden contract (blocks `_app` etc. from importing `functualize.app`).
6. "`_cli` uses public API only" — forbidden contract (blocks `_cli` from importing any `_`-prefixed package).
7. "Delivery adapters go through the request, not the engine" — public adapters cannot import `_engine`.

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

### Proposed runtime-persistence layer (not shipped)

The runtime-persistence design adds `_persistence` as another independent peer:

```text
_types/ + _primitives/
          |
    _persistence/  <---- protocols and DTOs only across the engine boundary
          |
        _app/      <---- selects and binds one provider factory at boot
          |
       _engine/    <---- consumes semantic repositories/UoW, never SQL
```

The final dependency contract must add `_persistence` to peer independence and
allow it to import only `_types`, `_primitives`, `_events`, and the standard library. The
proposal is deliberately absent from `pyproject.toml` until the package exists;
claiming it as an enforced rule now would disguise a transitional state. See
[`runtime-persistence.md`](runtime-persistence.md) and the canonical
[`runtime-persistence` research package](../research/runtime-persistence/README.md).

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
├── jinja2>=3.1.0              # scaffold/config templating
└── cryptography>=42.0.0       # local secrets-vault encryption
# The interactivity contract (Surface/PromptCollector/prompt types, the stdin
# fallback) now lives IN core; functualize.ui (TextualApp/StdoutSurface) is in
# the [cli] extra below.

functualize[cli] (optional, needed for `func`/TUI)
├── click>=8.0.0                     # CLI framework (command/param construction)
├── rich>=13.0.0                     # terminal rendering
├── textual>=8.0                     # TUI framework
├── textual[syntax]>=8.0             # syntax highlighting for the TUI
└── textual-autocomplete>=4.0.0      # SmartBar autocomplete widget

functualize[all] = [cli] + first-party plugins except Bitwarden
# Bitwarden remains a workspace/dev dependency because its SDK has no musl
# wheel or sdist; see the declaration comment in pyproject.toml.
```

## Build & CI Wiring

- **Build backend**: `hatchling.build`; wheel packages `src/functualize`.
- **Workspace**: `[tool.uv.workspace] members = ["plugins/*"]` — all 12 plugins are workspace members with one `uv.lock`.
- **CI** (`.github/workflows/ci.yml`, triggers on push/PR to `master`): includes `spec-only-change`, lint, import contracts, mypy, fast tests, docs checks, full-test legs for Python 3.11/3.12/3.13, and the spec-artifact guard.
- **Security** (`security.yml`): gitleaks secret scan, on push/PR to `master` plus a weekly Monday 06:00 UTC cron.
- **Release** (`release.yml`, on tag `v*`): `build` → `publish` (PyPI Trusted Publishing/OIDC) → `github-release`.
- **Docs** (`docs.yml`, on push to `master`): `mkdocs build --strict` → `mkdocs gh-deploy`.
