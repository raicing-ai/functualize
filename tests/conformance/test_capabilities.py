"""Capability tiers over the shipped stores (AC-1, AC-2 second half).

The tiers a store runs are read from its profile, never from a list: the
stub-profile test declares a capability on a store that does not have it and
watches the tier run — and fail.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from functualize.testing.conformance.capabilities import (
    CAPABILITY_TIERS,
    run_capability_tiers,
    tiers_for,
)
from tests.conformance.test_baseline import documents_store, sqlite_store

if TYPE_CHECKING:
    from functualize.plugin import RuntimeStore

TIERS = {tier.name: tier for tier in CAPABILITY_TIERS}
OBSERVABLE = ("cross_aggregate_atomicity=True", "fencing='cross-process'")


@pytest.mark.parametrize("tier", OBSERVABLE)
def test_sqlite_passes_each_observable_tier(tier: str, tmp_path: Path) -> None:
    TIERS[tier].check(sqlite_store, tmp_path)


def test_sqlite_declares_all_four_tiers() -> None:
    profile = sqlite_store.__globals__["sqlite"].SQLITE_PROFILE
    assert [t.name for t in tiers_for(profile)] == list(TIERS)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "TRANSITIONAL(sqlite-runtime-provider task 13): durable_outbox and "
        "versioned_migrations need a harness hook on run_capability_tiers, "
        "pending a decision on the public signature"
    ),
)
def test_sqlite_passes_every_tier_it_declares(tmp_path: Path) -> None:
    run_capability_tiers(sqlite_store, tmp_path)


def test_the_document_store_runs_what_its_profile_declares(tmp_path: Path) -> None:
    """It declares ``fencing="cross-process"``, so it runs — and passes — that
    tier; it declares none of the other three, so it runs none of them."""
    assert run_capability_tiers(documents_store, tmp_path) == (
        "fencing='cross-process'",
    )


def test_the_tiers_are_chosen_by_the_profile_not_a_list(tmp_path: Path) -> None:
    """Declare atomicity on the document store and the tier runs for it.

    It also *passes* there, which is worth knowing: at the port a fault can
    only land between commands, and the document store buffers until exit
    too, so this tier cannot tell an atomic commit from two documents written
    in turn. A fault between the *statements* of a commit needs a hook into
    the store's write path — the same open question as the two tiers that
    refuse below.
    """

    def overclaiming(root: Path) -> RuntimeStore:
        store = documents_store(root)
        store.profile = replace(store.profile, cross_aggregate_atomicity=True)  # type: ignore[misc]
        return store

    ran = run_capability_tiers(overclaiming, tmp_path)

    assert ran == ("cross_aggregate_atomicity=True", "fencing='cross-process'")
