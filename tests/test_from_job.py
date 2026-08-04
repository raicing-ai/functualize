"""`FromJob` references — the declaration half of S8 (§D.5, contracts §7).

`FromJob` names an upstream job in a parameter annotation, making that one
annotation both the dependency edge and the injection. This module covers the
reference and its extraction only; resolving a reference to a *value* (is the
upstream fresh? is its value reusable? must it run first?) is the engine's
job and is tested with the engine.

Two things here are load-bearing and easy to get wrong:

- Extraction must resolve PEP 563 string annotations. A job module using
  `from __future__ import annotations` stores the annotation as a string,
  whose `get_origin` is None — so a raw read finds no references at all, in a
  module that plainly declares them. Every test that matters runs both ways.
- The reference must survive as *metadata*, not as a type. `FromJob[job]` was
  the ratified primary form until it was measured against mypy; a function
  object is not valid in a type position, so it cannot type-check in user
  code.
"""

import textwrap
from pathlib import Path
from types import ModuleType
from typing import Annotated

import pytest

from functualize._types.from_job import FromJob, FromStep, from_job_refs

MODULE = """
{future_import}
from pathlib import Path
from typing import Annotated

from functualize.job import FromJob


def build_wheel() -> Path:
    return Path("dist/x.whl")


def publish(wheel: Annotated[Path, FromJob(build_wheel)]) -> None: ...


def publish_by_name(wheel: Annotated[Path, FromJob("pkg.build_wheel")]) -> None: ...


def unrelated(count: int = 1) -> int:
    return count
"""


def _module(use_future: bool) -> ModuleType:
    source = MODULE.format(
        future_import="from __future__ import annotations" if use_future else ""
    )
    module = ModuleType(f"fromjob_jobs_{use_future}")
    exec(compile(textwrap.dedent(source), module.__name__, "exec"), module.__dict__)
    return module


class TestReference:
    def test_a_callable_reference_resolves_to_the_job_name(self) -> None:
        def build_wheel() -> None: ...

        assert FromJob(build_wheel).name == "build-wheel"

    def test_a_string_reference_is_canonicalized(self) -> None:
        """A string is an address too, so it normalizes like any other."""
        assert FromJob("pkg.build_wheel").name == "pkg.build-wheel"

    def test_a_grouped_job_resolves_to_its_qualified_name(self) -> None:
        """A grouped job registers as `group.func`, so that is what a
        reference must resolve to — a bare leaf name matches nothing."""

        def compile_it() -> None: ...

        compile_it.__functualize_job__ = type("D", (), {"group": "build"})()
        assert FromJob(compile_it).name == "build.compile-it"

    def test_an_empty_reference_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            FromJob("   ")

    def test_a_non_callable_non_string_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="registered job name or a callable"):
            FromJob(42)  # type: ignore[arg-type]

    def test_a_reference_is_immutable(self) -> None:
        ref = FromJob("build")
        with pytest.raises(AttributeError):
            ref.job = "other"  # type: ignore[misc]

    def test_references_compare_by_name(self) -> None:
        """The object and string forms name the same upstream and must not be
        two different dependencies."""

        def build() -> None: ...

        assert FromJob(build) == FromJob("build")
        assert len({FromJob(build), FromJob("build")}) == 1


class TestSubscriptIsRefused:
    """`FromJob[job]` was ratified as primary, then measured and dropped."""

    def test_it_raises_with_the_syntax_that_works(self) -> None:
        def build_wheel() -> None: ...

        with pytest.raises(TypeError) as excinfo:
            FromJob[build_wheel]

        message = str(excinfo.value)
        assert "Annotated[" in message, "the error must show the working form"
        assert "build_wheel" in message

    def test_the_reason_is_stated_not_just_the_rule(self) -> None:
        """A reader who is told only "don't" will try it again elsewhere."""
        with pytest.raises(TypeError, match="type position"):
            FromJob["build"]


