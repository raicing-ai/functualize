"""One set of checks per provider table, and one check that no table is missed.

`EXECUTOR_PROVIDERS` (`_engine/agent_providers.py`) is the second table in core
answering *"why is this name unregistered?"*. Two is where copying starts, and
a test copied per table is how `pitfalls.md` §6 drifts: each copy stays green
while the table it does not cover quietly loses an entry.

So every check here is parametrized over a list. A third table joins `_TABLES`
and inherits all of them, and
`TestEveryTableIsListedHere::test_every_provider_table_in_src_is_listed_here`
refuses to let a table exist without joining — a registry nothing verifies is
just one more copy.

The strategy table's checks moved here from `tests/gate/test_registry.py`, which
is about the gate registry's *behaviour* rather than about its table.
"""

from __future__ import annotations

import importlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = REPO_ROOT / "src"

#: A provider table declaration: `NAME_PROVIDERS: dict[...] = {` or the plain
#: assignment. Anchored at the line start, so prose about a table is not one.
_TABLE_DEFINITION = re.compile(r"^([A-Z][A-Z0-9_]*_PROVIDERS)\s*[:=]", re.MULTILINE)


@dataclass(frozen=True)
class ProviderTable:
    """One `*_PROVIDERS` table, with the names it is read through.

    The module path and attribute names are held as strings rather than as the
    objects themselves, so the list below is the same thing
    `test_every_provider_table_in_src_is_listed_here` compares against what it
    discovers on disk.
    """

    module: str
    table: str
    core: str
    hint: str

    def _attr(self, name: str) -> Any:
        return getattr(importlib.import_module(self.module), name)

    @property
    def providers(self) -> dict[str, str]:
        return self._attr(self.table)

    @property
    def core_names(self) -> frozenset[str]:
        return self._attr(self.core)

    def hint_for(self, name: str) -> str:
        return self._attr(self.hint)(name)

    @property
    def plugin_packages(self) -> list[str]:
        """The packages this table names, minus core's own."""
        return sorted({p for p in self.providers.values() if p != "functualize"})


_TABLES: tuple[ProviderTable, ...] = (
    ProviderTable(
        module="functualize._gate._strategy",
        table="STRATEGY_PROVIDERS",
        core="CORE_STRATEGIES",
        hint="missing_strategy_hint",
    ),
    ProviderTable(
        module="functualize._engine.agent_providers",
        table="EXECUTOR_PROVIDERS",
        core="CORE_EXECUTORS",
        hint="missing_executor_hint",
    ),
)

_TABLE_IDS = [table.table for table in _TABLES]


