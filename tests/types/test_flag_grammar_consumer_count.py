"""Pin the set of files that read the flag grammar, so growth is a reviewable diff.

Spec AC-10, risk R-e. ``_types/flag_grammar.py`` exists because five surfaces
once kept their own copies of the flag vocabulary; the count below is the
registry-plus-test shape that stops a sixth copy from appearing silently.
Adding a legitimate consumer is one obvious line here and the assertion
message names the files actually found — a reviewer sees in the diff exactly
which file started reading the grammar.

The scan is the T12 gate from ``tasks.md``, implemented in Python (not shell)
so the test runs anywhere. It is a **mention** scan, like the ``rg -l`` gate it
replaces: any file under ``src/functualize`` naming one of the nine public
grammar spellings counts. Two current hits are prose rather than imports —
``_cli/completions/data.py`` explains the builder's rule in a docstring, and
``_cli/tui/sync.py`` mentions ``flag_aliases`` while calling
``negative_flag_for`` — which is exactly what the gate measures: a reader of
that file learns the vocabulary lives in the grammar, and the file's behaviour
stays honest because it calls the function.

Four modules are excluded by path, and only those:

- ``_types/flag_grammar.py`` — **defines** every name in the pattern.
- ``_types/naming.py`` — legacy re-export home of ``negative_flag_for``, kept
  for older importers (T8 moved the rule out; the module now only re-sells it).
- ``app/utils.py`` — re-exports the vocabulary for public consumers.
- ``types/__init__.py`` — the public re-export surface.

Nothing else is carved out: a file that *mentions* the grammar counts, so the
set cannot silently shrink or grow without this test moving.
"""

from __future__ import annotations

import pathlib
import re

_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "functualize"

# Every public spelling the grammar publishes — the union of the three pattern
# groups in the T12 gate. (The tasks.md shell line passes the first group as a
# positional pattern next to ``-e`` flags, which rg treats as a file path and
# drops; Python has no such hazard, and the gate's intent is the union.)
_PATTERN = re.compile(
    "|".join(
        [
            "GLOBAL_OPTIONS_ALWAYS_VALUE",
            "GLOBAL_OPTIONS_OPTIONAL_VALUE",
            "OPTIONAL_VALUE_VALID_SET",
            "GLOBAL_OPTIONS_WITH_VALUE",
            "GLOBAL_BOOL_FLAGS",
            "flag_aliases",
            "negative_aliases",
            "match_group_flag",
            "negative_flag_for",
        ]
    )
)

# The publishers, excluded by path — see the module docstring for why each.
_EXCLUDED = {
    "_types/flag_grammar.py",  # the authority itself: defines every name
    "_types/naming.py",  # re-export of negative_flag_for for older importers
    "app/utils.py",  # public re-export of the vocabulary
    "types/__init__.py",  # public re-export of the vocabulary
}

#: Relative-to-``src/functualize`` paths of every current consumer, sorted.
EXPECTED_CONSUMERS = [
    "_cli/completions/data.py",
    "_cli/dispatch.py",
    "_cli/main.py",
    "_cli/tui/bar.py",
    "_cli/tui/sync.py",
    "app/adapters/cli.py",
    "app/adapters/click_params.py",
]


def _scan() -> list[str]:
    """Files under ``src/functualize`` that name a grammar spelling.

    Mirrors the gate's ``rg -l`` semantics: hidden paths and ``__pycache__``
    are skipped (rg ignores both by default), binary files are skipped, and a
    file counts on a single textual mention of any pattern name.
    """
    found: list[str] = []
    for path in sorted(_SRC.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(_SRC).as_posix()
        if any(
            part.startswith(".") or part == "__pycache__" for part in rel.split("/")
        ):
            continue
        if rel in _EXCLUDED:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary — rg would skip it too
        if _PATTERN.search(text):
            found.append(rel)
    return found


def test_grammar_consumer_set_is_pinned() -> None:
    found = _scan()
    assert found == EXPECTED_CONSUMERS, (
        "flag-grammar consumer set moved.\n"
        f"found ({len(found)}):\n"
        + "\n".join(f"  {f}" for f in found)
        + f"\nexpected ({len(EXPECTED_CONSUMERS)}):\n"
        + "\n".join(f"  {f}" for f in EXPECTED_CONSUMERS)
    )
