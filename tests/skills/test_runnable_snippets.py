"""Introspection one-liners the skills tell an agent to run must actually run.

Every skill says the same thing: do not trust this document, ask the framework.
That instruction is only worth giving while the *asking* works — and one of
them did not. `import functualize.workflow as w; print(w.__all__)` raises
``AttributeError``, because the package re-exports the decorator over the
module name, so an agent following the advice gets a traceback and falls back
to guessing.

A broken verification command is worse than none: it is the one line a careful
agent runs first.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from .conftest import SKILLS_ROOT, markdown_files

#: A fenced ```python block is a runnable claim only when it is a single
#: statement line — an illustrative job body is not something to execute.
_ONE_LINER = re.compile(r"^import .+; print\(.+\)$")


def _python_one_liners() -> list[tuple[str, str]]:
    """(source file, one-liner) for every runnable introspection snippet."""
    found: list[tuple[str, str]] = []
    for path in markdown_files():
        relative = str(path.relative_to(SKILLS_ROOT))
        for block in re.findall(
            r"```python\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL
        ):
            for line in block.splitlines():
                if _ONE_LINER.match(line.strip()):
                    found.append((relative, line.strip()))
    return found


ONE_LINERS = _python_one_liners()


def test_the_skills_actually_offer_introspection_snippets():
    """Guards the extractor: a regex that matches nothing passes vacuously."""
    assert ONE_LINERS, (
        "no introspection one-liners found in the skills — either they were "
        "removed, or their formatting changed and this test now checks nothing"
    )


@pytest.mark.parametrize(
    ("source", "snippet"),
    ONE_LINERS,
    ids=[f"{src}::{snippet[:40]}" for src, snippet in ONE_LINERS],
)
def test_introspection_snippet_runs(source, snippet):
    """Run it exactly as an agent would: a fresh interpreter, verbatim."""
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"{source} tells an agent to run:\n  {snippet}\nand it fails:\n"
        f"{result.stderr.strip()}"
    )
    assert result.stdout.strip(), f"{source}: snippet produced no output"
