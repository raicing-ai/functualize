"""The `aws-sm://` / `aws-ssm://` grammar (remote-source-activation/5.1).

The governing rule: an override the caller wrote must either take effect or
raise. It must never be ignored. A `?porfile=prod-admin` that resolves quietly
under the default identity is the same defect as `remote_first()` silently
behaving as `classic()` — the caller states an intent and the system does
something else without saying so.
"""

from __future__ import annotations

import pytest
from functualize_aws import HONOURED_KEYS, InvalidReferenceError, parse_reference


class TestThePlainForm:
    def test_a_bare_name_parses(self) -> None:
        assert parse_reference("prod/db-password").name == "prod/db-password"

    def test_no_overrides_means_the_ambient_chain(self) -> None:
        ref = parse_reference("prod/db")
        assert (ref.profile, ref.role, ref.account, ref.region) == (None,) * 4

    def test_an_ssm_leading_slash_survives(self) -> None:
        """`aws-ssm:///prod/api-url` reaches us as `/prod/api-url`."""
        assert parse_reference("/prod/api-url").name == "/prod/api-url"

    def test_an_arn_survives_its_colons(self) -> None:
        """Core passes the reference through opaquely; colons are not special
        to this grammar either."""
        arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:prod/db-AbCdEf"
        assert parse_reference(arn).name == arn

    def test_an_empty_name_is_rejected(self) -> None:
        with pytest.raises(InvalidReferenceError, match="No secret id"):
            parse_reference("?profile=admin")


class TestEachHonouredKey:
    def test_profile(self) -> None:
        assert parse_reference("prod/db?profile=prod-admin").profile == "prod-admin"

    def test_region(self) -> None:
        assert parse_reference("prod/db?region=eu-west-1").region == "eu-west-1"

    def test_account(self) -> None:
        assert parse_reference("prod/db?account=123456789012").account == "123456789012"

    def test_role(self) -> None:
        arn = "arn:aws:iam::123456789012:role/Deploy"
        assert parse_reference(f"prod/db?role={arn}").role == arn

    def test_every_honoured_key_is_reachable(self) -> None:
        """Derived from HONOURED_KEYS, so adding a key without wiring it fails."""
        sample = {
            "profile": "p",
            "region": "eu-west-1",
            "account": "123456789012",
            "role": "arn:aws:iam::123456789012:role/R",
        }
        assert set(sample) == set(HONOURED_KEYS), "a key was added without a sample"
        for key, value in sample.items():
            assert getattr(parse_reference(f"n?{key}={value}"), key) == value

    def test_they_combine(self) -> None:
        ref = parse_reference(
            "prod/db?profile=admin&region=eu-west-1&account=123456789012"
            "&role=arn:aws:iam::123456789012:role/Deploy"
        )
        assert ref.profile == "admin"
        assert ref.region == "eu-west-1"
        assert ref.account == "123456789012"
        assert ref.role.endswith("role/Deploy")


class TestAnUnknownKeyIsRejected:
    """The headline acceptance: a typo must not resolve under the wrong
    identity."""

    def test_a_typo_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="Unknown override 'porfile'"):
            parse_reference("prod/db?porfile=prod-admin")

    def test_the_error_suggests_the_intended_key(self) -> None:
        with pytest.raises(InvalidReferenceError, match="Did you mean 'profile'"):
            parse_reference("prod/db?porfile=prod-admin")

    def test_the_error_lists_what_is_honoured(self) -> None:
        with pytest.raises(InvalidReferenceError) as exc:
            parse_reference("prod/db?nonsense=1")
        for key in HONOURED_KEYS:
            assert key in str(exc.value)

    def test_a_plausible_but_unimplemented_key_raises(self) -> None:
        """`?key=` for a JSON field is a reasonable thing to expect and is not
        implemented. Rejecting says so; ignoring would hand the job the whole
        JSON blob."""
        with pytest.raises(InvalidReferenceError, match="Unknown override 'key'"):
            parse_reference("prod/db?key=password")


