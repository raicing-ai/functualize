"""Module-level mutable state in ``src/functualize`` is enumerated, never grown.

``.spec/CONSTITUTION.md`` forbids *global mutable state / module-level
singletons*. The rule was prose with no check behind it, so the audits that
counted the sites never agreed on the count. This ratchet reads the source and
pins the census: every site is either **excepted** (the Constitution's dated
exception, member-approved) or **pinned** (known and listed beside it, still a
violation, owed a decision or a repair). A site that is neither fails here
with its ``path:line``; a listed site that has gone fails too, so the list
only shrinks.

**What counts as module-level mutable state.** Five shapes, each found by AST
alone -- nothing is imported, so the check is deterministic and offline:

- ``rebound`` -- a module-level name a ``global`` statement rebinds.
- ``container`` -- a module- or class-level list, dict, set (or ``defaultdict``,
  ``deque``, weak collection ...) that some ``src/functualize`` code mutates in
  place. A container nobody mutates is a lookup table, not state.
- ``primitive`` -- a module- or class-level lock, ``threading.local`` or
  ``ContextVar``: an ambient channel, process- or context-wide by construction.
- ``memo`` -- a ``functools.cache`` / ``lru_cache`` on a module-level function.
- ``instance`` -- a module-level instance of a ``src/functualize`` class that
  has a method writing to ``self``.

**What it cannot see.** Instances of third-party classes (``click.Group``,
``logging.getLogger``), mutation through an alias the name never appears
under, and anything under ``plugins/`` -- the ban and this census are about
the core package.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = _ROOT / "src" / "functualize"
_CONSTITUTION = _ROOT / ".spec" / "CONSTITUTION.md"

#: The Constitution's exception: member-approved, kept on purpose.
EXCEPTED: frozenset[tuple[str, str]] = frozenset(
    {
        ("_config/vault_keyring_macos.py", "_INTERACTION_LOCK"),
        ("_discovery/lazy_wrapper.py", "_IMPORT_LOCK"),
        ("_types/workflow.py", "_in_doubt_model"),
    }
)

#: Known and listed beside the exception, **not** excepted. Each is still a
#: violation of the ban; the Constitution states its reason or its repair.
PINNED: frozenset[tuple[str, str]] = frozenset(
    {
        ("_primitives/entry_points.py", "_lock"),
        ("_primitives/entry_points.py", "_snapshot"),
        ("_primitives/run_store.py", "_ID_LOCK"),
        ("_primitives/run_store.py", "_LAST"),
        ("_cli/completions/engine.py", "_scan_path_executables"),
        ("_cli/data/func_settings.py", "_PREBOOT_OVERRIDES"),
        ("_events/run_log.py", "_local"),
        ("_events/tracing.py", "_context_var"),
        ("_app/boot.py", "_DIAGNOSTIC_BOOT"),
        ("_types/discovery_report.py", "_ACTIVE"),
        ("_cli/data/func_settings.py", "_REGISTERED"),
        ("_primitives/fingerprint.py", "_WARNED_UNREUSABLE"),
        ("_config/_emit.py", "_sink"),
        ("_app/event_wiring.py", "_sink_installed"),
        ("_engine/capabilities/stdin_collector.py", "_STDIN_COLLECTOR"),
        ("_events/tracing.py", "_EMPTY_CONTEXT"),
        ("_events/perf.py", "perf_timeline"),
        ("_app/state.py", "AppState._state"),
        ("_app/state.py", "AppState._lock"),
    }
)

_CONTAINER_LITERALS = (
    ast.List,
    ast.Dict,
    ast.Set,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
)
_CONTAINER_CALLS = frozenset(
    {
        "list",
        "dict",
        "set",
        "bytearray",
        "defaultdict",
        "OrderedDict",
        "Counter",
        "deque",
        "ChainMap",
        "WeakValueDictionary",
        "WeakKeyDictionary",
        "WeakSet",
    }
)
_PRIMITIVE_CALLS = frozenset(
    {
        "Lock",
        "RLock",
        "Condition",
        "Semaphore",
        "BoundedSemaphore",
        "Event",
        "Barrier",
        "local",
        "ContextVar",
    }
)
_MEMO_DECORATORS = frozenset({"cache", "lru_cache"})
_MUTATORS = frozenset(
    {
        "append",
        "appendleft",
        "extend",
        "extendleft",
        "insert",
        "add",
        "update",
        "setdefault",
        "pop",
        "popitem",
        "popleft",
        "remove",
        "discard",
        "clear",
        "sort",
        "reverse",
        "difference_update",
        "intersection_update",
        "symmetric_difference_update",
        "__setitem__",
        "__delitem__",
    }
)
_CONSTRUCTION = frozenset({"__init__", "__post_init__", "__new__"})


@dataclass(frozen=True)
class Site:
    """One module-level mutable binding."""

    path: str
    line: int
    symbol: str
    kind: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.path, self.symbol)


def _callee(node: ast.expr) -> str | None:
    """The terminal name of a call (``threading.Lock()`` -> ``Lock``)."""
    func = node.func if isinstance(node, ast.Call) else node
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _bindings(body: list[ast.stmt]) -> list[tuple[str, int, ast.expr]]:
    """``(name, line, value)`` for each plain-name assignment in ``body``."""
    found: list[tuple[str, int, ast.expr]] = []
    for stmt in body:
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            targets, value = [stmt.target], stmt.value
        else:
            continue
        found.extend(
            (target.id, stmt.lineno, value)
            for target in targets
            if isinstance(target, ast.Name)
        )
    return found


def _is_container(value: ast.expr) -> bool:
    return isinstance(value, _CONTAINER_LITERALS) or (
        isinstance(value, ast.Call) and _callee(value) in _CONTAINER_CALLS
    )


def _is_primitive(value: ast.expr) -> bool:
    return isinstance(value, ast.Call) and _callee(value) in _PRIMITIVE_CALLS


def _mutated_receiver(node: ast.AST) -> ast.expr | None:
    """The expression ``node`` mutates in place, if it is a mutation."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _MUTATORS
    ):
        return node.func.value
    targets: list[ast.expr] = []
    if isinstance(node, (ast.Assign, ast.Delete)):
        targets = list(node.targets)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        targets = [node.target]
    for target in targets:
        if isinstance(target, ast.Subscript):
            return target.value
        if isinstance(node, ast.AugAssign) and isinstance(target, ast.Attribute):
            return target
    return None


