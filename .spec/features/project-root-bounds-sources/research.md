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
