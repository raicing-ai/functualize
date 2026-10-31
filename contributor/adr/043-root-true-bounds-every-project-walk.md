# ADR-043: `root = true` Bounds Every Project Walk, and One Primitive Owns the Boundary

**Status**: accepted
**Date**: 2026-10-26 (D5 added 2026-10-28)
**Deciders**: maintainer

## Context

A project is found by walking upward from the working directory, and four
walks did it, each with its own stop:

| Walk | What it resolves | Where it stopped |
|---|---|---|
| A | project config layers, `jobs_directories`, `import_libs`, `extra_directories`, convention `.functualize/jobs/` and `lib/`, the TUI settings list | the filesystem root; `root = true` honoured only by the merge |
| B | job configuration: stage 1 finds the first `config.<slot>.*` directory, stage 2 layers it and its ancestors | `~`, both stages |
| C | the `.functualize/` folder: project mode, runtime state, discovery cache, convention plugins | the first `.functualize/` met |
| identity | the key of standalone state, cache and vault | the working directory |

So a nested project that declared `root = true` stopped only its *settings
merge*. An ancestor's project file — empty is enough — added its jobs and
library path; a root without its own `.functualize/` adopted the ancestor's
plugins, state and project mode; an ancestor's `config.base.toml` supplied job
values, key by key; and `builtin config path` showed none of those files as
part of the project. Walk A alone was copied four times, and the project file
list itself was written out in six places.

## Decision

- **`root = true` ends the project for every walk.** The file that declares it
  is included; nothing above it contributes through implicit upward discovery —
  not jobs, libraries, plugins, extra directories, settings layers, job-config
  values, state, cache or vault. Without a root, inheritance is unchanged.
- **One primitive owns the answer: `_primitives/project_root.py`.** It holds
  the project-file candidates, the one predicate `is_root_config` (only the
  boolean `true` counts; `"true"` does not), `find_project_boundary`, walk C
  (`find_functualize_dir`, bounded *inclusive*: a `.functualize/` in the root
  directory is found, one above it is not) and `project_identity_dir`. Walk A
  (`_config/project_dirs.py::project_config_layers`), walk B
  (`_app/boot.py::_job_config_stop`) and every identity reader ask it. It sits
  in `_primitives` because walk C does: the folder lookup is called by readers
  that must not boot (the CLI fast path, completions, the MCP translator), so
  the boundary must be answerable without threading a parameter through them.
- **Walk A is one function and ends at the root.** `project_config_layers`
  returns the per-directory layers nearest first and stops after the first
  root layer; the merge, `auto_discover` and `list_project_config_files` all
  read it. **Allowed difference: the settings store walks for itself.** It
  probes each `AppSettingsSchema.sources.project_file_names` per directory and
  stops on the same `is_root_config` predicate, because a second app declares
  its own file names and section prefixes and the store needs each file's text
  to write an edit back. That is the one permitted independent walk:
  `builtin config path` renders the store's snapshot, so it lists the bounded
  project files the store reads plus the expected candidates that are not
  layers. `tests/config/test_settings_layers.py` pins the two paths to the same
  files, in the same order, for a marker-only root.
- **Walk B is bounded on both stages (B1).** Discovery and layering stop at
  the boundary when it comes before `~`, else at `~` as before; a boundary
  above `~` widens nothing. An explicit `--config-directory` layers up to the
  boundary *of the directory it names* (D4 (a)); a directory outside any root
  layers exactly as before. The user-global source (`search_platform_user`,
  the XDG **data** directory) still applies under a root.
- **Identity: `.functualize/`'s parent, else the root directory, else the
  start (D2 (b)).** A root without its own folder is standalone, and the root
  and every subfolder of it share one ledger, cache and vault. The vault key
  lookups take the same identity as the vault file. A loose directory with
  neither keeps its per-directory id; child projects (`ancestor_search=False`,
  ADR-011) keep theirs.
- **The project file list has one declaration.** `_types/settings.py` holds
  `PROJECT_FILE_NAMES` and `PROJECT_FILE_SECTION_PREFIXES`; the walk-A
  candidates are *derived* from them, and the public
  `SettingsSources.project_file_names` defaults to them, so the documented
  field is the list `func` actually reads. Not public-API breaking: names,
  defaults and docs are unchanged.
- **`builtin config path` lists the bounded project files and the expected
  candidates (D5 (a)):** the global file first, then each directory the bounded
  walk reached, nearest last, every line `✓ used` (supplies a value in effect),
  `○ found` (exists, supplies none — a marker-only `root = true` file reads
  this way) or `✗ missing`, with unknown keys annotated in place. A directory
  above a root is neither listed nor probed.
- **Ancestor data is never moved or copied automatically.** Keeping runtime
  records or secrets after a root stops inheriting them is a documented, user
  chosen migration (`docs/guides/configuration.md` § *Project boundaries and
  `root = true`*).

## Consequences

### Positive

- "Which project am I in?" has one answer, and every surface — job list, run,
  `builtin info`, `builtin config path`, the settings panel, `data show`, the
  vault — gives it.
- A new walk cannot forget the root: it asks `project_root.py`, or it is a
  fifth copy that review can name.
- A root and its subfolders share state even without a `.functualize/`, where
  before each subfolder got a fresh standalone id.

### Negative

- A nested root that relied on inherited ancestor sources loses them. The
  remedy is to remove `root = true`, or keep it and declare the shared path
  explicitly in the root's own file.
- Existing standalone state of such a root moves to a new key: the old ledger,
  cache and vault stay where they were and are no longer selected until the
  user migrates them.
- Walk C now reads project config at each level it passes, so the
  `.functualize/` lookup costs a few `stat`s more per level and parses TOML
  where a project file exists. The startup budget held.

### Neutral

- `find_functualize_dir` moved from `_primitives/locator.py`, with no shim.
  `cache_format` and `fresh_format` still bind it unqualified, because
  `tests/conftest.py::_isolate_state_root` patches `fresh_format`'s binding.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|-------------|------|------|-------------|
| Keep the candidates in `_config` and pass a boundary predicate down to `_primitives` as a callable | no new module | an implicit `Callable` convention for a port, plus speculative generality | a Forbidden Pattern |
| Compute the boundary in `_config` and thread `stop=` through every walk-C caller | the primitive stays config-blind | shotgun surgery over ≥13 call sites, several in `_cli`, which cannot import `_config` | the layer rules forbid it and every new reader would have to remember |
| A process-wide memo of "the project", set at boot | one walk per process | global mutable state; readers that never boot would see none | a Forbidden Pattern |
| Bound walk B with a new `ConfigSources` stop parameter | explicit | widens public API; boot and `refresh()` must both pass it | the chain builder exists so that neither can forget |
| D2 (a): leave walk C and identity alone | smallest diff | the root still runs an ancestor's plugins and writes its state | the maintainer chose the full boundary |
| D4 (b): carry an "explicit" flag so `--config-directory` keeps crossing the root | today's behaviour exactly | new app state threaded through `refresh()`; keeps the leak behind the flag | one rule from any start is simpler and closes it |
