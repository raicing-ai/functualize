"""Template registry for scaffold init templates.

Defines the available project templates and provides lookup/validation utilities.

Validates: Requirements R4-AC3, R4-AC9
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TemplateManifest:
    """Describes a scaffold init template."""

    name: str
    description: str
    template_dir: str
    dependencies: list[str] = field(default_factory=list)
    has_config_layers: bool = True


TEMPLATES: dict[str, TemplateManifest] = {
    "simple": TemplateManifest(
        name="simple",
        description="Minimal project with one sample job and layered configuration",
        template_dir="simple",
    ),
    "full-interactivity": TemplateManifest(
        name="full-interactivity",
        description="All interactivity plugins with samples demonstrating prompts, events, workflow steps",
        template_dir="full-interactivity",
        dependencies=[
            "functualize-inline",
            "functualize-flow-viz",
            "functualize-state-sqlite",
        ],
    ),
    "plugin-project": TemplateManifest(
        name="plugin-project",
        description="Starter for building a functualize plugin with OutputRenderer and InputProvider",
        template_dir="plugin-project",
    ),
    "job-folder": TemplateManifest(
        name="job-folder",
        description="Standalone jobs directory with file-based plugins",
        template_dir="job-folder",
    ),
}


def get_template(name: str) -> TemplateManifest:
    """Return the TemplateManifest for the given template name.

    Raises ValueError with available templates listed if name is invalid.
    """
    if name not in TEMPLATES:
        available = ", ".join(sorted(TEMPLATES.keys()))
        raise ValueError(f"Unknown template '{name}'. Available: {available}")
    return TEMPLATES[name]


def list_templates() -> list[str]:
    """Return a sorted list of all available template names."""
    return sorted(TEMPLATES.keys())


def validate_template_name(name: str) -> bool:
    """Return True if name is a valid template, False otherwise."""
    return name in TEMPLATES
