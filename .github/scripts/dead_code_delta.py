"""Report the dead code a change introduces or orphans, by comparing two commits.

    uv run python .github/scripts/dead_code_delta.py <base> <head> [--json]
                                                     [--neighbourhood N]

vulture over the whole tree reports hundreds of names on `master`, most of them
dispatched by a framework (Textual handlers, Click commands, pytest fixtures)
rather than called. Running it at *both* ends of a change and keeping only what
is new at the head cancels every one of those, and every piece of dead code the
change did not cause, so what is left is the change's own blast radius:

- ``NEW_DEAD`` — unreferenced anywhere at the head, tests included, and not so
  at the base: a definition the change added without a caller, or one whose last
  caller of any kind it removed.
- ``TESTS_ONLY`` — unreferenced by production code at the head, referenced once
  tests are included, and not in that state at the base. A test calling a symbol
  is not a production call path, so this covers a new symbol only tests reach
  and an old one whose last production caller this change removed — even when
  the change never touched that symbol's file.

Both commits are read straight from the object database (``git ls-tree`` and
``git cat-file``) into a temporary directory, so the working tree, the index and
any uncommitted change are never read or written.

The vulture configuration is the ``[tool.vulture]`` table of the **head**
commit's ``pyproject.toml``, applied to both ends, so the same two commits give
the same answer from any checkout. Findings are keyed by ``(path, symbol,
kind)`` — the symbol qualified by its enclosing class or function — never by
line number, and file renames between the two commits are followed, so moved
lines and moved files produce no noise. A renamed *symbol* is a new key and
reads as new.

Deliberately not reported:

- an unused **function argument** (vulture's 100%-confidence variable): it is an
  interface concern — a protocol, a callback, an injected job dependency — not a
  definition left without a caller;
- a public module-level function in a ``jobs/`` module: functualize discovers
  jobs by convention, so nothing calls them by name;
- anything matched by ``ignore_names`` / ``ignore_decorators``.

A finding whose definition line, or the line above it, carries
``# TRANSITIONAL(`` is flagged ``marker=TRANSITIONAL``. Whether any other
finding is accounted for by the feature's ``plan.md`` or ``tasks.md`` is for the
reader to decide; this command only reports.

Exit status: 0 no new findings, 1 new findings, 2 usage or tool error.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

#: The output's shape. Consumers pin it; bump it on any incompatible change.
FORMAT_VERSION = 1

DEFAULT_MIN_CONFIDENCE = 60
DEFAULT_NEIGHBOURHOOD = 5

#: Roots that are materialised. Everything a scope names lives under these.
ROOTS = ("src", "plugins", "examples", "tests")

#: ``plugins/<group>/<package>/<dir>`` — the grouped plugin workspace layout.
PRODUCTION_DIRS = ("src", "examples")
TEST_DIRS = ("tests",)

MARKER = "# TRANSITIONAL("

NEW_DEAD = "NEW_DEAD"
TESTS_ONLY = "TESTS_ONLY"
NEIGHBOURHOOD = "NEIGHBOURHOOD"

NOTES = (
    "findings are keyed by (path, symbol, kind); file renames are followed, "
    "a renamed symbol reads as new",
    "unused function arguments and convention-discovered job functions are "
    "not reported",
)


class ToolError(Exception):
    """git or vulture could not give an answer; the run exits 2."""


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    symbol: str
    kind: str
    confidence: int

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.path, self.symbol, self.kind)


@dataclass(frozen=True)
class Reported:
    finding: Finding
    label: str
    marker: str | None

    def as_line(self) -> str:
        f = self.finding
        text = f"{f.path}:{f.line} {f.symbol} {f.kind} {self.label}"
        return f"{text} marker={self.marker}" if self.marker else text

    def as_json(self) -> dict[str, Any]:
        f = self.finding
        return {
            "path": f.path,
            "line": f.line,
            "symbol": f.symbol,
            "kind": f.kind,
            "class": self.label,
            "marker": self.marker,
            "confidence": f.confidence,
        }


# --- git ---------------------------------------------------------------------


def _git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            input=stdin,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ToolError(f"cannot run git: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise ToolError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _repo_root() -> Path:
    return Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())


def _resolve(root: Path, rev: str) -> str:
    try:
        sha = _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
        return sha.decode().strip()
    except ToolError:
        raise ToolError(f"not a commit: {rev!r}") from None


def _python_blobs(root: Path, sha: str) -> list[tuple[str, str]]:
    """``(object, path)`` for every tracked regular ``.py`` file under ROOTS."""
    listing = _git(root, "ls-tree", "-r", "-z", "--full-tree", sha, "--", *ROOTS)
    blobs: list[tuple[str, str]] = []
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        meta, _, raw_path = entry.partition(b"\t")
        mode, typ, obj = meta.decode().split()
        path = raw_path.decode()
        if typ == "blob" and mode in ("100644", "100755") and path.endswith(".py"):
            blobs.append((obj, path))
    return blobs


def materialise(root: Path, sha: str, dest: Path) -> None:
    """Write the commit's Python files under ``dest``, from objects alone."""
    blobs = _python_blobs(root, sha)
    if not blobs:
        return
    stream = _git(
        root,
        "cat-file",
        "--batch",
        stdin="".join(f"{obj}\n" for obj, _ in blobs).encode(),
    )
    offset = 0
    for obj, path in blobs:
        header_end = stream.index(b"\n", offset)
        header = stream[offset:header_end].decode().split()
        if header[0] != obj or header[1] != "blob":
            raise ToolError(f"unexpected object for {path}: {' '.join(header)}")
        size = int(header[2])
        start = header_end + 1
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(stream[start : start + size])
        offset = start + size + 1


