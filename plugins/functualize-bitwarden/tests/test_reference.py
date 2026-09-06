"""The `bws://` grammar (remote-source-activation/5.2).

Same governing rule as the AWS provider: an override the caller wrote must
either take effect or raise. Here that rule has a second edge — an override
that is spelled correctly but cannot apply is also refused, because a config
file full of load-bearing-looking no-ops is no better than one full of typos.
"""

from __future__ import annotations

import pytest
from functualize_bitwarden import (
    HONOURED_KEYS,
    InvalidReferenceError,
    parse_reference,
)

from tests.conftest import ORG, PROJECT_A, SECRET_ID


class TestTheTwoAddressingForms:
    def test_a_uuid_is_a_secret_id(self) -> None:
        ref = parse_reference(SECRET_ID)
        assert ref.secret_id == SECRET_ID
        assert ref.key is None

    def test_anything_else_is_a_key_name(self) -> None:
        ref = parse_reference("DB_PASSWORD")
        assert ref.key == "DB_PASSWORD"
        assert ref.secret_id is None

    @pytest.mark.parametrize(
        "almost",
        [
            "8a9c2f0e-1b3d-4c5e-9f70-2a1b3c4d5e6",  # one char short
            "8a9c2f0e1b3d4c5e9f702a1b3c4d5e6f",  # no hyphens
            "8a9c2f0e-1b3d-4c5e-9f70-2a1b3c4d5e6g",  # not hex
        ],
    )
    def test_a_near_uuid_is_treated_as_a_key(self, almost: str) -> None:
        """Guessing 'they meant a uuid' would search for a key that cannot
        exist; treating it as a key produces an error naming the key."""
        assert parse_reference(almost).key == almost

    def test_uuid_matching_is_case_insensitive(self) -> None:
        assert parse_reference(SECRET_ID.upper()).secret_id == SECRET_ID.upper()

    def test_an_empty_target_is_rejected(self) -> None:
        with pytest.raises(InvalidReferenceError, match="No secret id or key"):
            parse_reference("?project=" + PROJECT_A)

    def test_the_label_never_needs_a_value(self) -> None:
        assert parse_reference("DB_PASSWORD").label == "DB_PASSWORD"
        assert parse_reference(SECRET_ID).label == SECRET_ID


class TestEachHonouredKey:
    def test_project(self) -> None:
        assert parse_reference(f"K?project={PROJECT_A}").project == PROJECT_A

    def test_organization(self) -> None:
        assert parse_reference(f"K?organization={ORG}").organization == ORG

    def test_they_combine(self) -> None:
        ref = parse_reference(f"K?project={PROJECT_A}&organization={ORG}")
        assert (ref.project, ref.organization) == (PROJECT_A, ORG)

    def test_every_honoured_key_is_reachable(self) -> None:
        """Derived from HONOURED_KEYS, so adding one without wiring it fails."""
        sample = {"project": PROJECT_A, "organization": ORG}
        assert set(sample) == set(HONOURED_KEYS), "a key was added without a sample"
        for key, value in sample.items():
            assert getattr(parse_reference(f"K?{key}={value}"), key) == value


class TestAnUnknownKeyIsRejected:
    def test_a_typo_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="Unknown override 'porject'"):
            parse_reference(f"K?porject={PROJECT_A}")

    def test_the_error_suggests_the_intended_key(self) -> None:
        with pytest.raises(InvalidReferenceError, match="Did you mean 'project'"):
            parse_reference(f"K?porject={PROJECT_A}")

    def test_the_error_lists_what_is_honoured(self) -> None:
        with pytest.raises(InvalidReferenceError) as exc:
            parse_reference("K?nonsense=1")
        for key in HONOURED_KEYS:
            assert key in str(exc.value)


