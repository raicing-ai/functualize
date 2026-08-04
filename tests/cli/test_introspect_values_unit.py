"""Unit tests for InProcessIntrospector.get_value_completions_async.

Tests path completions with real filesystem, behavior with no ArgumentHistory,
and behavior with unknown job/field names.

Validates: Requirements 4.3, 4.4, 4.5
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from functualize._cli.introspect import InProcessIntrospector
from functualize._types import FieldDescriptor, JobDescriptor


def _make_job(
    name: str,
    parameters: list[FieldDescriptor] | None = None,
) -> JobDescriptor:
    """Create a minimal JobDescriptor for testing."""
    return JobDescriptor(
        name=name,
        group=None,
        function=lambda: None,
        docstring=None,
        parameters=parameters or [],
        source="<test>",
        metadata={},
    )


def _make_app(jobs: list[JobDescriptor]) -> MagicMock:
    """Create a mock FunctualizeApp with get_jobs()."""
    app = MagicMock()
    app.get_jobs.return_value = jobs
    app.name = "test-app"
    return app


# ---------------------------------------------------------------------------
# Path completions with actual filesystem (tmp_path fixture)
# ---------------------------------------------------------------------------


class TestPathCompletions:
    """Tests for path-based value completions using real filesystem."""

    @pytest.mark.asyncio
    async def test_path_field_returns_directory_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A field with type 'Path' returns cwd entries as completions."""
        # Create files in tmp_path
        (tmp_path / "config.toml").write_text("x = 1")
        (tmp_path / "data.csv").write_text("a,b,c")
        (tmp_path / "subdir").mkdir()

        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))

        field = FieldDescriptor(
            name="output",
            type_annotation="Path",
            default=None,
            description="Output path",
            required=True,
            choices=None,
        )
        job = _make_job("build", parameters=[field])
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async("build", "output")

        path_completions = [c for c in completions if c.source == "path"]
        values = {c.value for c in path_completions}
        assert "config.toml" in values
        assert "data.csv" in values
        assert "subdir" in values

    @pytest.mark.asyncio
    async def test_field_name_with_file_triggers_path_completions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A field named 'input_file' triggers path completions."""
        (tmp_path / "readme.md").write_text("hello")

        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))

        field = FieldDescriptor(
            name="input_file",
            type_annotation="str",
            default=None,
            description="Input file to process",
            required=True,
            choices=None,
        )
        job = _make_job("process", parameters=[field])
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async(
            "process", "input_file"
        )

        path_completions = [c for c in completions if c.source == "path"]
        values = {c.value for c in path_completions}
        assert "readme.md" in values

    @pytest.mark.asyncio
    async def test_field_name_with_path_triggers_path_completions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A field named 'config_path' triggers path completions."""
        (tmp_path / "app.yaml").write_text("key: val")

        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))

        field = FieldDescriptor(
            name="config_path",
            type_annotation="str",
            default=None,
            description="Path to config",
            required=True,
            choices=None,
        )
        job = _make_job("init", parameters=[field])
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async(
            "init", "config_path"
        )

        path_completions = [c for c in completions if c.source == "path"]
        values = {c.value for c in path_completions}
        assert "app.yaml" in values

    @pytest.mark.asyncio
    async def test_path_completions_filtered_by_partial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Path completions are filtered when partial is provided."""
        (tmp_path / "deploy.sh").write_text("#!/bin/bash")
        (tmp_path / "readme.md").write_text("# README")
        (tmp_path / "docker-compose.yml").write_text("version: 3")

        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))

        field = FieldDescriptor(
            name="script_path",
            type_annotation="Path",
            default=None,
            description="Script to run",
            required=True,
            choices=None,
        )
        job = _make_job("run", parameters=[field])
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async(
            "run", "script_path", partial="dep"
        )

        values = [c.value for c in completions]
        assert "deploy.sh" in values
        assert "readme.md" not in values


# ---------------------------------------------------------------------------
# Behavior with no ArgumentHistory (None parameter)
# ---------------------------------------------------------------------------


class TestNoHistory:
    """Tests for value completions when history is None."""

    @pytest.mark.asyncio
    async def test_no_history_still_returns_choices(self) -> None:
        """With history=None, choices completions are still returned."""
        field = FieldDescriptor(
            name="environment",
            type_annotation="str",
            default=None,
            description="Target environment",
            required=True,
            choices=["dev", "staging", "production"],
        )
        job = _make_job("deploy", parameters=[field])
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async(
            "deploy", "environment"
        )

        choice_completions = [c for c in completions if c.source == "choices"]
        values = [c.value for c in choice_completions]
        assert values == ["dev", "staging", "production"]

    @pytest.mark.asyncio
    async def test_no_history_omits_history_completions(self) -> None:
        """With history=None, no history-sourced completions appear."""
        field = FieldDescriptor(
            name="target",
            type_annotation="str",
            default=None,
            description="Deploy target",
            required=True,
            choices=None,
        )
        job = _make_job("deploy", parameters=[field])
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async("deploy", "target")

        history_completions = [c for c in completions if c.source == "history"]
        assert history_completions == []

    @pytest.mark.asyncio
    async def test_no_history_path_completions_still_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With history=None, path completions still work for Path fields."""
        (tmp_path / "output.log").write_text("log content")

        monkeypatch.setattr(Path, "cwd", staticmethod(lambda: tmp_path))

        field = FieldDescriptor(
            name="log_file",
            type_annotation="str",
            default=None,
            description="Log file path",
            required=False,
            choices=None,
        )
        job = _make_job("analyze", parameters=[field])
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async(
            "analyze", "log_file"
        )

        path_completions = [c for c in completions if c.source == "path"]
        values = {c.value for c in path_completions}
        assert "output.log" in values


# ---------------------------------------------------------------------------
# Behavior with unknown job/field names (empty results)
# ---------------------------------------------------------------------------


class TestUnknownJobField:
    """Tests for value completions with unknown job or field names."""

    @pytest.mark.asyncio
    async def test_unknown_job_returns_empty(self) -> None:
        """Requesting completions for a non-existent job returns empty list."""
        job = _make_job("deploy")
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async(
            "nonexistent_job", "some_field"
        )

        assert completions == []

    @pytest.mark.asyncio
    async def test_unknown_field_returns_empty(self) -> None:
        """Requesting completions for a non-existent field returns empty list."""
        field = FieldDescriptor(
            name="target",
            type_annotation="str",
            default=None,
            description="",
            required=True,
            choices=None,
        )
        job = _make_job("deploy", parameters=[field])
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async(
            "deploy", "nonexistent_field"
        )

        assert completions == []

    @pytest.mark.asyncio
    async def test_empty_job_name_returns_empty(self) -> None:
        """Empty job name returns empty list."""
        job = _make_job("deploy")
        app = _make_app([job])
        introspector = InProcessIntrospector(app, history=None)

        completions = await introspector.get_value_completions_async("", "target")

        assert completions == []