def _renames(root: Path, base: str, head: str) -> dict[str, str]:
    """Base path → head path for every file git sees renamed between the two."""
    out = _git(root, "diff", "-z", "--name-status", "-M", base, head)
    fields = out.split(b"\0")
    renames: dict[str, str] = {}
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i].decode()
        if status[0] in "RC":
            old, new = fields[i + 1].decode(), fields[i + 2].decode()
            if status[0] == "R":
                renames[old] = new
            i += 3
        else:
            i += 2
    return renames


def _changed_files(root: Path, base: str, head: str) -> set[str]:
    out = _git(root, "diff", "-z", "--name-only", "-M", base, head)
    return {p.decode() for p in out.split(b"\0") if p}


# --- configuration -----------------------------------------------------------


@dataclass(frozen=True)
class Config:
    min_confidence: int
    ignore_names: tuple[str, ...]
    ignore_decorators: tuple[str, ...]


def load_config(root: Path, head: str) -> Config:
    try:
        text = _git(root, "show", f"{head}:pyproject.toml").decode()
    except ToolError:
        text = ""
    try:
        table = tomllib.loads(text).get("tool", {}).get("vulture", {})
    except tomllib.TOMLDecodeError as exc:
        raise ToolError(f"pyproject.toml at {head[:12]} is not TOML: {exc}") from exc
    return Config(
        min_confidence=int(table.get("min_confidence", DEFAULT_MIN_CONFIDENCE)),
        ignore_names=tuple(table.get("ignore_names", ())),
        ignore_decorators=tuple(table.get("ignore_decorators", ())),
    )


# --- scanning ----------------------------------------------------------------


def scope_paths(tree: Path, names: tuple[str, ...]) -> list[Path]:
    """``names`` at the top of ``tree`` and in every plugin package, in order."""
    paths = [tree / name for name in names]
    plugins = tree / "plugins"
    if plugins.is_dir():
        for package in sorted(plugins.glob("*/*")):
            paths.extend(package / name for name in names)
    return [p for p in paths if p.is_dir()]


class Span(NamedTuple):
    """The lines one class or function occupies, decorators included."""

    start: int
    end: int
    qualname: str
    name: str
    is_class: bool


_SCOPES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def spans(node: ast.AST, prefix: tuple[str, ...] = ()) -> list[Span]:
    """Every class and function under ``node``, to qualify a bare vulture name."""
    found: list[Span] = []
    for child in ast.iter_child_nodes(node):
        inner = prefix
        if isinstance(child, _SCOPES):
            inner = (*prefix, child.name)
            start = min([child.lineno, *(d.lineno for d in child.decorator_list)])
            end = child.end_lineno or child.lineno
            is_class = isinstance(child, ast.ClassDef)
            found.append(Span(start, end, ".".join(inner), child.name, is_class))
        found.extend(spans(child, inner))
    return found


def _qualify(scopes: list[Span], name: str, line: int, kind: str) -> str:
    """``name`` prefixed with the class or function that encloses ``line``.

    An attribute (`self.x = ...` inside a method) belongs to its class, not to
    the method that happens to assign it.
    """
    enclosing = [
        s
        for s in scopes
        if s.start <= line <= s.end and not (s.start == line and s.name == name)
    ]
    if kind == "attribute" and any(s.is_class for s in enclosing):
        enclosing = [s for s in enclosing if s.is_class]
    if not enclosing:
        return name
    return f"{max(enclosing, key=lambda s: s.start).qualname}.{name}"


def _is_job_function(path: str, symbol: str, kind: str) -> bool:
    """A public top-level function in a ``jobs/`` module: discovered, not called."""
    parts = PurePosixPath(path).parts
    return (
        kind == "function"
        and "jobs" in parts[:-1]
        and "." not in symbol
        and not symbol.startswith("_")
    )


