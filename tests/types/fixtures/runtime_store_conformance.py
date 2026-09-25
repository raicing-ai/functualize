"""`DocumentRuntimeStore` satisfies `RuntimeStore`, checked by mypy — T11.

Not a test module. `tests/types/test_runtime_store_port.py` runs mypy over this
file and requires **zero** errors. The file's whole content is one assignment
that only type-checks if every one of the port's six members matches the
store's, signature for signature.

This is the half `isinstance` cannot do. A `@runtime_checkable` Protocol's
`isinstance` checks *attribute presence* and nothing else: a store whose
`transaction` returned an unrelated object would still pass it. The port would
then be a claim about the one store boot is handed that the store does not
honour.

The transaction's five writers are **not** reached from here, which is worth
knowing before trusting this file: mypy reports errors in the modules it is
asked to check, not in those it merely follows, so a member of
`_DocumentTransaction` can drift and leave this run green — measured, not
assumed. An `EventWriter.append` given an extra required argument fails
`uv run mypy src/` at `document_store.py`'s writer assignment and this
invocation still says "Success". `mypy src/` is therefore where T11's
annotation is enforced, because there the store is a *source*: both the writer
assignments and `transaction()`'s declared `Iterator[RuntimeTransaction]` yield
are visible to it. This file is the store-to-port assignment alone.

The store arrives as a parameter rather than being constructed here, because
unlike `FunctualizeApp(name="probe")` a `DocumentRuntimeStore` needs a
`StoreSubstrate`, and that argument is `app.fresh_root` — a running app's. This
file is never executed; the runtime half of the pair builds a real instance on
`tmp_path` instead.
"""
# ruff: noqa: E301, E302, E305, E704, ARG001, D103, TC001

from __future__ import annotations

from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._types.persistence import RuntimeStore


def takes_the_port(store: RuntimeStore) -> None: ...


def hand_it_the_selected_store(store: DocumentRuntimeStore) -> None:
    takes_the_port(store)
