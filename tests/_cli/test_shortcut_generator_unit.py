"""Unit tests for ShortcutGenerator.

Tests generate_shortcut_content, ShortcutSpec properties, and
_validate_shortcut_name with specific inputs covering Python shortcut
generation, empty kwargs, special character escaping, name validation,
JOB_GROUP declaration, and append/dedupe behavior.

Feature: TUI Smart Bar & Modals (Phase 2 + Phase 3)
Task: 3.3 — Write unit tests for ShortcutGenerator
Validates: Requirements 9.1, 9.3, 9.4, 9.6
"""

from __future__ import annotations

from pathlib import Path

import pytest

from functualize._cli.data.shortcut_generator import (
    ShortcutSpec,
    _validate_shortcut_name,
    append_or_write_python_shortcut,
    generate_shortcut_content,
)
from functualize._discovery.naming import qualified_name


class TestPythonOutput:
    """Tests for Python shortcut generation."""

    def test_python_output_contains_function_named_after_shortcut(self) -> None:
        """Python output defines a function named after shortcut_name."""
        spec = ShortcutSpec(
            shortcut_name="my_deploy",
            job_name="deploy",
            kwargs={"env": "staging"},
            output_file=Path("/tmp/shortcuts.py"),
        )
        content = generate_shortcut_content(spec)

        assert "def my_deploy(" in content

    def test_output_contains_job_group_shortcut(self) -> None:
        """Generated output declares JOB_GROUP = "shortcut" at module level."""
        spec = ShortcutSpec(
            shortcut_name="deploy",
            job_name="deploy",
            kwargs={},
            output_file=Path("/tmp/shortcuts.py"),
        )
        content = generate_shortcut_content(spec)

        assert 'JOB_GROUP = "shortcut"' in content
        compile(content, "<test>", "exec")

    def test_empty_kwargs_produces_valid_python(self) -> None:
        """Empty kwargs generates valid compilable Python."""
        spec = ShortcutSpec(
            shortcut_name="simple_job",
            job_name="build",
            kwargs={},
            output_file=Path("/tmp/shortcuts.py"),
        )
        content = generate_shortcut_content(spec)

        # Must compile without SyntaxError
        compile(content, "<test>", "exec")
        assert "def simple_job(" in content

    def test_kwargs_with_quotes_escaped_in_python(self) -> None:
        """Kwargs values containing double quotes are properly escaped."""
        spec = ShortcutSpec(
            shortcut_name="quoted_job",
            job_name="echo",
            kwargs={"msg": 'hello "world"'},
            output_file=Path("/tmp/shortcuts.py"),
        )
        content = generate_shortcut_content(spec)

        # Must compile without SyntaxError (proves escaping works)
        compile(content, "<test>", "exec")
        # The escaped form should be present
        assert '\\"' in content

    def test_kwargs_with_backslashes_escaped_in_python(self) -> None:
        """Kwargs values containing backslashes are properly escaped."""
        spec = ShortcutSpec(
            shortcut_name="path_job",
            job_name="deploy",
            kwargs={"path": "C:\\Users\\admin"},
            output_file=Path("/tmp/shortcuts.py"),
        )
        content = generate_shortcut_content(spec)

        # Must compile without SyntaxError
        compile(content, "<test>", "exec")
        # The escaped form should contain double backslashes
        assert "\\\\" in content


class TestValidateShortcutName:
    """Tests for _validate_shortcut_name."""

    def test_validate_rejects_invalid_python_identifier(self) -> None:
        """Names starting with digits are rejected."""
        with pytest.raises(ValueError, match="not a valid Python identifier"):
            _validate_shortcut_name("123invalid")

    def test_validate_rejects_python_keyword(self) -> None:
        """Python keywords are rejected."""
        with pytest.raises(ValueError, match="Python keyword"):
            _validate_shortcut_name("class")

    def test_validate_rejects_empty_name(self) -> None:
        """Empty names are rejected."""
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_shortcut_name("")

    def test_validate_accepts_valid_python_identifier(self) -> None:
        """Valid Python identifiers pass validation."""
        # Should not raise
        _validate_shortcut_name("my_shortcut")


