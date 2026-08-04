"""Property-based tests for PEP 723 inline script metadata parsing and delegation.

# Feature: cli-simplification-and-robustness, Property 8: PEP 723 parse returns None for absent/malformed
# Feature: cli-simplification-and-robustness, Property 9: PEP 723 delegation determined by dep availability
# Feature: cli-simplification-and-robustness, Property 10: PEP 723 recursion guard prevents re-delegation
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from functualize._cli.pep723 import (
    _DEPTH_ENV_VAR,
    check_deps_available,
    maybe_delegate_to_uv,
    parse_pep723_deps,
)

# =============================================================================
# Strategies for Property 8: PEP 723 parse returns None
# =============================================================================

# Characters safe for Python source files (printable ASCII, no null bytes)
_printable_ascii = st.characters(min_codepoint=32, max_codepoint=126)

# Strategy for Python source without any script block
_python_without_script_block = st.text(
    alphabet=_printable_ascii,
    min_size=0,
    max_size=200,
).filter(lambda s: "# /// script" not in s)


@st.composite
def python_with_malformed_toml_block(draw: st.DrawFn) -> str:
    """Generate Python file content with a # /// script block containing malformed TOML.

    Ensures the TOML inside cannot be parsed by tomllib.
    """
    # Generate malformed TOML content (unbalanced brackets, invalid syntax, etc.)
    malformed_variant = draw(
        st.sampled_from(
            [
                "not valid toml {{{",
                "[unclosed",
                'key = "unterminated',
                "= no_key",
                "[[[]]]",
                "dependencies = [unterminated",
                'key = """triple\nquote',
                ";;;garbage;;;",
                "[section\nbroken = true",
                '{ inline = "broken"',
            ]
        )
    )

    # Generate optional Python code before/after
    before = draw(
        st.sampled_from(
            [
                "",
                "import os\n",
                "x = 42\n\n",
                '"""Module docstring."""\n',
                "# A comment\n",
            ]
        )
    )
    after = draw(
        st.sampled_from(
            [
                "",
                "\ndef main(): pass\n",
                "\nprint('hello')\n",
                "\n# end\n",
            ]
        )
    )

    # Construct the file with a malformed script block
    # Each line in the block must start with #
    toml_lines = malformed_variant.split("\n")
    commented_lines = "\n".join(f"# {line}" for line in toml_lines)

    return f"{before}# /// script\n{commented_lines}\n# ///\n{after}"


# =============================================================================
# Property 8: PEP 723 parse returns None for absent or malformed metadata
# Feature: cli-simplification-and-robustness, Property 8
# =============================================================================


@pytest.mark.slow
class TestParsePep723ReturnsNoneForAbsentOrMalformed:
    """Property 8: PEP 723 parse returns None for absent or malformed metadata.

    For any Python source file that either (a) does not contain a
    `# /// script` metadata block, or (b) contains a block with malformed
    TOML, `parse_pep723_deps()` SHALL return None.

    **Validates: Requirements 11.5, 11.10**
    """

    @given(content=_python_without_script_block)
    @settings(max_examples=100)
    def test_no_script_block_returns_none(self, content: str) -> None:
        """Files without a # /// script block always return None.

        **Validates: Requirements 11.5**
        """
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            result = parse_pep723_deps(source)

            assert result is None, (
                f"parse_pep723_deps should return None for files without "
                f"a script block.\n"
                f"  Content (first 100 chars): {content[:100]!r}\n"
                f"  Got: {result}"
            )

    @given(content=python_with_malformed_toml_block())
    @settings(max_examples=100)
    def test_malformed_toml_returns_none(self, content: str) -> None:
        """Files with malformed TOML in the script block return None.

        **Validates: Requirements 11.10**
        """
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            result = parse_pep723_deps(source)

            assert result is None, (
                f"parse_pep723_deps should return None for malformed TOML.\n"
                f"  Content (first 200 chars): {content[:200]!r}\n"
                f"  Got: {result}"
            )

    @given(
        content=st.sampled_from(
            [
                "# Regular comment\nprint('hi')\n",
                "#!/usr/bin/env python\nimport sys\n",
                "# /// not-script\n# something\n# ///\n",
                "# /// script but no closing\n# deps = []\n",
                "",
            ]
        )
    )
    @settings(max_examples=100)
    def test_similar_but_non_matching_patterns_return_none(self, content: str) -> None:
        """Content that looks similar but doesn't match the PEP 723 pattern returns None.

        **Validates: Requirements 11.5**
        """
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            result = parse_pep723_deps(source)

            assert result is None, (
                f"parse_pep723_deps should return None for non-matching patterns.\n"
                f"  Content: {content!r}\n"
                f"  Got: {result}"
            )


