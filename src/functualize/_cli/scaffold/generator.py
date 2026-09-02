"""Scaffold generator for creating new functualize projects and components."""

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader

from functualize._cli.scaffold.registry import get_template

# PEP 508 naming: lowercase, starts with letter, ends with letter/digit,
# contains only letters, digits, hyphens, or underscores.
PEP508_PATTERN = re.compile(r"^[a-z]([a-z0-9]|[-_])*[a-z0-9]$")

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_jinja_env() -> Environment:
    """Create a Jinja2 environment loading templates from the templates directory."""
    return Environment(
        loader=PackageLoader("functualize._cli.scaffold", "templates"),
        keep_trailing_newline=True,
    )


def _validate_name(name: str) -> None:
    """Validate a name against PEP 508 conventions.

    Raises:
        ValueError: If the name does not conform to PEP 508 naming.
    """
    if not PEP508_PATTERN.match(name):
        raise ValueError(
            f"Invalid name '{name}'. Names must conform to PEP 508: "
            "lowercase, start with a letter, end with a letter or digit, "
            "and contain only letters, digits, hyphens, or underscores."
        )


class ScaffoldGenerator:
    """Generates new project structures and individual components."""

    def __init__(self) -> None:
        self._env = _load_jinja_env()

    def create_project(self, project_name: str, target_dir: Path) -> None:
        """Create a full project scaffold.

        Validates the project name against PEP 508, checks that the target
        directory does not already exist, then renders all templates.

        Args:
            project_name: The name for the new project (PEP 508 compliant).
            target_dir: The directory where the project will be created.

        Raises:
            ValueError: If the project name is invalid.
            FileExistsError: If the target directory already exists.
        """
        _validate_name(project_name)

        if target_dir.exists():
            raise FileExistsError(
                f"Directory '{target_dir}' already exists. "
                "Cannot scaffold into an existing directory."
            )

        # Derive the Python package name (replace hyphens with underscores)
        package_name = project_name.replace("-", "_")

        context = {
            "project_name": project_name,
            "package_name": package_name,
        }

        # Create directory structure
        src_dir = target_dir / "src" / package_name
        jobs_dir = src_dir / "jobs"
        jobs_dir.mkdir(parents=True)

        # Render pyproject.toml
        self._render_template(
            "pyproject.toml.j2", target_dir / "pyproject.toml", context
        )

        # Render main entry point
        self._render_template("main.py.j2", src_dir / "main.py", context)

        # Create package __init__.py
        (src_dir / "__init__.py").write_text(
            f'"""The {project_name} CLI application."""\n\n__version__ = "0.1.0"\n'
        )

        # Create jobs __init__.py
        (jobs_dir / "__init__.py").write_text("")

        # Render sample job
        self._render_template(
            "job.py.j2",
            jobs_dir / "sample_job.py",
            {"job_name": "sample", "class_name": "Sample"},
        )

        # Render config.base.toml
        self._render_template(
            "config.base.toml.j2", target_dir / "config.base.toml", context
        )

    def init_project(
        self, project_name: str, target_dir: Path, template: str = "simple"
    ) -> None:
        """Create a project from a named template.

        Validates the project name, looks up the template in the registry,
        and renders template files from the template directory into target_dir.

        Args:
            project_name: The name for the new project (PEP 508 compliant).
            target_dir: The directory where the project will be created.
            template: The template name to use (default: "simple").

        Raises:
            ValueError: If the project name is invalid or template is unknown.
            FileExistsError: If the target directory already exists.
        """
        _validate_name(project_name)

        manifest = get_template(template)

        if target_dir.exists():
            raise FileExistsError(
                f"Directory '{target_dir}' already exists. "
                "Cannot scaffold into an existing directory."
            )

        # Derive the Python package name (replace hyphens with underscores)
        package_name = project_name.replace("-", "_")

        # Derive a PascalCase class name from the project name
        class_name = "".join(
            part.capitalize() for part in project_name.replace("-", "_").split("_")
        )

        context = {
            "project_name": project_name,
            "package_name": package_name,
            "class_name": class_name,
        }

        # Create target directory
        target_dir.mkdir(parents=True)

        # Render template files from the template's directory
        template_subdir = TEMPLATES_DIR / manifest.template_dir
        if template_subdir.is_dir():
            # Build file mapping: template filename → output path
            file_map = self._build_file_map(
                manifest.template_dir, target_dir, package_name
            )

            for template_file in sorted(template_subdir.glob("*.j2")):
                output_name = template_file.stem  # strip .j2 extension
                template_rel = f"{manifest.template_dir}/{template_file.name}"

                if output_name in file_map:
                    output_path = file_map[output_name]
                else:
                    output_path = target_dir / output_name

                self._render_template(template_rel, output_path, context)

            # Create jobs/__init__.py for templates that have a jobs directory
            jobs_dir = target_dir / "src" / package_name / "jobs"
            if jobs_dir.exists():
                init_file = jobs_dir / "__init__.py"
                if not init_file.exists():
                    init_file.write_text("")

        # A .gitignore is emitted for every template, not just those with config
        # layers: without one, a scaffolded project has nothing keeping .env and
        # the per-environment config overlays out of version control.
        gitignore_path = target_dir / ".gitignore"
        if not gitignore_path.exists():
            self._render_template("_shared/gitignore.j2", gitignore_path, context)

        # Render shared config layer files if the template declares has_config_layers
        if manifest.has_config_layers:
            shared_configs = {
                "_shared/config.base.toml.j2": "config.base.toml",
                "_shared/config.dev.toml.j2": "config.dev.toml",
                "_shared/config.prod.toml.j2": "config.prod.toml",
            }
            for template_rel, output_name in shared_configs.items():
                output_path = target_dir / output_name
                # Skip if the file already exists (template-specific config takes priority)
                if not output_path.exists():
                    self._render_template(template_rel, output_path, context)

    @staticmethod
    def _build_file_map(
        template_dir: str, target_dir: Path, package_name: str
    ) -> dict[str, Path]:
        """Build a mapping from template output names to their target paths.

        Different templates have different directory layouts. This method
        returns a dict mapping each rendered filename to its final location
        within the project structure.
        """
        src_pkg = target_dir / "src" / package_name
        jobs_dir = src_pkg / "jobs"

        if template_dir == "simple":
            return {
                "pyproject.toml": target_dir / "pyproject.toml",
                "README.md": target_dir / "README.md",
                "__init__.py": src_pkg / "__init__.py",
                "main.py": src_pkg / "main.py",
                "sample_job.py": jobs_dir / "sample_job.py",
            }

        if template_dir == "full-interactivity":
            return {
                "pyproject.toml": target_dir / "pyproject.toml",
                "README.md": target_dir / "README.md",
                "__init__.py": src_pkg / "__init__.py",
                "main.py": src_pkg / "main.py",
                "interactive_job.py": jobs_dir / "interactive_job.py",
                "workflow_job.py": jobs_dir / "workflow_job.py",
                "events_job.py": jobs_dir / "events_job.py",
            }

        if template_dir == "plugin-project":
            return {
                "pyproject.toml": target_dir / "pyproject.toml",
                "README.md": target_dir / "README.md",
                "__init__.py": src_pkg / "__init__.py",
                "plugin.py": src_pkg / "plugin.py",
                "renderer.py": src_pkg / "renderer.py",
                "provider.py": src_pkg / "provider.py",
            }

        if template_dir == "job-folder":
            plugins_dir = target_dir / ".functualize" / "plugins"
            return {
                "sample_job.py": target_dir / "sample_job.py",
                "file_plugin.py": plugins_dir / "file_plugin.py",
                "config.base.toml": target_dir / "config.base.toml",
                "README.md": target_dir / "README.md",
            }

        # Default: flat rendering into target_dir
        return {}

    def add_job(
        self, job_name: str, target_dir: Path, standalone: bool = False
    ) -> None:
        """Add a job module file.

        If standalone=True, uses standalone_job.py.j2 for bare-context jobs.
        Otherwise uses job.py.j2 for project-context jobs.

        Args:
            job_name: The name for the new job (PEP 508 compliant).
            target_dir: The directory where the file will be created.
            standalone: If True, generate a standalone job file for Mode D.

        Raises:
            ValueError: If the job name is invalid.
            FileExistsError: If the target file already exists.
        """
        _validate_name(job_name)

        # Convert hyphens to underscores for the filename
        file_name = job_name.replace("-", "_")
        target_file = target_dir / f"{file_name}.py"

        if target_file.exists():
            raise FileExistsError(
                f"File '{target_file}' already exists. "
                "Cannot overwrite existing job file."
            )

        # Derive a class name from the job name
        class_name = "".join(
            part.capitalize() for part in job_name.replace("-", "_").split("_")
        )

        context = {
            "job_name": job_name.replace("-", "_"),
            "class_name": class_name,
        }

        template_name = "standalone_job.py.j2" if standalone else "job.py.j2"
        self._render_template(template_name, target_file, context)

    def add_plugin(
        self, plugin_name: str, target_dir: Path, file_based: bool = False
    ) -> None:
        """Add a plugin scaffold.

        If file_based=True, uses file_plugin.py.j2 for file-based plugins.
        Otherwise uses plugin.py.j2 for entry-point plugins.

        Args:
            plugin_name: The name for the new plugin (PEP 508 compliant).
            target_dir: The directory where the plugin file will be created.
            file_based: If True, generate a file-based plugin for Mode D.

        Raises:
            ValueError: If the plugin name is invalid.
            FileExistsError: If the target file already exists.
        """
        _validate_name(plugin_name)

        file_name = plugin_name.replace("-", "_")
        target_file = target_dir / f"{file_name}.py"

        if target_file.exists():
            raise FileExistsError(
                f"File '{target_file}' already exists. "
                "Cannot overwrite existing plugin file."
            )

        context = {
            "plugin_name": plugin_name,
            "module_name": file_name,
            "class_name": "".join(
                part.capitalize() for part in plugin_name.replace("-", "_").split("_")
            ),
        }

        template_name = "file_plugin.py.j2" if file_based else "plugin.py.j2"
        self._render_template(template_name, target_file, context)

    def add_tui_screen(self, screen_name: str, target_dir: Path) -> None:
        """Add a TUI screen (Textual Screen subclass + TCSS).

        Args:
            screen_name: The name for the new screen (PEP 508 compliant).
            target_dir: The directory where the screen file will be created.

        Raises:
            ValueError: If the screen name is invalid.
            FileExistsError: If the target file already exists.
        """
        _validate_name(screen_name)

        file_name = screen_name.replace("-", "_")
        target_file = target_dir / f"{file_name}.py"

        if target_file.exists():
            raise FileExistsError(
                f"File '{target_file}' already exists. "
                "Cannot overwrite existing screen file."
            )

        class_name = (
            "".join(
                part.capitalize() for part in screen_name.replace("-", "_").split("_")
            )
            + "Screen"
        )

        context = {
            "screen_name": screen_name,
            "module_name": file_name,
            "class_name": class_name,
        }

        self._render_template("screen.py.j2", target_file, context)

        # Also create the TCSS file
        tcss_file = target_dir / f"{file_name}.tcss"
        if not tcss_file.exists():
            self._render_template("screen.tcss.j2", tcss_file, context)

    def add_domain_plugin(
        self, domain_name: str, plugin_name: str, output_dir: Path
    ) -> None:
        """Generate a domain plugin package with full project structure.

        Creates a plugin package targeting a specific domain SDK, containing:
        - pyproject.toml with entry point and Domain SDK dependency
        - src/<package>/__init__.py
        - src/<package>/_plugin.py with plugin boot class
        - tests/test_plugin.py with placeholder property test

        Args:
            domain_name: The domain to target (e.g., "ai", "state").
            plugin_name: The provider name (e.g., "my-provider").
            output_dir: Parent directory where the package will be created.

        Raises:
            ValueError: If the plugin name is invalid.
            FileExistsError: If the target directory already exists.
        """
        _validate_name(domain_name)
        _validate_name(plugin_name)

        # Derive names
        project_name = f"functualize-{domain_name}-{plugin_name}"
        package_name = project_name.replace("-", "_")
        class_name = "".join(
            part.capitalize() for part in plugin_name.replace("-", "_").split("_")
        )
        # Domain SDK package dependency
        domain_sdk_package = f"functualize-{domain_name}"
        # Entry point group follows the convention: functualize.<domain>_providers
        entry_point_group = f"functualize.{domain_name}_providers"
        # Provider name is the plugin_name with hyphens replaced
        provider_name = plugin_name.replace("-", "_")

        target_dir = output_dir / project_name
        if target_dir.exists():
            raise FileExistsError(
                f"Directory '{target_dir}' already exists. "
                "Cannot scaffold into an existing directory."
            )

        # Build context for templates
        context = {
            "project_name": project_name,
            "package_name": package_name,
            "class_name": class_name,
            "domain_name": domain_name,
            "domain_sdk_package": domain_sdk_package,
            "entry_point_group": entry_point_group,
            "provider_name": provider_name,
            "plugin_name": plugin_name,
            "description": f"{class_name} provider for the {domain_name} domain",
        }

        # Create directory structure
        src_dir = target_dir / "src" / package_name
        tests_dir = target_dir / "tests"
        src_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        # Render templates
        self._render_template(
            "domain-plugin/pyproject.toml.j2",
            target_dir / "pyproject.toml",
            context,
        )
        self._render_template(
            "domain-plugin/__init__.py.j2",
            src_dir / "__init__.py",
            context,
        )
        self._render_template(
            "domain-plugin/_plugin.py.j2",
            src_dir / "_plugin.py",
            context,
        )
        self._render_template(
            "domain-plugin/test_plugin.py.j2",
            tests_dir / f"test_{provider_name}_plugin.py",
            context,
        )

    def add_domain_sdk(self, domain_name: str, output_dir: Path) -> None:
        """Generate a new domain SDK package with all standard modules.

        Creates a domain SDK package following the standard structure with:
        - pyproject.toml with functualize.domains entry point
        - src/functualize_<domain>/__init__.py
        - src/functualize_<domain>/_types.py
        - src/functualize_<domain>/_protocols.py
        - src/functualize_<domain>/_errors.py
        - src/functualize_<domain>/_events.py
        - src/functualize_<domain>/_metadata.py
        - src/functualize_<domain>/testing/__init__.py

        Args:
            domain_name: The domain identifier (e.g., "analytics").
            output_dir: Parent directory where the package will be created.

        Raises:
            ValueError: If the domain name is invalid.
            FileExistsError: If the target directory already exists.
        """
        _validate_name(domain_name)

        project_name = f"functualize-{domain_name}"
        package_name = f"functualize_{domain_name}"
        class_name = "".join(
            part.capitalize() for part in domain_name.replace("-", "_").split("_")
        )
        display_name = class_name
        domain_name_upper = domain_name.upper().replace("-", "_")

        target_dir = output_dir / project_name
        if target_dir.exists():
            raise FileExistsError(
                f"Directory '{target_dir}' already exists. "
                "Cannot scaffold into an existing directory."
            )

        # Build context for templates
        context = {
            "project_name": project_name,
            "package_name": package_name,
            "class_name": class_name,
            "domain_name": domain_name,
            "display_name": display_name,
            "domain_name_upper": domain_name_upper,
        }

        # Create directory structure
        src_dir = target_dir / "src" / package_name
        testing_dir = src_dir / "testing"
        src_dir.mkdir(parents=True)
        testing_dir.mkdir(parents=True)

        # Render templates
        self._render_template(
            "domain-sdk/pyproject.toml.j2",
            target_dir / "pyproject.toml",
            context,
        )
        self._render_template(
            "domain-sdk/__init__.py.j2",
            src_dir / "__init__.py",
            context,
        )
        self._render_template(
            "domain-sdk/_types.py.j2",
            src_dir / "_types.py",
            context,
        )
        self._render_template(
            "domain-sdk/_protocols.py.j2",
            src_dir / "_protocols.py",
            context,
        )
        self._render_template(
            "domain-sdk/_errors.py.j2",
            src_dir / "_errors.py",
            context,
        )
        self._render_template(
            "domain-sdk/_events.py.j2",
            src_dir / "_events.py",
            context,
        )
        self._render_template(
            "domain-sdk/_metadata.py.j2",
            src_dir / "_metadata.py",
            context,
        )
        self._render_template(
            "domain-sdk/testing/__init__.py.j2",
            testing_dir / "__init__.py",
            context,
        )

    def _render_template(
        self, template_name: str, output_path: Path, context: dict[str, Any]
    ) -> None:
        """Render a Jinja2 template to the specified output path."""
        template = self._env.get_template(template_name)
        content = template.render(**context)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content)
