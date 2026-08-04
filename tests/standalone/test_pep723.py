"""Tests for functualize.standalone.pep723 module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from functualize._cli.pep723 import (
    _extract_package_name,
    check_deps_available,
    maybe_delegate_to_uv,
    parse_pep723_deps,
)


class TestParsePep723Deps:
    """Tests for parse_pep723_deps()."""

    def test_valid_script_block(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text(
            "# /// script\n"
            '# dependencies = ["requests", "rich>=13.0"]\n'
            "# ///\n"
            "\nimport requests\n"
        )
        result = parse_pep723_deps(source)
        assert result == ["requests", "rich>=13.0"]

    def test_multiline_dependencies(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text(
            "# /// script\n"
            "# dependencies = [\n"
            '#     "requests>=2.0",\n'
            '#     "click",\n'
            "# ]\n"
            "# ///\n"
            '\nprint("hello")\n'
        )
        result = parse_pep723_deps(source)
        assert result == ["requests>=2.0", "click"]

    def test_no_script_block_returns_none(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text('print("no metadata")\n')
        result = parse_pep723_deps(source)
        assert result is None

    def test_no_dependencies_key_returns_none(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text('# /// script\n# [project]\n# name = "my-script"\n# ///\n')
        result = parse_pep723_deps(source)
        assert result is None

    def test_empty_dependencies_list(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text("# /// script\n# dependencies = []\n# ///\n")
        result = parse_pep723_deps(source)
        assert result == []

    def test_invalid_toml_returns_none(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text("# /// script\n# not valid toml {{{\n# ///\n")
        result = parse_pep723_deps(source)
        assert result is None

    def test_script_block_in_middle_of_file(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text(
            "import os\n"
            "\n"
            "# /// script\n"
            '# dependencies = ["pathlib2"]\n'
            "# ///\n"
            "\ndef main(): pass\n"
        )
        result = parse_pep723_deps(source)
        assert result == ["pathlib2"]


class TestCheckDepsAvailable:
    """Tests for check_deps_available()."""

    def test_all_available_returns_empty(self) -> None:
        # pytest and sys are always available in our test environment
        result = check_deps_available(["pytest"])
        assert result == []

    def test_missing_dep_returned(self) -> None:
        result = check_deps_available(["nonexistent_package_xyz_999"])
        assert result == ["nonexistent_package_xyz_999"]

    def test_mixed_available_and_missing(self) -> None:
        deps = ["pytest", "nonexistent_pkg_abc_123", "sys"]
        result = check_deps_available(deps)
        assert result == ["nonexistent_pkg_abc_123"]

    def test_hyphen_normalized_to_underscore(self) -> None:
        # "typing-extensions" should be found as "typing_extensions"
        # which is available in Python 3.13 stdlib
        with patch("importlib.util.find_spec") as mock_find:
            # Simulate: find_spec("my_package") returns a spec
            mock_find.return_value = object()  # truthy
            result = check_deps_available(["my-package>=1.0"])
            mock_find.assert_called_with("my_package")
            assert result == []

    def test_version_specifiers_stripped(self) -> None:
        with patch("importlib.util.find_spec") as mock_find:
            mock_find.return_value = object()
            result = check_deps_available(["requests>=2.0,<3.0"])
            mock_find.assert_called_with("requests")
            assert result == []

    def test_empty_deps_list(self) -> None:
        result = check_deps_available([])
        assert result == []

    def test_extras_stripped_from_package_name(self) -> None:
        with patch("importlib.util.find_spec") as mock_find:
            mock_find.return_value = object()
            result = check_deps_available(["package[extra]>=1.0"])
            mock_find.assert_called_with("package")
            assert result == []


class TestMaybeDelegateToUv:
    """Tests for maybe_delegate_to_uv()."""

    def test_no_pep723_block_returns_false(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text('print("hello")\n')
        result = maybe_delegate_to_uv(source, ["run"])
        assert result is False

    def test_all_deps_available_returns_false(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text('# /// script\n# dependencies = ["pytest"]\n# ///\n')
        result = maybe_delegate_to_uv(source, ["run"])
        assert result is False

    def test_missing_deps_delegates_to_uv(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text(
            '# /// script\n# dependencies = ["nonexistent_pkg_delegate_test"]\n# ///\n'
        )
        with patch("subprocess.call", return_value=0) as mock_call:
            with pytest.raises(SystemExit) as exc_info:
                maybe_delegate_to_uv(source, ["myarg"])
            assert exc_info.value.code == 0
            # Verify uv was called with correct args
            call_args = mock_call.call_args[0][0]
            assert call_args[0] == "uv"
            assert call_args[1] == "run"
            assert "--with" in call_args
            assert "nonexistent_pkg_delegate_test" in call_args
            assert "functualize" in call_args

    def test_uv_not_found_prints_error(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text(
            '# /// script\n# dependencies = ["nonexistent_pkg_uv_test"]\n# ///\n'
        )
        with (
            patch("functualize._cli.pep723.shutil.which", return_value=None),
            pytest.raises(SystemExit) as exc_info,
        ):
            maybe_delegate_to_uv(source, ["myarg"])
        assert exc_info.value.code == 1

    def test_uv_not_found_error_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = tmp_path / "script.py"
        source.write_text(
            '# /// script\n# dependencies = ["nonexistent_pkg_msg_test"]\n# ///\n'
        )
        with (
            patch("functualize._cli.pep723.shutil.which", return_value=None),
            pytest.raises(SystemExit),
        ):
            maybe_delegate_to_uv(source, [])
        captured = capsys.readouterr()
        assert "uv" in captured.err
        assert "pip install uv" in captured.err
        assert "PEP 723" in captured.err

    def test_uv_exit_code_propagated(self, tmp_path: Path) -> None:
        source = tmp_path / "script.py"
        source.write_text(
            '# /// script\n# dependencies = ["nonexistent_pkg_exit_test"]\n# ///\n'
        )
        with (
            patch("subprocess.call", return_value=42),
            pytest.raises(SystemExit) as exc_info,
        ):
            maybe_delegate_to_uv(source, ["arg1", "arg2"])
        assert exc_info.value.code == 42


class TestExtractPackageName:
    """Tests for the _extract_package_name helper."""

    @pytest.mark.parametrize(
        ("specifier", "expected"),
        [
            ("requests", "requests"),
            ("requests>=2.0", "requests"),
            ("requests>=2.0,<3.0", "requests"),
            ("my-package", "my-package"),
            ("my_package", "my_package"),
            ("My.Package", "My.Package"),
            ("package[extra]", "package"),
            ("package[extra]>=1.0", "package"),
            ("  requests  ", "requests"),
            ("A", "A"),
        ],
    )
    def test_extracts_name(self, specifier: str, expected: str) -> None:
        assert _extract_package_name(specifier) == expected
