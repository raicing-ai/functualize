"""Property-based tests for ScaffoldGenerator.

Tests Properties 1, 2, and 3 from the design document.
Validates: Requirements 1.2, 1.4, 1.8, 1.10, 1.11, 1.12
"""

import tempfile
from pathlib import Path

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from functualize._cli.scaffold import PEP508_PATTERN, ScaffoldGenerator

# --- Strategies ---

# Characters allowed in PEP 508 names
_pep508_inner_chars = st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789-_"))
_pep508_start_chars = st.sampled_from(list("abcdefghijklmnopqrstuvwxyz"))
_pep508_end_chars = st.sampled_from(list("abcdefghijklmnopqrstuvwxyz0123456789"))


@st.composite
def valid_pep508_names(draw: st.DrawFn) -> str:
    """Generate valid PEP 508 project names.

    Pattern: ^[a-z]([a-z0-9]|[-_])*[a-z0-9]$
    Minimum length is 2 (start char + end char).
    """
    start = draw(_pep508_start_chars)
    end = draw(_pep508_end_chars)
    middle_len = draw(st.integers(min_value=0, max_value=20))
    middle = draw(
        st.lists(_pep508_inner_chars, min_size=middle_len, max_size=middle_len)
    )
    name = start + "".join(middle) + end
    # Ensure it actually matches the pattern (sanity check)
    assume(PEP508_PATTERN.match(name) is not None)
    return name


@st.composite
def invalid_pep508_names(draw: st.DrawFn) -> str:
    """Generate strings that do NOT match the PEP 508 naming pattern."""
    strategy = draw(
        st.sampled_from(
            [
                "starts_with_digit",
                "uppercase",
                "special_chars",
                "empty",
                "single_char_invalid",
                "ends_with_hyphen",
                "ends_with_underscore",
            ]
        )
    )

    if strategy == "starts_with_digit":
        digit = draw(st.sampled_from(list("0123456789")))
        rest = draw(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
                min_size=1,
                max_size=10,
            )
        )
        name = digit + rest
    elif strategy == "uppercase":
        name = draw(
            st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=2, max_size=10)
        )
    elif strategy == "special_chars":
        base = draw(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=5)
        )
        special = draw(st.sampled_from(list("!@#$%^&*()+={}[]|\\:;\"'<>,./? ")))
        name = base + special + base
    elif strategy == "empty":
        name = ""
    elif strategy == "single_char_invalid":
        # Single characters don't match ^[a-z](...)*[a-z0-9]$ since the pattern
        # requires at least 2 chars (start + end)
        name = draw(st.sampled_from(list("abcdefghijklmnopqrstuvwxyz")))
    elif strategy == "ends_with_hyphen":
        start = draw(st.sampled_from(list("abcdefghijklmnopqrstuvwxyz")))
        middle = draw(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
                min_size=0,
                max_size=5,
            )
        )
        name = start + middle + "-"
    elif strategy == "ends_with_underscore":
        start = draw(st.sampled_from(list("abcdefghijklmnopqrstuvwxyz")))
        middle = draw(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
                min_size=0,
                max_size=5,
            )
        )
        name = start + middle + "_"
    else:
        name = ""

    # Ensure it does NOT match the pattern
    assume(PEP508_PATTERN.match(name) is None)
    return name


# --- Property 1: PEP 508 Name Validation ---


