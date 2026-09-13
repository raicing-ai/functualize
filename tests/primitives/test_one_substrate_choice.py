"""One choice moves every store, or none of them.

`store-substrate`/T4. Spec AC-4.

The failure this rules out is a **split brain**: scope records in one backend
while the job state *inside those records* is in another, so a resumed run finds
its steps and not its variables. Before this feature each store resolved its own
location, and they agreed because five copies of one upward walk happened to
agree — a convention, held by care.

So these tests do not check that the five answers match. They check that there
is **one answer**: `substrate_for_project` is the only thing that decides, and
redirecting it moves every store at once. A test that asserted "the paths are
siblings" would pass just as happily with five independent resolutions, which is
the arrangement this feature exists to end.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from functualize._primitives import substrate as substrate_module
from functualize._primitives.fresh_store import FreshStore
from functualize._primitives.run_store import RunStore
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.shell_history import ShellHistoryStore
from functualize._primitives.substrate import (
    JsonFileSubstrate,
    substrate_for_project,
)

if TYPE_CHECKING:
    from functualize._types.protocols import StoreSubstrate

#: Every store that keeps durable state. The list is the point: a sixth store
#: added without a `for_project` that routes through the one decision is exactly
#: the regression AC-4 forbids, and it fails here rather than in a resumed run.
STORES = (FreshStore, ScopeStore, RunStore, ShellHistoryStore)

SRC = Path(__file__).resolve().parents[2] / "src" / "functualize"


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    from functualize._engine.executor import JobExecutionEngine
    from functualize._engine.middleware import ExecutionMiddlewareChain
    from functualize._events.bus import EventBus
    from functualize._events.hooks import HookRegistry
    from functualize._primitives.di import DIRegistry

    return JobExecutionEngine(
        di_registry=DIRegistry(),
        event_bus=EventBus(),
        hook_registry=HookRegistry(),
        middleware_chain=ExecutionMiddlewareChain(),
        fresh_root=tmp_path,
    )


class TestRedirectingTheChoiceMovesEveryStore:
    def test_every_store_follows_one_redirect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The capability, stated as the thing a configured backend will do.

        Redirected **inside** the one decision rather than by rebinding its
        name, because that is where a configured substrate will actually land:
        `substrate_for_project` reads the configuration and returns something
        else. Rebinding the module attribute would not even reach the stores —
        they import the function by name — and a test that patched each store's
        own binding would be asserting the convention this feature replaced.

        If any store resolved its own, it would still be on the filesystem here
        while the others moved, which is the split brain reproduced.
        """
        elsewhere = JsonFileSubstrate(tmp_path / "elsewhere")
        monkeypatch.setattr(
            substrate_module.JsonFileSubstrate,
            "for_project",
            classmethod(lambda _cls, _start: elsewhere),
        )

        for store_cls in STORES:
            built = store_cls.for_project(tmp_path)
            assert built.substrate is elsewhere, (
                f"{store_cls.__name__} resolved its own substrate instead of "
                f"asking substrate_for_project — one choice no longer moves it"
            )

    def test_the_scope_store_and_its_state_cannot_diverge(self, tmp_path: Path) -> None:
        """The split brain, named.

        A scope's records and the job state inside them are two documents. They
        are reachable from one `ScopeStore`, which holds one substrate, so there
        is no second object that could be pointed elsewhere.
        """
        store = ScopeStore.for_project(tmp_path)
        store.set_state("wf", "k", 1)

        assert store._state_store("wf")._substrate is store.substrate  # noqa: SLF001


class TestThereIsOnlyOneDecision:
    def test_exactly_one_place_names_the_filesystem_substrate(self) -> None:
        """Counted by walking the AST, not by grepping for the name.

        Four docstrings in `_primitives` explain what
        `JsonFileSubstrate.for_project` does, and a grep answers with them. What
        must stay singular is the number of places that *call* it.
        """
        callers: list[str] = []
        walked = 0
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                walked += 1
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "for_project"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "JsonFileSubstrate"
                ):
                    callers.append(f"{path.relative_to(SRC)}:{node.lineno}")

        assert walked > 1000, (
            f"the AST walk found only {walked} calls in all of src/, so it is "
            f"not looking at what it thinks it is"
        )
        assert callers == ["_primitives/substrate.py:273"] or len(callers) == 1, (
            f"more than one place decides which substrate a project uses: {callers}"
        )

    def test_every_store_for_project_routes_through_it(self) -> None:
        """Stated over the store list, so a sixth store is caught here."""
        source = {
            cls.__name__: (SRC / "_primitives" / module).read_text()
            for cls, module in zip(
                STORES,
                (
                    "fresh_store.py",
                    "scope_store.py",
                    "run_store.py",
                    "shell_history.py",
                ),
                strict=True,
            )
        }
        for name, text in source.items():
            assert "substrate_for_project(" in text, (
                f"{name}.for_project does not route through the one decision"
            )


class TestTheChoiceIsNotCached:
    @pytest.mark.json_substrate
    def test_two_projects_get_two_substrates(self, tmp_path: Path) -> None:
        """A cache keyed by path would be module-level mutable state, and worse.

        The CLI changes directory, and so do the tests. A memoised answer would
        hand the second project the first one's documents — the failure is
        silent and looks like data loss.
        """
        (tmp_path / "a" / ".functualize").mkdir(parents=True)
        (tmp_path / "b" / ".functualize").mkdir(parents=True)

        first = substrate_for_project(tmp_path / "a")
        second = substrate_for_project(tmp_path / "b")

        assert first.path_for("fresh") != second.path_for("fresh")


class TestTheEngineResolvesOnce:
    def test_the_engine_holds_one_substrate(self, engine: Any) -> None:
        """Not cached globally — cached on the object with a run's lifetime.

        A run touches the ledger, the records, the state inside them and the run
        log. Resolving per store means four upward walks for one run, and once a
        substrate is configurable it also means four chances to be told a
        different answer halfway through.
        """
        assert engine.substrate is engine.substrate

    def test_the_stores_it_builds_share_it(self, engine: Any) -> None:
        substrate: Any = engine.substrate

        assert engine._state_store().substrate is substrate  # noqa: SLF001
        assert engine._scope_store().substrate is substrate  # noqa: SLF001


class TestItIsStillASubstrate:
    def test_the_one_decision_returns_the_port(self, tmp_path: Path) -> None:
        from functualize._types.protocols import StoreSubstrate as Port

        resolved: StoreSubstrate = substrate_for_project(tmp_path)
        assert isinstance(resolved, Port)
