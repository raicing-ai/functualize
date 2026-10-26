"""A job's shell spelling has one author: ``CommandPath``.

A job has a dotted identity (``suite.inventory``) and a command path
(``suite inventory``). Sixteen sites used to turn the first into the second by
hand -- ``name.replace(".", " ")`` or ``name.split(".")`` -- and each was wrong
in the same two ways: a literal dot inside one leaf (``tools.lint``) became a
group boundary, and the result was a spelling no surface had agreed on. The
path now comes from the descriptor (``JobDescriptor.command_path``) or from the
trie, both of which use the one segment rule in ``_types/naming.py``.

This ratchet keeps it that way. It reads the source, not behaviour: a new
renderer that rebuilds a path from a name would pass every behavioural test
that happens not to use a literal-dot leaf.

**What counts as a job name.** The receiver's own name is checked against a
vocabulary of identity names (``name``, ``job_name``, ``workflow_name``, ...),
so the dotted identifiers that are *not* job names -- versions, modules, event
names, config sections, vault targets, plugin namespaces, groups, typed shell
tokens -- stay legal. ``rsplit(".", 1)`` is outside this rule: E8 names the two
conversions above, and the leaf derivations that use ``rsplit`` predate it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

#: The one module allowed to split a job identity: it owns the segment rule.
_NAMING_BOUNDARY = _ROOT / "src" / "functualize" / "_types" / "naming.py"

#: Receivers that hold a job's dotted identity (or a token spelled like one).
_JOB_IDENTITY = frozenset(
    {
        "name",
        "job_name",
        "workflow_name",
        "canonical_name",
        "qualified_name",
        "payload",
        "raw_name",
        "dotted_token",
    }
)


def _receiver_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_str(node: ast.expr, value: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


def job_name_conversions(source: str) -> list[tuple[int, str]]:
    """``(line, call)`` for every dot-to-space or dot split of a job identity."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if _receiver_name(node.func.value) not in _JOB_IDENTITY:
            continue
        args = node.args
        to_spaces = (
            node.func.attr == "replace"
            and len(args) == 2
            and _is_str(args[0], ".")
            and _is_str(args[1], " ")
        )
        split = node.func.attr == "split" and len(args) >= 1 and _is_str(args[0], ".")
        if to_spaces or split:
            found.append((node.lineno, ast.unparse(node)))
    return found


def _production_sources() -> list[Path]:
    roots = [_ROOT / "src" / "functualize", *(_ROOT / "plugins").glob("*/*/src")]
    return sorted(
        path
        for root in roots
        for path in root.rglob("*.py")
        if path.resolve() != _NAMING_BOUNDARY.resolve()
    )


def test_no_production_source_converts_a_job_name_by_hand() -> None:
    offenders = [
        f"{path.relative_to(_ROOT)}:{line}: {call}"
        for path in _production_sources()
        for line, call in job_name_conversions(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "A job name is converted to a shell spelling by hand. Render "
        "`descriptor.command_path` (or the trie's path) instead; only "
        "`_types/naming.py` may split an identity:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_covers_the_tree() -> None:
    """A ratchet that reads no files passes forever."""
    sources = _production_sources()
    assert len(sources) > 300
    assert any(path.name == "_workflow_resume.py" for path in sources)
    assert not any(path.resolve() == _NAMING_BOUNDARY.resolve() for path in sources)


@pytest.mark.parametrize(
    "snippet",
    [
        'job_name.replace(".", " ")',
        "workflow_name.replace('.', ' ')",
        'descriptor.name.split(".")',
        'job.name.split(".")[0]',
        'resolution.dotted_token.replace(".", " ")',
        'name.split(".", 1)',
    ],
)
def test_a_conversion_of_a_job_identity_is_caught(snippet: str) -> None:
    assert job_name_conversions(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        'version_str.split(".")',
        'module_name.split(".")',
        'event_name.split(".")',
        'section.split(".")',
        'identity.target.split(".")',
        'namespace.split(".")[0]',
        'group.split(".")',
        'token.split(".")',
        'text.lower().replace(".", " ")',
        'job_name.rsplit(".", 1)',
        'name.replace("_", "-")',
    ],
)
def test_unrelated_dotted_identifiers_are_left_alone(snippet: str) -> None:
    assert not job_name_conversions(snippet)
