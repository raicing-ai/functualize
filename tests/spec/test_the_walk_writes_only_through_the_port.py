"""W-AC-1 — the walk never touches the legacy scope store.

An `ast` walk over **every module under ``src/functualize/_engine/``**, not a
regex: docstrings name `ScopeStore` freely and must not count, and a scope
store call hiding behind a helper the regex never heard of must still trip.

It refuses, anywhere under the engine:

- an import of ``functualize._primitives.scope_store``;
- a call to ``_scope_store(…)``;
- an attribute access through ``.scopes`` (``engine.scopes.get_scope`` was a
  real shape this rule exists for);
- a call to any ``ScopeStore``-only method name — unless its receiver is a
  legitimate carrier: the runtime-store port (``tx.workflows.record_branch``,
  ``store.workflows.steps``), the walk's own port helpers
  (``self._walk.record_branch`` — `FrontierWalk`'s method of the same name),
  or — the homonym this test names — ``WorkflowTracker.get_step``
  (``capabilities/workflow.py:38``), reached as ``…._get_tracker().get_step``
  in ``capabilities/observability_facade.py``. ``get_step`` is on the
  ScopeStore-only list and *also* a tracker method, so the receiver rule is
  what keeps the list honest without exempting a whole file.

The only other exceptions are the sites the spec puts out of scope (§3), each
with its reason:

- ``executor._scope_store`` — the definition itself, and the import inside
  it: the engine's non-walk paths still build a `ScopeStore` over the
  substrate;
- ``executor._scope_for`` — builds a non-walk ``State`` over it;
- ``executor._close_scope`` — closes a non-walk run's scope through it;
- ``capabilities/state.py`` — `ScopeBackedStateStore`, the ``State`` a
  context with no walk generation keeps (spec §3).
"""

from __future__ import annotations

import ast
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "src" / "functualize" / "_engine"

#: `ScopeStore`-only method names (spec W-AC-1): the walk's reads and writes
#: of its own scope must go through the runtime-store port, not these.
SCOPE_STORE_ONLY = frozenset(
    {
        "get_scope",
        "ensure_scope",
        "get_step",
        "record_step",
        "get_branch",
        "record_branch",
        "get_position",
        "set_position",
        "set_scope_status",
        "get_graph_digest",
        "set_graph_digest",
        "get_epilogue",
        "record_epilogue",
        "get_gate",
        "renew_scope",
        "release_scope",
        "hold",
    }
)

#: The port's own member names — a call through one of these is the port,
#: whatever the method is called (``tx.workflows.record_branch``).
_PORT_MEMBERS = frozenset({"workflows", "inputs", "runs", "events", "effects"})

#: (module name, function name) the spec puts out of scope, with the reason
#: carried in the assertion message so a reader never has to leave this file.
ALLOWED_FUNCTIONS = {
    ("executor.py", "_scope_store"): "the definition: non-walk paths build one",
    ("executor.py", "_scope_for"): "builds a non-walk State over it",
    ("executor.py", "_close_scope"): "closes a non-walk run's scope through it",
}

#: Modules whose *module-level* scope-store use is out of scope wholesale.
ALLOWED_MODULES = {
    "capabilities/state.py": "ScopeBackedStateStore — the State a non-walk context keeps",
}


def _receiver_is_legitimate(func: ast.expr) -> bool:
    """Is this call's receiver a carrier the port allows?

    - a port member: ``tx.workflows.record_branch``, ``store.inputs.request``;
    - the walk's own helpers: ``self._walk.record_branch``;
    - the tracker homonym: ``self._rc._get_tracker().get_step`` — a
      `WorkflowTracker`, not a scope store (named in the module docstring).
    """
    if isinstance(func, ast.Attribute):
        base = func.value
        if isinstance(base, ast.Attribute) and base.attr in _PORT_MEMBERS:
            return True  # tx.workflows.record_branch, store.inputs.request
        if ast.unparse(base) == "self._walk":
            return True
        if (
            isinstance(base, ast.Call)
            and isinstance(base.func, ast.Attribute)
            and base.func.attr == "_get_tracker"
        ):
            return True
    return False


def _violations(path: Path) -> list[str]:
    """Every refusal this module's tree trips, as `module:line — what` lines."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module_allows_all = path.relative_to(ENGINE).as_posix() in ALLOWED_MODULES
    found: list[str] = []

    def allow(func: ast.FunctionDef | ast.AsyncFunctionDef | None) -> bool:
        return module_allows_all or (
            func is not None and (path.name, func.name) in ALLOWED_FUNCTIONS
        )

    def visit(
        node: ast.AST, enclosing: ast.FunctionDef | ast.AsyncFunctionDef | None
    ) -> None:
        for child in ast.iter_child_nodes(node):
            inside = enclosing
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                inside = child
            elif isinstance(child, (ast.Import, ast.ImportFrom)) and not allow(inside):
                names = (
                    [child.module or ""]
                    if isinstance(child, ast.ImportFrom)
                    else [alias.name for alias in child.names]
                )
                for name in names:
                    if name.startswith("functualize._primitives.scope_store"):
                        found.append(f"{path.name}:{child.lineno} — imports {name}")
            elif isinstance(child, ast.Attribute) and child.attr == "scopes":
                # `.scopes` as a carrier: `engine.scopes.get_scope(...)`. The
                # attribute itself is flagged only when something reaches
                # through it, so a docstring example or a field named scopes
                # is not a refusal.
                if isinstance(child.ctx, ast.Load) and not allow(inside):
                    found.append(
                        f"{path.name}:{child.lineno} — reaches through `.scopes`"
                    )
            elif isinstance(child, ast.Call) and not allow(inside):
                func_name: str | None = None
                if isinstance(child.func, ast.Name):
                    func_name = child.func.id
                elif isinstance(child.func, ast.Attribute):
                    func_name = child.func.attr
                if func_name == "_scope_store":
                    found.append(f"{path.name}:{child.lineno} — calls _scope_store()")
                elif func_name in SCOPE_STORE_ONLY and not _receiver_is_legitimate(
                    child.func
                ):
                    found.append(
                        f"{path.name}:{child.lineno} — calls the scope store's "
                        f"{func_name}()"
                    )
            visit(child, inside)

    visit(tree, None)
    return found


def test_no_module_under_the_engine_reaches_the_scope_store() -> None:
    """Every module under `_engine/`, swept; nothing may trip a refusal."""
    modules = sorted(ENGINE.rglob("*.py"))
    assert modules, f"no modules found under {ENGINE}"
    violations = [line for path in modules for line in _violations(path)]
    assert not violations, (
        "the walk (or anything else under _engine/) reached the legacy scope "
        "store — the port is the only door:\n  " + "\n  ".join(violations)
    )


def test_the_allowlist_is_still_exact() -> None:
    """The out-of-scope sites exist as named — an allowlist for a deleted
    function is a licence for the next one."""
    executor = (ENGINE / "executor.py").read_text(encoding="utf-8")
    for name in ("_scope_store", "_scope_for", "_close_scope"):
        assert f"def {name}(" in executor, f"executor no longer defines {name}"
    assert (ENGINE / "capabilities" / "state.py").exists()
