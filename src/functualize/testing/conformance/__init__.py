"""The runtime-store conformance suite, shipped so any backend can run it.

``run_baseline(make_store)`` holds every store to the same port behaviour;
``run_capability_tiers(make_store)`` holds it to what its profile declares;
``make_store`` builds a store over a directory, and building it again over
the same directory must reopen the same data. Plain functions raising
``AssertionError`` — no test framework is imported, so a third-party backend
runs it from whatever harness it already has::

    from functualize.testing.conformance import run_baseline
    run_baseline(lambda root: MyRuntimeStore(root / "db"))
"""

from functualize.testing.conformance.baseline import run_baseline
from functualize.testing.conformance.capabilities import run_capability_tiers

__all__ = ["run_baseline", "run_capability_tiers"]
