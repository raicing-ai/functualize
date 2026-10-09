## Release path

```text
BEFORE
build (uv build --all-packages)
  └─ dist artifact ─┬─> publish download ─> remove two wheels ─> PyPI
                   └─> bake download ─> standalone binary

AFTER
build (uv build --all-packages)
  └─ dist artifact ─┬─> publish download ─> PyPI
                   └─> bake download ─> install [all] ─> standalone binary
```

The boundary is the uploaded `dist` artifact. Removing the publish-only
filter leaves the bake path as it is. The two credential projects and the
already-included decision provider require PyPI bootstrap before merge.

The packaging boundary also changes: `pyproject.toml`'s `[all]` extra drops
the AWS distribution, and the curated catalog mirrors that choice. The bake
recipe still installs `[all]`, so the binary omits AWS by default. The install
guides supply an explicit `plugin install` route for binary users. The plugin
command uses the same package installer as `self install`, but records the
extension under the plugin key for `self update`.

## Design guidance consulted

`python-design-patterns` and `design-patterns-refactoring`: keep the existing
build and consumer responsibilities separate. This change removes a release
filter and adds no component or abstraction.

## Files and checks

- `.github/workflows/release.yml`: remove the deferred-package step.
- `plugins/PUBLISHING.md`: update the current classification, upload mapping,
  trusted-publisher guidance, and `[all]` count.
- `pyproject.toml`: remove AWS from `[all]`; keep both credential plugins as
  workspace members and keep the optional `[aws]` question open.
- `uv.lock`, `examples/project/weather_app/uv.lock`, and
  `examples/project/monorepo_children/uv.lock`: refresh the local-core
  metadata. `uv lock --check` failed after the extra changed, and searches
  found the old `extra == 'all'` AWS edge in all three files.
- `src/functualize/_cli/data/plugin_catalog.toml` and
  `tests/cli/test_plugin_catalog.py`: make AWS discoverable but not
  recommended, with an explicit regression assertion.
- `docs/getting-started/installation.md` and
  `docs/guides/configuration.md`: show the AWS opt-in path for binary users.
- Check both jobs' artifact downloads, the two upload rows, counts, and a
  negative search for the removed filter. Check the exact `[all]` entries,
  catalog parity, lockfile consistency, packaged wheel metadata, and
  repository verification gates.

## Surviving smells

None identified in this release path: build produces one artifact, publish and
bake consume separate downloads, and catalog recommendation mirrors `[all]`.
The external PyPI bootstrap is an explicit release precondition. Removing AWS
from the standalone binary is the maintainer's accepted product consequence,
not an unreviewed architectural compromise.
