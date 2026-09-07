"""Shared fixtures for functualize-lambda plugin tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from functualize.types import RunStatus


@dataclass
class FakeJobResult:
    """Carries a real ``RunStatus``; see the note in ``plugins/conftest.py``."""

    status: RunStatus = RunStatus.SUCCESS
    return_value: Any = None
    duration_ms: float = 10.0
    exception: BaseException | None = None


class FakeApp:
    """Minimal FunctualizeApp fake for Lambda adapter tests."""

    def __init__(
        self,
        execute_results: dict[str, FakeJobResult] | None = None,
        execute_error: Exception | None = None,
    ):
        self._execute_results = execute_results or {}
        self._execute_error = execute_error

    def execute(self, job_name: str, **kwargs: Any) -> FakeJobResult:
        if self._execute_error:
            raise self._execute_error
        if job_name in self._execute_results:
            return self._execute_results[job_name]
        return FakeJobResult(return_value=f"executed {job_name}")


@pytest.fixture
def fake_app() -> FakeApp:
    return FakeApp()


@pytest.fixture
def failing_app() -> FakeApp:
    return FakeApp(execute_error=RuntimeError("deploy failed"))