# =============================================================================
# Strategies for Property 9: Delegation determined by dep availability
# =============================================================================

# Strategy for valid Python package names (PEP 508 compatible)
_package_name_start = st.sampled_from("abcdefghijklmnopqrstuvwxyz")
_package_name_chars = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789")
_package_name = st.builds(
    lambda first, rest: first + rest,
    _package_name_start,
    st.text(_package_name_chars, min_size=1, max_size=10),
)

# Strategy for version specifiers
_version_spec = st.sampled_from(["", ">=1.0", ">=2.0,<3.0", "==1.2.3", "~=1.0"])

# Strategy for dependency specifiers (name + optional version)
_dep_specifier = st.builds(
    lambda name, ver: f"{name}{ver}" if ver else name,
    _package_name,
    _version_spec,
)


@st.composite
def valid_pep723_source_with_deps(draw: st.DrawFn, deps: list[str]) -> str:
    """Generate a Python source file with a valid PEP 723 block declaring deps."""
    deps_str = ", ".join(f'"{d}"' for d in deps)
    before = draw(st.sampled_from(["", "import os\n", "# header\n", '"""Module."""\n']))
    return f"{before}# /// script\n# dependencies = [{deps_str}]\n# ///\n\ndef main(): pass\n"


# =============================================================================
# Property 9: PEP 723 delegation is determined by dependency availability
# Feature: cli-simplification-and-robustness, Property 9
# =============================================================================


