"""The guide's *Which parameters are inputs* table is rendered from the matrix.

`docs/guides/jobs-discovery.md` documents, per declaration, what kind of input
a parameter is and where a caller can supply it. The table between the two
`parameter-inputs` markers is not prose to keep in step by hand: it is
:func:`render_table` over rows of the same declaration table the parity test
(`test_parameter_surface_parity.py`) drives every surface from
(`tests/_support/parameter_matrix.py`, spec AC-10). A verdict that changes in
the matrix changes the expected table, and this test fails until the guide
says the same.

To regenerate after a deliberate change, run
``uv run python -m tests.surfaces.test_parameter_docs_table`` and paste the
output between the markers.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from tests._support.parameter_matrix import ROWS

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "guides" / "jobs-discovery.md"
BEGIN = (
    "<!-- parameter-inputs:begin (rendered from tests/_support/parameter_matrix.py) -->"
)
END = "<!-- parameter-inputs:end -->"

#: The documented rows, by matrix id, with a reader-facing label where the
#: matrix's own declaration names a generated test class.
DOC_ROWS: tuple[tuple[str, str | None], ...] = (
    ("A001", None),
    ("A002", None),
    ("A003", None),
    ("A013", None),
    ("B053", None),
    ("B067", None),
    ("C079", None),
    ("B077", None),
    ("C081", None),
    ("C082", None),
    ("F144", "`f: int`, a field of a config model `p: Cfg`"),
    ("E111", None),
    ("H163", "`p: ProvWidget`, a class a plugin provides"),
    (
        "H166",
        '`p: Annotated[ProvWidget, Provide("nope")]`, no provider under that qualifier',
    ),
    ("C085", "`p: Widget`, a class nothing provides"),
    ("C088", None),
    ("A049", None),
    ("G155", None),
    ("D102", None),
)

_KIND = {
    "ACCEPTED_POSITIONAL": "caller input",
    "ACCEPTED_FLAG": "caller input",
    "INVOCATION_ONLY": "caller input, wire only",
    "CONFIG_FIELD": "config field",
    "INJECTED": "supplied by the framework",
    "REJECTED_DISCOVERY": "refused at discovery",
}


def _command_line(row: dict[str, Any]) -> str:
    spelling = row["cli_spelling"]
    if not spelling:
        return "—"
    word = spelling[0]
    repeatable = str(row["delivered_type"] or "").startswith(("list", "tuple"))
    if word.startswith("-"):
        cell = f"`{word}`"
        if repeatable:
            cell += ", repeatable"
    else:
        cell = f"positional `{word.upper()}`"
        if repeatable:
            cell += ", variadic"
    return cell + (", required" if row["required"] else "")


def _wire(row: dict[str, Any]) -> str:
    spelling = row["wire_spelling"]
    if not spelling:
        return "—"
    return f"`{spelling[0]}`" + (", required" if row["required"] else "")


def _receives(row: dict[str, Any]) -> str:
    delivered = row["delivered_type"]
    if row["expected_verdict"] == "REJECTED_DISCOVERY" or not delivered:
        return "— (every call is refused)"
    return f"`{delivered}`"


def _code(text: str) -> str:
    """``text`` as inline code that a table cell can hold.

    A `|` would end the cell, and Markdown's `\\|` escape shows its backslash
    inside a code span, so such a declaration is written as HTML code with the
    character reference.
    """
    if "|" not in text:
        return f"`{text}`"
    return "<code>" + html.escape(text, quote=False).replace("|", "&#124;") + "</code>"


def render_table() -> str:
    """The guide's table, from the matrix rows :data:`DOC_ROWS` names."""
    by_id = {row["id"]: row for row in ROWS}
    lines = [
        "| Declaration | Kind | `func <job>` | MCP, HTTP, Lambda, `info schema` "
        "| The job receives |",
        "| --- | --- | --- | --- | --- |",
    ]
    for rid, label in DOC_ROWS:
        row = by_id[rid]
        declaration = label or _code(row["declaration"])
        lines.append(
            f"| {declaration} | {_KIND[row['expected_verdict']]} "
            f"| {_command_line(row)} | {_wire(row)} | {_receives(row)} |"
        )
    return "\n".join(lines)


def _guide_table() -> str:
    text = GUIDE.read_text(encoding="utf-8")
    assert BEGIN in text and END in text, f"{GUIDE} lost its parameter-inputs markers"
    return text.split(BEGIN, 1)[1].split(END, 1)[0].strip()


def test_the_guide_table_is_the_rendered_matrix() -> None:
    expected = render_table()
    assert _guide_table() == expected, (
        "docs/guides/jobs-discovery.md disagrees with the declaration matrix; "
        "paste this between the markers:\n\n" + expected
    )


def test_every_verdict_is_documented() -> None:
    by_id = {row["id"]: row for row in ROWS}
    documented = {by_id[rid]["expected_verdict"] for rid, _ in DOC_ROWS}
    assert documented == {row["expected_verdict"] for row in ROWS}


def test_documented_rows_exist_and_are_unique() -> None:
    ids = [rid for rid, _ in DOC_ROWS]
    assert len(ids) == len(set(ids))
    assert set(ids) <= {row["id"] for row in ROWS}


if __name__ == "__main__":
    print(render_table())
