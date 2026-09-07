"""The handler reports the run's outcome, not a constant (STATUS #21).

Authoring-time behaviour::

    result = app.execute(job_name, **job_kwargs)
    return {"statusCode": 200, "body": result.return_value}

``result.status`` was never read. A failure, a refusal, and a workflow paused
at a gate all arrived as ``{"statusCode": 200, "body": None}`` — the same shape
as a job that succeeded and returned nothing. Only an exception escaping
``execute()`` produced a 500, and the engine's design is that failures are
*returned*, not raised, so the branch that reported failure was the one the
engine tries hardest never to take.

This matters beyond tidiness: ``discovery-and-gate-defects``/3.3 turns an
unresolvable workflow gate into a returned ``BLOCKED``. Without this, that
change converts a visible crash into a silent 200.
"""

from __future__ import annotations

import pytest
from functualize_lambda import LambdaAdapter

from functualize.types import RunStatus, http_status_for_status
from tests.conftest import FakeApp, FakeJobResult

#: Every status a *request* can terminate on. RUNNING is excluded because a
#: synchronous handler cannot return while its job is still running.
TERMINAL = [s for s in RunStatus if s is not RunStatus.RUNNING]


def _adapter(status: RunStatus, **kwargs: object) -> LambdaAdapter:
    app = FakeApp(
        execute_results={"deploy": FakeJobResult(status=status, **kwargs)}  # type: ignore[arg-type]
    )
    adapter = LambdaAdapter()
    adapter(app)
    return adapter


class TestTheHeadline:
    def test_blocked_is_202_not_200(self) -> None:
        """The specific regression STATUS #21 names."""
        response = _adapter(RunStatus.BLOCKED).run({"job": "deploy"}, None)
        assert response["statusCode"] == 202

    def test_failure_is_500_even_though_nothing_was_raised(self) -> None:
        """The engine returns failures. The old code only saw raised ones."""
        response = _adapter(RunStatus.FAILURE).run({"job": "deploy"}, None)
        assert response["statusCode"] == 500

    def test_not_every_outcome_is_200(self) -> None:
        """A guard against the mapping being reintroduced as a constant."""
        codes = {
            _adapter(s).run({"job": "deploy"}, None)["statusCode"] for s in TERMINAL
        }
        assert len(codes) > 1


class TestEveryTerminalStatus:
    @pytest.mark.parametrize("status", TERMINAL, ids=lambda s: s.name)
    def test_fat_handler_matches_the_table(self, status: RunStatus) -> None:
        response = _adapter(status).run({"job": "deploy"}, None)
        assert response["statusCode"] == http_status_for_status(status)

    @pytest.mark.parametrize("status", TERMINAL, ids=lambda s: s.name)
    def test_thin_handler_matches_the_table(self, status: RunStatus) -> None:
        """Two handler shapes, one table — they drifted apart once already."""
        handler = _adapter(status).make_handler("deploy")
        assert handler({}, None)["statusCode"] == http_status_for_status(status)

    @pytest.mark.parametrize("status", TERMINAL, ids=lambda s: s.name)
    def test_the_status_name_is_reported_too(self, status: RunStatus) -> None:
        """A code partitions; the name identifies. CANCELLED and UNKNOWN are
        both 500, so the code alone cannot say which happened."""
        response = _adapter(status).run({"job": "deploy"}, None)
        assert response["status"] == status.value


class TestTheBodyContract:
    def test_a_successful_return_value_is_unchanged(self) -> None:
        """`status` is added, not substituted: existing callers keep working."""
        response = _adapter(RunStatus.SUCCESS, return_value={"n": 1}).run(
            {"job": "deploy"}, None
        )
        assert response["body"] == {"n": 1}

    def test_a_returned_exception_reaches_the_caller(self) -> None:
        """A 500 whose body is `null` tells a caller nothing at all."""
        response = _adapter(RunStatus.FAILURE, exception=ValueError("bad region")).run(
            {"job": "deploy"}, None
        )
        assert response["statusCode"] == 500
        assert "bad region" in response["error"]

    def test_no_error_key_on_a_clean_run(self) -> None:
        assert "error" not in _adapter(RunStatus.SUCCESS).run({"job": "deploy"}, None)


class TestUnchangedPaths:
    def test_a_raised_exception_is_still_500(self) -> None:
        """The pre-existing escape hatch must survive."""
        adapter = LambdaAdapter()
        adapter(FakeApp(execute_error=RuntimeError("boom")))
        response = adapter.run({"job": "deploy"}, None)
        assert response["statusCode"] == 500
        assert "boom" in response["body"]

    def test_a_missing_job_field_is_still_400(self) -> None:
        adapter = LambdaAdapter()
        adapter(FakeApp())
        assert adapter.run({}, None)["statusCode"] == 400