# Feature: functualize, Property 1: PEP 508 Name Validation
# For any string input, the ScaffoldGenerator SHALL accept it if and only if
# it matches the PEP 508 naming pattern (lowercase, starts with a letter,
# contains only letters/digits/hyphens/underscores, ends with letter or digit),
# and SHALL reject all other strings with an appropriate error message.
# Validates: Requirements 1.2
class TestPEP508NameValidation:
    """Property 1: PEP 508 Name Validation."""

    @given(name=valid_pep508_names())
    def test_valid_names_are_accepted(self, name: str):
        """Valid PEP 508 names are accepted by ScaffoldGenerator."""
        # Feature: functualize, Property 1: PEP 508 Name Validation
        # **Validates: Requirements 1.2**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / name
            # Should not raise ValueError for valid names
            generator.create_project(name, target_dir)
            assert target_dir.exists()

    @given(name=invalid_pep508_names())
    def test_invalid_names_are_rejected(self, name: str):
        """Invalid PEP 508 names are rejected with ValueError."""
        # Feature: functualize, Property 1: PEP 508 Name Validation
        # **Validates: Requirements 1.2**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "test-project"
            with pytest.raises(ValueError, match="PEP 508"):
                generator.create_project(name, target_dir)

    @given(name=valid_pep508_names())
    def test_valid_names_accepted_by_add_job(self, name: str):
        """Valid PEP 508 names are accepted by add_job."""
        # Feature: functualize, Property 1: PEP 508 Name Validation
        # **Validates: Requirements 1.2**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            generator.add_job(name, Path(tmp))

    @given(name=invalid_pep508_names())
    def test_invalid_names_rejected_by_add_job(self, name: str):
        """Invalid PEP 508 names are rejected by add_job."""
        # Feature: functualize, Property 1: PEP 508 Name Validation
        # **Validates: Requirements 1.2**
        generator = ScaffoldGenerator()
        with (
            tempfile.TemporaryDirectory() as tmp,
            pytest.raises(ValueError, match="PEP 508"),
        ):
            generator.add_job(name, Path(tmp))


# --- Property 2: Scaffold Entry Point Correctness ---


# Feature: functualize, Property 2: Scaffold Entry Point Correctness
# For any valid PEP 508 project name, the generated pyproject.toml SHALL
# contain a [project.scripts] entry where the key equals the project name
# and the value references the correct module entry point.
# Validates: Requirements 1.4
class TestScaffoldEntryPointCorrectness:
    """Property 2: Scaffold Entry Point Correctness."""

    @given(name=valid_pep508_names())
    def test_pyproject_contains_correct_entry_point(self, name: str):
        """Generated pyproject.toml has correct [project.scripts] entry."""
        # Feature: functualize, Property 2: Scaffold Entry Point Correctness
        # **Validates: Requirements 1.4**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / name
            generator.create_project(name, target_dir)

            pyproject_path = target_dir / "pyproject.toml"
            assert pyproject_path.exists(), "pyproject.toml should be generated"

            content = pyproject_path.read_text()

            # The entry point key should be the project name
            # The value should reference the correct module entry point
            package_name = name.replace("-", "_")
            expected_entry = f'{name} = "{package_name}.main:run"'

            assert expected_entry in content, (
                f"Expected entry point '{expected_entry}' not found in pyproject.toml.\n"
                f"Content:\n{content}"
            )

    @given(name=valid_pep508_names())
    def test_pyproject_has_scripts_section(self, name: str):
        """Generated pyproject.toml contains [project.scripts] section."""
        # Feature: functualize, Property 2: Scaffold Entry Point Correctness
        # **Validates: Requirements 1.4**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / name
            generator.create_project(name, target_dir)

            pyproject_path = target_dir / "pyproject.toml"
            content = pyproject_path.read_text()

            assert "[project.scripts]" in content, (
                "pyproject.toml should contain [project.scripts] section"
            )


# --- Property 3: Sub-Scaffold File Generation ---


