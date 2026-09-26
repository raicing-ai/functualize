"""The gate itself, tested — because every row above is measured through it.

A gate that silently stops gating turns "skipped, no credentials" into "green,
measured nothing", and this probe's whole value is that the difference is
visible. These are the cheapest tests here and the ones that keep
`NOT MEASURED` honest; they run on every machine, credentialed or not.

This module is also where the instrument's **offline** falsifiers live: the
import boundary, the record's refusal to invent a cell, and the terminal
summary's behaviour when a run measured nothing at all. Without a module like
this, `uv run pytest -q tests/jev_probe/` on a credential-less host would
collect no runnable item and exit 5 (`NO_TESTS_COLLECTED`) rather than green.
"""

from __future__ import annotations

import re
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from tests.jev_probe.conftest import (
    missing_env,
    pytest_collect_file,
    pytest_terminal_summary,
    reachable,
    require_client,
    require_endpoint,
    require_env,
)
from tests.jev_probe.report import (
    NOT_MEASURED,
    REAL_SERVICE,
    REPORT,
    Report,
    measured,
    not_measured,
)

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter

_HERE = Path(__file__).parent

#: The boundary rule this directory exists to keep, as one regex.
_PRODUCT_IMPORT_RE = re.compile(r"^(from|import)\s+functualize", re.MULTILINE)


@contextmanager
def _isolated_record() -> Iterator[Report]:
    """Record onto the real record and put the run's facts back afterwards.

    The tests below assert what `render()` prints; writing to a second `Report`
    would assert the printer while leaving the printer that runs unasserted. The
    run's own facts are restored in `finally`, so a credentialed run's matrix
    survives this module running after the measurement modules.
    """
    saved = list(REPORT.facts)
    REPORT.clear()
    try:
        yield REPORT
    finally:
        REPORT.clear()
        REPORT.facts.extend(saved)


