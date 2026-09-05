"""Annotation discovery keys on registered providers, not on the URL shape.

The trap these tests exist for: ANNOTATION_PATTERN matches any `scheme://rest`,
so `https://api.example.com` parses as provider 'https'. Classifying on the
pattern would turn every URL in a config file into an annotation.
"""

from __future__ import annotations

import pytest

from functualize._config.annotations import scan_annotations

_REGISTERED = ("aws-sm", "aws-ssm")


class TestOrdinaryUrlsAreNotAnnotations:
    """The headline requirement; the reason registration is the test."""

    @pytest.mark.parametrize(
        "value",
        [
            "https://api.example.com",
            "http://localhost:8080",
            "postgres://user:pw@host/db",
            "redis://cache:6379/0",
            "s3://bucket/key",
            "file:///etc/hosts",
            "wss://events.example.com/stream",
        ],
    )
    def test_a_plain_url_is_left_alone(self, value: str) -> None:
        scan = scan_annotations({"api_url": value}, _REGISTERED)
        assert scan.annotations == {}
        assert scan.unresolved == []

    def test_a_url_and_an_annotation_can_coexist(self) -> None:
        scan = scan_annotations(
            {
                "api_url": "https://api.example.com",
                "db_password": "aws-sm://floci/db-password",
            },
            _REGISTERED,
        )
        assert list(scan.annotations) == ["db_password"]


class TestRegisteredProvidersAreAnnotations:
    def test_a_registered_scheme_is_parsed(self) -> None:
        scan = scan_annotations(
            {"db_password": "aws-sm://floci/db-password"}, _REGISTERED
        )
        (annotation,) = scan.annotations["db_password"]
        assert annotation.provider == "aws-sm"
        assert annotation.reference == "floci/db-password"

    def test_an_ssm_path_reference_keeps_its_leading_slash(self) -> None:
        """SSM parameter names begin with '/'; losing it breaks the lookup."""
        scan = scan_annotations({"api_url": "aws-ssm:///floci/api-url"}, _REGISTERED)
        (annotation,) = scan.annotations["api_url"]
        assert annotation.reference == "/floci/api-url"

    def test_a_fallback_chain_parses_in_order(self) -> None:
        scan = scan_annotations(
            {"token": "aws-sm://prod/token | aws-ssm:///fallback/token"},
            _REGISTERED,
        )
        chain = scan.annotations["token"]
        assert [a.provider for a in chain] == ["aws-sm", "aws-ssm"]

    def test_nothing_is_found_when_no_provider_is_registered(self) -> None:
        """With no plugins installed, nothing resolves remotely."""
        scan = scan_annotations({"db_password": "aws-sm://prod/db"}, [])
        assert scan.annotations == {}


class TestTheMissingPluginCase:
    """Keying on registration creates a silent-literal risk. It is reported."""

    def test_an_unregistered_credential_scheme_is_reported(self) -> None:
        """Without this, a job would receive 'vault://...' AS its password."""
        scan = scan_annotations({"db_password": "vault://secret/db"}, _REGISTERED)
        assert scan.annotations == {}
        (unresolved,) = scan.unresolved
        assert unresolved.key == "db_password"
        assert unresolved.providers == ("vault",)

    def test_a_partially_installed_chain_is_reported_and_still_used(self) -> None:
        """The registered half works; the missing half is not hidden."""
        scan = scan_annotations(
            {"token": "vault://secret/token | aws-sm://prod/token"}, _REGISTERED
        )
        assert "token" in scan.annotations
        (unresolved,) = scan.unresolved
        assert unresolved.providers == ("vault",)

    def test_a_common_url_scheme_is_not_reported(self) -> None:
        """A config file legitimately holds URLs; warning on them is noise."""
        scan = scan_annotations({"api_url": "https://example.com"}, _REGISTERED)
        assert scan.unresolved == []

    def test_the_report_carries_no_resolved_value(self) -> None:
        scan = scan_annotations({"db_password": "vault://secret/db"}, _REGISTERED)
        assert scan.unresolved[0].value == "vault://secret/db"


