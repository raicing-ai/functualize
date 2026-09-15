"""The entry-point scan has one cache, and a bounded number of bypasses.

``functualize._primitives.entry_points`` exists so the installed path is
scanned once per process. Three callers deliberately read ``importlib.metadata``
directly instead; each carries a ``# Deliberate exception`` comment naming why:

- ``src/functualize/_cli/skills.py`` — ``_cli`` may not import internal
  packages (import-linter contract), so it cannot reach the cached helper.
- ``src/functualize/_cli/tui/display_provider_discovery.py`` — same ``_cli``
  restriction.
- ``plugins/functualize-ai/src/functualize_ai/_provider_discovery.py`` — a
  standalone-published distribution whose pyproject declares no ``functualize``
  dependency, so importing the internal helper would be an undeclared
  dependency.

pitfalls.md §6: a registry nothing verifies is just a list. This test is the
verification: it scans the same surface the boot path scans and pins the bypass
count, so a fourth direct caller **in that surface** cannot appear silently —
it must either use the cached helper or be added here with its reason.

**What "that surface" means, and what it does not.** The scan covers
``src/functualize/`` and ``plugins/*/src/``: the code that runs during boot,
which is the whole point — the invariant is that *booting* scans the installed
path once. ``tests/`` is deliberately outside it, and there is a live direct
caller there (``tests/test_packaging.py``) which is fine: a test that asks the
installed environment a question is not a boot-path bypass. The docstring used
to claim no fourth caller could appear silently, full stop, and that live
caller already disproved it (adj S6).

**Spellings.** The scan resolves imports through the AST rather than matching
two literal spellings, because a regex pinned to ``importlib.metadata.entry_points(``
and ``from importlib.metadata import entry_points`` misses at least three
one-line re-spellings that mean exactly the same thing — ``from importlib import
metadata``, ``import importlib.metadata as ilm``, and binding the function to a
name without calling it. ``TestTheScannerSeesEverySpelling`` runs each of those
through the scanner, so the "cannot appear silently" claim above is itself
tested rather than asserted.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PLUGINS_SRC = sorted((_ROOT / "plugins").glob("*/src"))
#: The stdlib function a bypass reaches, spelled the way the AST resolves it.
#: The canonical module is excluded from the scan: it is the cache, not a
#: bypass.
_TARGET = "importlib.metadata.entry_points"

#: The marker each deliberate exception must carry, so a bare direct caller
#: (no comment, no reason) fails this test.
_EXCEPTION_MARKER = "# Deliberate exception"

#: The three permitted bypass sites, relative to their scan root (``src/`` for
#: core modules, the repo root for plugins). A fourth file appearing in the
#: scan fails the test.
_DOCUMENTED_SITES = {
    Path("functualize/_cli/skills.py"),
    Path("functualize/_cli/tui/display_provider_discovery.py"),
    Path("functualize-ai/src/functualize_ai/_provider_discovery.py"),
}

_CANONICAL_MODULE = Path("functualize/_primitives/entry_points.py")


def _python_files() -> list[tuple[Path, Path]]:
    """``(scan_root, file)`` pairs for every module in the scanned surface.

    ``scan_root`` is the directory the file is relative to — ``src/`` for core
    modules (so paths read ``functualize/_cli/…``), the repo root for plugins
    (so paths read ``plugins/<name>/src/…``). Keeping both rooted consistently
    lets the documented-site set below be spelled the same way the gate's
    ``src/ plugins/*/src/`` invocation sees them.
    """
    files: list[tuple[Path, Path]] = []
    for file in sorted((_ROOT / "src").rglob("*.py")):
        files.append((_ROOT / "src", file))
    for plugin_src in _PLUGINS_SRC:
        for file in sorted(plugin_src.rglob("*.py")):
            files.append((_ROOT / "plugins", file))
    return files


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for a Name/Attribute chain, or ``None`` for anything else."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _alias_map(tree: ast.AST) -> dict[str, str]:
    """Local name → the absolute dotted path it stands for.

    Every ``import``/``from`` in the file, at any scope: a bypass hidden inside
    a function is still a bypass, and a function-local import is exactly how
    one would be written to stay out of a line-oriented scan.
    """
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # `import a.b` binds `a`; `import a.b as c` binds `c` to `a.b`.
                bindings[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return bindings


def _references(tree: ast.AST, bindings: dict[str, str]) -> list[int]:
    """Line numbers where an expression resolves to :data:`_TARGET`.

    References, not calls. ``read = importlib.metadata.entry_points`` defers the
    call by one line and bypasses the cache just as completely.
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name | ast.Attribute):
            continue
        dotted = _dotted(node)
        if dotted is None:
            continue
        head, _, tail = dotted.partition(".")
        resolved = bindings.get(head)
        if resolved is None:
            continue
        full = f"{resolved}.{tail}" if tail else resolved
        if full == _TARGET:
            lines.append(node.lineno)
    return lines


def _bypass_sites() -> list[tuple[Path, int]]:
    """``(repo-relative file, lineno)`` for every direct stdlib read."""
    sites: list[tuple[Path, int]] = []
    for root, file in _python_files():
        relative = file.relative_to(root)
        if relative == _CANONICAL_MODULE:
            continue
        source = file.read_text(encoding="utf-8")
        if "entry_points" not in source:  # cheap pre-filter, not the test
            continue
        tree = ast.parse(source, filename=str(file))
        bindings = _alias_map(tree)
        # An `Attribute` chain yields its own line once; dedupe so one
        # expression is one site even when nested nodes agree.
        for lineno in sorted(set(_references(tree, bindings))):
            sites.append((relative, lineno))
    return sites


def _site_is_documented(relative: Path) -> bool:
    """True when the file is an allowed bypass and says why, in its own text.

    Per **file**, not per line. The marker's job is to make the file explain
    itself; pinning it to a fixed window above the reference made the check
    depend on where in the function the import sits — the marker in
    ``_cli/skills.py`` sits above a function-local ``from importlib.metadata
    import entry_points``, seven lines above the call that uses it, which a
    six-line window missed. A documented file that grows a *second* bypass is
    still caught, by the count assertion below.
    """
    if relative not in _DOCUMENTED_SITES:
        return False
    for root, file in _python_files():
        if file.relative_to(root) == relative:
            return _EXCEPTION_MARKER in file.read_text(encoding="utf-8")
    return False


def test_the_bypass_count_is_pinned_to_the_documented_exceptions() -> None:
    """A fourth direct caller cannot appear silently.

    The count and the site set are both pinned: converting one of the three to
    the cached helper, or adding a fourth bare caller, fails this test and
    forces the change to be deliberate.
    """
    sites = _bypass_sites()
    assert len(sites) == len(_DOCUMENTED_SITES), (
        f"expected {len(_DOCUMENTED_SITES)} direct entry-point reads, found "
        f"{len(sites)}: {sites}. A new caller must use "
        f"functualize._primitives.entry_points, or be added to "
        f"_DOCUMENTED_SITES with its reason."
    )
    assert {site for site, _ in sites} == _DOCUMENTED_SITES, (
        f"bypass sites drifted from the documented set: {sites}"
    )
    undocumented = [
        (site, lineno) for site, lineno in sites if not _site_is_documented(site)
    ]
    assert not undocumented, (
        f"direct entry-point reads missing their '# Deliberate exception' "
        f"comment: {undocumented}"
    )


class TestTheScannerSeesEverySpelling:
    """The claim in this module's docstring, tested rather than asserted.

    A scan that pins a count is only worth the spellings it can see. The
    regex this replaced matched two, and a review found three one-line
    re-spellings that mean the same thing and slipped past it (adj S6). Each
    is run through the real scanner below, so a future simplification back to
    a pattern match fails here first.
    """

    @staticmethod
    def _found(source: str) -> list[int]:
        tree = ast.parse(source)
        return _references(tree, _alias_map(tree))

    def test_the_two_spellings_the_regex_already_caught(self) -> None:
        assert self._found(
            "import importlib.metadata\n"
            "eps = importlib.metadata.entry_points(group='g')\n"
        ) == [2]
        assert self._found(
            "from importlib.metadata import entry_points\neps = entry_points()\n"
        ) == [2]

    def test_from_importlib_import_metadata(self) -> None:
        """`metadata.entry_points(...)` — the module bound one level up."""
        assert self._found(
            "from importlib import metadata\neps = metadata.entry_points()\n"
        ) == [2]

    def test_an_aliased_module(self) -> None:
        assert self._found(
            "import importlib.metadata as ilm\neps = ilm.entry_points()\n"
        ) == [2]

    def test_an_aliased_function(self) -> None:
        assert self._found(
            "from importlib.metadata import entry_points as ep\neps = ep()\n"
        ) == [2]

    def test_a_reference_that_never_calls(self) -> None:
        """Binding the function defers the call; it does not avoid the bypass.

        `read = importlib.metadata.entry_points` then `read(...)` a hundred
        lines later reads the installed path exactly as directly. The scanner
        looks for references, not call syntax, so the deferral does not hide.
        """
        assert self._found(
            "import importlib.metadata\nread = importlib.metadata.entry_points\n"
        ) == [2]

    def test_a_function_local_import(self) -> None:
        """A bypass inside a function is still a bypass.

        This is the shape the two real `_cli` exceptions use, and the shape
        someone would reach for to keep an import out of a line-oriented scan.
        """
        assert self._found(
            "def load():\n"
            "    from importlib.metadata import entry_points\n"
            "    return entry_points()\n"
        ) == [3]

    def test_the_cached_helper_is_not_a_bypass(self) -> None:
        """The falsifier. A scanner that flagged everything named
        `entry_points` would pass every test above and be worthless."""
        assert (
            self._found(
                "from functualize._primitives.entry_points import entry_points\n"
                "eps = entry_points(group='g')\n"
            )
            == []
        )

    def test_an_unrelated_metadata_module_is_not_a_bypass(self) -> None:
        """`metadata` is a common name; only `importlib`'s counts."""
        assert (
            self._found(
                "from mypackage import metadata\neps = metadata.entry_points()\n"
            )
            == []
        )
