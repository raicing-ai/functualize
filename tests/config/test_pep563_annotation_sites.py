"""Every site that decides something from an annotation, under PEP 563.

`from __future__ import annotations` turns every annotation in a module into a
string. Code that reads `inspect.Parameter.annotation` raw and then asks
`isinstance(x, type)` or `get_origin(x)` matches nothing in such a module, and
matches nothing *silently* — a string annotation is perfectly legal, so there
is no error, just a feature that stops working.

An audit found five such sites. They are covered here together because they
fail the same way for the same reason, and because a fix applied to one is
worth nothing if the next contributor writes site six.

Every job module in this file is compiled twice — once with the future import
and once without — and both are asserted to agree. "Agrees with the non-PEP-563
form" is the property; it cannot be satisfied by a fix that merely makes the
PEP 563 path do *something*.
"""

import textwrap
from collections.abc import Generator
from pathlib import Path
from types import ModuleType

import pytest

from functualize._app.state import AppState
from functualize._types.annotations import resolved_hints


@pytest.fixture(autouse=True)
def _isolated_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    project = tmp_path / "project"
    (project / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    AppState.reset()
    yield
    AppState.reset()


def _compile(source: str, name: str) -> ModuleType:
    module = ModuleType(name)
    exec(compile(textwrap.dedent(source), name, "exec"), module.__dict__)
    return module


def _both_forms(body: str, name: str) -> tuple[ModuleType, ModuleType]:
    """The same module compiled with and without PEP 563."""
    live = _compile(body, f"{name}_live")
    pep563 = _compile(
        "from __future__ import annotations\n" + textwrap.dedent(body),
        f"{name}_pep563",
    )
    return live, pep563


CONFIG_JOB = """
from pydantic import BaseModel


class ReportConfig(BaseModel):
    city: str = "Tokyo"
    days: int = 3


def report(config: ReportConfig) -> str:
    return f"{config.city}/{config.days}"
"""

FIELD_JOB = """
from typing import Annotated

from pydantic import Field


def bounded(count: Annotated[int, Field(ge=0, le=10)] = 1) -> int:
    return count
"""


class TestResolvedHintsPrimitive:
    def test_it_resolves_string_annotations(self) -> None:
        _, pep563 = _both_forms(CONFIG_JOB, "prim")

        hints = resolved_hints(pep563.report)

        assert hints["config"] is pep563.ReportConfig

    def test_it_returns_empty_rather_than_raising(self) -> None:
        """A TYPE_CHECKING-only name makes get_type_hints raise for the whole
        function. Callers fall back to raw annotations, so one unresolvable
        parameter must not cost them the others."""
        module = _compile(
            """
            from __future__ import annotations

            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                from nowhere import Ghost


            def haunted(x: Ghost) -> None: ...
            """,
            "prim_unresolvable",
        )

        assert resolved_hints(module.haunted) == {}

    def test_it_keeps_annotated_metadata(self) -> None:
        """include_extras=True — without it, Field()/Arg()/Option() markers are
        stripped and every marker-driven feature breaks instead."""
        from typing import get_args, get_origin

        _, pep563 = _both_forms(FIELD_JOB, "prim_field")
        annotation = resolved_hints(pep563.bounded)["count"]

        from typing import Annotated

        assert get_origin(annotation) is Annotated
        assert get_args(annotation)[1:], "Field() metadata was stripped"


class TestConfigClassDetection:
    """`_detect_job_config_class` — registry.py. Broken here means a job runs with
    no config resolution at all."""

    def test_both_forms_detect_the_config_class(self) -> None:
        from functualize._discovery.registry import JobRegistry

        live, pep563 = _both_forms(CONFIG_JOB, "detect")
        detect = JobRegistry._detect_job_config_class

        assert detect(live.report) is live.ReportConfig
        assert detect(pep563.report) is pep563.ReportConfig


class TestFieldDescriptorExtraction:
    """`extract_capability_markers` / parameter extraction — providers.py.
    Broken here means no CLI options and an empty TUI config panel."""

    def test_both_forms_yield_the_same_parameter_types(self) -> None:
        """Types, not just names.

        Parameter *names* come from the signature and survive even a total
        failure to resolve annotations, so asserting on them proves nothing.
        The type string is what the CLI builds an option from, and it is
        derived from the annotation.
        """
        from functualize._discovery.providers import (
            extract_parameters_from_signature,
        )

        live, pep563 = _both_forms(FIELD_JOB, "params")

        live_types = {
            p.name: p.type_annotation
            for p in extract_parameters_from_signature(live.bounded)
        }
        pep563_types = {
            p.name: p.type_annotation
            for p in extract_parameters_from_signature(pep563.bounded)
        }

        assert live_types == pep563_types == {"count": "int"}


class TestArgumentValidation:
    """`_build_validation_model` — validation.py. The worst of the five:
    `Field()` constraints stop being enforced, so out-of-range input is
    silently accepted rather than rejected."""

    def test_both_forms_build_a_validation_model(self) -> None:
        from functualize._engine.validation import _build_validation_model

        live, pep563 = _both_forms(FIELD_JOB, "validate")

        assert _build_validation_model(live.bounded) is not None
        assert _build_validation_model(pep563.bounded) is not None, (
            "PEP 563 module produced no validation model — Field() constraints "
            "would be silently unenforced"
        )

    def test_constraints_are_actually_enforced_under_pep563(self) -> None:
        """Not "a model was built" — that the model rejects bad input."""
        from pydantic import ValidationError

        from functualize._engine.validation import ArgValidator

        _, pep563 = _both_forms(FIELD_JOB, "enforce")
        validator = ArgValidator()

        assert validator.validate(pep563.bounded, {"count": 5}) == {"count": 5}
        with pytest.raises(ValidationError):
            validator.validate(pep563.bounded, {"count": 99})

    def test_the_two_forms_agree_on_rejection(self) -> None:
        from pydantic import ValidationError

        from functualize._engine.validation import ArgValidator

        live, pep563 = _both_forms(FIELD_JOB, "agree")
        validator = ArgValidator()

        for module in (live, pep563):
            with pytest.raises(ValidationError):
                validator.validate(module.bounded, {"count": -1})
