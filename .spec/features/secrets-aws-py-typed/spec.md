# Spec — `functualize-secrets-aws` ships its PEP 561 marker

## Problem

`plugins/credentials/functualize-secrets-aws/pyproject.toml` declares the
`Typing :: Typed` classifier, but the package has no `py.typed` marker, so the
built wheel carries none. A type checker skips the installed package and types
its whole API as `Any`. Measured on `d58500f`: the wheel built by
`uv build --package functualize-secrets-aws` lists nine files and no
`functualize_secrets_aws/py.typed`; mypy on a consumer importing
`SecretsManagerProvider` reports `[import-untyped]` and reveals `Any`.

## Behaviour

The wheel and the sdist carry a 0-byte `functualize_secrets_aws/py.typed`, so
the classifier is true and type checkers read the package's annotations.

## Acceptance criteria

- **AC-1** — `uv build --package functualize-secrets-aws` produces a wheel
  whose `unzip -l` listing contains `functualize_secrets_aws/py.typed`.
- **AC-2** — mypy, run on a consumer module in a clean venv with the built
  wheel installed, reports no `import-untyped` for `functualize_secrets_aws`
  and reveals the real type of `SecretsManagerProvider`.
- **AC-3** — `CHANGELOG.md` `[Unreleased]` states the consequence for users.

## Out of scope

The README, `examples/`, a CI leg, and every other plugin (including
`functualize-secrets-bitwarden`, which has the same defect and its own task).