#: The per-kind collections a `vulture.Vulture` fills while scanning.
_DEFINED = (
    "defined_attrs",
    "defined_classes",
    "defined_funcs",
    "defined_imports",
    "defined_methods",
    "defined_props",
    "defined_vars",
    "unreachable_code",
)


def _vulture(tree: Path, paths: list[Path], config: Config) -> Any:
    try:
        import vulture
        from vulture.core import ExitCode
    except ImportError as exc:  # pragma: no cover - environment, not logic
        raise ToolError(
            "vulture is not importable; run through `uv run` after `uv sync`"
        ) from exc

    # `ignore_names` is applied afterwards, to the findings: vulture matches it
    # against every definition it meets, which for this tree is most of the run.
    v = vulture.Vulture(ignore_decorators=list(config.ignore_decorators))
    v.scavenge([str(p) for p in paths])
    if v.exit_code == ExitCode.InvalidInput:
        raise ToolError(f"vulture could not parse a file under {tree.name}")
    return v


def scan(tree: Path, config: Config) -> tuple[list[Finding], list[Finding]]:
    """The commit at ``tree`` as ``(production findings, full findings)``.

    Each file is parsed once: production and tests are scanned separately, and
    the full scope is the union of the two scans' definitions and uses — which
    is all a vulture result is, so it equals one scan over both.
    """
    v = _vulture(tree, scope_paths(tree, PRODUCTION_DIRS), config)
    production = _findings(tree, v, config)
    tests = _vulture(tree, scope_paths(tree, TEST_DIRS), config)
    for collection in _DEFINED:
        getattr(v, collection).extend(getattr(tests, collection))
    v.used_names.update(tests.used_names)
    return production, _findings(tree, v, config)


def _findings(tree: Path, v: Any, config: Config) -> list[Finding]:
    ignored = re.compile("|".join(fnmatch.translate(p) for p in config.ignore_names))
    scopes: dict[Path, list[Span]] = {}
    findings: list[Finding] = []
    for item in v.get_unused_code(min_confidence=config.min_confidence):
        filename = Path(item.filename)
        if not filename.is_absolute() or not filename.is_relative_to(tree):
            continue  # vulture's bundled whitelists, never a finding of ours
        if item.typ == "variable" and item.confidence == 100:
            continue  # an unused argument — see the module docstring
        if config.ignore_names and ignored.match(item.name):
            continue
        if filename not in scopes:
            scopes[filename] = spans(ast.parse(filename.read_bytes()))
        path = filename.relative_to(tree).as_posix()
        symbol = _qualify(scopes[filename], item.name, item.first_lineno, item.typ)
        if _is_job_function(path, symbol, item.typ):
            continue
        findings.append(
            Finding(path, item.first_lineno, symbol, item.typ, item.confidence)
        )
    return findings


# --- the delta ---------------------------------------------------------------

Index = dict[tuple[str, str, str], list[Finding]]


def _index(findings: list[Finding]) -> Index:
    index: Index = defaultdict(list)
    for finding in findings:
        index[finding.key].append(finding)
    for occurrences in index.values():
        occurrences.sort(key=lambda f: f.line)
    return index


def _renamed(findings: list[Finding], renames: dict[str, str]) -> list[Finding]:
    return [
        Finding(renames.get(f.path, f.path), f.line, f.symbol, f.kind, f.confidence)
        for f in findings
    ]


def _tests_only(production: Index, full: Index) -> Index:
    """Unreferenced by production, referenced once tests are scanned."""
    only: Index = {}
    for key, occurrences in production.items():
        extra = len(occurrences) - len(full.get(key, ()))
        if extra > 0:
            only[key] = occurrences[-extra:]
    return only


def _new(head: Index, base: Index) -> list[Finding]:
    """Occurrences at ``head`` beyond the number ``base`` already had."""
    new: list[Finding] = []
    for key, occurrences in head.items():
        extra = len(occurrences) - len(base.get(key, ()))
        if extra > 0:
            new.extend(occurrences[-extra:])
    return new


def _marker(tree: Path, finding: Finding, cache: dict[str, list[str]]) -> str | None:
    if finding.path not in cache:
        cache[finding.path] = (
            (tree / finding.path)
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
        )
    lines = cache[finding.path]
    for number in (finding.line - 1, finding.line):
        if 1 <= number <= len(lines) and MARKER in lines[number - 1]:
            return "TRANSITIONAL"
    return None


def _sorted(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (f.path, f.line, f.symbol, f.kind))


