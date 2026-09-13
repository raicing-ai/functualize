"""#27 — a module that will not parse is reported on every run, not just the first.

A `SyntaxError` in a discovered module was reported on run one and **vanished on
run two** against a warm cache, while a `ModuleNotFoundError` in the same tree
repeated every run. The asymmetry was the tell: two stages reject a module
(parse, then import), and only the parse stage's answer was being cached.

The pre-filter persists a *negative* decision so the next boot can skip the AST
parse. It answers `False` both for "this file holds nothing to import" and for
"this file could not be read", and caching the second kind meant the parse that
produces the report never happened again — a short job list with no
explanation, on every run after the first.

The tests below keep both halves in view: a fix that reported the parse failure
by disabling decision caching altogether would pass the first one alone and
cost every warm boot an AST parse per module.
"""

from __future__ import annotations

import json

from tests.conftest import surfaces

GOOD = 'def hello() -> None:\n    """Say hi."""\n    print("hi")\n'

SYNTAX_ERROR = 'def broken(x: int = 1) -> None\n    """Missing the colon."""\n'

IMPORT_ERROR = (
    'import totally_missing_pkg\n\n\ndef fetch() -> None:\n    """Fetch a thing."""\n'
)


def _failures(cli_run, root) -> list[dict[str, str]]:
    result = cli_run(["builtin", "info", "--json"], cwd=root)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)["discovery_failures"]


def _error_types(entries: list[dict[str, str]]) -> list[str]:
    return sorted(entry["error_type"] for entry in entries)


def _broken_tree(project_tree):
    return project_tree(
        jobs={
            "greet.py": GOOD,
            "broken.py": SYNTAX_ERROR,
            "importer.py": IMPORT_ERROR,
        }
    )


def _cached_decisions(root) -> dict[str, object]:
    cache = root / ".functualize" / "cache.json"
    assert cache.exists(), "the first run wrote no cache, so the second run is not warm"
    return json.loads(cache.read_text())["pre_filter_decisions"]


def test_a_parse_failure_is_reported_on_the_second_run(cli_run, project_tree) -> None:
    """AC-13. The first run is the one that never was the problem."""
    root = _broken_tree(project_tree)

    first = _failures(cli_run, root)
    second = _failures(cli_run, root)

    assert "SyntaxError" in _error_types(first)
    assert "SyntaxError" in _error_types(second)


def test_an_import_failure_is_reported_on_the_second_run(cli_run, project_tree) -> None:
    """The other half of the asymmetry, which already held.

    Nothing caches the import attempt, so this one never disappeared — which is
    what made the pair a defect rather than a quiet rule about warm caches.
    """
    root = _broken_tree(project_tree)

    first = _failures(cli_run, root)
    second = _failures(cli_run, root)

    assert "ModuleNotFoundError" in _error_types(first)
    assert "ModuleNotFoundError" in _error_types(second)


def test_a_warm_run_reports_exactly_what_the_cold_one_did(
    cli_run, project_tree
) -> None:
    """Not "the parse failure is there" — the same list, in the same order.

    The report is what `builtin info` renders and what an operator acts on; a
    warm run that agreed only on a subset would still send them hunting for a
    difference between two runs of the same tree.
    """
    root = _broken_tree(project_tree)

    first = _failures(cli_run, root)
    second = _failures(cli_run, root)

    assert second == first


def test_a_file_nobody_could_read_is_never_a_cached_decision(
    cli_run, project_tree
) -> None:
    """Cache what was decided; a failure to read decides nothing."""
    root = project_tree(
        jobs={"greet.py": GOOD, "_helper.py": GOOD, "broken.py": SYNTAX_ERROR}
    )

    cli_run(["builtin", "info", "--json"], cwd=root)

    cached = {path.rsplit("/", 1)[-1] for path in _cached_decisions(root)}
    assert "broken.py" not in cached


@surfaces("func")
def test_a_decided_negative_is_still_cached(cli_run, project_tree) -> None:
    """The other direction, so the fix cannot be "stop caching".

    `_helper.py` is rejected by rule — the leading underscore — and that answer
    is reusable, so it is still persisted. Restricted to `func` because that is
    the surface whose provider is built with a pre-filter chain at all: an
    app's own provider runs without one, so it caches no decision either way
    and the assertion would be vacuous there rather than true.
    """
    root = project_tree(jobs={"greet.py": GOOD, "_helper.py": GOOD})

    cli_run(["builtin", "info", "--json"], cwd=root)

    cached = {path.rsplit("/", 1)[-1] for path in _cached_decisions(root)}
    assert "_helper.py" in cached
