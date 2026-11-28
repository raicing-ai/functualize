# Plan — `functualize-secrets-bitwarden` ships its PEP 561 marker from inside the package

## BEFORE / AFTER

```
BEFORE (force-include placement)                 AFTER

plugins/credentials/functualize-secrets-bitwarden/
  py.typed            (0 bytes, plugin root)       (removed)
  pyproject.toml                                   pyproject.toml
    packages = ["src/functualize_secrets_bitwarden"]   packages = [...] (unchanged)
    [...wheel.force-include]                           (no force-include)
      "py.typed" = "functualize_secrets_bitwarden/py.typed"
  src/functualize_secrets_bitwarden/               src/functualize_secrets_bitwarden/
    __init__.py _client.py _pm_client.py             __init__.py _client.py _pm_client.py
    _pm_reference.py _reference.py                   _pm_reference.py _reference.py
                                                     py.typed          (0 bytes, moved here)
        │ uv build                                       │ uv build
        ▼                                                ▼
  wheel: 12 files, marker via mapping              wheel: 12 files, identical bytes
  sdist: marker at distribution root               sdist: marker inside src/<package>/
        │ uv sync --all-packages (editable)              │ uv sync --all-packages (editable)
        ▼                                                ▼
  package dir has no marker                        package dir has the marker
```

Layer: a workspace plugin package (outside `src/functualize`); no import
crosses a boundary and no import-linter contract is involved.

Smells the BEFORE carries: no code smell from the catalogue (no code is
involved), but one convention deviation — one plugin placed its marker by a
second mechanism (`force-include` from the plugin root) where eleven plugins
and core use the package directory, and
`contributor/adr/009-shipping-skills-in-the-distribution.md` sanctions
`force-include` only for a canonical file that a second consumer needs at the
repository root. The marker has one consumer, the built distribution.

## Approach

Hatchling's `packages = [...]` ships every file in the package directory, so
the marker inside `src/functualize_secrets_bitwarden/` needs no `include` or
`force-include` wiring. Move the file there (`git mv`) and delete the
`force-include` table. Correct the one `plugins/PUBLISHING.md` sentence that
named a missing marker as a Tier 2 reason. The `[Unreleased]` changelog entry
already states the user-visible consequence and is unchanged by the move.

## Files to change

- `plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/py.typed` (renamed from the plugin root, 0 bytes)
- `plugins/credentials/functualize-secrets-bitwarden/pyproject.toml` (delete the `force-include` table)
- `plugins/PUBLISHING.md` (tier-reason sentence)
- `CHANGELOG.md` (`[Unreleased]`, added with the first placement)

## Design skills consulted

`design-patterns-refactoring` was available. The change removes a second
convention rather than adding structure; no pattern applies.

## Surviving smells

None. The AFTER removes the BEFORE's only deviation (the second packaging
convention) and adds one empty data file and no code, so it introduces no
structure that could carry a smell. Nothing needs maintainer review.
Pre-existing and out of scope: no test pins the marker in the built wheel
(a `tests/test_packaging.py` row is follow-up work for the plugin test
standard).

## Risks

- Consumers who run a type checker now see the package's annotations, so
  errors hidden behind `Any` can appear in their code. Intended, and stated in
  the changelog.
- `functualize-secrets-aws` carries its own marker change, which edits the same
  `.spec/STATUS.md` section and, once published, the same `plugins/PUBLISHING.md`
  sentence; whichever merges second reconciles that text.
