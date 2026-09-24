"""The instrument, checked before anything is measured with it.

Every later wave reports through `harness.py`, so a harness that quietly
accepts a cell nobody measured would put exactly the kind of unearned claim
into the matrix that this ticket exists to remove. These tests are that
claim's falsifier.

Task 1.3 lists `harness.py` as its only file; this module is a declared
deviation, for the same reason `test_gating.py` is — the task's gate is
`uv run pytest -q tests/substrate_probe/` green, and a directory whose only
runnable content is a credential-gated measurement exits 5, not 0.
"""

from __future__ import annotations

import pytest

from tests.substrate_probe.harness import (
    EVIDENCE_LEVELS,
    FIELDS,
    QUESTIONS,
    Answer,
    cell,
    downgrade,
    measured,
    not_measured,
    reading,
)


class TestTheTenQuestions:
    def test_the_ten_storeprofile_fields_are_enumerated_here(self) -> None:
        """Transcribed from the design's twelve attributes, two labels — shipped as
        `StoreProfile` in `src/functualize/_types/persistence.py` (ADR-028).
        """
        assert FIELDS == (
            "cross_aggregate_atomicity",
            "fencing",
            "multi_process",
            "multi_machine",
            "durable_outbox",
            "versioned_migrations",
            "interactive_transaction",
            "remote",
            "max_document_bytes",
            "offline_capable",
        )
        assert len(QUESTIONS) == 10
        assert "name" not in FIELDS and "description" not in FIELDS

    def test_every_question_carries_a_question_and_its_observation(self) -> None:
        """`answered_by` is what makes "measured" checkable by a reader."""
        for question in QUESTIONS:
            assert question.asks.endswith("?"), question.field
            assert len(question.answered_by) > 20, question.field

    def test_the_four_evidence_levels_are_the_acceptance_criterion_verbatim(
        self,
    ) -> None:
        assert EVIDENCE_LEVELS == (
            "measured (real service)",
            "measured (emulator)",
            "measured (fake)",
            "NOT MEASURED",
        )

    def test_a_vendor_doc_is_not_an_evidence_level(self) -> None:
        """AC6: traceable to a probe result, never to a vendor doc."""
        assert not [level for level in EVIDENCE_LEVELS if "doc" in level]


class TestABackendAnswersASubsetWithoutInheritingAnything:
    def test_the_unanswered_fields_come_back_not_measured(self) -> None:
        column = reading(
            "Cloudflare D1",
            [
                measured(
                    "interactive_transaction",
                    False,
                    evidence="measured (real service)",
                    detail="BEGIN was refused: D1 has no interactive transaction",
                ),
                measured(
                    "remote",
                    True,
                    evidence="measured (real service)",
                    detail="every call is an HTTPS round trip",
                ),
            ],
            why="NOT MEASURED (no credentials) — CLOUDFLARE_API_TOKEN not set",
        )

        assert len(column.answers) == 10
        assert tuple(a.field for a in column.answers) == FIELDS
        assert column["interactive_transaction"].value is False
        assert len(column.unmeasured) == 8
        assert all("no credentials" in a.detail for a in column.unmeasured), (
            "an unmeasured cell inherits the reason the backend gave"
        )

    def test_answering_nothing_is_a_full_column_of_not_measured(self) -> None:
        """Supabase is expected to land here, and must still occupy ten cells."""
        column = reading("Supabase Postgres", [], why="NOT MEASURED (no account)")
        assert len(column.answers) == 10
        assert len(column.unmeasured) == 10

    def test_a_backend_needs_no_base_class(self) -> None:
        """The design constraint, asserted rather than described.

        `.spec/CONSTITUTION.md` → *Forbidden Patterns*: no ABC, no shared base.
        A module that returns `Answer`s is a backend; there is nothing to
        subclass and nothing that could grow into an intersection contract.
        """
        assert Answer.__mro__ == (Answer, object)
        assert not hasattr(Answer, "__abstractmethods__")


class TestNeverInventACell:
    def test_an_unknown_field_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not a StoreProfile field"):
            measured(
                "eventual_consistency",
                True,
                evidence="measured (real service)",
                detail="x",
            )

    def test_a_measurement_cannot_be_stamped_not_measured(self) -> None:
        with pytest.raises(ValueError, match="use not_measured"):
            measured("remote", True, evidence="NOT MEASURED", detail="x")

    def test_a_measurement_without_its_observation_is_refused(self) -> None:
        with pytest.raises(ValueError, match="observation that produced it"):
            measured("remote", True, evidence="measured (real service)", detail="   ")

    def test_an_unmeasured_cell_without_a_reason_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must say why"):
            not_measured("remote", "")

    def test_one_field_cannot_be_answered_twice(self) -> None:
        answer = measured(
            "remote", True, evidence="measured (real service)", detail="round trip"
        )
        with pytest.raises(ValueError, match="answered twice"):
            reading("AWS S3", [answer, answer])

    def test_a_value_of_the_wrong_shape_is_refused(self) -> None:
        with pytest.raises(ValueError, match="is a bool"):
            measured("remote", "yes", evidence="measured (real service)", detail="x")
        with pytest.raises(ValueError, match="process-local"):
            measured("fencing", True, evidence="measured (real service)", detail="x")
        with pytest.raises(ValueError, match="positive byte count"):
            measured(
                "max_document_bytes",
                True,
                evidence="measured (real service)",
                detail="x",
            )

    def test_an_unbounded_document_size_is_none_not_zero(self) -> None:
        assert (
            measured(
                "max_document_bytes",
                None,
                evidence="measured (real service)",
                detail="1 GiB written and read back",
            ).value
            is None
        )
        with pytest.raises(ValueError, match="positive byte count"):
            measured(
                "max_document_bytes", 0, evidence="measured (real service)", detail="x"
            )


class TestTheCellCarriesItsEvidence:
    def test_a_measured_cell_renders_its_evidence_level(self) -> None:
        assert (
            cell(
                measured(
                    "remote",
                    False,
                    evidence="measured (real service)",
                    detail="no socket opened",
                )
            )
            == "no — measured (real service)"
        )
        assert cell(
            measured(
                "max_document_bytes",
                2_097_152,
                evidence="measured (emulator)",
                detail="refused at 2 MiB + 1",
            )
        ) == ("2097152 — measured (emulator)")

    def test_an_unmeasured_cell_renders_its_reason(self) -> None:
        rendered = cell(not_measured("fencing", "NOT MEASURED (no credentials)"))
        assert rendered == "NOT MEASURED (no credentials)"
        assert cell(not_measured("fencing", "the account was never created")) == (
            "NOT MEASURED — the account was never created"
        )

    def test_an_emulator_result_can_be_re_stamped_but_keeps_its_observation(
        self,
    ) -> None:
        """AC3: whatever floci answers may never back a shipped field."""
        from_floci = measured(
            "cross_aggregate_atomicity",
            True,
            evidence="measured (emulator)",
            detail="TransactWriteItems cancelled without writing its sibling",
        )
        restamped = downgrade(
            from_floci, "measured (emulator)", "floci 2.1.0, not real DynamoDB"
        )
        assert "TransactWriteItems" in restamped.detail
        assert "floci 2.1.0" in restamped.detail

    def test_an_unmeasured_cell_cannot_be_promoted(self) -> None:
        with pytest.raises(ValueError, match="nothing to re-stamp"):
            downgrade(
                not_measured("remote", "no credentials"), "measured (real service)", "x"
            )
