"""The gate itself, tested — because every later wave is measured through it.

A gate that silently stops gating turns "skipped, no credentials" into "green,
measured nothing", and the probe's whole value is that the difference is
visible. These are the cheapest tests in the ticket and they are the ones that
keep `NOT MEASURED` honest.

Task 1.2 lists `conftest.py` and `pyproject.toml` as its files; this module is
a declared deviation. Without it `uv run pytest -q tests/substrate_probe/`
collects no runnable test on a credential-less host and exits **5**
(`NO_TESTS_COLLECTED`) rather than green, so the task's own gate could not be
run as written.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from tests.substrate_probe.conftest import (
    missing_env,
    pytest_collect_file,
    reachable,
    require_client,
    require_endpoint,
    require_env,
)

_HERE = Path(__file__).parent


class TestTheCredentialGate:
    def test_absent_and_blank_variables_both_count_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUN25_GATE_SET", "value")
        monkeypatch.setenv("FUN25_GATE_BLANK", "   ")
        monkeypatch.delenv("FUN25_GATE_ABSENT", raising=False)

        assert missing_env("FUN25_GATE_SET") == ()
        assert missing_env("FUN25_GATE_BLANK", "FUN25_GATE_ABSENT") == (
            "FUN25_GATE_BLANK",
            "FUN25_GATE_ABSENT",
        )

    def test_a_missing_variable_skips_at_module_level(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Module level, not test level — before any client is constructed.

        This is the property AC5 rests on: at import time there is nothing to
        raise a collection error, so a contributor with no AWS account sees a
        skip rather than an error.
        """
        monkeypatch.delenv("FUN25_GATE_ABSENT", raising=False)

        with pytest.raises(pytest.skip.Exception) as caught:
            require_env("AWS S3", "FUN25_GATE_ABSENT")

        assert caught.value.allow_module_level is True

    def test_the_skip_reason_is_the_matrix_cell_and_names_what_is_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """6.1 transcribes this reason; it never composes one."""
        monkeypatch.setenv("FUN25_GATE_SET", "value")
        monkeypatch.delenv("FUN25_GATE_ABSENT", raising=False)

        with pytest.raises(pytest.skip.Exception) as caught:
            require_env(
                "AWS DynamoDB",
                "FUN25_GATE_SET",
                "FUN25_GATE_ABSENT",
                hint="See FUN-25.",
            )

        reason = str(caught.value)
        assert "AWS DynamoDB" in reason
        assert "NOT MEASURED (no credentials)" in reason
        assert "FUN25_GATE_ABSENT" in reason
        assert "FUN25_GATE_SET" not in reason, "a present variable is not a reason"
        assert ".env.example" in reason
        assert "See FUN-25." in reason

    def test_a_fully_credentialed_environment_does_not_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUN25_GATE_SET", "value")
        assert require_env("AWS S3", "FUN25_GATE_SET") is None


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
            require_endpoint("floci", endpoint)

        assert caught.value.allow_module_level is True
        assert endpoint in str(caught.value)
        assert "NOT MEASURED (service not reachable)" in str(caught.value)


class TestTheClientGate:
    def test_an_absent_client_library_skips_at_module_level(self) -> None:
        with pytest.raises(pytest.skip.Exception) as caught:
            require_client("Turso/libSQL", "fun25_no_such_client_library")

        assert caught.value.allow_module_level is True
        assert "NOT MEASURED (client absent)" in str(caught.value)

    def test_a_present_client_library_is_returned(self) -> None:
        assert require_client("stdlib", "json").dumps({"a": 1}) == '{"a": 1}'


class TestTheMeasurementModulesAreCollectedAtAll:
    """The probe's modules are not named `test_*.py`, so the hook is load-bearing.

    `tasks.md` fixes those names — `tier_a.py`, `d1.py`, `s3.py`,
    `_floci_survey.py` — and none matches pytest's default `python_files`.
    Without `pytest_collect_file` a plain `uv run pytest` collects nothing here
    and the "skips, never fails" guarantee is never exercised by any run.
    """

    @pytest.fixture
    def parent(self, request: pytest.FixtureRequest) -> pytest.Collector:
        collector = request.node.parent.parent
        assert isinstance(collector, pytest.Collector)
        return collector

    def test_a_measurement_module_is_collected(self, parent: pytest.Collector) -> None:
        collected = pytest_collect_file(_HERE / "_floci_survey.py", parent)
        assert isinstance(collected, pytest.Module)

    def test_machinery_is_not_collected_as_a_measurement(
        self, parent: pytest.Collector
    ) -> None:
        assert pytest_collect_file(_HERE / "conftest.py", parent) is None
        assert pytest_collect_file(_HERE / "__init__.py", parent) is None

    def test_a_test_module_is_left_to_the_builtin_collector(
        self, parent: pytest.Collector
    ) -> None:
        """Returning a second Module for it would run every test here twice."""
        assert pytest_collect_file(_HERE / "test_gating.py", parent) is None

    def test_a_non_python_file_is_not_collected(self, parent: pytest.Collector) -> None:
        assert pytest_collect_file(_HERE / "notes.md", parent) is None


def test_every_probe_item_carries_the_marker(request: pytest.FixtureRequest) -> None:
    """Registered in `pyproject.toml`, applied by the conftest, not by hand."""
    assert request.node.get_closest_marker("substrate_probe") is not None
