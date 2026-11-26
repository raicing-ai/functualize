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

from functualize.types import RunStatus

# ---------------------------------------------------------------------------
# Fake descriptors / app — reusable across all plugin tests
# ---------------------------------------------------------------------------


def signature_fields(function: Any) -> list[Any]:
    """The fields discovery records for ``function``, each with its contract.

    A descriptor's fields carry the parameter contract every surface renders
    from, and no type string, so the fixtures use real records rather than a
    hand-built stand-in.
    """
    from functualize._discovery import extract_parameters_from_signature

    return extract_parameters_from_signature(function)


def _greet(name: str) -> None: ...


def _deploy(env: str, dry_run: bool = False) -> None: ...


@dataclass
class FakeDescriptor:
    """Minimal job descriptor for testing."""

    name: str
    group: str | None = None
    docstring: str | None = None
    config_fields: list[Any] = field(default_factory=list)
    parameters: list[Any] = field(default_factory=list)
    metadata: Any = field(
        default_factory=lambda: SimpleNamespace(
            tags=[],
            visibility=None,
            extra_description=None,
            examples=None,
            category=None,
        )
    )


#: The fakes below carry a real ``RunStatus``, not the string they once used.
#: A fake that mistypes the field under test is how ``functualize-lambda``
#: could return 200 for every outcome with a green suite: `result.status` was
#: never read, and nothing in these fakes could have noticed.
class FakeJobResult:
    """Fake result from app.execute()."""

    def __init__(
        self,
        status: RunStatus = RunStatus.SUCCESS,
        return_value: Any = None,
        duration_ms: float = 42.0,
        exception: BaseException | None = None,
    ):
        self.status = status
        self.return_value = return_value
        self.duration_ms = duration_ms
        self.exception = exception


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
        return FakeJobResult(return_value=f"executed {job_name}")


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
            config_fields=signature_fields(_greet),
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
            config_fields=signature_fields(_deploy),
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