@pytest.mark.slow
class TestDelegationDeterminedByDepAvailability:
    """Property 9: PEP 723 delegation is determined by dependency availability.

    For any Python file with valid PEP 723 metadata declaring dependencies:
    if ALL are importable, proceed normally (no delegation); if ANY is missing,
    delegate to uv.

    **Validates: Requirements 11.2, 11.3**
    """

    @given(deps=st.lists(_dep_specifier, min_size=1, max_size=5, unique=True))
    @settings(max_examples=100)
    def test_all_deps_available_means_no_delegation(self, deps: list[str]) -> None:
        """When all declared dependencies are importable, no delegation occurs.

        We mock find_spec to return a truthy value for all packages,
        simulating that all dependencies are available.

        **Validates: Requirements 11.2**
        """
        deps_str = ", ".join(f'"{d}"' for d in deps)
        content = (
            f"# /// script\n# dependencies = [{deps_str}]\n# ///\n\ndef main(): pass\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            # Mock find_spec to always return a truthy value (all deps available)
            with patch("importlib.util.find_spec", return_value=object()):
                result = maybe_delegate_to_uv(source, ["run"])

            assert result is False, (
                f"When all deps are available, maybe_delegate_to_uv should "
                f"return False (no delegation).\n"
                f"  deps: {deps}\n"
                f"  Got: {result}"
            )

    @given(deps=st.lists(_dep_specifier, min_size=1, max_size=5, unique=True))
    @settings(max_examples=100)
    def test_missing_deps_triggers_delegation(self, deps: list[str]) -> None:
        """When any dependency is missing, delegation to uv occurs.

        We mock find_spec to return None for all packages (all missing),
        and mock subprocess.call to capture the delegation attempt.

        **Validates: Requirements 11.3**
        """
        deps_str = ", ".join(f'"{d}"' for d in deps)
        content = (
            f"# /// script\n# dependencies = [{deps_str}]\n# ///\n\ndef main(): pass\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            # Mock find_spec to return None (all deps missing)
            # Mock shutil.which to find "uv"
            # Mock subprocess.call to prevent actual delegation
            with (
                patch("importlib.util.find_spec", return_value=None),
                patch(
                    "functualize._cli.pep723.shutil.which", return_value="/usr/bin/uv"
                ),
                patch("subprocess.call", return_value=0) as mock_call,
                pytest.raises(SystemExit) as exc_info,
            ):
                maybe_delegate_to_uv(source, ["run"])

            # Delegation happened (sys.exit called with subprocess return code)
            assert exc_info.value.code == 0

            # Verify uv was called
            assert mock_call.called, (
                "subprocess.call should have been called for delegation"
            )
            call_args = mock_call.call_args[0][0]
            assert call_args[0] == "uv", (
                f"Expected 'uv' as first arg, got: {call_args[0]}"
            )
            assert call_args[1] == "run", (
                f"Expected 'run' as second arg, got: {call_args[1]}"
            )

    @given(
        available_deps=st.lists(_dep_specifier, min_size=1, max_size=3, unique=True),
        missing_deps=st.lists(_dep_specifier, min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=100)
    def test_mixed_deps_some_missing_triggers_delegation(
        self, available_deps: list[str], missing_deps: list[str]
    ) -> None:
        """When some deps are available but at least one is missing, delegation occurs.

        **Validates: Requirements 11.3**
        """
        # Ensure no overlap between available and missing dep names
        available_names = {
            d.split(">")[0]
            .split("=")[0]
            .split("<")[0]
            .split("~")[0]
            .split("[")[0]
            .strip()
            for d in available_deps
        }
        missing_names = {
            d.split(">")[0]
            .split("=")[0]
            .split("<")[0]
            .split("~")[0]
            .split("[")[0]
            .strip()
            for d in missing_deps
        }
        assume(not available_names.intersection(missing_names))

        all_deps = available_deps + missing_deps
        deps_str = ", ".join(f'"{d}"' for d in all_deps)
        content = (
            f"# /// script\n# dependencies = [{deps_str}]\n# ///\n\ndef main(): pass\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            # Mock find_spec: return object for available, None for missing
            def mock_find_spec(name: str) -> object | None:
                # Normalize: strip underscores back to check
                for dep in available_deps:
                    pkg = (
                        dep.split(">")[0]
                        .split("=")[0]
                        .split("<")[0]
                        .split("~")[0]
                        .split("[")[0]
                        .strip()
                    )
                    if pkg.replace("-", "_") == name:
                        return object()
                return None

            with (
                patch("importlib.util.find_spec", side_effect=mock_find_spec),
                patch(
                    "functualize._cli.pep723.shutil.which", return_value="/usr/bin/uv"
                ),
                patch("subprocess.call", return_value=0) as mock_call,
                pytest.raises(SystemExit) as exc_info,
            ):
                maybe_delegate_to_uv(source, ["run"])

            assert exc_info.value.code == 0
            assert mock_call.called, "Delegation should occur when any dep is missing"

    @given(deps=st.lists(_dep_specifier, min_size=1, max_size=5, unique=True))
    @settings(max_examples=100)
    def test_check_deps_available_returns_empty_when_all_found(
        self, deps: list[str]
    ) -> None:
        """check_deps_available returns empty list when all deps are importable.

        **Validates: Requirements 11.2**
        """
        with patch("importlib.util.find_spec", return_value=object()):
            missing = check_deps_available(deps)

        assert missing == [], (
            f"check_deps_available should return [] when all deps found.\n"
            f"  deps: {deps}\n"
            f"  Got: {missing}"
        )

    @given(deps=st.lists(_dep_specifier, min_size=1, max_size=5, unique=True))
    @settings(max_examples=100)
    def test_check_deps_available_returns_all_when_none_found(
        self, deps: list[str]
    ) -> None:
        """check_deps_available returns all deps when none are importable.

        **Validates: Requirements 11.3**
        """
        with patch("importlib.util.find_spec", return_value=None):
            missing = check_deps_available(deps)

        assert missing == deps, (
            f"check_deps_available should return all deps when none found.\n"
            f"  deps: {deps}\n"
            f"  Got: {missing}"
        )


# =============================================================================
# Strategies for Property 10: Recursion guard
# =============================================================================

# Strategy for non-zero depth values (the recursion guard triggers on these)
_nonzero_depth_values = st.one_of(
    st.integers(min_value=1, max_value=100).map(str),
    st.sampled_from(["1", "2", "5", "10", "99"]),
)


# =============================================================================
# Property 10: PEP 723 recursion guard prevents re-delegation
# Feature: cli-simplification-and-robustness, Property 10
# =============================================================================


@pytest.mark.slow
class TestRecursionGuardPreventsReDelegation:
    """Property 10: PEP 723 recursion guard prevents re-delegation.

    For any execution context where `_FUNCTUALIZE_PEP723_DEPTH` is set to
    a non-zero value, the execution path SHALL NOT delegate to uv.

    **Validates: Requirements 11.8, 11.9**
    """

    @given(depth_value=_nonzero_depth_values)
    @settings(max_examples=100)
    def test_nonzero_depth_prevents_delegation(self, depth_value: str) -> None:
        """When _FUNCTUALIZE_PEP723_DEPTH is non-zero, delegation is prevented.

        Instead of delegating, the function prints an error and exits with code 1.

        **Validates: Requirements 11.8, 11.9**
        """
        content = (
            '# /// script\n# dependencies = ["nonexistent_pkg_guard_test"]\n# ///\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            # Set the depth env var to a non-zero value
            env_patch = {_DEPTH_ENV_VAR: depth_value}

            with (
                patch.dict(os.environ, env_patch),
                patch("importlib.util.find_spec", return_value=None),
                patch("subprocess.call") as mock_call,
                pytest.raises(SystemExit) as exc_info,
            ):
                maybe_delegate_to_uv(source, ["run"])

            # Should exit with code 1 (error), not delegate
            assert exc_info.value.code == 1, (
                f"Recursion guard should exit with code 1.\n"
                f"  depth_value: {depth_value}\n"
                f"  Got exit code: {exc_info.value.code}"
            )

            # subprocess.call should NOT have been called (no delegation)
            assert not mock_call.called, (
                f"subprocess.call should NOT be called when recursion guard "
                f"is active.\n"
                f"  depth_value: {depth_value}"
            )

    @given(
        depth_value=st.sampled_from(["0", ""]),
        deps=st.lists(_dep_specifier, min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=100)
    def test_zero_or_empty_depth_allows_delegation(
        self, depth_value: str, deps: list[str]
    ) -> None:
        """When _FUNCTUALIZE_PEP723_DEPTH is "0" or empty, delegation proceeds normally.

        **Validates: Requirements 11.8**
        """
        deps_str = ", ".join(f'"{d}"' for d in deps)
        content = (
            f"# /// script\n# dependencies = [{deps_str}]\n# ///\n\ndef main(): pass\n"
        )

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            env_patch = {_DEPTH_ENV_VAR: depth_value} if depth_value else {}

            with (
                patch.dict(os.environ, env_patch, clear=False),
                patch("importlib.util.find_spec", return_value=None),
                patch(
                    "functualize._cli.pep723.shutil.which", return_value="/usr/bin/uv"
                ),
                patch("subprocess.call", return_value=0) as mock_call,
                pytest.raises(SystemExit) as exc_info,
            ):
                maybe_delegate_to_uv(source, ["run"])

            # Should delegate (exit with subprocess return code)
            assert exc_info.value.code == 0, (
                f"Delegation should proceed when depth is '0' or empty.\n"
                f"  depth_value: {depth_value!r}\n"
                f"  Got exit code: {exc_info.value.code}"
            )

            # subprocess.call SHOULD have been called (delegation happened)
            assert mock_call.called, (
                f"subprocess.call should be called when recursion guard "
                f"is not active.\n"
                f"  depth_value: {depth_value!r}"
            )

    @given(depth_value=_nonzero_depth_values)
    @settings(max_examples=100)
    def test_recursion_guard_prints_error_with_missing_packages(
        self, depth_value: str
    ) -> None:
        """When recursion guard triggers, error message lists the missing packages.

        **Validates: Requirements 11.9**
        """
        import io
        from contextlib import redirect_stderr

        content = (
            '# /// script\n# dependencies = ["missing_alpha", "missing_beta"]\n# ///\n'
        )

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "script.py"
            source.write_text(content, encoding="utf-8")

            env_patch = {_DEPTH_ENV_VAR: depth_value}
            stderr_capture = io.StringIO()

            with (
                patch.dict(os.environ, env_patch),
                patch("importlib.util.find_spec", return_value=None),
                redirect_stderr(stderr_capture),
                pytest.raises(SystemExit),
            ):
                maybe_delegate_to_uv(source, ["run"])

            stderr_output = stderr_capture.getvalue()
            # Error should mention the missing packages
            assert "missing_alpha" in stderr_output, (
                f"Error should list missing packages.\n  stderr: {stderr_output}"
            )
            assert "missing_beta" in stderr_output, (
                f"Error should list missing packages.\n  stderr: {stderr_output}"
            )
