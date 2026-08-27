"""Guards for the wall-clock startup budget tests.

The budget assertions in ``test_startup_budget.py`` measure real elapsed
time during ``FunctualizeApp`` boot. That number is only meaningful in a
clean, serial process.

The ``test-full`` CI tier runs ``pytest --run-slow --cov=functualize -n auto``:
coverage tracing inflates every call in the boot path, and the xdist workers
contend for the runner's cores. A budget assertion there measures the test
harness and the machine's load, not the code under test — which is how
``test-full (3.12)`` came to fail on a docs-only PR with ``552.25ms`` against
a 500ms budget while 8528 other tests passed.

Nothing is lost by skipping them in that tier: the ``test-fast`` tier runs the
same tests with plain ``pytest`` — no coverage, no workers — so the budgets
are still enforced on every PR.
"""

from __future__ import annotations

import os

import pytest


def _instrumentation(config: pytest.Config) -> list[str]:
    """Name the active sources of timing distortion, if any.

    Deliberately uses the xdist env var and pytest-cov's parsed option rather
    than ``sys.gettrace()``: on 3.12+ coverage may attach via ``sys.monitoring``
    instead of the trace hook, so ``gettrace()`` can miss it. Both signals used
    here behave identically across 3.11-3.13.
    """
    active = []
    if os.environ.get("PYTEST_XDIST_WORKER"):
        active.append("xdist")
    if getattr(config.option, "cov_source", None):
        active.append("coverage")
    return active


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    active = _instrumentation(config)
    if not active:
        return
    skip = pytest.mark.skip(
        reason=f"wall-clock budget is not measurable under {'+'.join(active)}"
    )
    for item in items:
        if "perf_budget" in item.keywords:
            item.add_marker(skip)
