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


class TestEveryDoorIsClassified:
    """`SURFACE_POLICY` is total, and the totality is the mechanism.

    Two engine decisions used to be string comparisons in the kernel:
    `request.surface not in CONSOLE_SURFACES` and
    `request.surface == "app.parallel"`. The first answered **silently** — a
    door added to `RunSurface` and forgotten in the set simply stopped
    resolving stdin, with the parameter's default winning and nothing said —
    and the second is the same shape one file away. The stdin set was also a
    second hand-maintained taxonomy beside the 18-value `Literal`, with a third
    copy re-typed in `tests/engine/test_run_request_stdin.py`.

    A total mapping fixes the class rather than the instance: the lookup is a
    subscript, so an unclassified door raises rather than behaving like the
    majority, and this test is what makes "total" true rather than intended.
    """

    def test_every_surface_has_a_policy(self) -> None:
        from functualize._types.run_request import SURFACE_POLICY

        missing = RUN_SURFACES - set(SURFACE_POLICY)
        assert not missing, (
            "these doors exist in `RunSurface` and nothing says how the engine "
            f"should treat them: {sorted(missing)}"
        )

    def test_the_policy_names_no_surface_that_does_not_exist(self) -> None:
        """The other direction: a policy for a door that was deleted is a
        stale entry that reads as coverage."""
        from functualize._types.run_request import SURFACE_POLICY

        extra = set(SURFACE_POLICY) - RUN_SURFACES
        assert not extra, f"policy entries for non-existent doors: {sorted(extra)}"

    def test_an_unclassified_door_raises_rather_than_defaulting(self) -> None:
        """The behaviour the `frozenset` membership test could not have.

        This is the whole reason for the change: `"unheard-of" not in
        CONSOLE_SURFACES` is `True` and yields the majority answer in silence.
        """
        from functualize._types.run_request import SURFACE_POLICY

        with pytest.raises(KeyError):
            SURFACE_POLICY["a-door-nobody-declared"]  # type: ignore[index]

    def test_the_console_set_is_derived_from_the_policy(self) -> None:
        """`CONSOLE_SURFACES` survives as a name, not as a second list."""
        from functualize._types.run_request import CONSOLE_SURFACES, SURFACE_POLICY

        assert (
            frozenset(
                surface
                for surface, policy in SURFACE_POLICY.items()
                if policy.owns_stdin
            )
            == CONSOLE_SURFACES
        )

    def test_exactly_one_door_records_its_batch_items(self) -> None:
        """The falsifier for `records_batch_items`.

        If every door answered alike the field would be dead weight, and
        `_records_history` would be back to a plain depth rule — which is what
        left `func builtin history` empty after `func builtin parallel a b`.
        """
        from functualize._types.run_request import SURFACE_POLICY

        recording = {
            surface
            for surface, policy in SURFACE_POLICY.items()
            if policy.records_batch_items
        }
        assert recording == {"app.parallel"}
