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

Below that skip, a shared host still turns budgets red with no code cause: a
serial run at 0.55-0.7x of 6 cores read `boot.total` 614ms against 500ms. Those
reds are kept — skipping there would also stop the budgets on a small CI runner
— and each one now carries the load it ran at, so a red is never one a reader
has to guess about.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import (
    _CONTENDED_LOAD_PER_CORE,
    _MAX_LOAD_PER_CORE,
    _budget_red_load_note,
    _oversubscription,
)


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


class TestABudgetRedCarriesItsLoad:
    def test_a_contended_host_is_named_as_a_possible_cause(self) -> None:
        """4.0 on 6 cores — inside the 0.55-0.7x band a red was measured in."""
        with (
            patch("os.getloadavg", return_value=(4.0, 3.3, 2.1)),
            patch("os.cpu_count", return_value=6),
        ):
            note = _budget_red_load_note()

        assert "host load 4.00 / 3.30 / 2.10" in note
        assert "on 6 cores = 0.67x per core" in note
        assert f"above {_CONTENDED_LOAD_PER_CORE}x" in note
        assert "idle host" in note

    def test_a_host_at_the_mark_is_not_blamed(self) -> None:
        """`>`, not `>=`, as for the skip: 3.0 on 6 cores is still quiet."""
        with (
            patch("os.getloadavg", return_value=(3.0, 3.0, 3.0)),
            patch("os.cpu_count", return_value=6),
        ):
            note = _budget_red_load_note()

        assert "= 0.50x per core" in note
        assert "load does not explain it" in note
        assert "idle host" not in note

    def test_an_unreadable_load_says_so(self) -> None:
        """Silence would read as "the host was quiet", which nobody measured."""
        with (
            patch.object(os, "cpu_count", return_value=6),
            patch.object(os, "getloadavg", None, create=True),
        ):
            note = _budget_red_load_note()

        assert "not readable" in note

    def test_the_mark_sits_below_the_skip(self) -> None:
        """Between the two a budget asserts and its red is labelled; a mark at
        or above the skip would label nothing."""
        assert 0 < _CONTENDED_LOAD_PER_CORE < _MAX_LOAD_PER_CORE


_INNER_CONFTEST = """\
import os

# Collection reads an idle host, so the skip guard never fires here and every
# budget below asserts. Each test then sets the load its red is reported at.
os.getloadavg = lambda: (0.0, 0.0, 0.0)
os.cpu_count = lambda: 6

from tests.conftest import (  # noqa: E402,F401
    pytest_addoption,
    pytest_collection_modifyitems,
    pytest_runtest_makereport,
    pytest_terminal_summary,
)
"""

_INNER_TESTS = """\
import os

import pytest


def _host(one_minute):
    os.getloadavg = lambda: (one_minute, 1.0, 1.0)


@pytest.mark.perf_budget
def test_red_on_a_contended_host():
    _host(4.0)
    assert False, "Total boot time 614.00ms exceeds budget of 500.0ms"


@pytest.mark.perf_budget
def test_red_on_a_quiet_host():
    _host(0.6)
    assert False, "Total boot time 614.00ms exceeds budget of 500.0ms"


@pytest.mark.perf_budget
def test_green_on_a_contended_host():
    _host(4.0)


def test_red_without_the_marker():
    _host(4.0)
    assert False
"""

_SUMMARY_HEADER = "perf_budget reds and the host load they ran at"


@pytest.fixture(scope="module")
def inner_session(tmp_path_factory: pytest.TempPathFactory) -> str:
    """One real pytest session wired with this suite's own hooks.

    A subprocess rather than a call to the hook, because what has to be
    proved is that pytest reaches it: a hook with the wrong name or wrapper
    style is silently never called, and the budgets then go red bare again.
    """
    root = tmp_path_factory.mktemp("budget_red")
    (root / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    perf_budget: wall-clock budget\n"
    )
    (root / "conftest.py").write_text(_INNER_CONFTEST)
    (root / "test_budget.py").write_text(_INNER_TESTS)

    # An outer xdist or coverage run must not leak in: a worker id would make
    # the inner guard skip every budget, and nothing would go red.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTEST_", "COV_CORE_"))
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", str(root)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    return completed.stdout


def _summary_lines(output: str) -> list[str]:
    """The lines of the load summary section, up to the next banner."""
    _, found, rest = output.partition(_SUMMARY_HEADER)
    assert found, output
    lines = rest.splitlines()[1:]
    end = next((i for i, line in enumerate(lines) if line.startswith("=")), None)
    return lines[:end]


class TestTheLoadReachesTheReport:
    def test_a_budget_red_stays_a_red(self, inner_session: str) -> None:
        """The load is attached, never used to turn the failure into a skip."""
        assert "3 failed, 1 passed" in inner_session, inner_session

    def test_each_budget_red_prints_its_load_section(self, inner_session: str) -> None:
        assert inner_session.count("perf_budget host load") == 2, inner_session

    def test_the_summary_names_each_budget_red_with_its_load(
        self, inner_session: str
    ) -> None:
        contended, quiet = _summary_lines(inner_session)

        assert contended.startswith("test_budget.py::test_red_on_a_contended_host: ")
        assert "= 0.67x per core" in contended
        assert f"above {_CONTENDED_LOAD_PER_CORE}x" in contended
        assert quiet.startswith("test_budget.py::test_red_on_a_quiet_host: ")
        assert "= 0.10x per core" in quiet
        assert "load does not explain it" in quiet
