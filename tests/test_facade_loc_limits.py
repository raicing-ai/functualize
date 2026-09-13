"""The two facades have a size, and exceeding it fails here (AC-10).

`RunContext` and `FunctualizeApp` are the objects a job author and an app author
hold. Both grew to the point where nobody could read them — 800 and 1450 lines —
by the same mechanism: every member individually reasonable, and no moment at
which anyone was told the total had moved. `engine-sealed-construction` put them
on a diet (T8, T9); this file is what keeps them there.

**Executable lines, not total.** The gate this replaced counted every line in
the class, and 792 of `FunctualizeApp`'s 1450 were docstrings. A total-line
budget is satisfied by deleting documentation from a public class, which is a
worse outcome than the size it was measuring. So docstrings, comments and blank
lines are excluded, and the numbers below are what the class actually *does*.

**It prints the count on failure**, so a breach reads as information rather than
as an accusation: you get the current number, the budget, and the largest
members, which is what you need to decide whether to split or to raise the
budget deliberately.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src" / "functualize"

#: `(module, class, budget)`. The budgets are AC-10's, and they are **ceilings
#: with headroom**, not targets: `RunContext` landed at 256 against 500 and
#: `FunctualizeApp` at 298 against 300. The second is tight on purpose — it is
#: the number the maintainer chose after the arithmetic showed 308 was the floor
#: with every movable body already gone, and it can only be met by *grouping
#: members*, which is the property worth defending.
#:
#: **300 → 302, 2026-09-12** (`store-substrate`/T5). `FunctualizeApp` gained
#: `substrate`, a new `EngineHost` member: a plugin installs a database there
#: and every store follows. Raised deliberately, which is the third answer this
#: file's failure message names, because the two cheaper ones were tried first
#: — the setter's guard is already in `_app/impl.py::install_substrate` (moving
#: it is what took this from +9 to +2), and `core.py` imports from `impl`
#: lazily on purpose, so hoisting the import to save a line would trade boot
#: time for a budget number.
#:
#: **302 → 303, 2026-09-12** (`workflow-graph-semantics`/T6). `FunctualizeApp`
#: gained `_notifier_registry`, beside `_agent_step_registry` and for the same
#: reason: the registry has to exist before the engine is constructed, because
#: `app.extensions.register_notifier` is a door a plugin may reach before boot
#: finishes. The two cheaper answers were tried first and neither applies — the
#: member is a bare annotation, so there is no body to move, and grouping it
#: with `_agent_step_registry` behind a "registries" facade is a refactor of
#: eleven call sites for one line, which trades a real seam for a number.
#:
#: The alternative considered and rejected: hanging the registry off the engine
#: and reaching it through a public `engine.register_notifier`. It saves the
#: line and costs the consistency — one port on the app, its twin on the
#: engine, with no reason a reader could find except this ceiling.
#:
#: No headroom added on top. A tight ceiling that is raised to exactly what fits
#: still binds the next addition; one raised to the next round number does not.
_BUDGETS: list[tuple[str, str, int]] = [
    ("_engine/capabilities/runcontext.py", "RunContext", 500),
    ("app/core.py", "FunctualizeApp", 303),
]


def _executable_lines(node: ast.ClassDef, lines: list[str]) -> int:
    """Lines in ``node`` that are neither blank, comment, nor docstring."""
    doc: set[int] = set()
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Expr)
            and isinstance(sub.value, ast.Constant)
            and isinstance(sub.value.value, str)
        ):
            doc.update(range(sub.lineno, sub.end_lineno + 1))
    return sum(
        1
        for i in range(node.lineno, node.end_lineno + 1)
        if lines[i - 1].strip()
        and not lines[i - 1].strip().startswith("#")
        and i not in doc
    )


def _members(node: ast.ClassDef, lines: list[str]) -> list[tuple[int, str]]:
    """``(executable lines, name)`` per method, largest first."""
    out = []
    for m in node.body:
        if not isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        start = min([d.lineno for d in m.decorator_list] + [m.lineno])
        stub = ast.ClassDef(
            name="_", bases=[], keywords=[], body=[m], decorator_list=[]
        )
        stub.lineno, stub.end_lineno = start, m.end_lineno
        out.append((_executable_lines(stub, lines), m.name))
    return sorted(out, reverse=True)


def _measure(
    relative: str, class_name: str
) -> tuple[int, list[tuple[int, str]], list[str]]:
    path = _SRC / relative
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    node = next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.ClassDef) and n.name == class_name
    )
    return _executable_lines(node, lines), _members(node, lines), lines


@pytest.mark.parametrize(
    ("relative", "class_name", "budget"),
    _BUDGETS,
    ids=[c for _, c, _ in _BUDGETS],
)
def test_the_facade_is_within_its_budget(
    relative: str, class_name: str, budget: int
) -> None:
    """The number, and — on a breach — what to do about it."""
    actual, members, _ = _measure(relative, class_name)

    largest = "\n".join(f"      {n:5} {name}" for n, name in members[:8])
    assert actual <= budget, (
        f"\n{class_name} is {actual} executable lines, over its {budget} budget "
        f"by {actual - budget}.\n\n"
        f"    Largest members:\n{largest}\n\n"
        f"    Moving a body to `_app/impl.py` or `_engine/` shrinks this. So does\n"
        f"    grouping members behind a facade — which is the only thing that\n"
        f"    works once the members are already thin, because a delegate costs\n"
        f"    about as many lines as it saves. Raising the budget is a legitimate\n"
        f"    third answer; make it deliberately, here, with the reason."
    )


@pytest.mark.parametrize(
    ("relative", "class_name", "budget"),
    _BUDGETS,
    ids=[c for _, c, _ in _BUDGETS],
)
def test_the_measurement_is_not_vacuous(
    relative: str, class_name: str, budget: int
) -> None:
    """A counter that returns 0 passes every budget and checks nothing.

    This is the falsifier for the test above. It also catches the class being
    renamed or moved: `_measure` raises `StopIteration` rather than reporting a
    comfortable zero.
    """
    actual, members, _ = _measure(relative, class_name)

    assert actual > 50, f"{class_name} measured {actual} lines — is the parse right?"
    assert members, f"{class_name} parsed as having no methods"


def test_docstrings_are_excluded_from_the_count() -> None:
    """The property the whole file turns on, asserted directly.

    `FunctualizeApp` carries ~750 lines of docstring. If those counted, the
    budget above would be met by deleting documentation from the framework's
    main public class — so this asserts the exclusion is real rather than
    assumed.
    """
    source = (_SRC / "app" / "core.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    node = next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.ClassDef) and n.name == "FunctualizeApp"
    )
    total = node.end_lineno - node.lineno + 1
    executable = _executable_lines(node, lines)

    assert total - executable > 200, (
        f"only {total - executable} lines were excluded as docstring/comment; "
        f"the exclusion looks broken"
    )