class TestMalformedOverrides:
    def test_a_repeated_key_raises(self) -> None:
        """Last-wins and first-wins are both defensible, which is the problem."""
        with pytest.raises(InvalidReferenceError, match="more than once"):
            parse_reference("prod/db?profile=a&profile=b")

    def test_a_valueless_key_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="missing a '='"):
            parse_reference("prod/db?profile")

    def test_an_empty_value_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="empty value"):
            parse_reference("prod/db?profile=")

    def test_an_empty_entry_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="Empty entry"):
            parse_reference("prod/db?profile=a&&region=eu-west-1")


class TestShapeChecksTurnTyposIntoMessages:
    """Each of these would otherwise surface as an opaque boto3 error that
    never mentions the annotation the operator actually wrote."""

    @pytest.mark.parametrize("bad", ["12345", "1234567890123", "12345678901a", "prod"])
    def test_a_non_twelve_digit_account_raises(self, bad: str) -> None:
        with pytest.raises(InvalidReferenceError, match="12 digits"):
            parse_reference(f"n?account={bad}")

    @pytest.mark.parametrize(
        "region", ["us-east-1", "eu-west-2", "ap-southeast-2", "us-gov-west-1"]
    )
    def test_real_regions_are_accepted(self, region: str) -> None:
        """Including the partitioned forms, which a naive pattern rejects."""
        assert parse_reference(f"n?region={region}").region == region

    @pytest.mark.parametrize("bad", ["useast1", "US-EAST-1", "eu-west", "1-2-3"])
    def test_a_malformed_region_raises(self, bad: str) -> None:
        with pytest.raises(InvalidReferenceError, match="AWS region"):
            parse_reference(f"n?region={bad}")

    def test_a_bare_role_name_raises(self) -> None:
        """The common mistake. STS's own error never mentions the annotation."""
        with pytest.raises(InvalidReferenceError, match="full IAM role ARN"):
            parse_reference("n?role=Deploy")

    def test_a_non_iam_arn_raises(self) -> None:
        with pytest.raises(InvalidReferenceError, match="full IAM role ARN"):
            parse_reference("n?role=arn:aws:s3:::my-bucket")

    @pytest.mark.parametrize(
        "arn",
        [
            "arn:aws:iam::123456789012:role/Deploy",
            "arn:aws-us-gov:iam::123456789012:role/Deploy",
            "arn:aws:iam::123456789012:role/path/to/Deploy",
        ],
    )
    def test_real_role_arns_are_accepted(self, arn: str) -> None:
        assert parse_reference(f"n?role={arn}").role == arn


class TestPercentEncoding:
    def test_an_encoded_value_is_decoded(self) -> None:
        assert parse_reference("n?profile=my%2Dprofile").profile == "my-profile"

    def test_a_plus_is_not_turned_into_a_space(self) -> None:
        """`parse_qsl` would. None of these values may contain a space, so
        that decoding could only ever corrupt one identity into another."""
        assert parse_reference("n?profile=a+b").profile == "a+b"


class TestTheIdentityKey:
    def test_two_secrets_under_one_identity_share_a_key(self) -> None:
        """What makes the assume-role cache worth having."""
        a = parse_reference("prod/one?profile=admin")
        b = parse_reference("prod/two?profile=admin")
        assert a.identity_key == b.identity_key

    def test_a_different_profile_is_a_different_key(self) -> None:
        a = parse_reference("prod/one?profile=admin")
        b = parse_reference("prod/one?profile=readonly")
        assert a.identity_key != b.identity_key

    def test_account_does_not_split_the_cache(self) -> None:
        """It is an assertion about the identity, not part of choosing one."""
        a = parse_reference("prod/one?profile=admin")
        b = parse_reference("prod/one?profile=admin&account=123456789012")
        assert a.identity_key == b.identity_key
