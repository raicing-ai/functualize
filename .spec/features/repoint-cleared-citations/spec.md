## Why

Around twenty source comments cite documents inside `.spec/features/<package>/`
trees that are deleted at each package's clearing step, so a reader following
one lands nowhere. The clearing step cannot repoint anything: its acceptance is
deletion-only.

## Change

Comment and test-comment citations only — no behavior. Every citation that
named a cleared feature-local document now names the durable location the
content actually lives at (contributor/reference pages, ADRs, the spec-workflow
contract), and states the package it came from where the provenance matters.

## Acceptance

1. No citation inside `src/` names a `.spec/features/**` path.
2. Every newly cited target resolves in the repository.
3. `ruff check`, `ruff format --check`, `mypy src/` stay clean (comment edits
   re-wrap lines).

## Shape

Comments-only repointing with no user-visible surface: shape gate not-required.
