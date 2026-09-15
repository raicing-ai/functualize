"""What `json_substrate` exempts, and why each one is allowed to be exempt.

`store-substrate`/T8.

The suite runs twice: once on `JsonFileSubstrate`, once on `SQLiteSubstrate`
(`FUNCTUALIZE_TEST_SUBSTRATE=sqlite`). The second run is this feature's sabotage
step — if the suite only passes on files, something still reaches through the
port and the failures name it.

Making that second run green needs a skip list, and **a skip list is how such a
check dies**. One test names a path, gets marked, and the marker becomes the
place a genuine leak goes to be forgotten. So the list is bounded here, and
every entry must justify itself mechanically: a marked test has to *actually
mention* the filesystem. A marker on a test that does not is either a real leak
being hidden or a marker that was never needed.

This file asserts nothing about production code. The claim that no *store*
reaches for a path is made where it can be observed —
`plugins/functualize-state-sqlite/tests/test_sqlite_substrate.py::
TestItNeedsNoSharedDisk::test_no_store_asks_the_substrate_for_a_path` wraps a
substrate so `path_for`, `root` and `path` raise, then drives all three stores.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

TESTS = pathlib.Path(__file__).resolve().parent.parent

#: How many tests carry the marker. A ceiling, deliberately tight.
#:
#: Recorded as a number rather than a list because the point is the *size* of
#: the exemption: a leak found later will be tempting to mark, and a number that
#: has to be raised in a diff is the thing that makes that visible.
#:
#: **Per test, never per file.** The first attempt marked nine whole files whose
#: subject is the JSON layout, and that exempted 113 tests to silence 69 — 44 of
#: them would have passed. An exemption that covers more than it needs is where
#: a real leak goes to hide, so the marker is applied to exactly the tests that
#: fail under another backend.
MARKED_CEILING = 80

#: What counts as "this test is about the filesystem". A marked test must
#: contain at least one of these; otherwise the marker is hiding something.
FILESYSTEM_TOKENS = (
    "path_for",
    "scopes.json",
    "fresh.json",
    "runs.json",
    "shell-history.json",
    "scope-state",
    ".functualize",
    "JsonFileSubstrate",
    "resolve_fresh",
    "FRESH_FILENAME",
    "SCOPES_FILENAME",
    "RUNS_FILENAME",
)


def _marked() -> dict[pathlib.Path, list[str]]:
    """Every test the marker exempts, by file.

    A module-level `pytestmark` marks the whole file; a decorator marks one
    test. Both are counted, because both are exemptions.
    """
    found: dict[pathlib.Path, list[str]] = {}
    for path in sorted(TESTS.rglob("test_*.py")):
        source = path.read_text()
        if "json_substrate" not in source:
            continue
        tree = ast.parse(source)
        module_wide = any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets
            )
            and "json_substrate" in ast.unparse(node.value)
            for node in tree.body
        )
        names: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith(
                "test_"
            ):
                continue
            decorated = any(
                "json_substrate" in ast.unparse(d) for d in node.decorator_list
            )
            if module_wide or decorated:
                names.append(node.name)
        if names:
            found[path] = names
    return found


class TestTheExemptionIsBounded:
    def test_the_marker_is_used_at_all(self) -> None:
        """Guards every count below against measuring nothing.

        An AST walk that found no marked tests would make the ceiling trivially
        satisfied and this whole file a gate that cannot fail.
        """
        assert _marked(), "no test carries the json_substrate marker"

    def test_it_has_not_grown(self) -> None:
        marked = _marked()
        total = sum(len(names) for names in marked.values())
        breakdown = "\n".join(
            f"      {len(names):3} {path.relative_to(TESTS)}"
            for path, names in sorted(marked.items())
        )
        assert total <= MARKED_CEILING, (
            f"\n{total} tests are exempt from the alternate-substrate run, over "
            f"the ceiling of {MARKED_CEILING}.\n\n{breakdown}\n\n"
            f"    A new exemption is either a test that genuinely names the\n"
            f"    filesystem — in which case raise the ceiling here, with the\n"
            f"    reason — or a store that has started reaching through the\n"
            f"    port, in which case the marker would hide it."
        )


class TestEveryExemptionJustifiesItself:
    def test_each_marked_file_names_the_filesystem(self) -> None:
        """A marked test that never mentions a path did not need marking.

        Checked per file rather than per test because a module-level
        `pytestmark` is a claim about the file, and a file whose subject is the
        JSON layout says so throughout.
        """
        unjustified = [
            str(path.relative_to(TESTS))
            for path in _marked()
            if not any(token in path.read_text() for token in FILESYSTEM_TOKENS)
        ]
        assert not unjustified, (
            f"these files are exempt from the alternate-substrate run but "
            f"never name a path, a store filename or JsonFileSubstrate: "
            f"{unjustified}. Either the marker is unnecessary, or it is "
            f"hiding a store that reaches through the port."
        )


class TestTheAlternateRunIsReachable:
    """The mechanism itself, so a typo cannot quietly disable the second run."""

    def test_the_env_var_name_is_what_the_conftest_reads(self) -> None:
        conftest = (TESTS / "conftest.py").read_text()
        assert 'os.environ.get("FUNCTUALIZE_TEST_SUBSTRATE"' in conftest

    def test_the_marker_is_registered(self) -> None:
        """An unregistered marker is silently inert under `--strict-markers`
        and merely a warning without it — either way it would stop skipping
        and the second run would fail for the wrong reason."""
        pyproject = (TESTS.parent / "pyproject.toml").read_text()
        assert "json_substrate:" in pyproject

    @pytest.mark.parametrize("backend", ["sqlite"])
    def test_the_conftest_knows_this_backend(self, backend: str) -> None:
        conftest = (TESTS / "conftest.py").read_text()
        assert f'!= "{backend}"' in conftest or f'== "{backend}"' in conftest
