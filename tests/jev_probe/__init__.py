"""The Jev / System One capability probe — an instrument, not a feature.

Each module here measures **one row of the matrix** against the real
service, over the wire, and reports the value it observed. The probe
deliberately does not measure through functualize: there is no
`DecisionProvider` adapter in this codebase yet, so a probe routed through one
would measure the adapter rather than the provider. Stage 1's adapter encodes
what this directory pins.

The boundary rule this directory exists to keep, checkable in one command::

    $ rg -n "^(from|import) functualize" tests/jev_probe/
    # must be empty

Two rules bind every module:

- **Never invent a cell.** An absent credential or an unreachable endpoint
  yields `NOT MEASURED (no credentials)` / `NOT MEASURED (service not
  reachable)` as a module-level skip — never a failure, never a guess, and
  never a recorded fixture standing in for the service.
- **Gate at module level**, before the first request, so a contributor with no
  credential gets a skip rather than a collection error.

The numbers these modules print are transcribed into
`contributor/reference/jev-system-one-capability-matrix.md`; the reference says
which commit they came from. Nothing here is read *by* the product, and no
number here is a vendor claim — rows that could not be measured say so.
"""

from __future__ import annotations
