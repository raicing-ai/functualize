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

### P3: job config ignores `root = true` (decision D3, 2026-10-21)

Job config is found by walk B (`_app/boot.py::discover_config_path`: upward to the first directory holding `config.<env>.<ext>`, stopping at `~`). The values are then read from that directory and every ancestor up to `~` (`boot.py:1396-1401`). Probe: nested `root = true`, job `greeter.greet` with a `BaseModel` config, and the ancestor `config.base.toml` `[greeter.greet] greeting = "ANCESTOR…"`. The job prints the ancestor's value. With a nested `config.base.toml` lacking the key, the ancestor's value still applies (key-by-key layering). A `[greeter.greet]` table in `.functualize.toml` is not read at all, nested or ancestor.

### Scope amendment (2026-10-21)

The owner selected D1(a), D2(b), and D3(b) on MCH-188 at 2026-10-21T15:02:26Z, overriding the previous designer's D2(a)/D3(a) recommendations. Confluence SD/17104898 v13 records the selections, a D3 alternatives assessment, and the D2 migration gate. Its `Authority` field remains `Approved`; the recommended detail within D3(b) awaits member review. The previous `plan.md` and `tasks.md` were removed from the branch because their architecture and waves explicitly leave walks C and B unchanged. A new Specify confirmation and Plan pass are required.

Code facts checked for the amendment on branch `c2a81c9`:

- Walk B has two independently leaky stages: `_app/boot.py:1176-1246` searches for the first job-config directory; `_app/boot.py:1396-1423` constructs a `ResourceLocator` that reads from that directory and its ancestors. Bounding only the first stage leaves key-by-key ancestor inheritance.
- `_app/boot.py:1005-1034` bypasses file discovery when a config resolution chain is supplied. `_app/impl.py:1346-1393` is the one builder used by boot and `refresh()`. `app/adapters/cli.py:1009-1020` makes `--config-directory` an explicit override and refreshes the app.
- `_primitives/locator.py:484-523` returns the nearest `.functualize/` without reading project config. `_primitives/cache_format.py:297-325` uses that answer for project cache versus XDG cache. `_config/vault_paths.py:43-76` stores vault data under XDG **data**, keyed by the chosen project root; it is inaccurate to say the vault moves into XDG cache. A D2 plan must keep one identity across subdirectories and verify state migration rather than assume a path.
- `docs/guides/configuration.md:131-159` documents base/active environment overlays and nearest-directory precedence. User-global and explicit sources are preserved by the recommended D3 model.

### Other forms measured for the shape page (2026-10-21)

- A nested `.functualize/` with no nested config file, run from `nested/sub/`: `['outer-only']`. The nested project's own job is missing while `Mode` names the nested folder. This is a pre-existing defect: convention `jobs/` is collected only at walk-A config-hit levels plus cwd.
- `.functualize/.functualize.toml` with `root = true` works as a marker, but `func builtin config path` lists only cwd's `pyproject.toml` and `.functualize.toml` (`_cli/builtins.py:2418-2467`).
- `pyproject.toml` without `[tool.functualize]` is not a marker; with the table and `root = true`, it behaves like `.functualize.toml`.

## Plan retrieval 2 (2026-10-22, branch `f30285c`, after "confirm B1 and D2 data rule")

### Walk C and project identity census

- `rg -n "find_functualize_dir" src plugins --type py`: definition at `_primitives/locator.py:484`. There are 7 importers: `_primitives/cache_format.py:29`, `_primitives/fresh_format.py:43`, `_config/vault_paths.py:37`, `_config/project_dirs.py:44`, `_app/impl.py:32`, and `_app/__init__.py:57` (a re-export in `__all__`). Calls: `cache_format.py:313`, `fresh_format.py:148`, `vault_paths.py:63`, `project_dirs.py:613`, `impl.py:81`, `impl.py:146`.
- Readers that pass `Path.cwd()` into a walk-C consumer: `_cli/main.py:970`, `:2062`; `app/adapters/cli.py:548`; `_cli/tui/cli_arg_parser.py:122`; `_cli/tui/display_provider_discovery.py:131`; `_cli/completions/data.py:143`; `_cli/builtins.py:584`, `:808`, `:826`, `:842`; `functualize_mcp/_translator.py:54`. Threading a boundary through them is why the stop belongs in the primitive (`plan.md` C3).
- Identity hashed from cwd or start: `cache_format.py:316`, `fresh_format.py:151`, `app/utils.py:1884`, `:2049`, `_app/boot.py:1319`, `_app/impl.py:92`, `:159`. The vault file is keyed by project root (`vault_paths.py:66-80`), while its key lookups at `boot.py:1319`, `utils.py:1884` and `:2049` use cwd. Both built-in key providers ignore `project_id` (`_config/vault_keys.py:155-160`, `:235-250`), so the key is per machine.
- Constraint: `tests/conftest.py::_isolate_state_root` patches `fresh_format`'s own binding of `find_functualize_dir`, and the `locator.py` docstring says both formats must bind it unqualified.

### Baselines

- N4 (nested `root = true`, no nested `.functualize/`): `func builtin data show` from `nested` and from `nested/sub` → `Mode: project (.functualize/ found at …/outer/.functualize)`, `Freshness path: …/outer/.functualize/fresh.json`.
- Standalone without a root (control, H2): `dir` → `…/cache/functualize/7a585e998736/fresh.json`; `dir/sub` → `…/ddcd051f4c69/fresh.json`. Fragmenting per cwd is today's behaviour, and it stays for projects without a root.

### P4: explicit `--config-directory` crosses the root (decision D4)

Nested `root = true`, ancestor `config.base.toml` `[greeter.greet] greeting = "ANCESTOR"`, `nested/cfg/config.base.toml` without the key, `func --config-directory cfg greeter greet` → `GREETING = ANCESTOR`. `app/adapters/cli.py:1016-1017` stores the choice in `app._config_path`, and `refresh()` rebuilds through `_app/impl.py::_build_resolution_chain` → `_app/boot.py::build_resolution_chain`, whose `FileSource` locator layers `config_path → ~` (`boot.py:1396-1401`). The builder cannot distinguish explicit from discovered.

### Tests referencing the identity and walk-B symbols

`rg -l "find_functualize_dir|resolve_cache_path|resolve_fresh_location|resolve_fresh_path|project_root_for|vault_path_for_project|compute_project_id|discover_config_path|build_resolution_chain" tests` → 34 files (listed by `rg`; T9 runs them all).
