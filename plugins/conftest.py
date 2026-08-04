"""Shared conftest for all plugin tests.

Provides common fixtures like fake FunctualizeApp instances
that plugins can use to test their adapters/integrations
without needing the full functualize kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Fake descriptors / app — reusable across all plugin tests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeField:
    """Minimal field descriptor for testing."""

    name: str
    type_annotation: str
    default: Any | None = None
    description: str = ""
    required: bool = True
    choices: list[str] | None = None


@dataclass
class FakeDescriptor:
    """Minimal job descriptor for testing."""

    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[FakeField] = field(default_factory=list)
    parameters: list[FakeField] = field(default_factory=list)
    metadata: Any = field(
        default_factory=lambda: SimpleNamespace(
            tags=[],
            visibility=None,
            extra_description=None,
            examples=None,
            category=None,
        )
    )


class FakeJobResult:
    """Fake result from app.execute()."""

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
    """Minimal fake FunctualizeApp for plugin testing.

    Supports get_jobs(), get_job(), and execute() — the interface
    that most adapter plugins rely on.
    """

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_descriptors() -> list[FakeDescriptor]:
    """A set of sample job descriptors for testing."""
    return [
        FakeDescriptor(
            name="greet",
            docstring="Greet someone by name.",
            config_fields=[
                FakeField(name="name", type_annotation="str", required=True),
            ],
            metadata=SimpleNamespace(
                tags=["util"],
                visibility=None,
                extra_description=None,
                examples=["greet --name Alice"],
                category="utility",
            ),
        ),
        FakeDescriptor(
            name="deploy",
            docstring="Deploy to an environment.",
            config_fields=[
                FakeField(name="env", type_annotation="str", required=True),
                FakeField(
                    name="dry_run",
                    type_annotation="bool",
                    default=False,
                    required=False,
                ),
            ],
            metadata=SimpleNamespace(
                tags=["ops"],
                visibility=None,
                extra_description=None,
                examples=None,
                category="operations",
            ),
        ),
    ]


@pytest.fixture
def fake_app(sample_descriptors: list[FakeDescriptor]) -> FakeApp:
    """A FakeApp pre-loaded with sample descriptors."""
    return FakeApp(descriptors=sample_descriptors)
