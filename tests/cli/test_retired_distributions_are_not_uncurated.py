"""A name this project published and renamed is not "not vetted by this project".

`plugin available --remote` enumerates every `functualize-*` project on the PyPI
Simple index. Anything outside the curated catalog renders as `kind="unknown"`,
under the heading:

    UNCURATED — found on PyPI, not vetted by this project

`plugin-taxonomy` renames `functualize-state-sqlite` to
`functualize-substrate-sqlite` and abandons the old name at 0.2.3 — it stays on
the index forever. So the command would file this project's own former release
under a heading saying nobody here vetted it, which is false.

Renames land one per pull request (`contracts.md` §1.1), so this recurs: PR-2
retires `functualize-aws` and PR-3 `functualize-bitwarden`. The suppression is a
list in the manifest rather than three edits to a function.
"""

from __future__ import annotations

from functualize._cli.plugin_cmd import (
    CatalogEntry,
    ExtensionEntry,
    available_rows,
    load_retired,
)

_CURATED = CatalogEntry(
    name="substrate-sqlite",
    distribution="functualize-substrate-sqlite",
    group="functualize.plugins",
    description="Keeps this project's documents in SQLite",
    recommended=True,
)


def test_the_shipped_manifest_retires_the_renamed_distribution() -> None:
    """The list is read from the manifest, not hard-coded in the function."""
    assert "functualize-state-sqlite" in load_retired()


def test_a_retired_name_on_pypi_is_not_listed() -> None:
    rows = available_rows(
        [_CURATED],
        [],
        remote=["functualize-substrate-sqlite", "functualize-state-sqlite"],
        retired=["functualize-state-sqlite"],
    )
    assert [r.distribution for r in rows] == ["functualize-substrate-sqlite"]


def test_without_the_list_it_would_be_listed_as_uncurated() -> None:
    """The defect, pinned — so the suppression cannot be deleted silently."""
    rows = available_rows(
        [_CURATED],
        [],
        remote=["functualize-substrate-sqlite", "functualize-state-sqlite"],
    )
    stale = [r for r in rows if r.distribution == "functualize-state-sqlite"]
    assert len(stale) == 1
    assert stale[0].kind == "unknown"


def test_an_unrelated_third_party_plugin_is_still_listed() -> None:
    """Suppression is by name, not a blanket filter on the remote half."""
    rows = available_rows(
        [_CURATED],
        [],
        remote=["functualize-state-sqlite", "functualize-somebody-elses"],
        retired=["functualize-state-sqlite"],
    )
    assert "functualize-somebody-elses" in [r.distribution for r in rows]


def test_an_installed_retired_distribution_is_still_reported() -> None:
    """What is on the machine is a fact; hiding it would be the worse lie."""
    rows = available_rows(
        [_CURATED],
        [
            ExtensionEntry(
                registered_name="sqlite",
                distribution="functualize-state-sqlite",
                group="functualize.state_providers",
            )
        ],
        remote=["functualize-state-sqlite"],
        retired=["functualize-state-sqlite"],
    )
    installed = [r for r in rows if r.distribution == "functualize-state-sqlite"]
    assert len(installed) == 1
    assert installed[0].installed is True
