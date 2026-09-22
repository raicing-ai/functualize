"""The FUN-25 substrate capability probe — an instrument, not a feature.

Each module here measures **one backend directly**, through that backend's own
client, and reports what a future `StoreProfile` would have to say about it.
The probe deliberately does not measure through functualize: there is no
`StoreProfile` in this codebase and no remote substrate to measure through, so
a probe routed through our adapter would measure the adapter
(`.spec/features/substrate-capability-probe/plan.md` §2, §4).

The boundary rule this directory exists to keep, checkable in one command::

    $ rg -n "^(from|import) functualize" tests/substrate_probe/ \
        | rg -v "^tests/substrate_probe/tier_a.py"
    # must be empty

`tier_a.py` is the single exception: for the JSON filesystem and local SQLite
the shipping substrate *is* the backend under test, which is what makes a
`measured (real service)` row obtainable on a host with no cloud account.

Two rules bind every module:

- **Never invent a cell.** A missing credential yields `NOT MEASURED (no
  credentials)` or a module-level skip — never a failure, never a guess, and
  never a fake standing in for a real service.
- **Gate at module level**, before any client is constructed, so a contributor
  with no AWS account gets a skip rather than a collection error.
"""
