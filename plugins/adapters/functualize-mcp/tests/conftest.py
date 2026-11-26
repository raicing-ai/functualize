"""Shared fixtures for functualize-mcp plugin tests.

Provides fake FunctualizeApp and descriptor objects for unit testing
the MCP adapter without requiring the full functualize runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest


def signature_fields(function: Any) -> list[Any]:
    """The fields discovery records for ``function``, each with its contract.

    A descriptor's fields carry the parameter contract every surface renders
    from, and no type string, so the fixtures use real records rather than a
    hand-built stand-in.
    """
    from functualize._discovery import extract_parameters_from_signature

    return extract_parameters_from_signature(function)


def _greet(name: str) -> None: ...


def _deploy(env: str) -> None: ...


@dataclass
class FakeDescriptor:
    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[Any] = field(default_factory=list)
    parameters: list[Any] = field(default_factory=list)
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

    def execute(self, request: Any) -> FakeJobResult:
        # One positional `RunRequest` — the facade's only form since
        # run-request-entry/T15. The old `(job_name, **kwargs)` signature was
        # the accidental control channel it closed: a payload splatted into it
        # let a caller's key choose the run's scope.
        job_name = request.job_name
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
                config_fields=signature_fields(_greet),
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
                config_fields=signature_fields(_deploy),
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
