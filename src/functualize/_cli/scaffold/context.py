"""Context detection for scaffold commands.

Determines whether the current working directory is inside a functualize
project (Project_Context) or a bare directory (Bare_Context).
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class ContextType(Enum):
    """Classification of the current working directory."""

    PROJECT = "project"
    BARE = "bare"


@dataclass(frozen=True)
class ScaffoldContext:
    """Result of context detection for the current working directory."""

    context_type: ContextType
    cwd: Path
    package_dir: Path | None = None  # src/<package>/ — None if BARE
    package_name: str | None = None  # The package name — None if BARE

    @property
    def is_project(self) -> bool:
        return self.context_type == ContextType.PROJECT

    @property
    def jobs_dir(self) -> Path | None:
        if self.package_dir is None:
            return None
        return self.package_dir / "jobs"


def detect_context(cwd: Path | None = None) -> ScaffoldContext:
    """Detect the scaffold context for the given or current directory.

    Classification rules:
    - Project_Context: cwd/src/ contains at least one child dir with __init__.py
    - Bare_Context: everything else

    Uses sorted() for deterministic package detection across platforms.
    """
    if cwd is None:
        cwd = Path.cwd()

    src_dir = cwd / "src"
    if src_dir.is_dir():
        for child in sorted(src_dir.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                return ScaffoldContext(
                    context_type=ContextType.PROJECT,
                    cwd=cwd,
                    package_dir=child,
                    package_name=child.name,
                )

    return ScaffoldContext(context_type=ContextType.BARE, cwd=cwd)
