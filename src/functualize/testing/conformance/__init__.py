"""The runtime-store conformance suite, shipped so any backend can run it.

``run_baseline(make_store)`` holds every store to the same port behaviour;
``run_capability_tiers(make_store)`` holds it to what its profile declares;
``make_store`` builds a store over a directory, and building it again over
the same directory must reopen the same data. Plain functions raising
``AssertionError`` — no test framework is imported, so a third-party backend
runs it from whatever harness it already has::

    from functualize.testing.conformance import run_baseline
    run_baseline(lambda root: MyRuntimeStore(root / "db"))

Capabilities the port cannot observe run through *harness hooks*
(:mod:`functualize.testing.conformance.hooks`): the backend's test code hands
the suite instruments that build faulted stores, read committed intents and
lay down historical schemas. A tier needing an absent hook refuses rather
than skips, and :func:`capability_report` reports each tier that ran with
the strength it was actually exercised at.
"""

from functualize.testing.conformance.baseline import run_baseline
from functualize.testing.conformance.capabilities import (
    capability_report,
    run_capability_tiers,
)
from functualize.testing.conformance.hooks import (
    CapabilityReport,
    HarnessHooks,
    MigrationHarness,
    OutboxProbe,
    RecordedIntent,
    StatementFault,
    StatementFaults,
    TierRun,
)

__all__ = [
    "run_baseline",
    "run_capability_tiers",
    "capability_report",
    "HarnessHooks",
    "StatementFaults",
    "StatementFault",
    "OutboxProbe",
    "RecordedIntent",
    "MigrationHarness",
    "CapabilityReport",
    "TierRun",
]
