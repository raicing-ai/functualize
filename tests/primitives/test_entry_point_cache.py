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
count, so a fourth direct caller cannot appear silently — it must either use
the cached helper or be added here with its reason.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "functualize"
_PLUGINS_SRC = sorted((_ROOT / "plugins").glob("*/src"))
#: The two spellings of a direct stdlib read, mirroring the T7 gate. The
#: canonical module is excluded: it is the cache, not a bypass.
_DIRECT_READ = re.compile(
    r"importlib\.metadata\.entry_points\(|from importlib\.metadata import entry_points"
)

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


def _bypass_sites() -> list[tuple[Path, int]]:
    """``(repo-relative file, lineno)`` for every direct stdlib read."""
    sites: list[tuple[Path, int]] = []
    for root, file in _python_files():
        relative = file.relative_to(root)
        if relative == _CANONICAL_MODULE:
            continue
        for lineno, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if _DIRECT_READ.search(line):
                sites.append((relative, lineno))
    return sites


def _site_is_documented(relative: Path, lineno: int) -> bool:
    """True when the site is allowed and carries the exception marker above it."""
    if relative not in _DOCUMENTED_SITES:
        return False
    for root, file in _python_files():
        if file.relative_to(root) == relative:
            context = file.read_text(encoding="utf-8").splitlines()
            return any(
                _EXCEPTION_MARKER in context[i - 1]
                for i in range(max(1, lineno - 6), lineno)
            )
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
        (site, lineno)
        for site, lineno in sites
        if not _site_is_documented(site, lineno)
    ]
    assert not undocumented, (
        f"direct entry-point reads missing their '# Deliberate exception' "
        f"comment: {undocumented}"
    )
