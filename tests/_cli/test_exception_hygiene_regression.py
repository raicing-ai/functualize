"""AST-based regression guard for the R4 exception-hygiene pass.

no exception is caught anywhere in ``src/functualize/_cli/tui/``
via a broad, silent ``except Exception`` (or tautological
``except (..., Exception)``) swallow — every such catch must either
re-raise, log the swallow, surface the bound exception to the user, or
narrow to the specific exception type the situation can actually raise.
The only sites exempted from this rule are enumerated in
``_ALLOWED_SILENT_SWALLOWS`` below, each with an inline rationale.

This test is the permanent standing guard described in the SPEC's
traceability table, broadened beyond the original literal
``except Exception: pass`` pattern to also catch broad catches with a
silent (non-logging, non-re-raising) fallback body.
"""

from __future__ import annotations

import ast
from pathlib import Path

TUI_ROOT = Path(__file__).resolve().parents[2] / "src" / "functualize" / "_cli" / "tui"

#: Load-bearing exceptions permitted by.
_ALLOWED_SILENT_SWALLOWS = {
    # A logging handler's emit() must never raise, so it keeps a broad,
    # silent catch.
    (str(TUI_ROOT / "job_execution.py"), "_TuiLogHandler.emit"),
}


_LOG_METHOD_NAMES = {"warning", "error", "exception", "critical", "debug", "info"}


def _is_log_call(node: ast.AST) -> bool:
    """True if ``node`` is a ``self.log.X(...)`` / ``app.log.X(...)`` /
    ``logger.X(...)``-shaped call (any attribute-chain ending in
    ``.log.<level>(...)`` or a bare ``logger.<level>(...)``)."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    func = node.func
    if func.attr not in _LOG_METHOD_NAMES:
        return False
    # `<anything>.log.<level>(...)` — e.g. self.log.warning, app.log.error
    if isinstance(func.value, ast.Attribute) and func.value.attr == "log":
        return True
    # `logger.<level>(...)` — bare module/instance logger
    return isinstance(func.value, ast.Name) and func.value.id in {"logger", "log"}


def _body_handles_exception(body: list[ast.stmt], exc_name: str | None) -> bool:
    """True if the except-handler body re-raises the exception, logs it via
    a ``.log.<level>(...)``/``logger.<level>(...)`` call, or otherwise
    surfaces the bound exception value (e.g. ``except Exception as e:`` with
    ``e`` referenced in a user-facing call such as writing it to a TUI
    output widget) rather than discarding it silently."""
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                return True
            if _is_log_call(node):
                return True
            if (
                exc_name
                and isinstance(node, ast.Name)
                and node.id == exc_name
                and isinstance(node.ctx, ast.Load)
            ):
                # The bound exception is referenced (e.g. included in an
                # f-string passed to a user-facing write call) — not a
                # silent swallow, even though it isn't routed through
                # self.log/logger specifically.
                return True
    return False


def _iter_bare_except_exception_pass_sites() -> list[tuple[str, int, str]]:
    """Return (file, lineno, qualified_function_name) for every
    unjustified broad ``except Exception`` (or ``except (..., Exception)``)
    site under ``src/functualize/_cli/tui/`` — i.e. a bare/tautological
    ``Exception`` handler whose body neither re-raises nor logs the
    exception. Handlers that narrow to a specific exception type (e.g.
    ``NoMatches``, ``AttributeError``) are exempt, per the audit rule's
    "narrow to a specific type" alternative."""
    sites: list[tuple[str, int, str]] = []
    for py_file in sorted(TUI_ROOT.rglob("*.py")):
        source = py_file.read_text()
        tree = ast.parse(source, filename=str(py_file))
        _visit_for_silent_swallows(tree, [], py_file, sites)
    return sites


def _visit_for_silent_swallows(
    node: ast.AST,
    stack: list[ast.AST],
    py_file: Path,
    sites: list[tuple[str, int, str]],
) -> None:
    """Recursively walk ``node``, recording unjustified broad-except sites."""
    if isinstance(node, ast.ExceptHandler):
        is_exception = False
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            is_exception = True
        elif isinstance(node.type, ast.Tuple):
            names = [elt.id for elt in node.type.elts if isinstance(elt, ast.Name)]
            if "Exception" in names:
                is_exception = True
        if is_exception and not _body_handles_exception(node.body, node.name):
            qualname_parts = [
                n.name
                for n in stack
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            qualname = ".".join(qualname_parts) or "<module>"
            sites.append((str(py_file), node.lineno, qualname))
    for child in ast.iter_child_nodes(node):
        _visit_for_silent_swallows(child, [*stack, node], py_file, sites)


def test_no_unjustified_silent_exception_swallows() -> None:
    """the only permitted broad-``except Exception`` sites in
    ``tui/`` are the entries in ``_ALLOWED_SILENT_SWALLOWS`` — every other
    broad catch must either re-raise, log the swallow (``self.log``/
    ``app.log``/``logger.<level>(...)``), surface the bound exception value
    to the user, or narrow to a specific exception type."""
    sites = _iter_bare_except_exception_pass_sites()
    unjustified = [
        (f, lineno, qualname)
        for f, lineno, qualname in sites
        if (f, qualname) not in _ALLOWED_SILENT_SWALLOWS
    ]
    assert unjustified == [], (
        "Unjustified silent 'except Exception: pass' swallow(s) found in "
        f"tui/: {unjustified}"
    )
    # Sanity check: exactly the allowlisted sites are present — guards
    # against silently widening the allowlist beyond what is documented
    # above.
    found = {(f, qualname) for f, _lineno, qualname in sites}
    assert found == _ALLOWED_SILENT_SWALLOWS
    assert len(sites) == len(_ALLOWED_SILENT_SWALLOWS)
