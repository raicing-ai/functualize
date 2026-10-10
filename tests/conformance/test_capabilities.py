"""Capability tiers over the shipped stores (AC-1, AC-2 second half).

The tiers a store runs are read from its profile, never from a list: the
stub-profile test declares a capability on a store that does not have it and
watches the tier run — and, without the hook that capability needs, refuse.

SQLite runs with its three harness hooks (`sqlite_hooks.py`); the document
store runs with none, because every tier it declares is port-observable.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from functualize.testing.conformance import (
    HarnessHooks,
    capability_report,
    run_capability_tiers,
)
from functualize.testing.conformance.capabilities import (
    CAPABILITY_TIERS,
    tiers_for,
)
from tests.conformance.sqlite_hooks import (
    SqliteMigrationHarness,
    SqliteOutboxProbe,
    SqliteStatementFaults,
)
from tests.conformance.test_baseline import documents_store, sqlite_store

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStore

TIERS = {tier.name: tier for tier in CAPABILITY_TIERS}
SQLITE_HOOKS = HarnessHooks(
    statement_faults=SqliteStatementFaults(),
    outbox=SqliteOutboxProbe(),
    migrations=SqliteMigrationHarness(),
)
SQLITE_TIERS = (
    "cross_aggregate_atomicity=True",
    "fencing='cross-process'",
    "durable_outbox=True",
    "versioned_migrations=True",
    "offline_capable=True",
)


@pytest.mark.parametrize("tier", SQLITE_TIERS)
def test_sqlite_passes_each_declared_tier(tier: str, tmp_path: Path) -> None:
    TIERS[tier].check(sqlite_store, tmp_path, SQLITE_HOOKS)


def test_sqlite_passes_every_tier_it_declares(tmp_path: Path) -> None:
    assert (
        run_capability_tiers(sqlite_store, tmp_path, hooks=SQLITE_HOOKS) == SQLITE_TIERS
    )


def test_the_report_states_the_strength_of_each_run(tmp_path: Path) -> None:
    report = capability_report(sqlite_store, tmp_path, hooks=SQLITE_HOOKS)
    strengths = {run.name: run.strength for run in report.runs}

    atomicity = strengths["cross_aggregate_atomicity=True"]
    assert (
        atomicity.startswith("statement faults at ")
        and "+ command faults at 4" in atomicity
    ), atomicity
    assert atomicity.endswith(
        "; observed through the ports — a split whose leading batch writes no "
        "port-visible row is not seen"
    ), atomicity
    assert (
        strengths["fencing='cross-process'"]
        == "stale write from a second OS process landed nothing"
    )
    assert (
        strengths["durable_outbox=True"]
        == "crash before commit, crash after commit, raised unit"
    )
    assert strengths["versioned_migrations=True"] == "2 historical, 3 refusals"
    assert strengths["offline_capable=True"] == "baseline round trip, network refused"


def test_the_document_store_runs_what_its_profile_declares(tmp_path: Path) -> None:
    """It declares ``fencing="cross-process"`` and ``offline_capable=True``,
    so it runs — and passes — exactly those two, with no hooks at all."""
    assert run_capability_tiers(documents_store, tmp_path) == (
        "fencing='cross-process'",
        "offline_capable=True",
    )


def test_a_tier_needing_no_hook_ignores_the_hooks_argument(tmp_path: Path) -> None:
    """H-1: with no hooks, hook-free tiers behave exactly as before."""
    assert capability_report(documents_store, tmp_path).names == (
        "fencing='cross-process'",
        "offline_capable=True",
    )


def test_an_overclaiming_store_without_the_hook_fails_that_tier(
    tmp_path: Path,
) -> None:
    """H-2, the overclaiming direction: declare atomicity on the document
    store and the tier runs for it — and fails, because the port cannot
    observe a fault between the statements of one commit and no hook was
    handed over. A skip would let the overclaim stand."""
    from functualize.testing.conformance.hooks import CapabilityReport  # noqa: F401

    def overclaiming(root: Path) -> RuntimeStore:
        store = documents_store(root)
        store.profile = replace(store.profile, cross_aggregate_atomicity=True)  # type: ignore[misc]
        return store

    with pytest.raises(AssertionError, match="statement_faults"):
        run_capability_tiers(overclaiming, tmp_path)


def test_sqlite_without_its_hooks_refuses_rather_than_skips(tmp_path: Path) -> None:
    """H-2, the honest-declaration direction: SQLite declares four
    hook-needing tiers, so with ``hooks=None`` the first of them refuses
    naming the missing instrument — nothing runs as if it had passed."""
    with pytest.raises(AssertionError, match="HarnessHooks.statement_faults"):
        run_capability_tiers(sqlite_store, tmp_path, hooks=None)


def test_every_hook_needing_tier_names_its_missing_attribute(tmp_path: Path) -> None:
    """Each of the three hook-needing fields refuses with its own attribute
    named, so a backend author knows exactly which instrument to write. Each
    field is declared alone on the document store, so the tier it switches on
    is the first hook-needing one the report reaches."""
    for field, attribute in (
        ("cross_aggregate_atomicity", "statement_faults"),
        ("durable_outbox", "outbox"),
        ("versioned_migrations", "migrations"),
    ):

        def declaring(root: Path, field: str = field) -> RuntimeStore:
            store = documents_store(root)
            store.profile = replace(store.profile, **{field: True})  # type: ignore[misc]
            return store

        with pytest.raises(AssertionError, match=attribute):
            run_capability_tiers(declaring, tmp_path / attribute, hooks=None)


def test_sqlite_declares_all_five_tiers() -> None:
    profile = sqlite_store.__globals__["sqlite"].SQLITE_PROFILE
    assert [tier.name for tier in tiers_for(profile)] == list(SQLITE_TIERS)
