# Tasks — `functualize-secrets-bitwarden` ships its PEP 561 marker from inside the package

Only an unchecked task in the lowest incomplete wave may start. A task is
checked only after its gate passes.

## Wave 0 — the marker lives in the package

- [x] **T1 — Place `py.typed` inside the package.**
  - Scope: `plugins/credentials/functualize-secrets-bitwarden/src/functualize_secrets_bitwarden/py.typed`
    (0 bytes; moved from the plugin root).
  - Gate: `test -f` on that path exits 0 (AC-4); after `uv sync --all-packages`
    the editable package directory contains the marker (AC-5).

## Wave 1 — one packaging convention, true documentation

- [x] **T2 — Remove the `force-include` mapping.**
  - Scope: `plugins/credentials/functualize-secrets-bitwarden/pyproject.toml`.
  - Gate: `grep -rn force-include plugins/*/*/pyproject.toml` finds nothing
    (AC-4); `uv build --package functualize-secrets-bitwarden` gives a 12-file
    wheel listing `functualize_secrets_bitwarden/py.typed` at 0 bytes,
    byte-identical to the `force-include` build (AC-1); the sdist lists the
    marker under `src/functualize_secrets_bitwarden/` only (AC-3).
    Call path: `uv build` (hatchling wheel target,
    `packages = ["src/functualize_secrets_bitwarden"]`) → wheel → install →
    mypy's PEP 561 lookup. Sabotage: the same build without the marker lists
    eleven files.
- [x] **T3 — Correct the Tier 2 reason in `plugins/PUBLISHING.md`.**
  - Scope: `plugins/PUBLISHING.md`, tier table notes.
  - Gate: the sentence states bitwarden has a `py.typed` marker and sits at
    Tier 2 for the missing `examples/` directory (AC-6).

## Wave 2 — record and verify

- [x] **T4 — Changelog and gates.**
  - Scope: `CHANGELOG.md`.
  - Gate: `[Unreleased]` entry present (AC-7); mypy in a clean venv with the
    built wheel reveals `def () -> functualize_secrets_bitwarden.PasswordManagerProvider`
    (AC-2); `uv run ruff check plugins/credentials/functualize-secrets-bitwarden`
    passes; `uv run pytest plugins/credentials/functualize-secrets-bitwarden/tests -q`
    and `uv run pytest tests/test_packaging.py -q` pass.

## Wave 3 — clear the feature artifacts

- [ ] **T5 — Deletion-only cleanup.**
  - Scope: `.spec/features/secrets-bitwarden-py-typed/` only, after the durable
    record is in `.spec/STATUS.md`.
  - Gate: the parent commit's validation jobs are green; the commit's entire
    diff is `git rm -r .spec/features/secrets-bitwarden-py-typed`;
    `spec-artifacts-cleared` passes.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["T1"]},
    {"id": 1, "tasks": ["T2", "T3"]},
    {"id": 2, "tasks": ["T4"]},
    {"id": 3, "tasks": ["T5"]}
  ]
}
```
