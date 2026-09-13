"""Every delivery surface names its family in code, and means it — AC-3.

`spec.md`: *"Each delivery surface names its family in one place, and the name
is greppable."* Three of six named it **in a docstring**. T6's gate was
`rg -c 'Family.WIRE' <file>` → `≥1`, which that docstring satisfied on its own —
and the docstring even asserted the property the gate was meant to check:
*"naming it keeps the surface-to-family map greppable"*. A gate matching its own
explanation is `AUDIT.md`'s hazard #1, and it is why `Family.WIRE` and
`Family.TOOL` reached this branch with **no code consumer anywhere**: nothing
imported `Family` in those three plugins at all. Two members of a four-member
vocabulary were decoration.

(They should also have failed T13's orphan scan, which asserts every added
symbol has a consumer. It did not catch them.)

Each of the three now declares `OUTCOME_FAMILY`, and this file is the consumer
that makes the declaration mean something: a family is not a label, it is a
claim about **how the surface treats a paused run**, and BLOCKED is the one
status the four families disagree about. So the declared family is checked
against what the surface actually renders.

That is the difference between "the name appears in the file" and "the name is
true of the file".
"""

from __future__ import annotations

import pytest

from functualize.types import Family, RunStatus, is_failure

pytest.importorskip("functualize_http", reason="plugin suites run per package")


def _surfaces() -> list[tuple[str, Family]]:
    """`(label, declared family)` for every surface that publishes one."""
    from functualize_http import OUTCOME_FAMILY as HTTP_FAMILY
    from functualize_lambda import OUTCOME_FAMILY as LAMBDA_FAMILY

    return [("http", HTTP_FAMILY), ("lambda", LAMBDA_FAMILY)]


def test_the_declared_families_are_real_members() -> None:
    """A string that merely looks like one would pass every test below."""
    for label, family in _surfaces():
        assert isinstance(family, Family), f"{label} declares {family!r}, not a Family"


def test_the_declared_family_matches_what_the_surface_does() -> None:
    """The declaration checked against behaviour, not merely against itself.

    A family is a claim about how the surface treats a paused run. Both of
    these surfaces render one through `http_status_for_status`, so the question
    is decidable: 202 Accepted is not an error class, a gated run has not
    failed, and a load balancer or retry policy reading the status line must
    not treat it as a fault.

    Written as an equality rather than as "if WIRE, then …" on purpose — a
    conditional would simply *skip* a surface that declared the wrong family,
    which is the case the test exists for.
    """
    from functualize.types import http_status_for_status

    renders_as_error = http_status_for_status(RunStatus.BLOCKED) >= 400
    for label, family in _surfaces():
        assert is_failure(RunStatus.BLOCKED, family=family) == renders_as_error, (
            f"{label} declares {family.name}, whose table says a paused run is "
            f"{'a failure' if is_failure(RunStatus.BLOCKED, family=family) else 'not a failure'}"
            f" — but it renders BLOCKED as "
            f"{http_status_for_status(RunStatus.BLOCKED)}"
        )


def test_the_families_would_notice_being_swapped() -> None:
    """The falsifier.

    If every family answered alike for BLOCKED, the assertion above would hold
    for any declaration at all and this file would be checking nothing.
    """
    assert is_failure(RunStatus.BLOCKED, family=Family.PROCESS)
    assert not is_failure(RunStatus.BLOCKED, family=Family.WIRE)


def test_the_declaration_is_greppable_as_code() -> None:
    """AC-3's literal wording, checked where the docstring used to pass it.

    The pattern requires an assignment, so a mention inside prose no longer
    satisfies the criterion the way it did for T6's gate.
    """
    import re
    from pathlib import Path

    plugins = Path(__file__).resolve().parents[2] / "plugins"
    expected = {
        "functualize-http/src/functualize_http/__init__.py": "WIRE",
        "functualize-lambda/src/functualize_lambda/__init__.py": "WIRE",
        "functualize-mcp/src/functualize_mcp/_tools.py": "TOOL",
    }
    for rel, family in expected.items():
        text = (plugins / rel).read_text(encoding="utf-8")
        assert re.search(rf"^OUTCOME_FAMILY = Family\.{family}$", text, re.M), (
            f"{rel} does not declare its family as code; a docstring mention "
            "is what AC-3 was already satisfied by"
        )
