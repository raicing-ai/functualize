"""The spec gate must keep guarding plugin source after the directories nest.

`plugin-taxonomy`/T1, T2. This is the mitigation for a smell the plan declares
and accepts (`plan.md` §5 entry 1): the "plugins are one level deep" assumption
is written into seven places across four execution contexts that share no import
path, so it cannot be consolidated into a single constant. What it *can* be is
**loud**.

Why that matters more here than in most places. `.claude/hooks/spec_gate.py` is
a `PreToolUse` hook, and its contract (stated in its own module docstring) is
that it **always exits 0** and that a pass is *silence* — it emits a deny or it
emits nothing. So a predicate that stops matching does not raise, does not log,
and does not fail a test. It stops guarding, and the repository looks exactly
the same.

That is what the old predicate did::

    rel = os.path.relpath(target, plugins_root).split(os.sep)
    return len(rel) >= 3 and rel[1] == "src"

It indexes a fixed position, so it was correct for exactly one tree shape:

===========================================================  ==========
path                                                         old result
===========================================================  ==========
``plugins/functualize-http/src/functualize_http/x.py``       True
``plugins/adapters/functualize-http/src/functualize_http/x.py``  **False**
===========================================================  ==========

`rel[1]` is ``"functualize-http"`` in the second case, not ``"src"`` — so every
plugin source file in the grouped layout left the gate, silently.

This test executes the predicate rather than reading it. `research.md` R1
established the same fact by reading the source and was believed; running it is
what makes it stay true. The suite is the only thing that can notice, because
the production caller is the coding harness, not this repository.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / ".claude" / "hooks" / "spec_gate.py"


def _load_gate():
    """Import the hook by path.

    It is not importable as a module: `.claude/hooks/` is not a package, is not
    on `sys.path`, and the hook is deliberately stdlib-only because it runs
    outside the project venv in clean clones.
    """
    spec = importlib.util.spec_from_file_location("_spec_gate_under_test", _GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


#: ``(path, gated)``. Paths need not exist — the predicate is pure path logic
#: over ``realpath``, which is what lets it be asked about the layout that
#: `plugin-taxonomy`/T3 is about to create.
CASES = [
    # Core source is gated at any depth.
    ("src/functualize/_app/boot.py", True),
    ("src/functualize/_types/host.py", True),
    # The flat plugin layout — what the repository had before T3.
    ("plugins/functualize-http/src/functualize_http/x.py", True),
    # The grouped plugin layout — what T3 creates. The old predicate said False
    # for every one of these, and said it silently.
    ("plugins/adapters/functualize-http/src/functualize_http/x.py", True),
    ("plugins/adapters/functualize-inline/src/functualize_inline/plugin.py", True),
    ("plugins/substrates/functualize-substrate-sqlite/src/pkg/substrate.py", True),
    ("plugins/credentials/functualize-aws/src/functualize_aws/__init__.py", True),
    ("plugins/domains/functualize-tasks-local/src/functualize_tasks_local/x.py", True),
    # Deliberately free, in both layouts: a plugin's tests, the shared conftest,
    # packaging metadata and prose. `spec_gate.py`'s own docstring lists these.
    ("plugins/functualize-http/tests/test_x.py", False),
    ("plugins/adapters/functualize-http/tests/test_x.py", False),
    ("plugins/adapters/functualize-http/pyproject.toml", False),
    ("plugins/conftest.py", False),
    ("plugins/PUBLISHING.md", False),
    # Outside the gated trees entirely.
    ("tests/spec/test_the_spec_gate_survives_nesting.py", False),
    (".spec/features/plugin-taxonomy/tasks.md", False),
    ("contributor/adr/010-spec-workflow-enforcement-point.md", False),
]


@pytest.mark.parametrize(("path", "gated"), CASES, ids=[c[0] for c in CASES])
def test_the_gate_decides_correctly_at_either_depth(path: str, gated: bool) -> None:
    assert _load_gate().is_gated(path, str(_ROOT)) is gated


def test_the_predicate_indexes_no_fixed_position() -> None:
    """Depth beyond the two shipped layouts is gated too, not just tolerated.

    The point of the fix is that it answers a question about the path — *is any
    directory component `src`* — rather than about one tree shape. A third level
    is not planned, and the gate should not have to be edited again if one
    arrives: failing open is the expensive direction.
    """
    gate = _load_gate()
    deep = "plugins/a/b/c/functualize-thing/src/pkg/module.py"
    assert gate.is_gated(deep, str(_ROOT)) is True


def test_a_file_named_src_is_not_a_package() -> None:
    """`parts[1:-1]` excludes the filename, so `src` as a *file* is not gated.

    Guards the obvious over-correction: matching `"src" in parts` would gate
    `plugins/functualize-http/tests/src` — a fixture file, not shipped code.
    """
    gate = _load_gate()
    assert gate.is_gated("plugins/functualize-http/tests/src", str(_ROOT)) is False
    assert gate.is_gated("plugins/src", str(_ROOT)) is False


def test_the_hook_still_exits_zero_and_stays_silent_on_a_pass() -> None:
    """Its first invariant: a validator that cannot decide must not decide.

    Exercised end to end through the real entry point, because the predicate
    being right is not the same as the hook being usable — an exception here
    routes as `deny` and would block every write in the repository.
    """
    import json
    import subprocess

    payload = json.dumps(
        {
            "cwd": str(_ROOT),
            "tool_input": {"file_path": "README.md"},
        }
    )
    result = subprocess.run(
        [sys.executable, str(_GATE)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0
    assert result.stdout == "", "a pass is silence, never an explicit allow"
