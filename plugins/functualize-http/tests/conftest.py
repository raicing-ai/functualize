"""Shared fixtures for functualize-http plugin tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class FakeDescriptor:
    name: str
    group: str | None = None
    docstring: str | None = None


@dataclass
class FakeJobResult:
    status: str = "success"
    return_value: Any = None
    duration_ms: float = 5.0


class FakeApp:
    """Minimal FunctualizeApp fake for HTTP adapter tests."""

    def __init__(
        self,
        descriptors: list[FakeDescriptor] | None = None,
        execute_results: dict[str, FakeJobResult] | None = None,
        execute_error: Exception | None = None,
    ):
        self._descriptors = descriptors or []
        self._execute_results = execute_results or {}
        self._execute_error = execute_error
        self._commands: dict[str, Any] = {}

    def get_jobs(self) -> list[FakeDescriptor]:
        return self._descriptors

    def get_job(self, name: str) -> FakeDescriptor | None:
        for d in self._descriptors:
            if d.name == name:
                return d
        return None

    def execute(self, job_name: str, **kwargs: Any) -> FakeJobResult:
        if self._execute_error:
            raise self._execute_error
        if job_name in self._execute_results:
            return self._execute_results[job_name]
        return FakeJobResult(return_value=f"executed {job_name}")

    def register_plugin_command(
        self, name: str, callback: Any, help_text: str = ""
    ) -> None:
        self._commands[name] = callback


@pytest.fixture
def fake_app() -> FakeApp:
    return FakeApp(
        descriptors=[
            FakeDescriptor(name="greet", docstring="Greet user"),
            FakeDescriptor(name="deploy", group="ops", docstring="Deploy"),
        ]
    )


@pytest.fixture
def empty_app() -> FakeApp:
    return FakeApp(descriptors=[])
