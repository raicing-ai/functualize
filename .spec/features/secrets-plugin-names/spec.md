## Why

Both deferred credentials plugins were named before the secrets prefix convention
existed. Neither distribution has ever been published to PyPI (both verified 404
on 2026-10-05), so renaming now is free; after the first launch it would
permanently orphan an index name, the way the earlier substrate rename orphaned
the old SQLite distribution at 0.2.3.

## Change

Distribution, import and directory names only — no behavior:

| was | is |
|---|---|
| distribution `functualize-aws` | `functualize-secrets-aws` |
| distribution `functualize-bitwarden` | `functualize-secrets-bitwarden` |
| import `functualize_aws` | `functualize_secrets_aws` |
| import `functualize_bitwarden` | `functualize_secrets_bitwarden` |
| `plugins/credentials/functualize-{aws,bitwarden}` | `plugins/credentials/functualize-secrets-{aws,bitwarden}` |

## Out of scope (unchanged on purpose)

- URL schemes `aws-sm://`, `aws-ssm://`, `bws://` — the user-facing API.
- Entry-point group `functualize.remote_providers` and keys (`aws-sm`, `aws-ssm`,
  `bws`); only the entry-point values (module paths) change.
- Provider class names (`SecretsManagerProvider`, `ParameterStoreProvider`).
- Publication status: both stay deferred; the release strip globs keep them off
  PyPI under the new names.

## Acceptance criteria

1. `uv build --all-packages` produces wheels under the new names only; the
   release strip globs match the new names.
2. `uv run pytest plugins/credentials/ tests/cli/ tests/config/` green; the
   plugin catalog and presets resolve the new names.
3. `git grep` for the four old tokens returns nothing outside the CHANGELOG's
   historical entries.
4. A CHANGELOG `[Unreleased]` entry records the rename and states that neither
   package was ever published, so no released artifact changes.

## Shape

No user-visible surface (never-published internals): shape gate not-required.
