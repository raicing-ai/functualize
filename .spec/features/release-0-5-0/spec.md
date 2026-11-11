# Release 0.5.0 — spec

A chore with no user-visible surface of its own: it moves every declared
version from 0.4.0 to 0.5.0 and finalizes the changelog's unreleased section.
The shape gate for this cut is `not-required`, set by the maintainer.

## Acceptance

- AC-1. Every release site declares `0.5.0`: the CONTRIBUTING verification
  one-liner prints exactly one line, `19 "0.5.0"`.
- AC-2. Every in-workspace dependency pin is satisfied by `0.5.0`, and
  `uv lock --check` passes.
- AC-3. `[all]` is unchanged: thirteen entries, no `functualize-secrets-*`, no
  `aws` extra.
- AC-4. `CHANGELOG.md` carries `## [0.5.0] - <date>` under an empty
  `## [Unreleased]`, with a `[0.5.0]` compare link, and every user-visible change
  merged since `v0.4.0` has an entry.
- AC-5. No product code changes. The two `src/functualize/**` paths the range
  touches are the `__version__` string and three version strings in a comment.
