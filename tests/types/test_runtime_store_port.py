"""`RuntimeStore` describes the store `_app` hands the engine — T11.

Three claims, and the first two are separate on purpose.

**Runtime.** `isinstance(store, RuntimeStore)` is True. That proves the six
names exist and nothing more: a `@runtime_checkable` Protocol's `isinstance`
ignores signatures entirely, so a store whose `transaction` returned an
unrelated object would still pass it.

**Static.** mypy accepts handing a real `DocumentRuntimeStore` to a
`RuntimeStore` parameter — the check that compares signature to signature. It is
deliberately the *implementation* that is handed over, per this wave's
annotation ruling: `_types/persistence.py` is the settled port and a store
conforms to it, never the other way round. `tests/types/test_plugin_host_port.py`
is the same pair for `PluginHost` and states the split; T11's mypy failure —
`boot.py:248` returning `DocumentRuntimeStore` where `RuntimeStore` was
declared — is what this file keeps from coming back.

**Shape.** The port's six members, and `RuntimeTransaction`'s five, are pinned
to `contracts.md` §1.5's table. A port grows by someone adding a member, and
every member there is argued from a measured client — so growth should be a line
in this file a reviewer sees, not a quiet widening. Both layers are pinned
together because the store satisfies the port *through* the transaction: the
readers are the store's own attributes, the five writers belong to the object
`transaction()` yields.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from functualize._primitives.document_store import DocumentRuntimeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._types.errors import (
    GateResolutionError,
    InputRequestNotOpenError,
)
from functualize._types.persistence import (
    InputReader,
    InputWriter,
    RuntimeStore,
    RuntimeTransaction,
)

FIXTURE = Path(__file__).parent / "fixtures" / "runtime_store_conformance.py"

#: The six members of `contracts.md` §1.5, in that table's order.
PORT_MEMBERS = {"profile", "runs", "workflows", "inputs", "transaction", "close"}

#: The transaction's five, from the same row: what `transaction()` yields.
TRANSACTION_MEMBERS = {"runs", "workflows", "inputs", "events", "effects"}

#: The inputs aggregate's two writers: a candidate arrives evaluated, and
#: consumption is a separate command rather than an argument of a deposit.
INPUT_WRITER_MEMBERS = {"append", "consume"}

#: The inputs reader's four questions. `request` and `candidates_for` are the
#: resolution read — asking by request id, which is the whole point of the id.
INPUT_READER_MEMBERS = {"open_for", "awaiting", "request", "candidates_for"}


def _members(protocol: type[Any]) -> set[str]:
    """A Protocol's declared members, across the Pythons this project supports.

    `__protocol_attrs__` is 3.12+; `typing._get_protocol_attrs` is the 3.11
    spelling. `requires-python = ">=3.11"`, so both have to work -- and reading
    `__annotations__` instead would miss every method and property, which is
    all of them.
    """
    attrs = getattr(protocol, "__protocol_attrs__", None)
    if attrs is not None:
        return set(attrs)
    from typing import _get_protocol_attrs  # type: ignore[attr-defined]

    return set(_get_protocol_attrs(protocol))


class TestTheSelectedStoreSatisfiesThePort:
    def test_at_runtime(self, tmp_path: Path) -> None:
        """Member presence -- and only that. See this file's docstring."""
        assert isinstance(
            DocumentRuntimeStore(JsonFileSubstrate(tmp_path)), RuntimeStore
        )

    def test_under_mypy(self) -> None:
        """Signatures. The half `isinstance` is blind to.

        The port's six members against the store's — not the transaction's
        five, which sit one import deeper: mypy errors on the files it is asked
        to check, not on those it follows, so the writer annotations are held
        by `uv run mypy src/` instead. The fixture's docstring carries the
        measurement.

        Warm `.mypy_cache` makes this about a second; cold it is ~15 s, and it
        is still not marked slow, because a gate that skips reads as a pass.
        """
        api = pytest.importorskip("mypy.api", reason="mypy is a dev dependency")
        out, _err, _code = api.run(["--strict", str(FIXTURE)])
        errors = [
            line for line in out.splitlines() if re.match(r"^.*?:\d+: error:", line)
        ]
        assert not errors, (
            "DocumentRuntimeStore no longer satisfies RuntimeStore, signature for "
            "signature:\n" + "\n".join(errors)
        )


class TestThePortsShapeIsPinned:
    def test_the_port_has_exactly_its_six_members(self) -> None:
        assert _members(RuntimeStore) == PORT_MEMBERS

    def test_the_transaction_has_exactly_its_five_writers(self) -> None:
        assert _members(RuntimeTransaction) == TRANSACTION_MEMBERS

    def test_the_input_writer_appends_candidates_and_consumes(self) -> None:
        assert _members(InputWriter) == INPUT_WRITER_MEMBERS

    def test_the_input_reader_answers_by_request_id(self) -> None:
        assert _members(InputReader) == INPUT_READER_MEMBERS


class TestTheRefusalCarriesItsFacts:
    """The two error amendments: a refusal that names its state, and a
    resolution failure that carries its evaluations without changing a word
    of the message operators already diagnose gates by."""

    def test_a_closed_request_names_itself_and_its_status(self) -> None:
        error = InputRequestNotOpenError("req_1", "accepted")
        assert error.request_id == "req_1"
        assert error.status == "accepted"
        assert "not open" in str(error)

    def test_evaluations_ride_along_without_touching_the_message(self) -> None:
        from functualize._types.gate_resolution import (
            CandidateEvaluation,
            EvaluationOutcome,
        )

        evaluation = CandidateEvaluation(EvaluationOutcome.FAILED, detail="no tty")
        baseline = GateResolutionError("approve", 3, "no strategies attempted")
        carrying = GateResolutionError(
            "approve", 3, "no strategies attempted", evaluations=(evaluation,)
        )
        assert str(carrying) == str(baseline)
        assert carrying.evaluations == (evaluation,)
        assert baseline.evaluations == ()
