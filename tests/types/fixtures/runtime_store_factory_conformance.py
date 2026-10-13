"""A minimal factory and the built-in one satisfy `RuntimeStoreFactory` under mypy.

Not a test module. `tests/types/test_runtime_store_port.py` runs mypy over this
file and requires **zero** errors: `isinstance` sees only member presence, and
this is the half that checks `prepare` and `unselected_data` signature for
signature. Never executed.
"""
# ruff: noqa: E301, E302, E305, E704, ARG001, ARG002, D101, D102, D103, TC001, TC003

from __future__ import annotations

from pathlib import Path

from functualize._app.store_selection import DocumentRuntimeStoreFactory
from functualize._primitives.document_store import DOCUMENT_PROFILE
from functualize._types.persistence import (
    PreparedStore,
    RuntimeStoreConfig,
    RuntimeStoreFactory,
    StoreProfile,
)


class MinimalFactory:
    scheme: str = "minimal"
    profile: StoreProfile = DOCUMENT_PROFILE

    def prepare(self, config: RuntimeStoreConfig) -> PreparedStore:
        raise NotImplementedError

    def unselected_data(self, project_root: Path) -> str | None:
        return None


def takes_a_factory(factory: RuntimeStoreFactory) -> None: ...


def hand_it_both(minimal: MinimalFactory, builtin: DocumentRuntimeStoreFactory) -> None:
    takes_a_factory(minimal)
    takes_a_factory(builtin)
