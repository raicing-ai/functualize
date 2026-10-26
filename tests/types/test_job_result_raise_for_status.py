"""Pin the existing JobResult value shape before adding its checked method."""

from dataclasses import fields

import pytest

from functualize._types.errors import JobFailedError
from functualize.app.core import FunctualizeApp
from functualize.types import JobResult, RunRequest, RunStatus


class TestFrozenShape:
    def test_fields_and_comparison_flags_are_unchanged(self) -> None:
        assert [(f.name, f.compare, f.hash) for f in fields(JobResult)] == [
            ("status", True, None),
            ("return_value", True, None),
            ("duration_ms", True, None),
            ("metadata", True, None),
            ("exception", False, False),
            ("job_name", True, None),
        ]

    def test_exception_is_excluded_from_equality_and_hash(self) -> None:
        # Hashable metadata lets this pin the generated dataclass hash as well.
        first = JobResult(RunStatus.SUCCESS, "ok", 1.0, (), ValueError("a"), "child")  # type: ignore[arg-type]
        second = JobResult(RunStatus.SUCCESS, "ok", 1.0, (), RuntimeError("b"), "child")  # type: ignore[arg-type]

        assert first == second
        assert hash(first) == hash(second)


class TestStatusTable:
    @pytest.mark.parametrize("status", list(RunStatus))
    @pytest.mark.parametrize("exception", [None, RuntimeError("boom failed")])
    def test_every_status_with_and_without_an_exception(
        self, status: RunStatus, exception: RuntimeError | None
    ) -> None:
        result = JobResult(status, None, 0.0, {"source": "child"}, exception, "boom")
        if status in {RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.BLOCKED}:
            assert result.raise_for_status() is result
            return

        with pytest.raises(JobFailedError) as raised:
            result.raise_for_status()

        error = raised.value
        assert error.result is result
        assert error.job_name == "boom"
        assert error.status is status
        assert error.exception is exception
        assert error.__cause__ is exception
        assert "boom" in str(error)
        assert status.value in str(error)
        if exception is not None:
            assert "RuntimeError: boom failed" in str(error)


class TestProductionResult:
    def test_app_execute_result_reaches_the_checked_method(self) -> None:
        def fail() -> None:
            raise RuntimeError("child failed")

        app = FunctualizeApp(name="checked-result")
        app.register_dynamic_job("fail", fail)

        result = app.execute(RunRequest(job_name="fail", surface="app.execute"))

        assert result.status is RunStatus.FAILURE
        with pytest.raises(JobFailedError) as raised:
            result.raise_for_status()
        assert raised.value.result is result
        assert raised.value.job_name == "fail"
