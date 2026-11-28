# Tasks — `functualize-secrets-aws` ships its PEP 561 marker

Only an unchecked task in the lowest incomplete wave may start. A task is
checked only after its gate passes.

## Wave 0 — the marker reaches the wheel

- [x] **1.1 — Add `py.typed` to the package.**
  - Scope: `plugins/credentials/functualize-secrets-aws/src/functualize_secrets_aws/py.typed`.
  - Gate: `uv build --package functualize-secrets-aws`, then `unzip -l` on the
    wheel lists `functualize_secrets_aws/py.typed` (AC-1); mypy on a consumer
    in a clean venv with that wheel installed reveals the real type of
    `SecretsManagerProvider` and reports no `import-untyped` (AC-2).
    Call path: `uv build` (hatchling wheel target,
    `packages = ["src/functualize_secrets_aws"]`) → wheel → install → mypy's
    PEP 561 lookup. Sabotage: the same build and mypy run without the marker
    list nine files and report `import-untyped` / `Any`.

## Wave 1 — record and verify

- [x] **2.1 — Changelog and gates.**
  - Scope: `CHANGELOG.md`.
  - Gate: `[Unreleased]` entry present (AC-3); `uv run ruff check src/ tests/ plugins/ examples/`,
    `uv run ruff format --check src/ tests/ plugins/ examples/`, `uv run mypy src/`,
    `uv run lint-imports` pass; the plugin's own suite
    `uv run pytest plugins/credentials/functualize-secrets-aws/tests -q` passes.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1"]}
  ]
}
```
