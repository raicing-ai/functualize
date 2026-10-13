"""The ``bwpm://`` grammar, parsed in isolation — no subprocess, no session.

Every refusal here is decided before any ``bw`` invocation could spawn; the
provider tests pin that property by asserting an empty invocation log after
a grammar error.
"""

from __future__ import annotations

import pytest
from functualize_secrets_bitwarden import (
    CUSTOM_FIELD_PREFIX,
    PM_FIELDS,
    InvalidReferenceError,
    PmReference,
    parse_pm_reference,
)

from tests.conftest import ITEM_ID

UUID = ITEM_ID


class TestTheTwoSegmentShape:
    def test_a_uuid_item_is_told_from_a_name(self) -> None:
        by_id = parse_pm_reference(f"{UUID}/password")
        assert by_id.item_id == UUID
        assert by_id.item_name is None
        assert by_id.field == "password"

        by_name = parse_pm_reference("deploy-token/password")
        assert by_name.item_name == "deploy-token"
        assert by_name.item_id is None

    def test_the_split_is_on_the_first_slash(self) -> None:
        """A `field:` name may itself hold a slash; the item side may not."""
        ref = parse_pm_reference(f"{UUID}/field:ops/api-key")
        assert ref.custom_field == "ops/api-key"

    def test_a_field_is_never_defaulted(self) -> None:
        with pytest.raises(InvalidReferenceError, match="never defaulted"):
            parse_pm_reference("deploy-token")

    def test_an_empty_item_is_refused(self) -> None:
        with pytest.raises(InvalidReferenceError, match="No item"):
            parse_pm_reference("/password")

    def test_an_empty_field_is_refused(self) -> None:
        with pytest.raises(InvalidReferenceError, match="No field"):
            parse_pm_reference("deploy-token/")

    def test_an_empty_reference_is_refused(self) -> None:
        with pytest.raises(InvalidReferenceError, match="No item"):
            parse_pm_reference("")


class TestTheFieldSlot:
    def test_every_builtin_field_is_honoured(self) -> None:
        for field in PM_FIELDS:
            ref = parse_pm_reference(f"deploy-token/{field}")
            assert ref.field == field
            assert ref.custom_field is None

    def test_an_unknown_field_is_an_error_not_a_noop(self) -> None:
        """The AWS plugin's rule: `?profile=prod` must not resolve quietly."""
        with pytest.raises(InvalidReferenceError, match="Unknown field 'api-key'"):
            parse_pm_reference("deploy-token/api-key")

    def test_an_unknown_field_suggests_the_field_prefix(self) -> None:
        with pytest.raises(
            InvalidReferenceError, match=f"{CUSTOM_FIELD_PREFIX}api-key"
        ):
            parse_pm_reference("deploy-token/api-key")

    def test_a_builtin_looking_custom_name_is_addressed_with_the_prefix(
        self,
    ) -> None:
        """`field:password` is a custom field *named* password — parse keeps
        the two apart, and extraction decides what exists."""
        ref = parse_pm_reference("deploy-token/field:password")
        assert ref.custom_field == "password"
        assert ref.field is None

    def test_an_empty_field_prefix_name_is_refused(self) -> None:
        with pytest.raises(InvalidReferenceError, match="no name"):
            parse_pm_reference("deploy-token/field:")

    def test_a_uuid_cannot_be_a_field(self) -> None:
        """A uuid-shaped second segment is not one of the five slots; it
        fails as an unknown field rather than being mistaken for an id."""
        with pytest.raises(InvalidReferenceError, match="Unknown field"):
            parse_pm_reference(f"deploy-token/{UUID}")


class TestTheQueryRefusal:
    def test_any_query_is_refused(self) -> None:
        with pytest.raises(InvalidReferenceError, match="takes no query"):
            parse_pm_reference("deploy-token/password?profile=prod")

    def test_a_bare_question_mark_is_refused(self) -> None:
        with pytest.raises(InvalidReferenceError, match="takes no query"):
            parse_pm_reference("deploy-token/password?")


class TestTheLabel:
    def test_the_label_names_parts_never_values(self) -> None:
        ref = parse_pm_reference("deploy-token/field:api-key")
        assert ref.label == "deploy-token/field:api-key"
        by_id = parse_pm_reference(f"{UUID}/totp")
        assert by_id.label == f"{UUID}/totp"


class TestNothingLeaksIntoErrors:
    @pytest.mark.parametrize(
        ("reference", "marker"),
        [
            ("deploy-token", "deploy-token"),
            ("deploy-token/", "'deploy-token/'"),
            ("deploy-token/bogus", "'deploy-token/bogus'"),
        ],
    )
    def test_errors_echo_the_reference_for_debugging(
        self, reference: str, marker: str
    ) -> None:
        """The reference is config-file text, not a value — quoting it in the
        error is what makes a typo debuggable."""
        with pytest.raises(InvalidReferenceError) as exc:
            parse_pm_reference(reference)
        assert marker in str(exc.value)


class TestTheDataclass:
    def test_it_is_frozen(self) -> None:
        ref = parse_pm_reference("deploy-token/password")
        with pytest.raises(AttributeError):
            ref.field = "username"  # type: ignore[misc]

    def test_the_parsed_contract_is_frozen_and_typed(self) -> None:
        assert PmReference.__dataclass_params__.frozen is True