# Feature: functualize, Property 3: Sub-Scaffold File Generation
# For any valid name and sub-scaffold type (job, plugin, screen), the
# ScaffoldGenerator SHALL create a file containing the provided name in the
# appropriate location (JOB_GROUP variable for jobs, entry point function for
# plugins, Screen class name for screens) without modifying any existing files.
# Validates: Requirements 1.8, 1.10, 1.11, 1.12
class TestSubScaffoldFileGeneration:
    """Property 3: Sub-Scaffold File Generation."""

    @given(name=valid_pep508_names())
    def test_add_job_creates_file_with_job_name(self, name: str):
        """add_job creates a file containing JOB_GROUP set to the provided name."""
        # Feature: functualize, Property 3: Sub-Scaffold File Generation
        # **Validates: Requirements 1.8, 1.10**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            generator.add_job(name, tmp_path)

            file_name = name.replace("-", "_")
            job_file = tmp_path / f"{file_name}.py"
            assert job_file.exists(), f"Job file {job_file} should be created"

            content = job_file.read_text()
            # The JOB_GROUP variable should contain the job name (underscored)
            expected_job_name = name.replace("-", "_")
            assert f'JOB_GROUP = "{expected_job_name}"' in content, (
                f'Expected JOB_GROUP = "{expected_job_name}" in job file.\n'
                f"Content:\n{content}"
            )

    @given(name=valid_pep508_names())
    def test_add_plugin_creates_file_with_register_function(self, name: str):
        """add_plugin creates a file with the register entry point function."""
        # Feature: functualize, Property 3: Sub-Scaffold File Generation
        # **Validates: Requirements 1.8, 1.11**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            generator.add_plugin(name, tmp_path)

            file_name = name.replace("-", "_")
            plugin_file = tmp_path / f"{file_name}.py"
            assert plugin_file.exists(), f"Plugin file {plugin_file} should be created"

            content = plugin_file.read_text()
            # The plugin should have a register function (entry point)
            assert "def register(" in content, (
                "Plugin file should contain a 'register' entry point function.\n"
                f"Content:\n{content}"
            )
            # The plugin name should appear in the file
            assert name in content, (
                f"Plugin file should contain the plugin name '{name}'.\n"
                f"Content:\n{content}"
            )

    @given(name=valid_pep508_names())
    def test_add_tui_screen_creates_file_with_screen_class(self, name: str):
        """add_tui_screen creates a file with a Screen class named after the input."""
        # Feature: functualize, Property 3: Sub-Scaffold File Generation
        # **Validates: Requirements 1.8, 1.12**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            generator.add_tui_screen(name, tmp_path)

            file_name = name.replace("-", "_")
            screen_file = tmp_path / f"{file_name}.py"
            assert screen_file.exists(), f"Screen file {screen_file} should be created"

            content = screen_file.read_text()
            # The class name should be derived from the name + "Screen"
            class_name = (
                "".join(part.capitalize() for part in name.replace("-", "_").split("_"))
                + "Screen"
            )
            assert f"class {class_name}(Screen):" in content, (
                f"Screen file should contain class '{class_name}(Screen):'.\n"
                f"Content:\n{content}"
            )

    @given(name=valid_pep508_names())
    def test_add_job_does_not_modify_existing_files(self, name: str):
        """add_job does not modify existing files in the directory."""
        # Feature: functualize, Property 3: Sub-Scaffold File Generation
        # **Validates: Requirements 1.8, 1.10**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create an existing file
            existing_file = tmp_path / "existing.py"
            existing_content = "# This file should not be modified\n"
            existing_file.write_text(existing_content)

            generator.add_job(name, tmp_path)

            # Verify existing file is unchanged
            assert existing_file.read_text() == existing_content

    @given(name=valid_pep508_names())
    def test_add_plugin_does_not_modify_existing_files(self, name: str):
        """add_plugin does not modify existing files in the directory."""
        # Feature: functualize, Property 3: Sub-Scaffold File Generation
        # **Validates: Requirements 1.8, 1.11**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            existing_file = tmp_path / "existing.py"
            existing_content = "# This file should not be modified\n"
            existing_file.write_text(existing_content)

            generator.add_plugin(name, tmp_path)

            assert existing_file.read_text() == existing_content

    @given(name=valid_pep508_names())
    def test_add_tui_screen_does_not_modify_existing_files(self, name: str):
        """add_tui_screen does not modify existing files in the directory."""
        # Feature: functualize, Property 3: Sub-Scaffold File Generation
        # **Validates: Requirements 1.8, 1.12**
        generator = ScaffoldGenerator()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            existing_file = tmp_path / "existing.py"
            existing_content = "# This file should not be modified\n"
            existing_file.write_text(existing_content)

            generator.add_tui_screen(name, tmp_path)

            assert existing_file.read_text() == existing_content
