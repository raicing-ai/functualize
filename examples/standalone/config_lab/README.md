# Config Lab — the precedence chain, layer by layer

One directory that walks the full settings resolution chain:

```
CLI flags  >  FUNCTUALIZE_* env vars  >  pyproject.toml  >  global config.toml  >  defaults
```

The trick: two job files, `jobs/job_deploy.py` and `jobs/task_build.py`, and a
`require_file_prefix` filter set differently at different layers. **Which job
appears in the listing tells you which layer won.**

```bash
cd examples/standalone/config_lab
```

The lab ships a *simulated* global config at `xdg/functualize/config.toml`.
Pointing `XDG_CONFIG_HOME` at `./xdg` activates it without touching your real
`~/.config/functualize/config.toml`.

> **Cache note:** the discovery cache persists the last scan and does not yet
> fingerprint the filter configuration. **Run `func builtin cache clear` between the
> steps below**, or the listing will show stale results.

## Step-by-step verification

| # | Run | Expect | Which layer won |
|---|-----|--------|-----------------|
| 1 | `func` | `deploy` listed, `build` absent | Project (`pyproject.toml`: prefix `job_`) |
| 2 | `XDG_CONFIG_HOME=$PWD/xdg func` | Still only `deploy` | Project **beats** global (global says `task_`) |
| 3 | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX=task_ func` | Only `build` | Env **beats** project |
| 4 | `func --require-file-prefix task_` | Only `build` | CLI **beats** project |
| 5 | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX=job_ func --require-file-prefix task_` | Only `build` | CLI **beats** env |

### Global-layer settings the project doesn't define

With the simulated global config active, settings unset at the project layer
fall through to the global file:

```bash
XDG_CONFIG_HOME=$PWD/xdg func builtin config show   # inspect the resolved chain
XDG_CONFIG_HOME=$PWD/xdg func d             # [aliases] d = "deploy" → runs deploy
```

- [ ] `config show` lists `output = "plain"`, `show_timing = true`, and both
  aliases with `# source: global` (drop `XDG_CONFIG_HOME` and they revert to
  defaults)
- [ ] `func d` resolves the alias and prints `Deployed to staging`

### Close the loop

```bash
func deploy --target production                      # → Deployed to production
FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX=task_ func build --release   # → Built (release)
```

## Where each layer lives

| Layer | This lab | Real projects |
|-------|----------|---------------|
| CLI flags | `--require-file-prefix …` | same |
| Env vars | `FUNCTUALIZE_DISCOVERY_REQUIRE_FILE_PREFIX` | same — `FUNCTUALIZE_<SECTION>_<KEY>` |
| Project | `pyproject.toml [tool.functualize]` | or `.functualize.toml` (see [`../showcase/`](../showcase/) — used only when pyproject has no `[tool.functualize]`) |
| Global | `xdg/functualize/config.toml` via `XDG_CONFIG_HOME` | `~/.config/functualize/config.toml` |
| Defaults | Pydantic/`DiscoveryConfig` defaults | same |

## Tests

```bash
uv run pytest examples/standalone/config_lab/ -v
```

## Related documentation

- [Configuration](../../../docs/cli/config.md) — the authoritative precedence reference
- [Global Config Directory](../../../docs/cli/global-config-directory.md)
- Job-value resolution (per-field source chain in the TUI) is demonstrated in [`../showcase/`](../showcase/) §2.4
