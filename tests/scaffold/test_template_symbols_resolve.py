"""Rendered scaffold templates only reference symbols that actually exist.

Every scaffold template is already checked with `ast.parse`, which proves the
generated file is syntactically valid Python. That is not enough: `ast.parse`
happily accepts `RunStatus.FAILED`, an attribute that does not exist on the enum,
because the reference is only resolved when the line runs.

That gap shipped. `full-interactivity/workflow_job.py.j2` referenced
`RunStatus.FAILED` on four lines, all of them on failure paths, so every
generated copy of that template raised `AttributeError` the moment the user's job
failed — and the success path, which is what anyone trying the template out
exercises, worked fine.

Importing the rendered module would not have caught it either: the references sit
inside a function body and are never evaluated at import time. So this checks
statically instead, resolving every `<Enum>.<MEMBER>` reference in the generated
source against the real class.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from functualize._cli.scaffold.generator import ScaffoldGenerator
from functualize._cli.scaffold.registry import list_templates

# Classes worth resolving members against: imported from functualize by the
# templates, and cheap to import here. Keyed by the name the templates bind.
_CHECKED_IMPORT_ROOTS = ("functualize",)


def _template_names() -> list[str]:
    """Every template the registry can scaffold."""
    return list_templates()


def _imported_symbols(tree: ast.Module) -> dict[str, str]:
    """Map locally-bound name -> "module:attr" for functualize imports."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if not node.module.startswith(_CHECKED_IMPORT_ROOTS):
                continue
            for alias in node.names:
                found[alias.asname or alias.name] = f"{node.module}:{alias.name}"
    return found


def _attribute_references(
    tree: ast.Module, bound: dict[str, str]
) -> list[ast.Attribute]:
    """`X.y` nodes where X is one of the imported names we can resolve."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in bound
    ]


@pytest.fixture(scope="module")
def generator() -> ScaffoldGenerator:
    return ScaffoldGenerator()


@pytest.mark.parametrize("template", _template_names())
def test_rendered_template_references_only_real_symbols(
    template: str, tmp_path: Path, generator: ScaffoldGenerator
) -> None:
    """Every `Imported.MEMBER` in generated code resolves on the real object.

    Catches the `RunStatus.FAILED` class of defect, which `ast.parse` cannot see
    and importing the module cannot see either.
    """
    project_dir = tmp_path / "my-app"
    generator.init_project("my-app", project_dir, template=template)

    for py_file in sorted(project_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text(), filename=str(py_file))
        bound = _imported_symbols(tree)
        if not bound:
            continue

        for node in _attribute_references(tree, bound):
            assert isinstance(node.value, ast.Name)  # narrowed by the helper
            module_path, attr_name = bound[node.value.id].split(":")
            obj = getattr(importlib.import_module(module_path), attr_name)
            # Only resolve against classes/enums; instances of runtime-injected
            # capabilities (RunContext and friends) are parameters here, not the
            # imported class, and their attribute surface is checked elsewhere.
            if not isinstance(obj, type):
                continue
            assert hasattr(obj, node.attr), (
                f"{py_file.relative_to(project_dir)}:{node.lineno} references "
                f"{node.value.id}.{node.attr}, which does not exist on "
                f"{module_path}:{attr_name}. Generated code would raise "
                f"AttributeError when this line runs."
            )
