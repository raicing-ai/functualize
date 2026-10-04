"""The public door for an unknown gate reference (gate-name-resolution T1).

`GateNotFoundError` is what an addressed lookup raises when the gate reference
matches none of the scope's gates. The Python caller cannot ignore it, and the
CLI and MCP surfaces translate it in later tasks of the same feature — this
file pins the type's own contract: what it carries and how it reads.
"""

from __future__ import annotations

import pytest

from functualize.app.utils import GateNotFoundError


class TestAttributes:
    def test_attributes_round_trip(self) -> None:
        exc = GateNotFoundError("nope", scope_id="rel-1", known=["approve-refund"])

        assert exc.gate == "nope"
        assert exc.scope_id == "rel-1"
        assert exc.known == ("approve-refund",)

    def test_known_is_sorted_and_a_tuple(self) -> None:
        exc = GateNotFoundError(
            "nope", scope_id="rel-1", known=["deploy-env", "approve-refund", "build"]
        )

        assert exc.known == ("approve-refund", "build", "deploy-env")
        assert isinstance(exc.known, tuple)


class TestMessage:
    def test_message_names_scope_reference_and_every_known_gate(self) -> None:
        exc = GateNotFoundError(
            "approveRefund", scope_id="rel-1", known=["deploy-env", "approve-refund"]
        )

        text = str(exc)

        assert "rel-1" in text
        assert "approveRefund" in text
        assert "approve-refund" in text
        assert "deploy-env" in text

    def test_empty_known_renders_none(self) -> None:
        exc = GateNotFoundError("nope", scope_id="rel-1", known=[])

        assert "Gates: none." in str(exc)

    def test_message_names_the_listing_command(self) -> None:
        exc = GateNotFoundError("nope", scope_id="rel-1", known=["approve-refund"])

        assert "func builtin workflow list" in str(exc)


class TestPublicDoor:
    def test_importable_from_app_utils(self) -> None:
        import functualize.app.utils as utils

        assert "GateNotFoundError" in utils.__all__

    def test_is_an_exception(self) -> None:
        with pytest.raises(GateNotFoundError):
            raise GateNotFoundError("nope", scope_id="rel-1", known=["approve-refund"])
