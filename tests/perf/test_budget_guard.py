"""The budgets only assert when the machine can actually be measured.

`tests/conftest.py` skips every `perf_budget` test under coverage or xdist,
because both distort the number. A review of this branch found the third
source, which the harness cannot see: the machine itself. `tests/perf/` was run
on a 12-core box at load 41.6 and reported a warm-command median of 5430ms
against an 1800ms budget — three budgets over, on a commit that touched none of
the boot path (rre F5). Re-run alone at load 4.0, the same file passed 12/12.

So the guard now reads the load average too, and this file tests that guard —
because a guard that silently never fires is worse than no guard, and one that
always fires deletes the budgets without saying so.
"""

from __future__ import annotations

from unittest.mock import patch

from tests.conftest import _MAX_LOAD_PER_CORE, _oversubscription


class TestTheLoadGuardFiresWhereItShould:
    def test_an_idle_machine_keeps_the_budgets(self) -> None:
        with (
            patch("os.getloadavg", return_value=(1.0, 1.0, 1.0)),
            patch("os.cpu_count", return_value=12),
        ):
            assert _oversubscription() is None

    def test_a_machine_at_the_threshold_keeps_the_budgets(self) -> None:
        """`>`, not `>=` — the threshold is the last load that still asserts."""
        with (
            patch("os.getloadavg", return_value=(24.0, 1.0, 1.0)),
            patch("os.cpu_count", return_value=12),
        ):
            assert _oversubscription() is None

    def test_the_load_the_reviewer_measured_skips(self) -> None:
        """41.55 on 12 cores — the real number from the review."""
        with (
            patch("os.getloadavg", return_value=(41.55, 40.11, 29.93)),
            patch("os.cpu_count", return_value=12),
        ):
            ratio = _oversubscription()

        assert ratio is not None
        assert ratio > _MAX_LOAD_PER_CORE


class TestAnUnmeasurableMachineStillAsserts:
    """Absence of a reading is not evidence of load.

    The alternative — treating "cannot measure" as "assume busy" — would
    disable every budget on any platform without `getloadavg`, and nothing
    would say so. Failing to skip is recoverable (a flake, re-run alone);
    failing to assert is not (a regression ships).
    """

    def test_no_getloadavg(self) -> None:
        import os

        with (
            patch.object(os, "cpu_count", return_value=12),
            patch.object(os, "getloadavg", None, create=True),
        ):
            assert _oversubscription() is None

    def test_no_cpu_count(self) -> None:
        with (
            patch("os.getloadavg", return_value=(99.0, 99.0, 99.0)),
            patch("os.cpu_count", return_value=None),
        ):
            assert _oversubscription() is None

    def test_getloadavg_raising(self) -> None:
        with (
            patch("os.getloadavg", side_effect=OSError("not available")),
            patch("os.cpu_count", return_value=12),
        ):
            assert _oversubscription() is None


def test_the_guard_is_wired_into_the_skip_reason() -> None:
    """The helper is not enough — it has to reach `_timing_instrumentation`.

    Without this the guard could compute the right ratio and never be
    consulted, which is exactly the shape of bug the review found in the
    budgets themselves.
    """
    from tests.conftest import _timing_instrumentation

    class _Option:
        cov_source = None

    class _Config:
        option = _Option()

    with (
        patch("os.getloadavg", return_value=(41.55, 40.11, 29.93)),
        patch("os.cpu_count", return_value=12),
        patch.dict("os.environ", {}, clear=False),
    ):
        import os

        os.environ.pop("PYTEST_XDIST_WORKER", None)
        active = _timing_instrumentation(_Config())  # type: ignore[arg-type]

    assert any("loaded" in reason for reason in active), active
