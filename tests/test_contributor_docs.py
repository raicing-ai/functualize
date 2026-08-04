"""Documentation-drift guard for contributor/public docs.

This suite is the durable, ongoing doc-sync mechanism: it fails CI whenever
contributor/public documentation references paths that no longer exist on
disk.

Three validators are covered:

(a) Every `src/functualize/...` path referenced in
    `contributor/reference/code-map.md` and
    `contributor/architecture/overview.md` exists on disk.
(b) Every file referenced in `mkdocs.yml`'s `nav:` section exists under
    `docs/`.
(c) Every real `.md` file under `docs/` is reachable from `mkdocs.yml`'s
    nav, except for files on the explicit allowlist below.

"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
DOCS_DIR = REPO_ROOT / "docs"
MKDOCS_YML = REPO_ROOT / "mkdocs.yml"
CODE_MAP_MD = REPO_ROOT / "contributor" / "reference" / "code-map.md"
OVERVIEW_MD = REPO_ROOT / "contributor" / "architecture" / "overview.md"

# Files under docs/ that are intentionally not linked from mkdocs.yml's nav
# (e.g. drafts, includes, or generated fragments). Currently empty — every
# real file under docs/ is expected to be nav-reachable. Add entries here
# (as paths relative to docs/, POSIX-style) only when a file is deliberately
# excluded from navigation for a documented reason.
DOCS_NAV_ALLOWLIST: set[str] = set()

# Matches path-like strings rooted at src/functualize/, optionally inside
# backticks or code fences. Stops at whitespace, backticks, or trailing
# punctuation that is not part of a path.
_SRC_FUNCTUALIZE_PATH_RE = re.compile(r"src/functualize/[\w\-./]*")


def _extract_src_functualize_paths(text: str) -> set[str]:
    """Extract every src/functualize/... path-like string from ``text``."""
    return {match.rstrip("/.,;:") for match in _SRC_FUNCTUALIZE_PATH_RE.findall(text)}


class _MkDocsSafeLoader(yaml.SafeLoader):
    """SafeLoader that tolerates mkdocs.yml's `!!python/name:...` tags.

    mkdocs.yml wires Python callables (e.g. emoji generators) via custom
    YAML tags that yaml.safe_load rejects outright. We only care about the
    `nav:` section, so callables are resolved to their dotted-name string
    instead of being imported.
    """


def _python_name_constructor(
    loader: yaml.SafeLoader, suffix: str, node: yaml.Node
) -> str:
    return suffix


_MkDocsSafeLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:", _python_name_constructor
)


def _load_mkdocs_nav(mkdocs_yml_path: Path) -> list[Any]:
    """Parse mkdocs.yml and return the raw `nav:` structure."""
    with mkdocs_yml_path.open(encoding="utf-8") as handle:
        data = yaml.load(handle, Loader=_MkDocsSafeLoader)
    return data["nav"]


def _extract_nav_files(nav: Any) -> set[str]:
    """Recursively collect every file reference from a parsed mkdocs nav.

    Nav entries come in three shapes: a bare string (file path), a dict
    mapping a title to either a file path or a nested list, or a list of
    any of the above.
    """
    files: set[str] = set()
    if isinstance(nav, str):
        files.add(nav)
    elif isinstance(nav, dict):
        for value in nav.values():
            files.update(_extract_nav_files(value))
    elif isinstance(nav, list):
        for item in nav:
            files.update(_extract_nav_files(item))
    return files


def _all_docs_md_files(docs_dir: Path) -> set[str]:
    """Return every `.md` file under ``docs_dir`` as a POSIX path relative to it."""
    return {path.relative_to(docs_dir).as_posix() for path in docs_dir.rglob("*.md")}


class TestCodeMapAndOverviewPathsExist:
    """Validator (a): src/functualize/... paths referenced in contributor
    docs must exist on disk."""

    def test_code_map_referenced_paths_exist(self) -> None:
        """Every src/functualize/... path in code-map.md exists on disk."""
        text = CODE_MAP_MD.read_text(encoding="utf-8")
        paths = _extract_src_functualize_paths(text)

        missing = [path for path in paths if not (REPO_ROOT / path).exists()]
        assert not missing, (
            f"contributor/reference/code-map.md references paths that do "
            f"not exist on disk: {sorted(missing)}"
        )

    def test_overview_referenced_paths_exist(self) -> None:
        """Every src/functualize/... path in overview.md exists on disk."""
        text = OVERVIEW_MD.read_text(encoding="utf-8")
        paths = _extract_src_functualize_paths(text)

        # The directory tree in overview.md must actually reference at
        # least the package root — guards against the regex silently
        # matching nothing if the file's structure changes.
        assert paths, "expected at least one src/functualize/ reference in overview.md"

        missing = [path for path in paths if not (REPO_ROOT / path).exists()]
        assert not missing, (
            f"contributor/architecture/overview.md references paths that "
            f"do not exist on disk: {sorted(missing)}"
        )


class TestMkdocsNavFilesExist:
    """Validator (b): every file referenced in mkdocs.yml's nav must exist
    under docs/."""

    def test_all_nav_files_exist_under_docs(self) -> None:
        """Every nav-referenced file resolves to a real file under docs/."""
        nav = _load_mkdocs_nav(MKDOCS_YML)
        nav_files = _extract_nav_files(nav)

        assert nav_files, "mkdocs.yml nav parsed to zero file references"

        missing = [
            nav_file for nav_file in nav_files if not (DOCS_DIR / nav_file).is_file()
        ]
        assert not missing, (
            f"mkdocs.yml nav references files missing under docs/: {sorted(missing)}"
        )


class TestDocsReachableFromNav:
    """Validator (c): every real docs/*.md file must be reachable from nav,
    subject to the explicit allowlist."""

    def test_every_real_doc_is_nav_reachable_or_allowlisted(self) -> None:
        """Every .md file under docs/ is either in nav or explicitly allowlisted."""
        nav = _load_mkdocs_nav(MKDOCS_YML)
        nav_files = _extract_nav_files(nav)
        all_docs = _all_docs_md_files(DOCS_DIR)

        unreachable = all_docs - nav_files - DOCS_NAV_ALLOWLIST
        assert not unreachable, (
            f"docs/ contains files not reachable from mkdocs.yml nav and "
            f"not present in DOCS_NAV_ALLOWLIST: {sorted(unreachable)}"
        )

    def test_allowlist_entries_still_correspond_to_real_files(self) -> None:
        """Every allowlisted path must still exist — stale allowlist entries hide drift."""
        stale = [
            entry for entry in DOCS_NAV_ALLOWLIST if not (DOCS_DIR / entry).is_file()
        ]
        assert not stale, f"DOCS_NAV_ALLOWLIST contains stale entries: {sorted(stale)}"


class TestMkdocsNavValidatorCatchesBrokenEntry:
    """Regression check (acceptance scenario #16): the validator (b) logic
    must independently detect a deliberately-broken mkdocs nav entry.

    This test never touches the real mkdocs.yml — it builds an isolated
    fake nav (via a temp mkdocs.yml) with one dangling file reference and
    asserts the checker actually fires.
    """

    def test_broken_nav_entry_is_detected(self, tmp_path: Path) -> None:
        """A nav entry pointing at a nonexistent file fails validator (b)."""
        fake_docs_dir = tmp_path / "docs"
        fake_docs_dir.mkdir()
        (fake_docs_dir / "index.md").write_text("# Home\n", encoding="utf-8")

        fake_mkdocs_yml = tmp_path / "mkdocs.yml"
        fake_mkdocs_yml.write_text(
            "nav:\n  - Home: index.md\n  - Broken: does/not/exist.md\n",
            encoding="utf-8",
        )

        nav = _load_mkdocs_nav(fake_mkdocs_yml)
        nav_files = _extract_nav_files(nav)

        missing = [
            nav_file
            for nav_file in nav_files
            if not (fake_docs_dir / nav_file).is_file()
        ]

        assert missing == ["does/not/exist.md"]

    def test_valid_nav_entry_is_not_flagged(self, tmp_path: Path) -> None:
        """A fully valid nav produces zero missing entries (sanity check for the fixture itself)."""
        fake_docs_dir = tmp_path / "docs"
        fake_docs_dir.mkdir()
        (fake_docs_dir / "index.md").write_text("# Home\n", encoding="utf-8")

        fake_mkdocs_yml = tmp_path / "mkdocs.yml"
        fake_mkdocs_yml.write_text("nav:\n  - Home: index.md\n", encoding="utf-8")

        nav = _load_mkdocs_nav(fake_mkdocs_yml)
        nav_files = _extract_nav_files(nav)

        missing = [
            nav_file
            for nav_file in nav_files
            if not (fake_docs_dir / nav_file).is_file()
        ]

        assert missing == []


@pytest.mark.parametrize(
    ("nav", "expected"),
    [
        ("index.md", {"index.md"}),
        ({"Home": "index.md"}, {"index.md"}),
        (
            [
                {"Home": "index.md"},
                {"Guides": ["guides/index.md", {"CLI": "cli/index.md"}]},
            ],
            {"index.md", "guides/index.md", "cli/index.md"},
        ),
        ([], set()),
    ],
)
def test_extract_nav_files_handles_all_nav_shapes(nav: Any, expected: set[str]) -> None:
    """_extract_nav_files recursively unpacks strings, dicts, and nested lists."""
    assert _extract_nav_files(nav) == expected
