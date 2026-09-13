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


def test_every_declared_surface_is_one_a_door_actually_produces() -> None:
    """Replaces a tautology (rre F13).

    This used to iterate `RUN_SURFACES` and assert each value constructs. But
    `RUN_SURFACES` **is** `get_args(RunSurface)` and `__post_init__` rejects
    exactly its complement — so it asserted that the set derived from the
    closed set is inside the closed set. It could not fail, which is the
    signature defect of this branch, sitting in the file that pins the type.

    The falsifiable property underneath is the one the vocabulary is *for*: a
    label nothing can produce is decoration, which is why `func.builtin` and
    `func.bare` were deleted (and why `func.builtin` came back only when a door
    needed it). So every declared surface must appear as a literal somewhere
    that builds or routes a request — not merely be constructible.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    haystack = "\n".join(
        path.read_text(encoding="utf-8")
        for folder in ("src", "plugins")
        for path in sorted((root / folder).rglob("*.py"))
        # The declaration itself is not a producer.
        if path.name != "run_request.py"
    )
    unproduced = [
        surface
        for surface in sorted(RUN_SURFACES)
        if not re.search(rf'["\']{re.escape(surface)}["\']', haystack)
    ]
    assert not unproduced, (
        "these surfaces are declared and nothing names them, so no door can "
        f"produce them: {unproduced}"
    )


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


class TestOneWireContract:
    """`request_from_envelope` is the only copy — rre F12.

    HTTP and Lambda held **byte-identical** `_envelope` functions differing
    only in the `surface` literal, and MCP's two doors restated the same shape
    in prose. One wire contract maintained in four places, with its breaking
    change documented four times — and three of the four citations pointing at
    the wrong criterion (`risk R-a` is T11's risk; `AC-4` is "no file outside
    `_engine/` passes a job function"; the criterion is **AC-17a**). A reader
    auditing AC-17a through its named keeper, which only exercises
    `request_for`, would have concluded the wire doors were uncovered.

    Nothing about layering required the fork: this module is stdlib-only and
    every one of those doors already imports `RunRequest` from it.
    """

    @staticmethod
    def _parse(**payload: object):
        from functualize._types.run_request import request_from_envelope

        return request_from_envelope(payload, job_name="deploy", surface="http")

    def test_job_arguments_stay_under_arguments(self) -> None:
        request = self._parse(arguments={"target": "prod"})
        assert request.kwargs == {"target": "prod"}

    def test_a_control_input_beside_arguments_is_not_a_job_argument(self) -> None:
        """AC-17a itself: the nesting is what stops a payload key binding to a
        control parameter."""
        request = self._parse(arguments={"target": "prod"}, scope_id="run-42")

        assert request.workflow_scope_id == "run-42"
        assert "scope_id" not in request.kwargs

    def test_a_job_parameter_named_scope_id_is_still_an_argument(self) -> None:
        """The other direction, and the reason the envelope exists: a flat body
        made these two indistinguishable."""
        request = self._parse(arguments={"scope_id": "a value the job wants"})

        assert request.kwargs == {"scope_id": "a value the job wants"}
        assert request.workflow_scope_id is None

    def test_the_surface_is_the_callers_to_state(self) -> None:
        """The literal that used to be the whole reason for two copies."""
        from functualize._types.run_request import request_from_envelope

        for door in ("http", "lambda"):
            request = request_from_envelope({}, job_name="d", surface=door)  # type: ignore[arg-type]
            assert request.surface == door

    def test_a_wrong_type_is_reported_by_field_name(self) -> None:
        """ "Invalid payload" sends a caller hunting through a body they believe
        is correct."""
        for field, value in (
            ("arguments", "not an object"),
            ("group_option_values", 7),
            ("scope_id", 42),
        ):
            with pytest.raises(ValueError, match=field):
                self._parse(**{field: value})

    def test_both_wire_doors_route_through_it(self) -> None:
        """The structural half: a fifth copy is what this finding was about.

        Asserted over the plugin sources rather than by calling them, because
        what must not come back is the *duplication*, and duplication is a
        property of the text.
        """
        import re
        from pathlib import Path

        plugins = Path(__file__).resolve().parents[2] / "plugins"
        for rel in (
            "functualize-http/src/functualize_http/__init__.py",
            "functualize-lambda/src/functualize_lambda/__init__.py",
        ):
            text = (plugins / rel).read_text(encoding="utf-8")
            assert "request_from_envelope(" in text, f"{rel} does not use the contract"
            assert not re.search(r"payload\.get\(['\"]scope_id['\"]\)", text), (
                f"{rel} parses the envelope itself again"
            )
