"""Tests for InProcessIntrospector — in-process command introspection."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from functualize._cli.introspect import InProcessIntrospector
from functualize._types import FieldDescriptor, JobDescriptor


def _make_job(
    name: str, docstring: str = "", parameters: list[FieldDescriptor] | None = None
) -> JobDescriptor:
    """Create a mock JobDescriptor."""
    return JobDescriptor(
        name=name,
        group=None,
        function=lambda: None,
        docstring=docstring,
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


class TestInProcessIntrospector:
    """Tests for InProcessIntrospector."""

    def test_job_names_from_app(self) -> None:
        """job_names property returns names from app.get_jobs()."""
        jobs = [_make_job("deploy"), _make_job("test")]
        app = _make_app(jobs)
        introspector = InProcessIntrospector(app)

        assert "deploy" in introspector.job_names
        assert "test" in introspector.job_names

    def test_is_executable_known_job(self) -> None:
        """Known job is executable."""
        jobs = [_make_job("deploy")]
        app = _make_app(jobs)
        introspector = InProcessIntrospector(app)

        is_exec, reason = asyncio.run(introspector.is_executable_async(["deploy"]))
        assert is_exec is True
        assert "Ready" in reason

    def test_is_executable_builtin(self) -> None:
        """Builtin command is executable."""
        app = _make_app([])
        introspector = InProcessIntrospector(app)

        is_exec, reason = asyncio.run(
            introspector.is_executable_async(["builtin", "version"])
        )
        assert is_exec is True

    def test_is_executable_unknown(self) -> None:
        """Unknown command is not executable."""
        app = _make_app([])
        introspector = InProcessIntrospector(app)

        is_exec, reason = asyncio.run(introspector.is_executable_async(["nonexistent"]))
        assert is_exec is False
        assert "Unknown" in reason

    def test_is_executable_empty_tokens(self) -> None:
        """Empty tokens → not executable."""
        app = _make_app([])
        introspector = InProcessIntrospector(app)

        is_exec, reason = asyncio.run(introspector.is_executable_async([]))
        assert is_exec is False

    def test_is_executable_py_file(self) -> None:
        """A .py file that exists is executable."""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"def run(): pass")
            py_path = f.name

        try:
            app = _make_app([])
            introspector = InProcessIntrospector(app)

            is_exec, reason = asyncio.run(introspector.is_executable_async([py_path]))
            assert is_exec is True
            assert "single-file" in reason
        finally:
            Path(py_path).unlink()

    def test_get_help_for_job(self) -> None:
        """get_help_async returns formatted help for a job."""
        jobs = [
            _make_job(
                "deploy",
                docstring="Deploy the application to production.",
                parameters=[
                    FieldDescriptor(
                        name="target",
                        type_annotation="str",
                        default=None,
                        description="Deploy target",
                        required=True,
                        choices=None,
                    ),
                    FieldDescriptor(
                        name="dry_run",
                        type_annotation="bool",
                        default=False,
                        description="Simulate without changes",
                        required=False,
                        choices=None,
                    ),
                ],
            )
        ]
        app = _make_app(jobs)
        introspector = InProcessIntrospector(app)

        help_text = asyncio.run(introspector.get_help_async(["deploy"]))

        assert "deploy" in help_text
        assert "Deploy the application" in help_text
        assert "--target" in help_text
        assert "--dry_run" in help_text
        assert "[required]" in help_text

    def test_get_help_top_level(self) -> None:
        """get_help_async with empty tokens returns top-level help."""
        jobs = [_make_job("deploy", "Deploy stuff")]
        app = _make_app(jobs)
        introspector = InProcessIntrospector(app)

        help_text = asyncio.run(introspector.get_help_async([]))

        assert "Commands:" in help_text
        assert "deploy" in help_text

    def test_get_help_builtin(self) -> None:
        """get_help_async for the builtin group returns its description.

        The in-process introspector is single-level (a TUI smart-bar helper); it
        keys off top-level command names only. Post-convergence the sole
        top-level builtin is ``builtin`` itself.
        """
        app = _make_app([])
        introspector = InProcessIntrospector(app)

        help_text = asyncio.run(introspector.get_help_async(["builtin"]))

        assert "builtin" in help_text.lower()

    def test_get_completions_no_tokens(self) -> None:
        """All commands returned when no tokens."""
        jobs = [_make_job("deploy"), _make_job("test")]
        app = _make_app(jobs)
        introspector = InProcessIntrospector(app)

        completions = asyncio.run(
            introspector.get_completions_async([], ["deploy", "test", "builtin"])
        )

        names = [c[0] for c in completions]
        assert "deploy" in names
        assert "test" in names
        assert "builtin" in names

    def test_get_completions_partial_match(self) -> None:
        """Partial token filters completions."""
        jobs = [_make_job("deploy"), _make_job("destroy")]
        app = _make_app(jobs)
        introspector = InProcessIntrospector(app)

        completions = asyncio.run(
            introspector.get_completions_async(["dep"], ["deploy", "destroy"])
        )

        names = [c[0] for c in completions]
        assert "deploy" in names
        # "destroy" doesn't match "dep" as substring
        # Actually "dep" is in "deploy" but not "destroy"

    def test_get_completions_job_options(self) -> None:
        """After command name, show job options as completions."""
        jobs = [
            _make_job(
                "deploy",
                parameters=[
                    FieldDescriptor(
                        name="target",
                        type_annotation="str",
                        default=None,
                        description="",
                        required=True,
                        choices=None,
                    ),
                ],
            )
        ]
        app = _make_app(jobs)
        introspector = InProcessIntrospector(app)

        completions = asyncio.run(
            introspector.get_completions_async(["deploy", ""], ["deploy"])
        )

        names = [c[0] for c in completions]
        assert "--target" in names

    def test_completions_include_descriptions(self) -> None:
        """Completions include job docstring first line as description."""
        jobs = [_make_job("deploy", "Deploy to prod.\nMore details.")]
        app = _make_app(jobs)
        introspector = InProcessIntrospector(app)

        completions = asyncio.run(introspector.get_completions_async([], ["deploy"]))

        assert completions[0][1] == "Deploy to prod."