class TestAppendOrWritePythonShortcut:
    """Tests for append_or_write_python_shortcut (Requirement 2 append behavior)."""

    def test_fresh_file_writes_normally(self, tmp_path: Path) -> None:
        """No existing file: content is written fresh, unchanged."""
        spec = ShortcutSpec(
            shortcut_name="deploy",
            job_name="deploy",
            kwargs={"env": "staging"},
            output_file=tmp_path / "shortcuts.py",
        )
        content = generate_shortcut_content(spec)

        append_or_write_python_shortcut(spec, content)

        written = spec.output_file.read_text()
        assert written == content
        compile(written, "<test>", "exec")

    def test_existing_file_without_import_gets_import_and_function_appended(
        self, tmp_path: Path
    ) -> None:
        """Existing file with no matching import: import + function appended."""
        spec = ShortcutSpec(
            shortcut_name="deploy",
            job_name="deploy",
            kwargs={"env": "staging"},
            output_file=tmp_path / "shortcuts.py",
        )
        spec.output_file.write_text('"""Existing shortcuts file."""\n')

        content = generate_shortcut_content(spec)
        append_or_write_python_shortcut(spec, content)

        written = spec.output_file.read_text()
        assert "Existing shortcuts file" in written
        assert written.count("from functualize.job import Invoke, Log") == 1
        assert written.count('JOB_GROUP = "shortcut"') == 1
        assert "def deploy(" in written
        compile(written, "<test>", "exec")

    def test_existing_file_with_exact_import_dedupes_import(
        self, tmp_path: Path
    ) -> None:
        """Existing file already has the exact import line: no duplicate import."""
        spec = ShortcutSpec(
            shortcut_name="deploy",
            job_name="deploy",
            kwargs={"env": "staging"},
            output_file=tmp_path / "shortcuts.py",
        )
        existing = (
            '"""Existing shortcuts file."""\n\n'
            'JOB_GROUP = "shortcut"\n\n'
            "from functualize.job import Invoke, Log\n\n\n"
            "def other(log: Log, invoke: Invoke):\n"
            '    """Other shortcut."""\n'
            '    invoke("other")\n'
        )
        spec.output_file.write_text(existing)

        content = generate_shortcut_content(spec)
        append_or_write_python_shortcut(spec, content)

        written = spec.output_file.read_text()
        assert written.count("from functualize.job import Invoke, Log") == 1
        assert written.count('JOB_GROUP = "shortcut"') == 1
        assert "def other(" in written
        assert "def deploy(" in written
        compile(written, "<test>", "exec")

    def test_existing_file_with_different_import_adds_new_import_line(
        self, tmp_path: Path
    ) -> None:
        """A different (non-matching) import is left alone; new import is added.

        Exact-line-match-only dedup: redundant imports in this edge case
        are an accepted trade-off (avoids AST-based source rewriting).
        """
        spec = ShortcutSpec(
            shortcut_name="deploy",
            job_name="deploy",
            kwargs={"env": "staging"},
            output_file=tmp_path / "shortcuts.py",
        )
        existing = (
            '"""Existing shortcuts file."""\n\nimport os\n\n\ndef noop():\n    pass\n'
        )
        spec.output_file.write_text(existing)

        content = generate_shortcut_content(spec)
        append_or_write_python_shortcut(spec, content)

        written = spec.output_file.read_text()
        assert "import os" in written
        assert written.count("from functualize.job import Invoke, Log") == 1
        assert written.count('JOB_GROUP = "shortcut"') == 1
        assert "def deploy(" in written
        compile(written, "<test>", "exec")

    def test_two_shortcuts_saved_sequentially_dedupe_job_group_and_import(
        self, tmp_path: Path
    ) -> None:
        """Two shortcuts saved sequentially to the same fresh file produce a
        file with exactly ONE JOB_GROUP line, ONE import line, and TWO
        function definitions — both syntactically valid and both
        conceptually resolving to distinct ``shortcut.<name>`` qualified
        names.
        """
        output_file = tmp_path / "shortcuts.py"

        spec1 = ShortcutSpec(
            shortcut_name="deploy",
            job_name="deploy",
            kwargs={"env": "staging"},
            output_file=output_file,
        )
        append_or_write_python_shortcut(spec1, generate_shortcut_content(spec1))

        spec2 = ShortcutSpec(
            shortcut_name="build",
            job_name="build",
            kwargs={"target": "release"},
            output_file=output_file,
        )
        append_or_write_python_shortcut(spec2, generate_shortcut_content(spec2))

        written = output_file.read_text()

        assert written.count('JOB_GROUP = "shortcut"') == 1
        assert written.count("from functualize.job import Invoke, Log") == 1
        assert written.count("def deploy(") == 1
        assert written.count("def build(") == 1

        # Both functions parse as valid Python and are syntactically distinct.
        tree = compile(written, "<test>", "exec")
        assert tree is not None

        # Both would register under the shortcut.* namespace, not colliding
        # with the real top-level `deploy`/`build` jobs.
        assert qualified_name("shortcut", "deploy") == "shortcut.deploy"
        assert qualified_name("shortcut", "build") == "shortcut.build"


class TestShortcutSpec:
    """Tests for the ShortcutSpec dataclass."""

    def test_output_file_field(self) -> None:
        """output_file stores the exact path the user typed."""
        spec = ShortcutSpec(
            shortcut_name="my_shortcut",
            job_name="deploy",
            kwargs={},
            output_file=Path("/home/user/.functualize/shortcuts/tools.py"),
        )

        assert spec.output_file == Path("/home/user/.functualize/shortcuts/tools.py")

    def test_no_format_field(self) -> None:
        """ShortcutSpec no longer has a format dataclass field."""
        assert "format" not in ShortcutSpec.__dataclass_fields__
