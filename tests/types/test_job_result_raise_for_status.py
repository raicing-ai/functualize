"""Pin the existing JobResult value shape before adding its checked method."""

from dataclasses import fields

from functualize.types import JobResult, RunStatus


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
