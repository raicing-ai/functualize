"""Every catalog entry has a producer, or is declared plugin-emitted.

The event catalog is public introspection: a plugin reads it at registration
time to learn what it can subscribe to. An entry nothing emits is a documented
lie, which is why `adjacent-defects` T6 gave `job.execute.error`,
`cli.parse.start` and `tui.session.*` a producer or removed them.

AC-5's second sentence then over-reached — *"No catalog entry lacks a
producer"* — and a review found the exception (adj N1): `interactivity.job.submit`
has **no in-tree producer by design**. It is the one event the framework
*consumes* rather than emits. `_app/boot.py` subscribes to it, and
`docs/guides/plugins.md` and `docs/guides/tui.md` tell an interactivity backend
to emit it; that is the whole contract. Deleting it would delete the seam.

So the rule is not "every entry is emitted" but **"every entry is emitted, or is
named here with the reason it is not"** — and this test is what makes the second
half cost something. The list below is one name long. A second one added without
a reason fails; a name that *acquires* a producer also fails, because a stale
exemption is the same documented lie pointed the other way.
"""

from __future__ import annotations

import ast
from pathlib import Path

from functualize._events._catalog_entries import get_framework_event_catalog

_SRC = Path(__file__).resolve().parents[2] / "src"
_CATALOG = _SRC / "functualize" / "_events" / "_catalog_entries.py"

#: Entries the framework subscribes to rather than emits, with why.
_CONSUMED_NOT_EMITTED = {
    "interactivity.job.submit": (
        "the interactivity seam: a backend (TUI, plugin, embedder) emits it and "
        "the framework subscribes at _app/boot.py. A producer in src/ would be "
        "the framework talking to itself."
    ),
}


def _emitted_names() -> set[str]:
    """Every string literal handed to something named `*emit*` in `src/`.

    An AST walk, not a regex: an emit call wrapped across lines — which several
    of the real ones are — has no single line to match, and matching the name
    loosely (`emit`, `self._emit`, `bus.emit`) is exactly right here, because
    the question is "does any code path publish this name", not "which object
    published it".
    """
    names: set[str] = set()
    for file in sorted(_SRC.rglob("*.py")):
        if file == _CATALOG:
            continue
        source = file.read_text(encoding="utf-8")
        if "emit" not in source:
            continue
        for node in ast.walk(ast.parse(source, filename=str(file))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else None
            if called is None and isinstance(func, ast.Name):
                called = func.id
            if called is None or "emit" not in called:
                continue
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names.add(arg.value)
    return names


def test_every_catalog_entry_is_emitted_or_declared_consumed() -> None:
    catalog = {entry.event_name for entry in get_framework_event_catalog()}
    emitted = _emitted_names()

    orphans = sorted(catalog - emitted - set(_CONSUMED_NOT_EMITTED))

    assert not orphans, (
        f"catalog entries with no producer in src/: {orphans}. Emit them, "
        f"remove them from the catalog, or add them to _CONSUMED_NOT_EMITTED "
        f"with the reason the framework only subscribes."
    )


def test_the_exemption_list_has_not_gone_stale() -> None:
    """An exemption that stopped being true is the same lie, reversed.

    If `interactivity.job.submit` ever gains an in-tree producer, the docs that
    tell a plugin to emit it are wrong and this list should shrink. Nothing
    would say so without this test.
    """
    emitted = _emitted_names()

    still_unemitted = {name for name in _CONSUMED_NOT_EMITTED if name not in emitted}

    assert still_unemitted == set(_CONSUMED_NOT_EMITTED), (
        f"these are now emitted in src/ and should leave _CONSUMED_NOT_EMITTED: "
        f"{sorted(set(_CONSUMED_NOT_EMITTED) - still_unemitted)}"
    )


def test_every_exemption_names_a_real_catalog_entry() -> None:
    """The list cannot exempt something that is not in the catalog.

    Without this, deleting an entry would leave its exemption behind as a
    permanent excuse for a name nothing knows about.
    """
    catalog = {entry.event_name for entry in get_framework_event_catalog()}

    assert set(_CONSUMED_NOT_EMITTED) <= catalog


def test_the_scan_actually_finds_producers() -> None:
    """The falsifier.

    A scanner that returned an empty set would make the first test fail loudly
    and the second pass vacuously — but a scanner that returned *everything*
    would make all of them pass while checking nothing. Pin a known producer:
    `job.execute.start` is emitted from `_engine/executor.py`.
    """
    emitted = _emitted_names()

    assert "job.execute.start" in emitted
    assert "interactivity.job.submit" not in emitted