class TestTheReferenceIsOpaqueToCore:
    """Providers own their reference syntax; core passes it through whole.

    The AWS provider must let an annotation override boto3's normal credential
    precedence — profile, role, account, region. That is expressed inside the
    reference, so these tests pin that core does not parse, split, normalise or
    truncate it. If core ever "helpfully" interprets a reference, every
    provider's addressing scheme becomes core's problem.
    """

    @pytest.mark.parametrize(
        "reference",
        [
            "floci/db-password?profile=prod",
            "prod/db?account=123456789012&region=eu-west-1",
            "prod/db?role=arn:aws:iam::123456789012:role/Deploy",
            "a/b/c?x=1&y=2&z=3",
        ],
    )
    def test_the_reference_survives_verbatim(self, reference: str) -> None:
        scan = scan_annotations({"k": f"aws-sm://{reference}"}, _REGISTERED)
        (annotation,) = scan.annotations["k"]
        assert annotation.reference == reference

    def test_an_arn_with_colons_is_not_truncated(self) -> None:
        """A role ARN carries colons; naive scheme-splitting would cut it."""
        value = "aws-ssm:///p?role=arn:aws:iam::123456789012:role/Deploy"
        scan = scan_annotations({"k": value}, _REGISTERED)
        (annotation,) = scan.annotations["k"]
        assert annotation.reference.endswith(":role/Deploy")
        assert "arn:aws:iam::123456789012" in annotation.reference

    def test_each_chain_entry_keeps_its_own_overrides(self) -> None:
        """Failing over must not carry the first entry's profile to the second."""
        scan = scan_annotations(
            {"k": "aws-sm://a?profile=x | aws-ssm:///b?profile=y"}, _REGISTERED
        )
        first, second = scan.annotations["k"]
        assert first.reference == "a?profile=x"
        assert second.reference == "/b?profile=y"


class TestNonAnnotations:
    @pytest.mark.parametrize(
        "value",
        ["just-a-string", "", "42", "C:/path/to/file", "no-scheme//here"],
    )
    def test_a_literal_is_left_alone(self, value: str) -> None:
        scan = scan_annotations({"k": value}, _REGISTERED)
        assert scan.annotations == {}
        assert scan.unresolved == []

    def test_a_malformed_chain_entry_makes_the_whole_value_a_literal(self) -> None:
        """A chain is a chain only when every entry is annotation-shaped."""
        scan = scan_annotations({"k": "aws-sm://a | not-an-annotation"}, _REGISTERED)
        assert scan.annotations == {}

    def test_non_string_values_are_skipped(self) -> None:
        scan = scan_annotations({"port": 5432, "on": True}, _REGISTERED)  # type: ignore[dict-item]
        assert scan.annotations == {}


class TestChainLimits:
    def test_a_chain_longer_than_the_maximum_raises(self) -> None:
        """MAX_FALLBACK_CHAIN is 5; the parser owns this rule."""
        value = " | ".join(f"aws-sm://s{i}" for i in range(6))
        with pytest.raises(ValueError, match="Fallback chain exceeds"):
            scan_annotations({"k": value}, _REGISTERED)

    def test_a_chain_at_the_maximum_is_accepted(self) -> None:
        value = " | ".join(f"aws-sm://s{i}" for i in range(5))
        scan = scan_annotations({"k": value}, _REGISTERED)
        assert len(scan.annotations["k"]) == 5


class TestScanTruthiness:
    def test_an_empty_scan_is_falsey(self) -> None:
        assert not scan_annotations({"a": "plain"}, _REGISTERED)

    def test_a_scan_with_annotations_is_truthy(self) -> None:
        assert scan_annotations({"a": "aws-sm://x"}, _REGISTERED)

    def test_a_scan_with_only_unresolved_is_truthy(self) -> None:
        """Something remote was declared, even though none of it resolves."""
        assert scan_annotations({"a": "vault://x"}, _REGISTERED)
