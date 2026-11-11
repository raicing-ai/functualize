# Release 0.5.0 — plan

BEFORE: master declares `0.4.0` at eighteen sites and `0.1.0` for
`functualize-decision-jev`; five merged user-visible changes have no changelog
entry.

AFTER: nineteen sites at `0.5.0`, the decision-jev publishing row updated, the
monorepo example child floors at `>=0.5.0`, `uv.lock` relocked, the missing
changelog entries written, and the unreleased section finalized as `[0.5.0]`.

Merge order: after every change that writes its own `[Unreleased]` entry for
this release, so that no later change writes into a finalized section.

## Surviving smells

- CONTRIBUTING's release checklist still says the one-liner prints `17`; it
  prints `19`. Documentation drift, outside this cut.