@pytest.mark.parametrize("use_future", [False, True], ids=["live", "pep563"])
class TestExtraction:
    """Every case runs with and without PEP 563; the two must agree."""

    def test_an_object_reference_is_found(self, use_future: bool) -> None:
        module = _module(use_future)
        assert from_job_refs(module.publish) == {"wheel": FromJob("build_wheel")}

    def test_a_string_reference_is_found(self, use_future: bool) -> None:
        module = _module(use_future)
        assert from_job_refs(module.publish_by_name) == {
            "wheel": FromJob("pkg.build_wheel")
        }

    def test_a_job_with_no_references_yields_nothing(self, use_future: bool) -> None:
        module = _module(use_future)
        assert from_job_refs(module.unrelated) == {}

    def test_the_two_annotation_forms_agree(self, use_future: bool) -> None:
        module = _module(use_future)
        assert (
            from_job_refs(module.publish)["wheel"].name
            == from_job_refs(module.publish_by_name)["wheel"].name.split(".")[-1]
        )


class TestExtractionEdges:
    def test_a_plain_annotated_parameter_is_not_a_reference(self) -> None:
        """`Annotated` carries many markers; only FromJob metadata counts."""

        def job(x: Annotated[int, "just a note"] = 1) -> None: ...

        assert from_job_refs(job) == {}

    def test_the_return_annotation_is_never_a_reference(self) -> None:
        def job() -> Annotated[Path, FromJob("build")]: ...  # type: ignore[empty-body]

        assert from_job_refs(job) == {}

    def test_several_references_are_all_found(self) -> None:
        def job(
            a: Annotated[Path, FromJob("one")],
            b: Annotated[Path, FromJob("two")],
        ) -> None: ...

        assert set(from_job_refs(job)) == {"a", "b"}

    def test_an_unresolvable_annotation_does_not_raise(self) -> None:
        """A TYPE_CHECKING-only import makes get_type_hints fail for the whole
        function. Losing the references is acceptable; failing the run is not.
        """
        module = _module(True)
        source = """
        from __future__ import annotations
        from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from nowhere import Ghost
        def haunted(x: Ghost) -> None: ...
        """
        ghost = ModuleType("fromjob_ghost")
        exec(compile(textwrap.dedent(source), ghost.__name__, "exec"), ghost.__dict__)

        assert from_job_refs(ghost.haunted) == {}
        assert from_job_refs(module.publish)  # unaffected


class TestFromStep:
    """`FromStep` reads this walk's recorded result (resolved Q20).

    Separate from `FromJob` because the two answer different questions: a
    `FromJob` in a signature is a dependency edge that may cause work, while
    a `FromStep` is read from inside a walk that has already produced it and
    can never trigger anything.
    """

    def test_a_name_is_canonicalized(self) -> None:
        assert FromStep("setup_vfs").name == "setup-vfs"

    def test_a_callable_reference_resolves(self) -> None:
        def setup_vfs() -> None: ...

        assert FromStep(setup_vfs).name == "setup-vfs"

    def test_references_compare_by_name(self) -> None:
        def setup_vfs() -> None: ...

        assert FromStep(setup_vfs) == FromStep("setup_vfs")
        assert len({FromStep("setup-vfs"), FromStep("setup_vfs")}) == 1

    def test_it_carries_no_run_flag(self) -> None:
        """There is nothing to opt out of: it never runs anything."""
        assert not hasattr(FromStep("x"), "run")

    def test_an_empty_reference_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            FromStep("   ")

    def test_a_non_callable_non_string_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="step name or a callable"):
            FromStep(42)  # type: ignore[arg-type]

    def test_it_is_immutable(self) -> None:
        ref = FromStep("build")
        with pytest.raises(AttributeError):
            ref.step = "other"  # type: ignore[misc]

    def test_it_is_not_interchangeable_with_from_job(self) -> None:
        """Distinct types on purpose — the whole point is that the position
        determines which operation is meant."""
        assert FromStep("build") != FromJob("build")
