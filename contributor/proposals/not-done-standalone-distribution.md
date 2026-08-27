# Standalone Distribution & Self-Management

**Status: proposed**

> Consolidated on 2026-07-16 from the former Plan 008 family (008 Parts 1/2/7/10/11, 008a).
> Revised 2026-07-18 after adversarial scrutiny
> (`.spec/scrutiny-reports/standalone-distribution-2026-07-18.md`) — fixed the PyApp `self`
> collision, the runtime-detection ladder, plugin persistence, and the embedding decision.
> Current state: none of this exists — no runtime detection, no `func self` commands, no
> install manifest, no standalone binary; plugin discovery works via entry points but has no
> user-facing management commands. The `func self`/`func plugin` builtin groups should be
> built on the implemented `BuiltinCommand` registry (`_cli/builtins.py`) and reuse the
> landed `_dispatch_group` seam (`_cli/main.py:774`).
>
> Sequencing: [remove-typer.md](./not-done-remove-typer.md) plans to delete the ad-hoc-Typer seam. If
> it lands first, author `self_cmd`/`plugin_cmd` click-native from the start rather than
> porting them later.
>
> Related: [persistent-process.md](./not-done-persistent-process.md) (`func self daemon *`
> subcommands — **contingent**: that document is the "maximal" answer pending
> [kernel-persistent-process-api.md](./not-done-kernel-persistent-process-api.md) adjudication; the
> PyApp runtime is what the daemon would run inside),
> [shell-and-task-runner.md](./not-done-shell-and-task-runner.md) (PEP 723 script deps installed via
> bundled uv).

---

## Goal

Make functualize installable and manageable by three audiences without Python knowledge
leaking into the UX:

| Mode | Audience | Installation | Python env |
|------|----------|-------------|------------|
| **standalone** | Non-Python dev, ops | `brew install functualize`, binary download | PyApp-managed (bundled) |
| **tool** | Python dev with uv/pipx | `uv tool install functualize` | uv/pipx isolated env |
| **project** | Framework user | `uv add functualize` | Project `.venv/` |

Two degraded modes exist for honesty, not as targets: **tool (pip)** (no venv: bare pip,
system Python, conda) and **unknown** (an unrecognized venv). In both, mutating commands
print guidance instead of executing.

---

## Runtime mode detection

Detection signals, first match wins:

1. `FUNCTUALIZE_RUNTIME` env var → explicit override (CI/testing)
2. `PYAPP=1` or `PYAPP_COMMAND_NAME` set → standalone (PyApp injects `PYAPP=1` into the
   spawned process at runtime; `PYAPP_COMMAND_NAME` is set when management commands are
   enabled)
3. `sys.prefix` is under the uv tools directory (`$XDG_DATA_HOME/uv/tools`, default
   `~/.local/share/uv/tools`) → tool (uv). **Not** `VIRTUAL_ENV`: that variable is set by
   shell *activation*, not by executing a venv interpreter through a script shebang — which
   is exactly how a uv-tool-installed binary runs (verified by experiment; see scrutiny
   report E1)
4. `sys.prefix` contains `pipx/venvs` → tool (pipx). (`PIPX_HOME` is unset for default
   pipx installs — do not rely on it)
5. Nearby `pyproject.toml` with functualize in deps → project
6. `sys.prefix == sys.base_prefix` (no venv at all: bare pip, system Python, conda) →
   tool (pip), degraded
7. Fallback → **unknown**, degraded. A venv we don't recognize — dev checkout, functualize
   as a transitive dependency. Never assume standalone: a wrong standalone guess makes
   `plugin add` print bundled-uv commands that don't exist and `self update` attempt a
   PyApp update against a non-PyApp binary.

Mode drives behavior:

| Behavior | standalone | tool (uv) | tool (pipx) | project | tool (pip) / unknown |
|----------|-----------|-----------|-------------|---------|----------------------|
| `func plugin add X` | bundled `uv pip install X` + record in manifest | receipt-merged `uv tool install functualize --with <all prior> --with X` | `pipx inject functualize X` | `uv add X` | print `pip install X`, do not execute |
| `func self update` | delegate to PyApp (`func pyapp update`), then reconcile plugins | `uv tool upgrade functualize` | `pipx upgrade functualize` | `uv lock --upgrade-package functualize && uv sync` | refuse with guidance |
| Python ownership | functualize | uv | pipx | project venv | user |

Edge cases: coexisting PyApp + uv-tool installs are both recorded in the manifest (PATH
decides which runs); CI with no venv falls to tool (pip) and doctor reports it.

Alternatives considered: explicit config file (manual burden — rejected), env-var +
`sys.prefix` signals (chosen), `VIRTUAL_ENV` heuristics (falsified — see above). For
distribution: PyApp (chosen — single binary, uv-powered, proven by Hatch which ships the
same way) over Nuitka (fragile with pydantic-core), PyInstaller (slow startup, AV false
positives), Docker (poor CLI UX).

---

## PyApp `self` collision (decided)

PyApp's built-in management command group is named **`self`** by default
(`PYAPP_SELF_COMMAND`) and PyApp intercepts `<binary> self …` *before Python starts* — so
without intervention, `func self doctor` would never reach functualize in standalone mode,
while `func self update` would accidentally hit PyApp's updater.