def _module_path(path: Path) -> str:
    parts = list(path.relative_to(_SRC).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _discovered_tables() -> set[tuple[str, str]]:
    """Every `(module, attribute)` in `src/` that declares a provider table."""
    found: set[tuple[str, str]] = set()
    for path in sorted((_SRC / "functualize").rglob("*.py")):
        found.update(
            (_module_path(path), name)
            for name in _TABLE_DEFINITION.findall(path.read_text(encoding="utf-8"))
        )
    return found


class TestEveryTableIsListedHere:
    def test_every_provider_table_in_src_is_listed_here(self) -> None:
        """A table nobody lists is a table nobody checks.

        Adding one to `_TABLES` is the whole cost of the checks below; leaving
        it out is the failure this test exists to make impossible, because a
        second table that only *looks* covered is worse than an obviously
        uncovered one.
        """
        discovered = _discovered_tables()
        listed = {(table.module, table.table) for table in _TABLES}

        unlisted = sorted(discovered - listed)
        assert not unlisted, (
            f"provider tables in src/ that this file does not check: {unlisted}. "
            "Add each to _TABLES."
        )

        missing = sorted(listed - discovered)
        assert not missing, (
            f"_TABLES names provider tables that no longer exist: {missing}. "
            "Remove them, or restore the tables they describe."
        )


@pytest.mark.parametrize("table", _TABLES, ids=_TABLE_IDS)
class TestEveryProviderTable:
    def test_it_maps_at_least_one_name_to_a_package(self, table: ProviderTable) -> None:
        """An empty table makes every hint empty, which is the one case where
        the diagnostic would not even name an unknown name as unknown."""
        assert table.providers, f"{table.table} is empty"
        for name, package in table.providers.items():
            assert name, f"{table.table} has an empty name"
            assert package, f"{table.table}[{name!r}] has an empty package"

    def test_a_core_name_is_registered_by_core(self, table: ProviderTable) -> None:
        """The core set is a subset core itself supplies — which is what makes
        "no install hint" true rather than merely convenient. A name moved into
        it by mistake would otherwise silently lose the hint that names its
        package."""
        for name in table.core_names:
            assert table.providers.get(name) == "functualize", (
                f"{table.table}[{name!r}] is core-registered but says "
                f"{table.providers.get(name)!r}"
            )

    def test_a_core_name_gets_no_install_hint(self, table: ProviderTable) -> None:
        for name in table.core_names:
            assert table.hint_for(name) == ""

    def test_a_plugin_name_names_its_package(self, table: ProviderTable) -> None:
        """Every non-core name, not a hand-picked two: a table that gained a
        name without gaining a hint is the failure the hint exists to prevent."""
        for name, package in table.providers.items():
            if name in table.core_names:
                continue
            assert table.hint_for(name) == f"install {package} to register it"

    def test_an_unknown_name_gets_no_hint(self, table: ProviderTable) -> None:
        assert table.hint_for("nope") == ""

    def test_core_names_the_plugins_without_importing_them(
        self, table: ProviderTable
    ) -> None:
        """Naming a package in a diagnostic is not a dependency. Importing one
        would invert the graph, since every plugin here depends on core.

        The pattern is derived from the table rather than written out, so a
        third table naming a third package is checked for free. The return code
        is asserted because grep exiting non-zero-for-an-error would otherwise
        look exactly like grep finding nothing.
        """
        packages = table.plugin_packages
        assert packages, (
            f"{table.table} names no package other than core's, so this check "
            "has nothing to prove"
        )
        modules = "|".join(p.replace("-", "_") for p in packages)
        # `(from|import) <module>` rather than the `import functualize_(ai|mcp)`
        # this check was written as: that spelling misses `from functualize_ai
        # import x` entirely, because the literal `import ` never precedes the
        # module name there. Verified by sabotage — see the report.
        pattern = rf"(^|[[:space:]])(from|import)[[:space:]]+({modules})"

        result = subprocess.run(
            ["grep", "-rn", "-E", pattern, "src/"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode in {0, 1}, (
            f"grep failed ({result.returncode}) for {table.table}: {result.stderr}"
        )
        assert result.stdout == "", (
            f"{table.table} names {packages}, which core imports:\n{result.stdout}"
        )


def _table(name: str) -> ProviderTable:
    return next(table for table in _TABLES if table.table == name)


def test_the_gate_table_covers_every_strategy_a_gate_may_declare() -> None:
    """The table must not go stale against the validator: a name a `Gate`
    accepts but the table omits produces a blocked walk with no hint, which is
    the failure that table exists to prevent.

    Not parametrized, because no executor table has an equivalent to drift
    from — `AgentStep.executor` is a free-form name checked against the
    registry, not against the table (`_engine/agent_providers.py` says so).
    """
    from functualize._types.workflow import _VALID_GATE_STRATEGIES

    assert set(_table("STRATEGY_PROVIDERS").providers) == set(_VALID_GATE_STRATEGIES)


def test_the_gate_table_names_the_plugin_that_registers_each_strategy() -> None:
    """The pairing is an absolute fact, not "whatever the table says": the
    parametrized format check above derives its expectation from the table, so
    on its own it would pass with the two plugins swapped. These two names are
    documented (`docs/guides/ai.md`), so the swap has to fail somewhere.
    """
    table = _table("STRATEGY_PROVIDERS")

    assert table.hint_for("ai_inbound") == "install functualize-ai to register it"
    assert table.hint_for("ai_outbound") == "install functualize-mcp to register it"


def test_the_executor_table_names_the_plugin_that_registers_each_executor() -> None:
    """Same shape, for the table this file was added for."""
    table = _table("EXECUTOR_PROVIDERS")

    assert table.hint_for("ai") == "install functualize-ai to register it"
    assert table.hint_for("mcp-elicitation") == "install functualize-mcp to register it"


class TestTheCoreSetIsTiedToSomething:
    """`CORE_*` is checked by iterating it — so an empty one checks nothing.

    Every parametrized `CORE_*` case in this file is a `for name in
    table.core_names` loop, and the one check that runs per *provider*
    (`test_a_plugin_name_names_its_package`) derives its expectation from the
    hint function itself. So the single edit the mechanism exists to catch —
    emptying the set — passed all four, and `missing_executor_hint("cli-prompt")`
    started answering `"install functualize to register it"`: the operator told
    to install core itself, suite green.

    A vacuous check is the branch's signature defect, and this is that defect
    inside the file written to prevent it. Two assertions close it: the set is
    non-empty, and its contents come from somewhere rather than being a literal
    that agrees with three other literals by luck.
    """

    @pytest.mark.parametrize("table", _TABLES, ids=_TABLE_IDS)
    def test_the_core_set_is_not_empty(self, table: ProviderTable) -> None:
        """The edit that used to pass everything."""
        assert table.core_names, (
            f"{table.core} is empty, which makes every `for name in core_names` "
            "check in this file vacuous — including the ones above."
        )

    @pytest.mark.parametrize("table", _TABLES, ids=_TABLE_IDS)
    def test_every_core_name_is_in_the_table(self, table: ProviderTable) -> None:
        """The two are separate declarations and neither validates the other."""
        assert table.core_names <= set(table.providers), (
            f"{table.core} names something {table.table} does not: "
            f"{sorted(table.core_names - set(table.providers))}"
        )

    def test_the_executor_core_set_is_the_class_that_supplies_it(self) -> None:
        """`CORE_EXECUTORS` ← `CliPromptExecutor.name`, asserted rather than
        imported: `agent_providers` cannot import `agent_step`, because
        `agent_step` imports `missing_executor_hint` from it.

        `_gate/_strategy.py` has no analogue to check — `CORE_STRATEGIES` is
        *built* from `GateStrategy.*.value`, the same members boot passes to
        `register_strategy`, so its coupling is in the code rather than here.
        This table was copied from that one and lost exactly that property.
        """
        from functualize._engine.agent_providers import (
            CORE_EXECUTORS,
            EXECUTOR_PROVIDERS,
        )
        from functualize._engine.agent_step import CliPromptExecutor

        assert {CliPromptExecutor.name} == CORE_EXECUTORS
        assert EXECUTOR_PROVIDERS[CliPromptExecutor.name] == "functualize"

    def test_renaming_the_executor_would_be_caught(self) -> None:
        """States what the test above is *for*, so it is not read as trivia.

        Three literals spell this name — the class attribute, the table key,
        and the core set. Rename the class and the other two drift silently:
        the registry would hold the new name, `AgentStep(executor=...)` naming
        it would resolve, and the hint table would answer about a name nothing
        registers any more.
        """
        from functualize._engine.agent_providers import missing_executor_hint
        from functualize._engine.agent_step import CliPromptExecutor

        assert missing_executor_hint(CliPromptExecutor.name) == ""
        assert missing_executor_hint(CliPromptExecutor.name + "-renamed") == ""
