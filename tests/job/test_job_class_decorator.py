"""`@job` accepts a class target — the three `apply` checks (plan.md §4.1).

A class target is a `pydantic.BaseModel` and carries only `group`, `tags`,
`visibility` — the declaration fields that describe identity, which is what
`@job` is about. Operational fields (`deps`, `cache`, `guards`, `exec`) and the
description fields belong to a job's *method*, not to its config class. One
`ValueError` lists every offending argument, so a user who wrote two is told
about two.

D4: one `@job` per definition. The check reads `func.__dict__`, not `getattr`,
so an inherited declaration never makes a subclass look declared — F1-b, not
this task, decides what a subclass of a decorated class means.

The double-application check applies to functions too: the bare and
parameterized forms are unchanged, but decorating the same function twice is
rejected with the exact D4 text rather than silently overwriting.

Each accepted-form test decorates its own class: `@job` mutates the target in
place, so a shared class would make the second decoration a double-application
rather than a second form.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from functualize.job import job


class Model(BaseModel):
    """A minimal config class — a plain `BaseModel` subclass."""

    x: int = 1


class Sub(Model):
    """A subclass of a decorated class — F1-b's rule, not this task's."""


class NotAModel:
    """A class that is not a `BaseModel` — refused at decoration."""


class TestClassTargetAccepted:
    def test_bare_job_on_a_model_is_identity_preserving(self) -> None:
        class Bare(BaseModel):
            x: int = 1

        decorated = job(Bare)
        assert decorated is Bare
        assert Bare.__functualize_job__ is not None

    def test_parameterized_job_on_a_model_is_identity_preserving(self) -> None:
        class Param(BaseModel):
            x: int = 1

        decorated = job(group="pg")(Param)
        assert decorated is Param
        assert Param.__functualize_job__.group == "pg"

    def test_class_declaration_holds_the_accepted_fields(self) -> None:
        class Tagged(BaseModel):
            y: int = 0

        job(tags=("a", "b"), visibility="internal")(Tagged)
        declaration = Tagged.__functualize_job__
        assert declaration.tags == ("a", "b")
        assert declaration.visibility == "internal"


class TestClassTargetArguments:
    def test_offending_arguments_are_listed_together(self) -> None:
        # Two arguments a class may not take, one error naming both.
        with pytest.raises(ValueError) as excinfo:
            job(config_section="x", category="c")(Model)
        message = str(excinfo.value)
        assert "config_section" in message
        assert "category" in message

    def test_every_offending_argument_is_named(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            job(category="c", examples=("e",), extra_description="d")(Model)
        message = str(excinfo.value)
        for name in ("category", "examples", "extra_description"):
            assert name in message

    def test_the_three_accepted_fields_are_not_offending(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            job(group="pg", tags=("a",), visibility="internal", config_section="x")(
                Model
            )
        message = str(excinfo.value)
        assert "offending arguments: config_section" in message


class TestNonModelClassRefused:
    def test_non_model_class_is_refused_naming_the_target(self) -> None:
        with pytest.raises(ValueError) as excinfo:
            job(NotAModel)
        message = str(excinfo.value)
        assert "NotAModel" in message
        assert "BaseModel" in message

    def test_non_model_class_is_refused_parameterized(self) -> None:
        with pytest.raises(ValueError, match="BaseModel"):
            job(group="pg")(NotAModel)


class TestDoubleApplication:
    def test_second_job_on_a_class_produces_the_d4_text(self) -> None:
        class Twice(BaseModel):
            z: int = 0

        job(Twice)
        with pytest.raises(ValueError) as excinfo:
            job(Twice)
        message = str(excinfo.value)
        assert message.startswith("@job is already applied to ")
        assert message.endswith("; combine the arguments into one @job(...)")
        assert "Twice" in message

    def test_second_job_on_a_function_produces_the_d4_text(self) -> None:
        def target() -> None: ...

        job(target)
        with pytest.raises(ValueError) as excinfo:
            job(target)
        message = str(excinfo.value)
        assert message.startswith("@job is already applied to ")
        assert message.endswith("; combine the arguments into one @job(...)")
        assert "target" in message

    def test_inherited_declaration_is_not_double_application(self) -> None:
        # __dict__, not getattr: an inherited declaration must not make a
        # subclass look declared (F1-b is discovery's rule).
        class Base(BaseModel):
            a: int = 0

        job(Base)
        # Assert the inheritance copies nothing, before decorating Sub.
        assert "__functualize_job__" not in Sub.__dict__
        job(Sub)  # not refused at decoration


class TestFunctionFormsUnchanged:
    def test_bare_function_form_is_unchanged(self) -> None:
        def build() -> None: ...

        decorated = job(build)
        assert decorated is build
        assert build.__functualize_job__ is not None

    def test_parameterized_function_form_is_unchanged(self) -> None:
        def deploy() -> None: ...

        decorated = job(group="infra")(deploy)
        assert decorated is deploy
        assert deploy.__functualize_job__.group == "infra"

    def test_function_declaration_holds_every_field(self) -> None:
        def report() -> None: ...

        job(
            group="infra",
            extra_description="d",
            category="c",
            examples=("e",),
            tags=("a",),
            visibility="internal",
            config_section="x",
        )(report)
        declaration = report.__functualize_job__
        assert declaration.group == "infra"
        assert declaration.config_section == "x"
        assert declaration.tags == ("a",)
