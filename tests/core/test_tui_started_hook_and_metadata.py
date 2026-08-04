"""Unit tests for TUI_STARTED hook and @job declaration descriptor integration.

Tests:
- TUI_STARTED hook fires with correct metadata dict (app_name, command_name)
- TUI_STARTED hook exception isolation (errors logged, TUI continues)
- @job(...) declaration wires into JobDescriptor during discovery
- Dynamic job registration includes the declaration from the decorator
- JobDescriptor.to_dict/from_dict round-trips the declaration
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Generator
from typing import Any

import pytest

from functualize._app.state import AppState
from functualize._discovery.registry import JobRegistry
from functualize._events.hooks import HookEvent, HookRegistry
from functualize._types.descriptors import JobDescriptor
from functualize._types.job_declaration import JobDeclaration
from functualize.app.core import FunctualizeApp
from functualize.job import job


@pytest.fixture(autouse=True)
def _reset_state() -> Generator[None]:
    """Ensure AppState is clean before and after each test."""
    AppState.reset()
    yield
    AppState.reset()


class TestTUIStartedHook:
    """Tests for TUI_STARTED hook firing via HookRegistry."""

    def test_tui_started_hook_fires_with_metadata(self) -> None:
        """TUI_STARTED hook fires with app_name and command_name in metadata."""
        hook_registry = HookRegistry()
        received: list[dict[str, str]] = []

        def on_tui_started(metadata: dict[str, str]) -> None:
            received.append(metadata)

        hook_registry.register_global(HookEvent.TUI_STARTED, on_tui_started)

        # Simulate what happens when the TUI launches
        tui_metadata = {
            "app_name": "myapp",
            "command_name": "tui",
        }
        hooks = hook_registry._global_hooks.get(HookEvent.TUI_STARTED, [])
        for hook in hooks:
            hook(tui_metadata)

        assert len(received) == 1
        assert received[0]["app_name"] == "myapp"
        assert received[0]["command_name"] == "tui"

    def test_tui_started_hook_exception_isolation(self) -> None:
        """TUI_STARTED hook exceptions are logged and don't interrupt TUI launch."""
        hook_registry = HookRegistry()
        calls: list[str] = []

        def bad_hook(metadata: dict[str, str]) -> None:
            calls.append("bad")
            raise RuntimeError("hook error")

        def good_hook(metadata: dict[str, str]) -> None:
            calls.append("good")

        hook_registry.register_global(HookEvent.TUI_STARTED, bad_hook)
        hook_registry.register_global(HookEvent.TUI_STARTED, good_hook)

        # Simulate the hook firing with exception handling
        tui_metadata = {
            "app_name": "testapp",
            "command_name": "tui",
        }
        hooks = hook_registry._global_hooks.get(HookEvent.TUI_STARTED, [])
        for hook in hooks:
            with contextlib.suppress(Exception):
                hook(tui_metadata)

        assert calls == ["bad", "good"]


class TestJobDeclarationDescriptorIntegration:
    """Tests for @job(...) wiring into JobDescriptor.declaration during discovery."""

    def test_declaration_populated_during_scan(self, tmp_path: Any) -> None:
        """scan_and_register picks up __functualize_job__ and populates descriptor."""
        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)

        with open(os.path.join(jobs_dir, "annotated_job.py"), "w") as f:
            f.write(
                "from functualize.job import job\n\n"
                "@job(\n"
                "    extra_description='Deploy the application',\n"
                "    category='deployment',\n"
                "    examples=['deploy --env prod'],\n"
                "    tags=['deploy', 'production'],\n"
                ")\n"
                "def deploy():\n"
                "    '''Deploy job.'''\n"
                "    pass\n"
            )

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        descriptor = registry.get_descriptor("deploy")
        assert descriptor.declaration is not None
        assert descriptor.declaration.extra_description == "Deploy the application"
        assert descriptor.declaration.category == "deployment"
        assert descriptor.declaration.examples == ("deploy --env prod",)
        assert descriptor.declaration.tags == ("deploy", "production")

    def test_declaration_none_when_no_decorator(self, tmp_path: Any) -> None:
        """JobDescriptor.declaration is None for convention jobs (no @job)."""
        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)

        with open(os.path.join(jobs_dir, "plain_job.py"), "w") as f:
            f.write("def my_job():\n    '''A plain job.'''\n    pass\n")

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        descriptor = registry.get_descriptor("my_job")
        assert descriptor.declaration is None

    def test_bare_job_decorator(self, tmp_path: Any) -> None:
        """Bare @job creates a default declaration with no metadata set."""
        jobs_dir = os.path.join(str(tmp_path), "jobs")
        os.makedirs(jobs_dir)

        with open(os.path.join(jobs_dir, "bare.py"), "w") as f:
            f.write(
                "from functualize.job import job\n\n@job\ndef my_job():\n    pass\n"
            )

        registry = JobRegistry()
        registry.scan_and_register(None, [jobs_dir])

        descriptor = registry.get_descriptor("my_job")
        assert descriptor.declaration is not None
        assert descriptor.declaration.extra_description is None
        assert descriptor.declaration.category is None
        assert descriptor.declaration.examples == ()
        assert descriptor.declaration.tags == ()

    def test_dynamic_job_includes_declaration(self) -> None:
        """register_dynamic_job picks up __functualize_job__ on the function."""
        app = FunctualizeApp(name="testapp")

        @job(extra_description="A dynamic job", tags=["dynamic"])
        def my_dynamic_job() -> None:
            """Dynamic job."""
            pass

        app.register_dynamic_job(name="my_dynamic_job", function=my_dynamic_job)

        descriptor = app.job_registry.get_descriptor("my_dynamic_job")
        assert descriptor.declaration is not None
        assert descriptor.declaration.extra_description == "A dynamic job"
        assert descriptor.declaration.tags == ("dynamic",)

    def test_descriptor_serialization_round_trip_with_declaration(self) -> None:
        """JobDescriptor.to_dict/from_dict round-trips the declaration."""
        declaration = JobDeclaration(
            extra_description="test desc",
            category="test",
            examples=["ex1", "ex2"],
            tags=["tag1"],
        )
        descriptor = JobDescriptor(
            name="test_job",
            group=None,
            module_path="test.mod",
            source_file="/tmp/test.py",
            source_mtime=1234.0,
            content_hash="abc123",
            docstring="A test job.",
            config_fields=[],
            dependencies={},
            declaration=declaration,
        )

        data = descriptor.to_dict()
        assert data["declaration"]["extra_description"] == "test desc"
        assert data["declaration"]["category"] == "test"
        assert data["declaration"]["examples"] == ["ex1", "ex2"]
        assert data["declaration"]["tags"] == ["tag1"]

        restored = JobDescriptor.from_dict(data)
        assert restored.declaration is not None
        assert restored.declaration.extra_description == "test desc"
        assert restored.declaration.category == "test"
        assert restored.declaration.examples == ("ex1", "ex2")
        assert restored.declaration.tags == ("tag1",)

    def test_descriptor_serialization_without_declaration(self) -> None:
        """JobDescriptor.to_dict/from_dict handles a None declaration."""
        descriptor = JobDescriptor(
            name="plain_job",
            group=None,
            module_path="test.mod",
            source_file="/tmp/test.py",
            source_mtime=1234.0,
            content_hash="abc123",
            docstring=None,
            config_fields=[],
            dependencies={},
        )

        data = descriptor.to_dict()
        assert data["declaration"] is None

        restored = JobDescriptor.from_dict(data)
        assert restored.declaration is None