**Decision**: build binaries with `PYAPP_SELF_COMMAND=pyapp`. PyApp's management commands
live at `func pyapp update|remove|restore` (documented as internal); functualize owns
`func self` in every mode. In standalone mode `func self update` re-execs
`func pyapp update` and then reconciles manifest-recorded plugins (below). Alternatives:
`PYAPP_SELF_COMMAND=none` (loses PyApp's battle-tested updater — rejected); renaming
functualize's group (surrenders the natural UX namespace — rejected).

---

## `func self` command group

```
func self doctor        # Health check (extensible by plugins)
func self config-info   # Full environment dump (--json supported)
func self paths         # Quick path reference
func self update        # Mode-aware update with confirmation
func self daemon start|stop|status|restart|list|register|unregister   # contingent — see persistent-process.md
```

Doctor checks: Python ≥ 3.11 (critical — matches `requires-python`), core import + version
(critical), CLI extras (warning), job discovery from CWD (info), config resolution chain
(warning), plugin loading (warning), manifest-vs-installed plugin reconciliation in
standalone mode (warning), stale manifest entries with dead `binary_path` (info), execution
smoke test (critical), terminal capabilities (info), daemon status (info).

## `func plugin` command group

```
func plugin list
func plugin add <pkg>     # mode-aware; prints the exact command + y/N confirmation
func plugin remove <pkg>
```

All commands show/confirm before executing side effects.

### Plugin persistence (load-bearing)

- **Tool (uv)**: `uv tool install` is declarative — the receipt records only the latest
  invocation's requirements, so emitting a single `--with X` would silently uninstall
  previously added plugins. `func plugin add`/`remove` must read the tool's
  `uv-receipt.toml` and re-emit **all** prior `--with` entries plus/minus the change.
  (`uv tool upgrade` preserves receipt-recorded settings, so upgrades are safe once the
  receipt is right.)
- **Standalone**: PyApp update/restore rebuilds the managed venv from the project
  requirement only, wiping `uv pip install`ed plugins. The manifest records added plugins;
  after `func self update` (and on doctor runs) missing recorded plugins are reinstalled
  via bundled uv, with confirmation.

---

## First-run detection

Manifest at `<user-config>/install.json`, resolved via the existing
`resolve_user_config_dir()` helper (`app/utils.py` — respects `XDG_CONFIG_HOME`; do not
hardcode `~/.config`). Append-only — installation records are never deleted, but doctor
flags entries whose `binary_path` no longer exists rather than trusting them:

```json
{
  "schema_version": 1,
  "installations": [{
    "binary_path": "/usr/local/bin/func",
    "runtime_mode": "standalone",
    "python_version": "3.12.4",
    "functualize_version": "0.1.0",
    "plugins": ["functualize-state-sqlite"],
    "first_run_at": "2026-06-20T10:30:00Z"
  }]
}
```

On first run: print a hint (`Run 'func self doctor' for a health check.`), don't block. The
hint fires on the first real invocation after PyApp's bootstrap completes — PyApp exposes no
hook to run app code mid-bootstrap. The first-run check must stay off the warm-boot hot
path (a single stat()).

---

## PyApp runtime (standalone mode)

PyApp is the environment manager: bundled version-pinned Python, isolated venv for
functualize + plugins + job deps, bundled uv (`PYAPP_UV_ENABLED`) for plugin installs and
PEP 723 inline-dependency resolution.

**Embedding (decided)**: build with `PYAPP_DISTRIBUTION_EMBED` and an embedded project
wheel, so first run is offline-capable and the ~3s bootstrap figure holds. PyApp's default
is network-first-run (downloads the distribution + package on first invocation) — rejected:
it makes `curl … | sh && func` fail offline and turns first-run latency into a network
lottery. Consequence: binary size target is **35–50MB** (python-build-standalone
install-only ≈25–30MB + wheel + PyApp binary; uv fetched on first plugin/PEP 723 use), not
the 30MB floor. CI asserts the actual size on release builds.

### Build & distribution pipeline

- Build standalone binaries on release tag: x86_64/aarch64 × linux/macos, with
  `PYAPP_SELF_COMMAND=pyapp`, `PYAPP_UV_ENABLED=1`, `PYAPP_DISTRIBUTION_EMBED=1`.
- Distribution: GitHub Releases + `install.sh` + Homebrew formula.

---

## User flows (abbreviated)

1. **Non-Python dev**: `curl … install.sh | sh` → `cd project && func` (PyApp bootstraps
   ~3s from the embedded distribution, manifest written, hint printed, TUI launches) →
   `func plugin add functualize-state-sqlite` (confirms bundled-uv install, records plugin
   in manifest) → later `func self update` delegates to `func pyapp update`, then
   reinstalls recorded plugins.
2. **uv tool user**: `uv tool install "functualize[cli]"` → `func plugin add
   functualize-inline` reads the receipt and confirms `uv tool install functualize
   --with functualize-inline` (plus any previously recorded `--with` entries) →
   `func self update` prints `uv tool upgrade functualize`.
3. **Project dev**: `uv add "functualize[cli]"` → `uv run func self config-info` reports
   project mode, paths, config → `func self update` prints
   `uv lock --upgrade-package functualize && uv sync`.

---

## Implementation notes

| Module | LOC est. | Dependencies |
|--------|----------|-------------|
| `_cli/runtime.py` | ~140 | stdlib only (no functualize imports — preserves the warm-boot 0-imports invariant) |
| `_cli/manifest.py` | ~100 | stdlib + json (path via `resolve_user_config_dir()`) |
| `_cli/builtins/self_cmd.py` | ~200 | public API only (import-linter enforced) |
| `_cli/builtins/plugin_cmd.py` | ~180 | public API + subprocess |

`builtins.py` (724-line module) converts to a `_cli/builtins/` package as part of this work;
the `BuiltinCommand` registry and existing commands move unchanged, `self` and `plugin`
entries are added to `BUILTIN_COMMANDS`, and the registry-mirror test is extended to cover
them.

Order: runtime detection + manifest + `func self doctor/config-info/paths` + first-run
wiring → `func plugin` + `func self update` (receipt-merge + manifest reconciliation) →
PyApp CI pipeline (`PYAPP_SELF_COMMAND=pyapp`, embedding) + install script. `_cli/` dogfoods
the public API throughout.
