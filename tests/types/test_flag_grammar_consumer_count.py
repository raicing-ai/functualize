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

Three modules are excluded by path, and only those:

- ``_types/flag_grammar.py`` — **defines** every name in the pattern.
- ``app/utils.py`` — re-exports the vocabulary for public consumers.
- ``types/__init__.py`` — the public re-export surface.

Nothing else is carved out: a file that *mentions* the grammar counts, so the
set cannot silently shrink or grow without this test moving.

``_types/naming.py`` used to be a fourth, carrying a re-export of
``negative_flag_for`` "kept for older importers". There were no older importers
— there was **one test that had not been migrated**
(``tests/adapters/test_boolean_negation.py``), which a scan bounded to ``src/``
could not see. It now imports from ``functualize.types`` like every other
consumer, and the re-export is deleted: this is a pre-release repository and a
clean cutover costs nothing (AGENTS.md). Found by adversarial review.

**What this test does and does not prove**, stated plainly because the AC
overstates it. ``spec.md`` says *"Every ``negative_flag_for`` consumer reads it
through the grammar module, and a test pins the consumer count so an eighth
fails the suite."* What is pinned is the set of **files under ``src/`` that
mention one of nine spellings**. That is a good tripwire and it is not a
dependency list:

- a mention in prose counts (``_cli/completions/data.py`` is a docstring);
- a *sixth copy* — a new file with its own table and its own names — matches
  nothing in the pattern and would not be noticed here;
- consumers under ``tests/`` and ``plugins/`` are invisible, which is exactly
  how the stale re-export survived.

`tests/types/test_no_second_failure_set.py` is the shape that catches a copy;
this one catches a new *reader*. Both are wanted; neither is the other.
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


def test_no_module_re_exports_the_grammar_outside_the_corridor() -> None:
    """The gap the `src/`-bounded scan above cannot see.

    `_types/naming.py` carried `negative_flag_for` "for older importers" and
    was excluded by path — so the scan could not report it, and the one
    importer that justified it lived under `tests/`, where the scan does not
    look. A re-export nobody needs is a second place to import a name from,
    which is how a vocabulary starts having two homes again.

    The corridor modules (`app/utils.py`, `types/__init__.py`) are the
    *intended* re-export surfaces and are named here rather than matched, so
    adding a fourth is a decision rather than an accident.
    """
    import re as _re

    corridor = {"app/utils.py", "types/__init__.py", "_types/flag_grammar.py"}
    pattern = _re.compile(r"from functualize\._types\.flag_grammar import")

    offenders = [
        path.relative_to(_SRC).as_posix()
        for path in sorted(_SRC.rglob("*.py"))
        if path.relative_to(_SRC).as_posix() not in corridor
        and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "these modules import the grammar directly rather than through the "
        f"public corridor, which makes them second homes for it: {offenders}"
    )


def test_every_consumer_reads_it_through_a_corridor() -> None:
    """AC-10's actual sentence, for the importers a scan *can* resolve.

    A mention scan cannot tell a reader from a mention. An import scan can, for
    the subset that imports — so this asserts the property the AC states, over
    the part of the tree where it is decidable, and says so rather than
    implying the mention count did it.
    """
    import re as _re

    pattern = _re.compile(r"import\s+.*negative_flag_for")
    bad_home = _re.compile(
        r"functualize\._types\.naming\s+import\s+.*negative_flag_for"
    )

    for root in (_SRC, _SRC.parents[1] / "tests"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if not pattern.search(text):
                continue
            assert not bad_home.search(text), (
                f"{path} imports `negative_flag_for` from `_types.naming`, "
                "which no longer publishes it"
            )
