# Plan — `functualize-secrets-aws` ships its PEP 561 marker

## BEFORE / AFTER

```
BEFORE                                         AFTER

plugins/credentials/functualize-secrets-aws/   plugins/credentials/functualize-secrets-aws/
  pyproject.toml   (hatchling,                   pyproject.toml   (unchanged)
    packages = ["src/functualize_secrets_aws"])
  src/functualize_secrets_aws/                   src/functualize_secrets_aws/
    __init__.py _reference.py _session.py          __init__.py _reference.py _session.py
                                                   py.typed            (0 bytes, new)
        │ uv build                                     │ uv build
        ▼                                              ▼
  wheel: 3 modules, no marker                    wheel: 3 modules + py.typed
        │ pip install; mypy consumer.py                │ pip install; mypy consumer.py
        ▼                                              ▼
  import-untyped, API is Any                     API typed from its annotations
```

Layer: a workspace plugin package (outside `src/functualize`); no import
crosses a boundary and no import-linter contract is involved.

## Approach

Hatchling's `packages = [...]` ships every file in the package directory, so
the marker needs no `include` or `force-include` wiring. Every sibling plugin
that ships `py.typed` (for example `functualize-mcp`, `functualize-tasks`)
uses exactly this wiring and only the file. Add the 0-byte marker; no
`pyproject.toml` change.

## Files to change

- `plugins/credentials/functualize-secrets-aws/src/functualize_secrets_aws/py.typed` (new, 0 bytes)
- `CHANGELOG.md` (`[Unreleased]`)

## Design skills consulted

`design-patterns-refactoring` was available; no structural change is made, so
no pattern applies.

## Surviving smells

None. The change adds one empty data file and no code, so it introduces no
structure that could carry a smell. Pre-existing and out of scope: mypy over
the plugin's own source reports six errors (`boto3` untyped, the `_ready`
redefinition in `__init__.py`); `mypy src/` in CI does not cover plugin
sources.

## Risks

Consumers who run a type checker now see the package's annotations, so errors
that were hidden behind `Any` can appear in their code. That is the intended
consequence and is stated in the changelog.