class TestAnInertOverrideIsAlsoRejected:
    """The edge this grammar adds over the AWS one.

    Both overrides exist to resolve a *name*. Paired with a uuid they consult
    nothing, so accepting them would leave a line in a config file that reads
    as though it constrains the lookup and does not.
    """

    def test_project_with_a_uuid_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="cannot apply"):
            parse_reference(f"{SECRET_ID}?project={PROJECT_A}")

    def test_organization_with_a_uuid_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="cannot apply"):
            parse_reference(f"{SECRET_ID}?organization={ORG}")

    def test_the_error_names_the_offending_keys(self) -> None:
        with pytest.raises(InvalidReferenceError) as exc:
            parse_reference(f"{SECRET_ID}?project={PROJECT_A}&organization={ORG}")
        assert "organization, project" in str(exc.value)

    def test_the_error_says_what_to_do_instead(self) -> None:
        with pytest.raises(InvalidReferenceError, match="by its key name"):
            parse_reference(f"{SECRET_ID}?project={PROJECT_A}")

    def test_a_uuid_with_no_overrides_is_fine(self) -> None:
        assert parse_reference(SECRET_ID).secret_id == SECRET_ID


class TestMalformedOverrides:
    def test_a_repeated_key_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="more than once"):
            parse_reference(f"K?project={PROJECT_A}&project={PROJECT_A}")

    def test_a_valueless_key_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="missing a '='"):
            parse_reference("K?project")

    def test_an_empty_value_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="empty value"):
            parse_reference("K?project=")

    def test_an_empty_entry_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="Empty entry"):
            parse_reference(f"K?project={PROJECT_A}&&organization={ORG}")


class TestUuidShapedOverridesMustBeUuids:
    """A project *name* here would search for a project id that cannot exist,
    and the resulting 'no such secret' would blame the wrong thing."""

    @pytest.mark.parametrize("key", ["project", "organization"])
    def test_a_name_is_rejected(self, key: str) -> None:
        with pytest.raises(InvalidReferenceError, match="must be a uuid"):
            parse_reference(f"K?{key}=my-project")

    def test_the_error_says_names_are_not_accepted(self) -> None:
        with pytest.raises(InvalidReferenceError, match="names.* are not accepted"):
            parse_reference("K?project=my-project")


class TestPercentEncoding:
    """Decoding applies to the override block, and *not* to the target.

    The asymmetry is deliberate and was settled by this test failing. Inside
    the override block, `&` and `=` are structural, so a value carrying them
    must be escapable. The target has exactly one structural character, `?`,
    and decoding it would corrupt a Bitwarden key that legitimately contains a
    literal `%5F` into one containing `_`. Passing the target through verbatim
    matches how core hands the reference over, and matches the AWS provider.

    The cost is stated rather than hidden: a key name containing `?` cannot be
    addressed by name. Address it by uuid.
    """

    def test_an_encoded_override_value_is_decoded(self) -> None:
        """Percent-encoded hyphens round-trip back to the real uuid."""
        encoded = PROJECT_A.replace("-", "%2D")
        assert encoded != PROJECT_A
        assert parse_reference(f"K?project={encoded}").project == PROJECT_A

    def test_the_target_is_passed_through_verbatim(self) -> None:
        assert parse_reference("MY%5FKEY").key == "MY%5FKEY"

    def test_a_key_containing_a_question_mark_is_refused_not_truncated(self) -> None:
        """The one thing splitting on `?` costs — and it costs an error, not a
        silent lookup of `WEIRD`.

        Everything after the `?` is read as an override block, so `KEY` is a
        malformed entry. Truncating to `WEIRD` and searching for that would be
        the quiet failure; the uuid form is the escape hatch.
        """
        with pytest.raises(InvalidReferenceError, match="missing a '='"):
            parse_reference("WEIRD?KEY")

    def test_a_plus_is_not_turned_into_a_space(self) -> None:
        """`parse_qsl` would, and neither a uuid nor a key may contain a
        space, so that decoding could only corrupt an identifier."""
        assert parse_reference("a+b").key == "a+b"
