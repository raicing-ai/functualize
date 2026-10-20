# Specify retrieval — project root boundary

Read 2026-10-20 on `sdd/project-root-bounds-sources` at `1b73983`. This is evidence for the draft, not an acceptance gate.

## Live authority

- Confluence SD/17104898 v7 has `Authority = Approved` and recommends Model A. Its body still contains older prose saying approval is open; the page's Authority field and the member's 2026-10-20 approval comment establish the current gate state.
- Jira FOSS-125, updated 2026-10-13T21:26:06.781+0700, records the nested root repro and its expected command behavior. Multica MCH-188 carries `Shape intent` pointing to that page and `Shape state = approved`.

## Premise checks on this checkout

- `src/functualize/app/utils.py:934-965` merges project config with root-stop, then gives the unbounded `results` to convention collection and effective-directory resolution. Verified with `rg -n 'walk_directories|convention_dirs|resolve_effective_directories_from_layers' src/functualize/app/utils.py` and source reading.
- `src/functualize/_config/merge.py:60-65` stops the merge at the first `root = true` layer. `src/functualize/_config/project_dirs.py:214-243` collects convention directories from every supplied walk directory. `project_dirs.py:307-395` collects directory lists from every supplied raw layer. Verified with `rg -n 'root_key|def collect_convention_directories|def resolve_effective_directories_from_layers' src/functualize/_config` and source reading.
- Prior art found by `zg query` on the absolute checkout: `docs/guides/plugins.md:78-114` promises that `root = true` stops inherited plugin directory declarations; `contributor/architecture/boot-sequence.md:43-62` records that plugin directories are resolved before plugin loading; `contributor/reference/code-map.md:155-164` locates project directory precedence in `_config/project_dirs.py`. Plan must include that early boot consumer.
- `tests/config/test_project_dirs.py:61-81` covers a root stop for a plugin-directory helper; it does not by itself prove job command inventory parity. Verified by reading that test and searching `rg -n 'root = true|root.*jobs|jobs_directories' tests/config tests/cli tests/integration`.

The current checkout has no synced virtual environment, so this pass did not claim a fresh runtime reproduction. Plan should establish baseline executable failures before authoring its gates.

## Plan retrieval (2026-10-20, branch head `36c8f46`)

Runtime: `uv sync --frozen --all-extras --all-packages` in this worktree; probes ran `func` from `.venv/bin` with `HOME`/`XDG_*` isolated under a scratch directory. zvec-grep index built in the worktree (14 416 entities). Serena was activated by absolute path. Graphify's graph is 71 commits behind HEAD, so it was used for dependency direction only.

### Walk A census

`rg -n "resolve_all_candidates\(PROJECT_CONFIG_CANDIDATES\)" src plugins` → 4 hits in 2 files: `_config/project_dirs.py:197` (`resolve_project_config`), `app/utils.py:510` (`list_project_config_files`), `:932` (`auto_discover`, ancestors), `:988` (`auto_discover`, local-only). Only the merge (`_config/merge.py:60-65`) applies `root = true`.

### Leaks measured on HEAD (nested `root = true`)

| Path | Probe | Result |
|---|---|---|
| leak 1, convention jobs | ticket tree | `['nested-only', 'outer-only']`; `func outer-only` runs |
| leak 1, convention lib | ancestor `.functualize/lib/outerlib.py` | nested job imports it (`LIB 1`) |
| leak 2, declared `jobs_directories` | ancestor `jobs_directories = ["shared"]` | `shared-job` listed |
| leak 2, declared `extra_directories` | ancestor `extra_directories = ["extra"]` | `extra-job` listed |
| not a leak, `exclude_patterns` | ancestor `[discovery] exclude_patterns` | not applied. `resolve_cli_config` builds `DiscoveryConfig` from `resolve_project_config`'s stopped merge (`_cli/config.py:476-484`); `auto_discover`'s `effective["exclude_patterns"]` is computed from raw layers but never read (`app/utils.py:972-1032` reads only jobs, extra and import_libs) |
| not a leak, declared plugins at boot | — | `resolve_project_directories` → `resolve_plugin_directories` passes no `config_layers`, so it falls back to the stopped `merged` (`project_dirs.py:569-575`) |
| control | nested file emptied | both jobs (inheritance) |
| control | nested `root = true` + `jobs_directories = ["../shared"]`, no ancestor file | `['nested-only', 'shared-job']` (explicit sharing works) |
| cache | warmed with the union, then the ancestor marker removed | next warm boot: `['nested-only']`. The cache follows the scanned directory set |

### P1: a third leak, the settings catalog (decision D1)

`list_project_config_files` (`app/utils.py:495-520`) walks unstopped and feeds `_cli/config.py::resolve_cli_config_layers` (`:810-843`), hence `FuncSettingsStore.discover()` (`_cli/data/func_settings.py:652`) and the TUI's write-target list (`_cli/tui/config_target_discovery.py:69`). Probe: ancestor `[cli] show_timing = true`, nested `root = true`. The store's chain lists `outer/.functualize.toml` and resolves `cli.show_timing = 'true'`, while `func builtin config show` (stopped merge) prints `show_timing = false  # source: default`. The shape's out-of-scope row assumed non-directory keys were "(already root-stopped)". That holds for the merge and fails for this consumer.

### P2: walk C crosses the root (decision D2)

`find_functualize_dir` (`_primitives/locator.py`, nearest `.functualize/` upward, config-blind) decides `Mode: project`, the location of runtime state, and the convention plugin directory (`project_dirs.py:613`). Probe: nested `.functualize.toml` = `root = true` + `jobs_directories = ["jobs"]`, **no** nested `.functualize/`, and the ancestor `.functualize/plugins/audit_log.py` (copied from `examples/project/shared_plugins`). Running `func nested-only` prints `[audit] nested-only: success`. `Mode` and `Freshness path` point at `outer/.functualize/`. This happens with the ancestor marker removed too, so walk A's fix cannot reach it. In the shape's own tree (nested has `.functualize/`) walk C stops at the nested project, and E3 holds.

### Blast radius (serena `find_referencing_symbols`)

- `merge_config_layers`: `project_dirs.py:208`, `app/utils.py:939`, `:992`; 14 tests in `tests/config/test_merge_config_layers.py`.
- `collect_convention_directories`: `project_dirs.py:295`, `app/utils.py:950`, `:998`.
- `resolve_effective_directories_from_layers`: `project_dirs.py:297`, `:569`; `app/utils.py:958`, `:1006`.
- `resolve_project_config`: `_cli/builtins.py:2287` (`config show`), `_cli/config.py:484`, `project_dirs.py:611`; tests `tests/cli/test_config_upward_walk.py`, `tests/config/test_project_dirs.py`, `tests/test_auto_discover_bug_condition.py`.
- `list_project_config_files`: `_cli/config.py:825`, `_cli/tui/config_target_discovery.py:69`.
- `auto_discover` is also reached by the MCP server manager (`plugins/adapters/functualize-mcp/src/functualize_mcp/_server_manager.py:266`), which therefore gets the fix with no change.
- Tests writing `root = true`: 13 files, all using it to isolate a tmp project.