def _writes_self(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(func):
        receiver = _mutated_receiver(node)
        if receiver is None and isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            receiver = next((t for t in targets if isinstance(t, ast.Attribute)), None)
        while isinstance(receiver, (ast.Attribute, ast.Subscript)):
            receiver = receiver.value
        if isinstance(receiver, ast.Name) and receiver.id == "self":
            return True
    return False


def _module_name(rel: str) -> str:
    parts = ["functualize", *Path(rel).with_suffix("").parts]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class _Module:
    def __init__(self, rel: str, source: str) -> None:
        self.rel = rel
        self.name = _module_name(rel)
        self.tree = ast.parse(source)
        self.top = {
            name: (line, value) for name, line, value in _bindings(self.tree.body)
        }
        self.classes = {
            node.name: node for node in self.tree.body if isinstance(node, ast.ClassDef)
        }
        #: local name -> (module, attribute or None for the module itself)
        self.imports: dict[str, tuple[str, str | None]] = {}
        #: names a ``global`` statement anywhere in the module rebinds
        self.rebound: set[str] = set()
        #: every name and attribute the module mentions
        self.mentions: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                self.mentions.add(node.id)
            elif isinstance(node, ast.Attribute):
                self.mentions.add(node.attr)
            elif isinstance(node, ast.Global):
                self.rebound.update(node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for alias in node.names:
                    self.imports[alias.asname or alias.name] = (node.module, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        self.imports[alias.asname] = (alias.name, None)


def _resolve(
    receiver: ast.expr, module: _Module, owner: ast.ClassDef | None
) -> tuple[str, str] | None:
    """``(module, symbol)`` a mutated receiver names, when it names a binding."""
    if isinstance(receiver, ast.Name):
        if receiver.id in module.top:
            return (module.name, receiver.id)
        target = module.imports.get(receiver.id)
        if target and target[1] is not None:
            return (target[0], target[1])
        return None
    if isinstance(receiver, ast.Attribute) and isinstance(receiver.value, ast.Name):
        base = receiver.value.id
        if owner is not None and base in {"cls", "self", owner.name}:
            return (module.name, f"{owner.name}.{receiver.attr}")
        if base in module.classes:
            return (module.name, f"{base}.{receiver.attr}")
        target = module.imports.get(base)
        if target:
            module_name = target[0] if target[1] is None else f"{target[0]}.{target[1]}"
            return (module_name, receiver.attr)
    return None


def _function_locals(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names a function binds locally (so they shadow a module binding)."""
    bound = {arg.arg for arg in ast.walk(func.args) if isinstance(arg, ast.arg)}
    declared_global: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Global):
            declared_global.update(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
    return bound - declared_global


def _mutations(module: _Module, candidates: set[str]) -> set[tuple[str, str]]:
    """Every ``(module, symbol)`` among ``candidates`` this module mutates."""
    found: set[tuple[str, str]] = set()
    if not module.mentions & candidates:
        return found
    scope_locals: dict[int, set[str]] = {}

    def shadowed(name: str, scopes: tuple[ast.AST, ...]) -> bool:
        for func in scopes:
            if id(func) not in scope_locals:
                assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
                scope_locals[id(func)] = _function_locals(func)
            if name in scope_locals[id(func)]:
                return True
        return False

    def visit(
        node: ast.AST, owner: ast.ClassDef | None, scopes: tuple[ast.AST, ...]
    ) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, child, scopes)
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, owner, (*scopes, child))
                continue
            receiver = _mutated_receiver(child)
            terminal = (
                receiver.id
                if isinstance(receiver, ast.Name)
                else receiver.attr
                if isinstance(receiver, ast.Attribute)
                else None
            )
            if receiver is not None and terminal in candidates:
                resolved = _resolve(receiver, module, owner)
                if resolved and not (
                    isinstance(receiver, ast.Name) and shadowed(receiver.id, scopes)
                ):
                    found.add(resolved)
            visit(child, owner, scopes)

    visit(module.tree, None, ())
    return found


def _is_stateful(cls: ast.ClassDef) -> bool:
    """Does a method other than construction write to ``self``?"""
    return any(
        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name not in _CONSTRUCTION
        and _writes_self(item)
        for item in cls.body
    )


def module_state(sources: dict[str, str]) -> list[Site]:
    """Every module-level mutable binding in ``sources`` (``rel path -> code``)."""
    modules = [_Module(rel, code) for rel, code in sorted(sources.items())]
    candidates = {
        name
        for module in modules
        for body in (
            module.tree.body,
            *(cls.body for cls in module.classes.values()),
        )
        for name, _, value in _bindings(body)
        if _is_container(value)
    }
    mutated = set().union(*(_mutations(module, candidates) for module in modules))
    classes = {
        (module.name, cls.name): cls
        for module in modules
        for cls in module.classes.values()
    }
    sites: list[Site] = []
    for module in modules:
        rebound = module.rebound
        for name, (line, value) in module.top.items():
            kind = None
            if name in rebound:
                kind = "rebound"
            elif _is_primitive(value):
                kind = "primitive"
            elif _is_container(value) and (module.name, name) in mutated:
                kind = "container"
            elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                cls_name = value.func.id
                origin = module.imports.get(cls_name)
                cls_key = (
                    (origin[0], origin[1])
                    if origin and origin[1]
                    else (module.name, cls_name)
                )
                if cls_key in classes and _is_stateful(classes[cls_key]):
                    kind = "instance"
            if kind:
                sites.append(Site(module.rel, line, name, kind))
        for name in sorted(rebound - module.top.keys()):
            sites.append(Site(module.rel, 0, name, "rebound"))
        for node in module.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                _callee(deco) in _MEMO_DECORATORS for deco in node.decorator_list
            ):
                sites.append(Site(module.rel, node.lineno, node.name, "memo"))
        for cls in module.classes.values():
            for name, line, value in _bindings(cls.body):
                symbol = f"{cls.name}.{name}"
                if _is_primitive(value) or (
                    _is_container(value) and (module.name, symbol) in mutated
                ):
                    sites.append(Site(module.rel, line, symbol, "class-level"))
    return sorted(sites, key=lambda site: (site.path, site.line, site.symbol))


def _package_sources() -> dict[str, str]:
    return {
        path.relative_to(_PACKAGE).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(_PACKAGE.rglob("*.py"))
    }


def _constitution_entries(label: str) -> set[tuple[str, str]]:
    """``(path, symbol)`` pairs enumerated under ``label`` in the Constitution."""
    text = _CONSTITUTION.read_text(encoding="utf-8")
    start = text.index(label)
    # A block ends at the next bold paragraph or the next top-level bullet.
    end = min(
        index
        for index in (
            text.find("\n  **", start + len(label)),
            text.find("\n- ", start + len(label)),
        )
        if index != -1
    )
    return {
        (path, symbol)
        for path, symbol in re.findall(
            r"^  - `([\w/]+\.py):\d+` `([\w.]+)`", text[start:end], re.MULTILINE
        )
    }


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def census() -> list[Site]:
    """One scan of the package, shared by the two ratchet tests."""
    return module_state(_package_sources())


def test_no_module_level_state_outside_the_census(census: list[Site]) -> None:
    known = EXCEPTED | PINNED
    offenders = [
        f"src/functualize/{site.path}:{site.line} {site.symbol} ({site.kind})"
        for site in census
        if site.key not in known
    ]
    assert not offenders, (
        "New module-level mutable state. `.spec/CONSTITUTION.md` forbids global "
        "mutable state / module-level singletons: give it an owner (the app, the "
        "engine, the run) instead. Keeping it needs a member-approved entry in the "
        "Constitution's exception and in EXCEPTED here:\n  " + "\n  ".join(offenders)
    )


def test_every_listed_site_still_exists(census: list[Site]) -> None:
    """A repaired site leaves the list, so the list can only shrink."""
    present = {site.key for site in census}
    stale = sorted(
        f"src/functualize/{path} {symbol}"
        for path, symbol in (EXCEPTED | PINNED) - present
    )
    assert not stale, (
        "Listed module-level state is gone: remove it from EXCEPTED/PINNED here "
        "and from `.spec/CONSTITUTION.md`:\n  " + "\n  ".join(stale)
    )


def test_the_constitution_enumerates_the_same_sites() -> None:
    assert not EXCEPTED & PINNED
    assert _constitution_entries("**Exception — process-wide state") == EXCEPTED
    assert _constitution_entries("**Pinned, not excepted") == PINNED


def test_the_scan_covers_the_tree() -> None:
    """A ratchet that reads no files passes forever."""
    sources = _package_sources()
    assert len(sources) > 300
    assert "_discovery/lazy_wrapper.py" in sources


# ---------------------------------------------------------------------------
# The detector, on snippets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("snippet", "symbol", "kind"),
    [
        ("_X = None\ndef f():\n    global _X\n    _X = 1\n", "_X", "rebound"),
        ("_SEEN = set()\ndef f(n):\n    _SEEN.add(n)\n", "_SEEN", "container"),
        ("_REG: list[int] = []\ndef f():\n    _REG.append(1)\n", "_REG", "container"),
        ("_M = {}\ndef f(k):\n    _M[k] = 1\n", "_M", "container"),
        ("_M = {}\ndef f(k):\n    del _M[k]\n", "_M", "container"),
        ("import threading\n_L = threading.Lock()\n", "_L", "primitive"),
        ("from threading import RLock\n_L = RLock()\n", "_L", "primitive"),
        ("import threading\n_T = threading.local()\n", "_T", "primitive"),
        (
            "from contextvars import ContextVar\n_V = ContextVar('v')\n",
            "_V",
            "primitive",
        ),
        ("from functools import cache\n@cache\ndef f():\n    return 1\n", "f", "memo"),
        (
            "import functools\n@functools.lru_cache(maxsize=1)\ndef f():\n    return 1\n",
            "f",
            "memo",
        ),
        (
            "class C:\n    def __init__(self):\n        self.n = 0\n"
            "    def bump(self):\n        self.n += 1\n_C = C()\n",
            "_C",
            "instance",
        ),
        (
            "class S:\n    _d: dict = {}\n    @classmethod\n"
            "    def put(cls, k, v):\n        cls._d[k] = v\n",
            "S._d",
            "class-level",
        ),
    ],
)
def test_module_state_is_caught(snippet: str, symbol: str, kind: str) -> None:
    sites = module_state({"m.py": snippet})
    assert [(site.symbol, site.kind) for site in sites] == [(symbol, kind)]


@pytest.mark.parametrize(
    "snippet",
    [
        "_TABLE = {'a': 1}\ndef f(k):\n    return _TABLE[k]\n",
        "_NAMES = frozenset({'a'})\n",
        "_NAMES = ('a', 'b')\n",
        "import logging\nlogger = logging.getLogger(__name__)\n",
        "_M = {}\ndef f():\n    _M = {}\n    _M['k'] = 1\n",
        "_M = {}\ndef f(_M):\n    _M['k'] = 1\n",
        "from dataclasses import dataclass\n@dataclass(frozen=True)\n"
        "class P:\n    n: int\n_P = P(1)\n",
        "class _Sentinel:\n    pass\n_MISSING = _Sentinel()\n",
        "class C:\n    def __init__(self):\n        self.n = 0\n"
        "    def get(self):\n        return self.n\n_C = C()\n",
        "class K:\n    BINDINGS = [1]\n",
    ],
)
def test_constants_and_locals_are_left_alone(snippet: str) -> None:
    assert module_state({"m.py": snippet}) == []
