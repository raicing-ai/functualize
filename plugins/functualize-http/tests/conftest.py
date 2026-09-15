"""Shared fixtures for functualize-http plugin tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from functualize.types import RunStatus


@dataclass
class FakeDescriptor:
    name: str
    group: str | None = None
    docstring: str | None = None


@dataclass
class FakeJobResult:
    """Carries a real ``RunStatus``; see the note in ``plugins/conftest.py``."""

    status: RunStatus = RunStatus.SUCCESS
    return_value: Any = None
    duration_ms: float = 5.0
    exception: BaseException | None = None


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

    def execute(self, request: Any) -> FakeJobResult:
        """The facade signature as of run-request-entry T3.

        The door hands over one `RunRequest`; the fake records it so tests can
        assert on the surface the request names, not only on the job that ran.
        """
        self.last_request = request
        job_name = request.job_name
        if self._execute_error:
            raise self._execute_error
        if job_name in self._execute_results:
            return self._execute_results[job_name]
        return FakeJobResult(return_value=f"executed {job_name}")

    @property
    def extensions(self) -> FakeExtensions:
        """`app.extensions` — the facade a plugin registers through.

        `register_plugin_command` moved off the app onto this facade in
        `engine-sealed-construction`/T9, with the ten other members a plugin
        reaches for. The fake mirrors the real shape: a double that keeps the
        old flat surface tests an app that no longer exists.
        """
        return FakeExtensions(self)


class FakeExtensions:
    """The `app.extensions` half of :class:`FakeApp`."""

    def __init__(self, app: FakeApp) -> None:
        self._app = app

    def register_plugin_command(
        self, name: str, callback: Any, help_text: str = ""
    ) -> None:
        self._app._commands[name] = callback


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
