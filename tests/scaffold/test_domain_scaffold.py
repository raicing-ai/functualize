"""Tests for domain scaffold commands.

Tests the scaffold commands for domain plugin and domain SDK generation:
- func scaffold add plugin --domain D --name N
- func scaffold add domain --name N
- func scaffold list domains

Validates: Requirements 23.1, 23.2, 23.3, 23.4, 23.5
"""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from functualize._cli.scaffold.cli import scaffold_app as app
from functualize._cli.scaffold.generator import ScaffoldGenerator

runner = CliRunner()


class TestAddDomainPlugin:
    """Tests for 'func scaffold add plugin --domain D --name N'."""

    def test_creates_plugin_package_directory(self, tmp_path: Path) -> None:
        """Requirement 23.1: Generates a plugin package."""
        result = runner.invoke(
            app,
            [
                "add",
                "plugin",
                "--domain",
                "ai",
                "--name",
                "my-provider",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        pkg_dir = tmp_path / "functualize-ai-my-provider"
        assert pkg_dir.is_dir()

    def test_generates_pyproject_toml(self, tmp_path: Path) -> None:
        """Requirement 23.2: Generated pyproject.toml has correct entry point."""
        result = runner.invoke(
            app,
            [
                "add",
                "plugin",
                "--domain",
                "ai",
                "--name",
                "my-provider",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        pyproject = tmp_path / "functualize-ai-my-provider" / "pyproject.toml"
        assert pyproject.exists()
        content = pyproject.read_text()

        # Entry point group matches domain convention
        assert "functualize.ai_providers" in content
        # Provider name is in the entry point
        assert "my_provider" in content
        # Dependency on domain SDK
        assert "functualize-ai" in content

    def test_generates_source_module(self, tmp_path: Path) -> None:
        """Requirement 23.1: Generates source module."""
        result = runner.invoke(
            app,
            [
                "add",
                "plugin",
                "--domain",
                "state",
                "--name",
                "redis-backend",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        src_dir = (
            tmp_path
            / "functualize-state-redis-backend"
            / "src"
            / "functualize_state_redis_backend"
        )
        assert src_dir.is_dir()
        assert (src_dir / "__init__.py").exists()
        assert (src_dir / "_plugin.py").exists()

    def test_generates_test_file_with_pbt_placeholder(self, tmp_path: Path) -> None:
        """Requirement 23.5: Generated test file includes placeholder property test."""
        result = runner.invoke(
            app,
            [
                "add",
                "plugin",
                "--domain",
                "ai",
                "--name",
                "my-provider",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        tests_dir = tmp_path / "functualize-ai-my-provider" / "tests"
        assert tests_dir.is_dir()
        test_files = list(tests_dir.glob("test_*.py"))
        assert len(test_files) == 1
        content = test_files[0].read_text()
        # Has hypothesis imports for property testing
        assert "hypothesis" in content
        assert "@given" in content

    def test_entry_point_matches_domain(self, tmp_path: Path) -> None:
        """Requirement 23.2: Entry point group is functualize.<domain>_providers."""
        result = runner.invoke(
            app,
            [
                "add",
                "plugin",
                "--domain",
                "tasks",
                "--name",
                "postgres",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        pyproject = tmp_path / "functualize-tasks-postgres" / "pyproject.toml"
        content = pyproject.read_text()
        assert "functualize.tasks_providers" in content
        assert "functualize-tasks" in content  # dependency on domain SDK

    def test_requires_name_with_domain(self, tmp_path: Path) -> None:
        """--name is required when --domain is specified."""
        result = runner.invoke(
            app,
            ["add", "plugin", "--domain", "ai", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "--name" in result.output

    def test_invalid_name_exits_with_error(self, tmp_path: Path) -> None:
        """Invalid PEP 508 name shows error."""
        result = runner.invoke(
            app,
            [
                "add",
                "plugin",
                "--domain",
                "ai",
                "--name",
                "BAD!NAME",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_existing_directory_exits_with_error(self, tmp_path: Path) -> None:
        """Cannot scaffold into an existing directory."""
        (tmp_path / "functualize-ai-existing").mkdir()
        result = runner.invoke(
            app,
            [
                "add",
                "plugin",
                "--domain",
                "ai",
                "--name",
                "existing",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_plugin_class_in_source(self, tmp_path: Path) -> None:
        """Source module contains the plugin class."""
        result = runner.invoke(
            app,
            [
                "add",
                "plugin",
                "--domain",
                "ai",
                "--name",
                "my-provider",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        plugin_file = (
            tmp_path
            / "functualize-ai-my-provider"
            / "src"
            / "functualize_ai_my_provider"
            / "_plugin.py"
        )
        content = plugin_file.read_text()
        assert "MyProviderPlugin" in content
        assert 'name = "my_provider"' in content
        assert 'domain = "ai"' in content


class TestAddDomainSdk:
    """Tests for 'func scaffold add domain --name N'."""

    def test_creates_domain_sdk_package(self, tmp_path: Path) -> None:
        """Requirement 23.3: Generates domain SDK package."""
        result = runner.invoke(
            app,
            [
                "add",
                "domain",
                "--name",
                "analytics",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        pkg_dir = tmp_path / "functualize-analytics"
        assert pkg_dir.is_dir()

    def test_generates_all_standard_modules(self, tmp_path: Path) -> None:
        """Requirement 23.3: Has all standard modules."""
        result = runner.invoke(
            app,
            [
                "add",
                "domain",
                "--name",
                "analytics",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        src_dir = tmp_path / "functualize-analytics" / "src" / "functualize_analytics"
        assert (src_dir / "__init__.py").exists()
        assert (src_dir / "_types.py").exists()
        assert (src_dir / "_protocols.py").exists()
        assert (src_dir / "_errors.py").exists()
        assert (src_dir / "_events.py").exists()
        assert (src_dir / "_metadata.py").exists()
        assert (src_dir / "testing" / "__init__.py").exists()

    def test_generates_pyproject_toml_with_entry_point(self, tmp_path: Path) -> None:
        """Generated pyproject.toml has functualize.domains entry point."""
        result = runner.invoke(
            app,
            [
                "add",
                "domain",
                "--name",
                "analytics",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        pyproject = tmp_path / "functualize-analytics" / "pyproject.toml"
        content = pyproject.read_text()
        assert "functualize.domains" in content
        assert "functualize_analytics" in content
        assert "hatchling" in content

    def test_metadata_has_correct_domain_info(self, tmp_path: Path) -> None:
        """DomainMetadata in _metadata.py has correct fields."""
        result = runner.invoke(
            app,
            [
                "add",
                "domain",
                "--name",
                "analytics",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        metadata_file = (
            tmp_path
            / "functualize-analytics"
            / "src"
            / "functualize_analytics"
            / "_metadata.py"
        )
        content = metadata_file.read_text()
        assert 'name="analytics"' in content
        assert 'entry_point_group="functualize.analytics_providers"' in content

    def test_protocols_has_provider_protocol(self, tmp_path: Path) -> None:
        """_protocols.py contains a runtime_checkable protocol."""
        result = runner.invoke(
            app,
            [
                "add",
                "domain",
                "--name",
                "analytics",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output

        protocols_file = (
            tmp_path
            / "functualize-analytics"
            / "src"
            / "functualize_analytics"
            / "_protocols.py"
        )
        content = protocols_file.read_text()
        assert "runtime_checkable" in content
        assert "Protocol" in content
        assert "AnalyticsProvider" in content

    def test_invalid_name_exits_with_error(self, tmp_path: Path) -> None:
        """Invalid PEP 508 name shows error."""
        result = runner.invoke(
            app,
            ["add", "domain", "--name", "BAD!", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_existing_directory_exits_with_error(self, tmp_path: Path) -> None:
        """Cannot scaffold into an existing directory."""
        (tmp_path / "functualize-existing").mkdir()
        result = runner.invoke(
            app,
            ["add", "domain", "--name", "existing", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output


class TestListDomains:
    """Tests for 'func scaffold list domains'."""

    def test_list_domains_outputs_discovered_domains(self) -> None:
        """Requirement 23.4: Lists discovered domains."""
        from functualize._plugins.domain_metadata import DomainMetadata

        mock_domains = [
            DomainMetadata(
                name="ai",
                display_name="AI / LLM",
                description="LLM interaction capabilities",
                capability_class="functualize_ai.AI",
                provider_protocol="functualize_ai.AIProvider",
                config_section="ai",
                entry_point_group="functualize.ai_providers",
                events_prefix="ai.",
            ),
            DomainMetadata(
                name="state",
                display_name="State / Persistence",
                description="State persistence and execution tracking",
                capability_class="functualize_state.StateBackend",
                provider_protocol="functualize_state.StateBackend",
                config_section="state",
                entry_point_group="functualize.state_providers",
                events_prefix="state.",
            ),
        ]

        with (
            patch(
                "functualize.plugin.discover_domains",
                return_value=mock_domains,
            ),
            patch(
                "functualize.plugin.scan_domain_providers",
                return_value={"pydantic": None},
            ),
        ):
            result = runner.invoke(app, ["list", "domains"])

        assert result.exit_code == 0, result.output
        assert "ai" in result.output
        assert "state" in result.output
        assert "AI / LLM" in result.output

    def test_list_domains_shows_providers(self) -> None:
        """Shows available providers for each domain."""
        from functualize._plugins.domain_metadata import DomainMetadata

        mock_domains = [
            DomainMetadata(
                name="ai",
                display_name="AI / LLM",
                description="LLM interaction capabilities",
                capability_class="functualize_ai.AI",
                provider_protocol="functualize_ai.AIProvider",
                config_section="ai",
                entry_point_group="functualize.ai_providers",
                events_prefix="ai.",
            ),
        ]

        with (
            patch(
                "functualize.plugin.discover_domains",
                return_value=mock_domains,
            ),
            patch(
                "functualize.plugin.scan_domain_providers",
                return_value={"pydantic": None},
            ),
        ):
            result = runner.invoke(app, ["list", "domains"])

        assert result.exit_code == 0, result.output
        assert "pydantic" in result.output

    def test_list_domains_empty_shows_install_hints(self) -> None:
        """Shows install hints when no domains are discovered."""
        with patch(
            "functualize.plugin.discover_domains",
            return_value=[],
        ):
            result = runner.invoke(app, ["list", "domains"])

        assert result.exit_code == 0, result.output
        assert "No domains discovered" in result.output
        assert "pip install" in result.output

    def test_list_domains_shows_scaffold_commands(self) -> None:
        """Shows scaffold command usage hints."""
        from functualize._plugins.domain_metadata import DomainMetadata

        mock_domains = [
            DomainMetadata(
                name="ai",
                display_name="AI / LLM",
                description="LLM interaction capabilities",
                capability_class="functualize_ai.AI",
                provider_protocol="functualize_ai.AIProvider",
                config_section="ai",
                entry_point_group="functualize.ai_providers",
                events_prefix="ai.",
            ),
        ]

        with (
            patch(
                "functualize.plugin.discover_domains",
                return_value=mock_domains,
            ),
            patch(
                "functualize.plugin.scan_domain_providers",
                return_value={},
            ),
        ):
            result = runner.invoke(app, ["list", "domains"])

        assert result.exit_code == 0, result.output
        assert "func scaffold add plugin --domain" in result.output
        assert "func scaffold add domain --name" in result.output


class TestScaffoldGeneratorDomainPlugin:
    """Direct tests for ScaffoldGenerator.add_domain_plugin."""

    def test_pyproject_dependency_on_domain_sdk(self, tmp_path: Path) -> None:
        """Requirement 23.2: pyproject.toml depends on the Domain SDK."""
        generator = ScaffoldGenerator()
        generator.add_domain_plugin(
            domain_name="ai", plugin_name="my-provider", output_dir=tmp_path
        )

        pyproject = tmp_path / "functualize-ai-my-provider" / "pyproject.toml"
        content = pyproject.read_text()
        # Must depend on the domain SDK
        assert '"functualize-ai"' in content

    def test_entry_point_correct_for_domain(self, tmp_path: Path) -> None:
        """Requirement 23.2: Entry point group matches domain convention."""
        generator = ScaffoldGenerator()
        generator.add_domain_plugin(
            domain_name="tasks", plugin_name="postgres", output_dir=tmp_path
        )

        pyproject = tmp_path / "functualize-tasks-postgres" / "pyproject.toml"
        content = pyproject.read_text()
        assert '"functualize.tasks_providers"' in content

    def test_test_file_imports_from_package(self, tmp_path: Path) -> None:
        """Requirement 23.5: Test file imports from the generated package."""
        generator = ScaffoldGenerator()
        generator.add_domain_plugin(
            domain_name="ai", plugin_name="my-provider", output_dir=tmp_path
        )

        tests_dir = tmp_path / "functualize-ai-my-provider" / "tests"
        test_file = tests_dir / "test_my_provider_plugin.py"
        content = test_file.read_text()
        assert "from functualize_ai_my_provider import" in content


class TestScaffoldGeneratorDomainSdk:
    """Direct tests for ScaffoldGenerator.add_domain_sdk."""

    def test_creates_full_structure(self, tmp_path: Path) -> None:
        """Requirement 23.3: Generates all standard modules."""
        generator = ScaffoldGenerator()
        generator.add_domain_sdk(domain_name="messaging", output_dir=tmp_path)

        pkg = tmp_path / "functualize-messaging"
        src = pkg / "src" / "functualize_messaging"

        assert (pkg / "pyproject.toml").exists()
        assert (src / "__init__.py").exists()
        assert (src / "_types.py").exists()
        assert (src / "_protocols.py").exists()
        assert (src / "_errors.py").exists()
        assert (src / "_events.py").exists()
        assert (src / "_metadata.py").exists()
        assert (src / "testing" / "__init__.py").exists()

    def test_pyproject_has_domains_entry_point(self, tmp_path: Path) -> None:
        """pyproject.toml registers via functualize.domains."""
        generator = ScaffoldGenerator()
        generator.add_domain_sdk(domain_name="messaging", output_dir=tmp_path)

        pyproject = tmp_path / "functualize-messaging" / "pyproject.toml"
        content = pyproject.read_text()
        assert '"functualize.domains"' in content
        assert "functualize_messaging:domain_metadata" in content
