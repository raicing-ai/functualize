# Spec — `functualize-secrets-bitwarden` ships its PEP 561 marker from inside the package

## Problem

`plugins/credentials/functualize-secrets-bitwarden/pyproject.toml` declares the
`Typing :: Typed` classifier, but on `d58500f` the package had no `py.typed`
marker, so the wheel built by `uv build --package functualize-secrets-bitwarden`
listed eleven files and no `functualize_secrets_bitwarden/py.typed`. A type
checker skipped the installed package: mypy on a consumer importing it reported
`[import-untyped]` and revealed `Any`.

A first fix placed the marker at the plugin root and mapped it into the wheel
with the repository's only plugin-level
`[tool.hatch.build.targets.wheel.force-include]`. That shipped a correct wheel
but failed `plugins/PUBLISHING.md`'s own `test -f
plugins/<name>/src/<package_name>/py.typed` check, put the marker at the sdist
root instead of inside the package, and left the editable workspace install
(`uv sync --all-packages`) without a marker.

## Behaviour

The 0-byte marker lives at
`plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/py.typed`,
like every other plugin's and core's, and reaches the wheel as ordinary package
data. The wheel, the sdist and the editable install all carry it inside the
package, so the classifier is true everywhere the package is imported from.

## Acceptance criteria

- **AC-1** — `uv build --package functualize-secrets-bitwarden` produces a
  12-file wheel whose `unzip -l` listing contains
  `functualize_secrets_bitwarden/py.typed` at 0 bytes.
- **AC-2** — mypy, run on a consumer module in a clean venv with that wheel
  installed, reports no `import-untyped` for `functualize_secrets_bitwarden`
  and reveals `def () -> functualize_secrets_bitwarden.PasswordManagerProvider`.
- **AC-3** — the sdist lists
  `functualize_secrets_bitwarden-0.4.0/src/functualize_secrets_bitwarden/py.typed`,
  and no marker at the distribution root.
- **AC-4** — `test -f plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/py.typed`
  exits 0, and `grep -rn force-include plugins/*/*/pyproject.toml` finds nothing.
- **AC-5** — after `uv sync --all-packages`, the editable install's package
  directory contains `py.typed`.
- **AC-6** — `plugins/PUBLISHING.md` no longer gives a missing marker as a
  reason `functualize-secrets-bitwarden` sits at Tier 2; the tier is unchanged
  and the stated reason is the missing `examples/` directory.
- **AC-7** — `CHANGELOG.md` `[Unreleased]` states the consequence for users.

## Out of scope

The README, `examples/`, a CI leg, a `tests/test_packaging.py` row pinning the
marker, and every other plugin (including `functualize-secrets-aws`, which has
its own change).
