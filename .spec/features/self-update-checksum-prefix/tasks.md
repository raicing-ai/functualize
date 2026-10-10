# Tasks: self-update-checksum-prefix

## Wave 0

- [x] **1.1 — the reader tolerates `./` and `*`** (AC1, AC2)
  - Files: `src/functualize/_cli/self_update.py`, `tests/_cli/test_self_update.py`
  - `verify` compares `asset_name` against the line name with one leading `*`
    and then one leading `./` removed; nothing else is normalised.
  - Gate: `uv run pytest tests/_cli/test_self_update.py -q` — the prefix matrix
    (`name`, `./name`, `*name`, `*./name`) passes; a differing digest still
    raises with both digests; an unlisted asset and near-miss names
    (`x-name`, `dir/name`, `../name`) still raise.
  - Reachability: `perform` → `verify` (`self_update.py:344`); proven by
    reverting the normalisation and watching the `./` cases fail.

- [x] **1.2 — the writer emits bare names** (AC3)
  - Files: `.github/workflows/release.yml`
  - The `checksums` job runs `sha256sum * > SHA256SUMS`; the set of files
    covered is unchanged.
  - Gate: the workflow line is the one 2.1 reads and executes.

## Wave 1

- [x] **2.1 — writer and reader are seen to agree, end to end** (AC3, AC4)
  - Files: `tests/_cli/test_self_update.py`, `CHANGELOG.md`
  - A test extracts the checksum command from `release.yml`, runs it over a
    release-style directory, and verifies each asset through `verify`.
  - A test checksums a release-style directory with `sha256sum ./*` (every
    release published to date) and runs `perform` against it through the
    injected opener; the binary is replaced.
  - Gate: both tests pass; reverting 1.1 fails the `./*` test.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1", "1.2"]},
    {"id": 1, "tasks": ["2.1"], "depends_on": [0]}
  ]
}
```
