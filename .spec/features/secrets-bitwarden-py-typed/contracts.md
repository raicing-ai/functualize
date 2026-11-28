# Contracts — `functualize-secrets-bitwarden` PEP 561 marker

No Python API changes: no module, symbol, signature, entry point or dependency
of `functualize_secrets_bitwarden` is added, removed or altered. The declared
surfaces are the distribution layout and one documentation statement.

## Source tree

| Path | Contract |
|---|---|
| `plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/py.typed` | Exists, 0 bytes (PEP 561 marker) |
| `plugins/credentials/functualize-secrets-bitwarden/py.typed` | Does not exist |
| `plugins/credentials/functualize-secrets-bitwarden/pyproject.toml` | Wheel target is `packages = ["src/functualize_secrets_bitwarden"]` only; no `[tool.hatch.build.targets.wheel.force-include]` table. Classifier `Typing :: Typed` kept |

## Built distributions (`uv build --package functualize-secrets-bitwarden`, version 0.4.0)

| Surface | Contract |
|---|---|
| Wheel | 12 files; contains `functualize_secrets_bitwarden/py.typed`, 0 bytes, recorded in `RECORD`. Byte-identical to the wheel the earlier `force-include` placement produced |
| sdist | Contains `functualize_secrets_bitwarden-0.4.0/src/functualize_secrets_bitwarden/py.typed`; no `functualize_secrets_bitwarden-0.4.0/py.typed` at the distribution root |
| Editable install (`uv sync --all-packages`) | The package resolves to `plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/`, which contains `py.typed` |

## Consumer-observable typing

A type checker resolving an installed `functualize_secrets_bitwarden` reads its
annotations instead of reporting `[import-untyped]` and typing the API as
`Any`. Projects importing the package may now see type errors that `Any`
previously hid.

## Documentation

`plugins/PUBLISHING.md`, tier table notes: `functualize-secrets-bitwarden` has
tests, a README and a `py.typed` marker but no `examples/` directory, and sits
at Tier 2. `CHANGELOG.md` `[Unreleased]` carries "Fixed — Bitwarden package
typing marker".
