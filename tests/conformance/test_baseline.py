"""BASELINE over both shipped runtime stores (AC-2, first half).

Imports public names only — ``functualize.testing.conformance`` is a shipped
library whose consumer is a test suite, so this file *is* its production
caller, and an import from a private module here would hide the surface a
third-party backend actually gets. The document store has no public
constructor, so it is reached the way a user reaches it: boot an app in a
project directory and take the store boot selected by default.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.plugin import (
    CompleteStep,
    RecordStep,
    RuntimeStore,
    RuntimeStoreConfig,
    StepView,
    SuspendAtGate,
)
from functualize.testing.conformance import run_baseline
from functualize.testing.conformance.baseline import BASELINE

sqlite = pytest.importorskip(
    "functualize_substrate_sqlite",
    reason="workspace plugins not installed; run `uv sync --all-packages --all-extras`",
)


def documents_store(root: Path) -> RuntimeStore:
    """The store an app selects with nothing configured, over ``root``."""
    (root / ".functualize").mkdir(parents=True, exist_ok=True)
    previous = Path.cwd()
    os.chdir(root)
    try:
        app = FunctualizeApp("conformance", job_sources=JobSources(directories=[]))
    finally:
        os.chdir(previous)
    store: RuntimeStore = app.execution_engine._runtime_store
    assert store.profile.name == "documents"
    return store


def sqlite_store(root: Path) -> RuntimeStore:
    """The SQLite store over ``root/state.db``, prepared as boot prepares it."""
    config = RuntimeStoreConfig(
        url=f"sqlite://{root / 'state.db'}", scheme="sqlite", project_root=root
    )
    return sqlite.SqliteRuntimeStoreFactory().prepare(config).store


STORES: dict[str, Callable[[Path], RuntimeStore]] = {
    "documents": documents_store,
    "sqlite": sqlite_store,
}


def test_new_port_fields_preserve_existing_constructor_defaults() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert (
        CompleteStep("scope", 1, "step", now).attempt,
        CompleteStep("scope", 1, "step", now).started_at,
    ) == (0, None)
    assert (
        RecordStep("scope", 1, "step", now, None).attempt,
        RecordStep("scope", 1, "step", now, None).started_at,
    ) == (0, None)
    assert (
        StepView("scope", "step", 0, "success").attempt,
        StepView("scope", "step", 0, "success").started_at,
    ) == (0, None)
    assert SuspendAtGate("scope", 1, "gate", "request", "gate", now).supersedes is None


@pytest.mark.parametrize("store", sorted(STORES))
@pytest.mark.parametrize("check", [name for name, _ in BASELINE])
def test_each_baseline_check(store: str, check: str, tmp_path: Path) -> None:
    dict(BASELINE)[check](STORES[store], tmp_path)


@pytest.mark.parametrize("store", sorted(STORES))
def test_run_baseline_is_the_whole_suite(store: str, tmp_path: Path) -> None:
    run_baseline(STORES[store], tmp_path)


def test_the_library_and_its_tests_import_nothing_private() -> None:
    """The shipped suite, and this consumer of it, use public modules only."""
    library = Path(__import__("functualize.testing.conformance").__file__).parent
    library = library / "testing" / "conformance"
    files = [*library.glob("*.py"), *Path(__file__).parent.glob("*.py")]
    private = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            private += [
                f"{path.name}: {n}"
                for n in names
                if any(
                    part.startswith("_") and part != "__future__"
                    for part in n.split(".")
                )
            ]
    assert files and not private, private
