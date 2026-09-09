"""`RunRequest` is a value object, and the door must name itself.

These are the properties wave 3 relies on: seven doors each build a request
independently, and the only thing keeping them honest is that the object
refuses to be built wrong.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from functualize.types import RUN_SURFACES, RunRequest


def test_surface_is_required() -> None:
    with pytest.raises(TypeError):
        RunRequest(job_name="build")  # type: ignore[call-arg]


def test_unknown_surface_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown surface"):
        RunRequest(job_name="build", surface="func.jobb")  # type: ignore[arg-type]


def test_every_declared_surface_is_constructible() -> None:
    for surface in RUN_SURFACES:
        assert RunRequest(job_name="build", surface=surface).surface == surface  # type: ignore[arg-type]


def test_instance_is_immutable() -> None:
    request = RunRequest(job_name="build", surface="func.job")
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.job_name = "other"  # type: ignore[misc]


def test_instance_is_hashable_even_carrying_a_dict() -> None:
    """A mapping field must not cost the object its hashability."""
    bare = RunRequest(job_name="build", surface="func.job")
    loaded = RunRequest(job_name="build", surface="func.job", kwargs={"target": "x"})
    assert {bare, loaded}  # both hash
    assert bare != loaded  # equality still sees the payload


def test_replace_returns_a_new_request() -> None:
    request = RunRequest(job_name="build", surface="func.job")
    moved = request.replace(surface="engine.dependency")
    assert moved.surface == "engine.dependency"
    assert request.surface == "func.job"
    assert moved.job_name == request.job_name


def test_module_imports_nothing_from_functualize() -> None:
    """The layer rule, enforced by reading the source.

    import-linter enforces this too, but only when it is run; this fails in the
    fast suite, which is where a violation would actually be introduced.
    """
    source = Path("src/functualize/_types/run_request.py").read_text()
    tree = ast.parse(source)
    offenders = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("functualize")
    ] + [
        alias
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.startswith("functualize")
    ]
    assert not offenders, "run_request.py must stay stdlib-only"


def test_surfaces_match_the_literal() -> None:
    """`RUN_SURFACES` is derived, never retyped."""
    from typing import get_args, get_type_hints

    hints = get_type_hints(RunRequest, include_extras=False)
    assert set(get_args(hints["surface"])) == RUN_SURFACES
