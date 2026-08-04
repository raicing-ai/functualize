"""Shared fixtures for functualize-mcp plugin tests.

Provides fake FunctualizeApp and descriptor objects for unit testing
the MCP adapter without requiring the full functualize runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest


@dataclass(frozen=True)
class FakeField:
    name: str
    type_annotation: str
    default: Any | None = None
    description: str = ""
    required: bool = True
    choices: list[str] | None = None


@dataclass
class FakeDescriptor:
    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[FakeField] = field(default_factory=list)
    parameters: list[FakeField] = field(default_factory=list)
    declaration: Any = field(
        default_factory=lambda: SimpleNamespace(
            tags=[],
            visibility=None,
            extra_description=None,
            examples=None,
            category=None,
        )
    )


class FakeJobResult:
    """Fake job result returned by app.execute()."""

    def __init__(
        self,
        status: str = "success",
        return_value: Any = None,
        duration_ms: float = 42.0,
    ):
        self.status = status
        self.return_value = return_value
        self.duration_ms = duration_ms


class FakeApp:
    """Minimal fake FunctualizeApp for testing MCP plugin components."""

    def __init__(
        self,
        descriptors: list[FakeDescriptor] | None = None,
        execute_results: dict[str, FakeJobResult] | None = None,
        execute_error: Exception | None = None,
    ):
        self._descriptors = descriptors or []
        self._execute_results = execute_results or {}
        self._execute_error = execute_error

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
        return FakeJobResult(status="success", return_value=f"executed {job_name}")


@pytest.fixture
def fake_app() -> FakeApp:
    """A FakeApp with a couple of visible jobs."""
    return FakeApp(
        descriptors=[
            FakeDescriptor(
                name="greet",
                docstring="Greet a user.",
                config_fields=[
                    FakeField(name="name", type_annotation="str", required=True),
                ],
                declaration=SimpleNamespace(
                    tags=["util"],
                    visibility=None,
                    extra_description=None,
                    examples=None,
                    category="utility",
                ),
            ),
            FakeDescriptor(
                name="deploy",
                docstring="Deploy to env.",
                config_fields=[
                    FakeField(name="env", type_annotation="str", required=True),
                ],
                declaration=SimpleNamespace(
                    tags=["ops"],
                    visibility=None,
                    extra_description=None,
                    examples=None,
                    category="operations",
                ),
            ),
        ]
    )
