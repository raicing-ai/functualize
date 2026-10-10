# Plan: self-update-checksum-prefix

## Alignment

Shape state is `not-required` on the tracking issue: a defect fix with no new
user-visible surface. No shape page is cited.

## Retrieval

- Prose (zvec-grep, index built for this worktree): the only prior decision is
  ADR-015 § *Correction (2026-09-04)* — "an archive the checksums file does not
  mention is refused exactly like one that fails to match". Kept as is. No
  ADR, guide or pitfall records a decision about how a line spells its name.
- Counts and negatives (rg): `SHA256SUMS` is written in one place
  (`release.yml:508`) and read in four — `self_update.verify`, `install.sh`
  `verify`, `install.ps1`, and `sha256sum -c` in
  `docs/getting-started/installation.md:96`. `verify` has one production
  caller (`perform`, `self_update.py:344`); the remaining references are tests.
- Dependency direction (graphify `get_neighbors verify()`): `perform → verify →
  ChecksumMismatchError`; nothing else.
- Serena was not run: the reference question was answered by rg and graphify,
  which agree, and the symbol is module-private in practice.

## Production call path

`func builtin self update` → `_cli/self_cmd.py:564` `update` →
`_cli/self_cmd.py:616` `_update_standalone` → `_cli/self_update.py:283`
`perform` → `_cli/self_update.py:344` `verify(archive, checksums,
source.archive_name)`.

## Architecture

```
BEFORE

  .github/workflows/release.yml  (CI, outside the package)
      checksums job:  sha256sum ./* > SHA256SUMS
              │  publishes "<d>  ./<asset>"
              ▼
  GitHub release assets ── SHA256SUMS, <asset>
              │  fetched by Opener
              ▼
  _cli/self_cmd.py ──► _cli/self_update.py  [delivery layer, _cli/]
                         perform ──► verify          compares "<asset>" to
                                                     "./<asset>"  → never equal
  install.sh / install.ps1  (outside the package)    tolerate "./" already
```

```
AFTER

  .github/workflows/release.yml
      checksums job:  sha256sum * > SHA256SUMS
              │  publishes "<d>  <asset>"   ← readable by 0.2.2–0.4.0 binaries
              ▼
  GitHub release assets
              ▼
  _cli/self_cmd.py ──► _cli/self_update.py
                         perform ──► verify ──► _listed_name(line name)
                                                  strips one "*", one "./"
  tests/_cli/test_self_update.py ──reads──► release.yml checksum command
                                  (agreement test: writer output → verify)
```

Layers: everything changed sits in `_cli/` (delivery) or outside the package
(CI workflow, tests). No import crosses a layer boundary; no import-linter
contract is affected. Dependency direction is unchanged — `self_update` gains
no import.

## Design skills consulted

`design-patterns-refactoring` (user-level; Refactoring.Guru catalogue) — used
for smell names. The in-repo `python-design-patterns` skill (KISS, single
responsibility) applies: the normalisation is one small private function rather
than a parser abstraction, because the file format has exactly one variable
part.

## BEFORE smells

- **Duplicated code** — four readers of one file format (`verify`, `install.sh`,
  `install.ps1`, `sha256sum -c`), each with its own idea of what a name looks
  like. The defect is this smell's consequence: the readers drifted apart.
  Not removable here — three are in different languages and run before the
  package exists.

## Candidate AFTERs considered

1. *Writer only* (`sha256sum *`). Fixes the next release for everyone, but the
   reader stays the one strict consumer; any future writer change (a `-b` flag,
   a subdirectory) re-breaks it silently. Rejected alone.
2. *Reader only*. Fixes binaries built from now on, but every installed binary
   (0.2.2–0.4.0) verifies the next release with the old reader and stays
   unable to update for ever. Rejected alone.
3. *Both* (chosen). Introduces no smell; the agreement test turns the implicit
   contract between `release.yml` and `verify` into a checked one.
4. *Generalised path normalisation* (`os.path.normpath`, basename). Rejected:
   `basename` would make `dir/<asset>` and `../<asset>` match, widening what
   passes (AC2).

## Surviving smells

- **Duplicated code** (above) survives: four readers, three languages. Accepted
  — consolidating them would mean the installers depend on a Python package
  they exist to install. The agreement test covers the Python reader against
  the writer; the installers keep their own tests
  (`examples/docs/scenarios/l-standalone-binary.toml`). Does not need
  maintainer review.

## Files

- `src/functualize/_cli/self_update.py` — `verify` matches through a private
  `_listed_name`.
- `.github/workflows/release.yml` — checksum step writes bare names.
- `tests/_cli/test_self_update.py` — prefix matrix, near-miss names, mismatch
  and unlisted preserved, workflow agreement, `perform` end to end.
- `CHANGELOG.md` — `[Unreleased]` *Fixed* entry.

## Risks

- A test that executes the workflow's shell line needs `bash` and `sha256sum`;
  it skips where either is absent (macOS without coreutils). CI runs on
  ubuntu, where both exist.
- Already-published releases (≤ 0.4.0) keep their `./` files. A new binary
  verifying them is irrelevant — it never installs an older version — and an old
  binary cannot be fixed retroactively; the writer change is what reaches it.