@dataclass(frozen=True)
class Delta:
    base: str
    head: str
    config: Config
    vulture_version: str
    findings: list[Reported]
    neighbourhood: list[Reported]
    neighbourhood_total: int

    def counts(self) -> dict[str, int]:
        counts = {NEW_DEAD: 0, TESTS_ONLY: 0}
        for reported in self.findings:
            counts[reported.label] += 1
        return counts


def compute(root: Path, base: str, head: str, neighbourhood: int) -> Delta:
    import vulture

    config = load_config(root, head)
    with tempfile.TemporaryDirectory(prefix="dead-code-delta-") as tmp:
        trees = {"base": Path(tmp) / "base", "head": Path(tmp) / "head"}
        for side, sha in (("base", base), ("head", head)):
            trees[side].mkdir()
            materialise(root, sha, trees[side])

        renames = _renames(root, base, head)
        scans: dict[tuple[str, bool], Index] = {}
        for side, tree in trees.items():
            production, full = scan(tree, config)
            if side == "base":
                production = _renamed(production, renames)
                full = _renamed(full, renames)
            scans[side, False] = _index(production)
            scans[side, True] = _index(full)

        head_full, base_full = scans["head", True], scans["base", True]
        head_only = _tests_only(scans["head", False], head_full)
        base_only = _tests_only(scans["base", False], base_full)

        new_dead = _new(head_full, base_full)
        tests_only = _new(head_only, base_only)

        lines: dict[str, list[str]] = {}
        reported = [
            Reported(f, label, _marker(trees["head"], f, lines))
            for label, group in ((NEW_DEAD, new_dead), (TESTS_ONLY, tests_only))
            for f in group
        ]
        reported.sort(key=lambda r: (r.finding.path, r.finding.line, r.finding.symbol))

        changed = _changed_files(root, base, head)
        new = {*new_dead, *tests_only}
        pre_existing = _sorted(
            [
                f
                for index in (head_full, head_only)
                for occurrences in index.values()
                for f in occurrences
                if f.path in changed and f not in new
            ]
        )
        shown = [
            Reported(f, NEIGHBOURHOOD, _marker(trees["head"], f, lines))
            for f in pre_existing[:neighbourhood]
        ]

    return Delta(
        base=base,
        head=head,
        config=config,
        vulture_version=vulture.__version__,
        findings=reported,
        neighbourhood=shown,
        neighbourhood_total=len(pre_existing),
    )


# --- output ------------------------------------------------------------------


def render_text(delta: Delta) -> str:
    counts = delta.counts()
    out = [
        f"dead-code delta {delta.base[:12]}..{delta.head[:12]} "
        f"(vulture {delta.vulture_version}, min confidence "
        f"{delta.config.min_confidence})",
        f"{NEW_DEAD}: {counts[NEW_DEAD]}  {TESTS_ONLY}: {counts[TESTS_ONLY]}",
    ]
    if delta.findings:
        out.append("")
        out.extend(r.as_line() for r in delta.findings)
    if delta.neighbourhood:
        out.append("")
        out.append(
            f"neighbourhood: {len(delta.neighbourhood)} of "
            f"{delta.neighbourhood_total} pre-existing findings in changed files"
        )
        out.extend(r.as_line() for r in delta.neighbourhood)
    out.append("")
    out.extend(f"note: {note}" for note in NOTES)
    return "\n".join(out)


def render_json(delta: Delta) -> str:
    document = {
        "version": FORMAT_VERSION,
        "base": delta.base,
        "head": delta.head,
        "tool": {
            "name": "vulture",
            "version": delta.vulture_version,
            "min_confidence": delta.config.min_confidence,
        },
        "counts": delta.counts(),
        "findings": [r.as_json() for r in delta.findings],
        "neighbourhood": {
            "total": delta.neighbourhood_total,
            "shown": [r.as_json() for r in delta.neighbourhood],
        },
        "notes": list(NOTES),
    }
    return json.dumps(document, indent=2)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dead_code_delta.py",
        description="Report the dead code <head> introduces or orphans relative to <base>.",
    )
    parser.add_argument("base", help="the commit the change starts from")
    parser.add_argument("head", help="the commit the change ends at")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--neighbourhood",
        type=int,
        default=DEFAULT_NEIGHBOURHOOD,
        metavar="N",
        help="show up to N pre-existing findings in changed files (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.neighbourhood < 0:
        print("error: --neighbourhood must be zero or more", file=sys.stderr)
        return EXIT_ERROR
    try:
        root = _repo_root()
        base = _resolve(root, args.base)
        head = _resolve(root, args.head)
        delta = compute(root, base, head, args.neighbourhood)
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(render_json(delta) if args.json else render_text(delta))
    return EXIT_FINDINGS if delta.findings else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