class TestTheCredentialGate:
    def test_absent_and_blank_variables_both_count_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JEV_GATE_SET", "value")
        monkeypatch.setenv("JEV_GATE_BLANK", "   ")
        monkeypatch.delenv("JEV_GATE_ABSENT", raising=False)

        assert missing_env("JEV_GATE_SET") == ()
        assert missing_env("JEV_GATE_BLANK", "JEV_GATE_ABSENT") == (
            "JEV_GATE_BLANK",
            "JEV_GATE_ABSENT",
        )

    def test_a_missing_variable_skips_at_module_level(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Module level, not test level — before the first request is sent.

        This is the property the credential-less acceptance criterion rests on:
        the gate runs at import time, so a contributor with no key sees a skip
        rather than a collection error.
        """
        monkeypatch.delenv("JEV_GATE_ABSENT", raising=False)

        with pytest.raises(pytest.skip.Exception) as caught:
            require_env("Jev / System One", "JEV_GATE_ABSENT")

        assert caught.value.allow_module_level is True

    def test_the_skip_reason_is_the_matrix_cell_and_names_what_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reference transcribes this reason; it never composes one."""
        monkeypatch.setenv("JEV_GATE_SET", "value")
        monkeypatch.delenv("JEV_GATE_ABSENT", raising=False)

        with pytest.raises(pytest.skip.Exception) as caught:
            require_env(
                "Jev / System One",
                "JEV_GATE_SET",
                "JEV_GATE_ABSENT",
                hint="See the reference's Provenance section.",
            )

        reason = str(caught.value)
        assert "Jev / System One" in reason
        assert "NOT MEASURED (no credentials)" in reason
        assert "JEV_GATE_ABSENT" in reason
        assert "JEV_GATE_SET" not in reason, "a present variable is not a reason"
        assert ".env.example" in reason
        assert "See the reference's Provenance section." in reason

    def test_a_fully_credentialed_environment_does_not_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JEV_GATE_SET", "value")
        assert require_env("Jev / System One", "JEV_GATE_SET") is None


class TestTheReachabilityGate:
    def test_a_listening_socket_is_reachable(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            assert reachable(f"http://127.0.0.1:{port}") is True

    def test_nothing_listening_is_not_reachable(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        assert reachable(f"http://127.0.0.1:{port}", timeout=0.5) is False

    def test_an_empty_or_unparseable_endpoint_is_a_no_not_a_crash(self) -> None:
        """The gate must skip where it cannot measure, never raise."""
        assert reachable("") is False
        assert reachable("not-a-url") is False

    def test_an_unreachable_endpoint_skips_and_names_the_endpoint(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}"

        with pytest.raises(pytest.skip.Exception) as caught:
            require_endpoint("Jev / System One", endpoint)

        assert caught.value.allow_module_level is True
        assert endpoint in str(caught.value)
        assert "NOT MEASURED (service not reachable)" in str(caught.value)


class TestTheClientGate:
    def test_an_absent_client_library_skips_at_module_level(self) -> None:
        with pytest.raises(pytest.skip.Exception) as caught:
            require_client("Jev / System One", "jev_probe_no_such_client_library")

        assert caught.value.allow_module_level is True
        assert "NOT MEASURED (client absent)" in str(caught.value)

    def test_a_present_client_library_is_returned(self) -> None:
        assert require_client("stdlib", "json").dumps({"a": 1}) == '{"a": 1}'


class TestTheMeasurementModulesAreCollectedAtAll:
    """The probe's modules are not named `test_*.py`, so the hook is load-bearing.

    Contract, identities, stability, cost and errors are rows of the matrix by
    filename, and none matches pytest's default `python_files`. Without
    `pytest_collect_file` a plain `uv run pytest` collects nothing here and the
    "skips, never fails" guarantee is never exercised by any run.
    """

    @pytest.fixture
    def parent(self, request: pytest.FixtureRequest) -> pytest.Collector:
        collector = request.node.parent.parent
        assert isinstance(collector, pytest.Collector)
        return collector

    def test_a_measurement_module_is_collected(self, parent: pytest.Collector) -> None:
        path = _HERE / "contract.py"
        if parent.session.isinitpath(path):
            pytest.skip(
                "this module was named on the command line, so the built-in "
                "collector owns it — see the initpath case below"
            )
        assert isinstance(pytest_collect_file(path, parent), pytest.Module)

    def test_machinery_is_not_collected_as_a_measurement(
        self, parent: pytest.Collector
    ) -> None:
        assert pytest_collect_file(_HERE / "conftest.py", parent) is None
        assert pytest_collect_file(_HERE / "__init__.py", parent) is None
        assert pytest_collect_file(_HERE / "client.py", parent) is None
        assert pytest_collect_file(_HERE / "report.py", parent) is None

    def test_a_test_module_is_left_to_the_builtin_collector(
        self, parent: pytest.Collector
    ) -> None:
        """Returning a second Module for it would run every test here twice."""
        assert pytest_collect_file(_HERE / "test_gating.py", parent) is None

    def test_a_module_named_on_the_command_line_is_left_to_the_builtin(self) -> None:
        """The same rule, for the case the built-in reaches by a different route.

        `_pytest.python.pytest_collect_file` collects an *init path* — anything
        named on the command line — whatever its name, so for an explicitly
        named measurement module both collectors fire and the module is
        collected twice: `uv run pytest tests/jev_probe/contract.py` would run
        every row twice and report doubled counts. Asserted against a stub
        session rather than by nesting a second pytest run inside this one: the
        guard returns before it touches `parent`, so an object that answers
        `isinitpath` alone reaches the branch deterministically.
        """

        class _Session:
            @staticmethod
            def isinitpath(path: object, *, with_parents: bool = False) -> bool:
                return True

        class _NamedOnTheCommandLine:
            session = _Session()

        parent = cast("pytest.Collector", _NamedOnTheCommandLine())
        assert pytest_collect_file(_HERE / "contract.py", parent) is None

    def test_a_non_python_file_is_not_collected(self, parent: pytest.Collector) -> None:
        assert pytest_collect_file(_HERE / "notes.md", parent) is None


class TestTheRecordCannotInventACell:
    """`measured` records an observation; `not_measured` records a gap and why."""

    def test_a_measured_cell_needs_the_value_that_was_measured(self) -> None:
        with pytest.raises(ValueError, match="value that was measured"):
            measured("A", "Z1", "a cell with no value", "   ")

    def test_an_unmeasured_cell_needs_its_reason(self) -> None:
        with pytest.raises(ValueError, match="must say why"):
            not_measured("A", "Z2", "a cell with no reason", "")

    def test_an_unknown_row_is_refused_by_both(self) -> None:
        with pytest.raises(ValueError, match="is not a matrix row"):
            measured("Q", "Z3", "a row nobody defines", "1")
        with pytest.raises(ValueError, match="is not a matrix row"):
            not_measured("Q", "Z4", "a row nobody defines", "because")

    def test_a_gap_renders_as_a_gap_and_not_as_a_number(self) -> None:
        """A gap records its evidence level as well as its reason.

        The record has to hold both kinds of cell, so the stamp is read off the
        fact rather than assumed by the printer: a gap printed under a
        measurement's stamp is the over-claim this instrument exists to prevent.
        """
        with _isolated_record() as report:
            not_measured("D", "Z5", "cost with no credential", "the account has none")
            measured("B", "Z6", "a number that was measured", "0.55")
            rendered = report.render()

        assert NOT_MEASURED in rendered
        assert "the account has none" in rendered
        assert rendered.index("B. Identities") < rendered.index("D. Cost shape")
        assert "Z5" in rendered and "Z6" in rendered
        assert "2 facts recorded." in rendered
        assert REAL_SERVICE in rendered
        assert rendered.count(REAL_SERVICE) == 1, (
            "a gap is not stamped as a measurement"
        )

    def test_the_runs_own_facts_survive_the_module(self) -> None:
        """The restore matters: this module may run after a measured row."""
        with _isolated_record() as report:
            measured("B", "Z6", "a number that was measured", "0.55")
            assert "Z6" in report.render()

        assert "Z6" not in REPORT.render()


class _FakeReporter:
    """The whole of `TerminalReporter` that the summary reads."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.stats: dict[str, list[object]] = {"skipped": []}

    def write_line(self, line: str = "") -> None:
        self.lines.append(line)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class _SkippedReport:
    """As much of a `TestReport` as a skip reason is read through."""

    def __init__(self, first_line: str) -> None:
        self.longrepr = f"Skipped: {first_line}\n\nreason chain continues"


def _summary(reporter: _FakeReporter) -> str:
    """Run the real terminal summary against a reporter that only records."""
    pytest_terminal_summary(
        cast("TerminalReporter", reporter), 0, cast("pytest.Config", None)
    )
    return reporter.text


class TestTheSummaryPrintsWhatWasMeasured:
    """`-q` prints an item's pass and nothing a passing module printed.

    So a run whose numbers only ever reached a module capture would publish
    nothing at all — which is why the record is printed from the summary hook
    and why these two cases, the empty record and the full one, are asserted.
    """

    def test_an_empty_record_prints_the_reasons_it_skipped(self) -> None:
        reporter = _FakeReporter()
        reporter.stats["skipped"] = [
            _SkippedReport(
                "Jev / System One: NOT MEASURED (no credentials) — "
                "OPENCODE_API_KEY not set in the environment. …"
            )
        ]
        with _isolated_record():
            text = _summary(reporter)

        assert "NOT MEASURED (no credentials)" in text
        assert "OPENCODE_API_KEY" in text
        assert "No facts recorded." in text

    def test_a_recorded_run_prints_the_values_by_row(self) -> None:
        reporter = _FakeReporter()
        with _isolated_record():
            measured("E", "Z7", "a refusal", "HTTP 422 · too_short")
            text = _summary(reporter)

        assert "E. Error taxonomy" in text
        assert "Z7" in text
        assert "HTTP 422 · too_short" in text
        assert "measured (real service)" in text


class TestTheBoundaryIsKept:
    """This directory measures the wire; it never imports the thing it measures."""

    def test_no_module_imports_the_product(self) -> None:
        offenders = {
            path.name: _PRODUCT_IMPORT_RE.findall(path.read_text())
            for path in sorted(_HERE.glob("*.py"))
            if _PRODUCT_IMPORT_RE.search(path.read_text())
        }
        assert not offenders, (
            "a probe that imports functualize measures the adapter rather than "
            f"the provider: {offenders}"
        )


def test_every_probe_item_carries_the_marker(request: pytest.FixtureRequest) -> None:
    """Registered in `pyproject.toml`, applied by the conftest, not by hand."""
    assert request.node.get_closest_marker("jev_probe") is not None
