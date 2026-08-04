"""What every name in the system is, right now, before the identity flip.

The flip changes *every registered name at once*. A green suite would not
prove it safe: the suite mostly builds names and asserts on the names it just
built, so a systematic rename moves both sides of the assertion together and
stays green while breaking every name a user has typed.

So this file asserts against literals. It is a characterization test in the
strict sense — it records what the code does, not what it should do. The flip
is expected to change these strings, and the diff *is* the review: every line
that changes here is a name someone's `func` invocation or `deps=` reference
depended on.

Delete nothing here when it fails. Read the diff, decide each change is
intended, then update the literal.
"""

from __future__ import annotations

import pytest

from functualize._discovery.naming import qualified_name
from functualize._types.naming import normalize_segment

# (group, func_name) -> registered name. Literals on purpose.
#
# The flip (2026-07-21) changed exactly the four entries carrying an
# underscore or a capital, and nothing else. `deploy` and `infra.deploy` did
# not move, which is the useful signal: the common case — a lowercase
# single-word job — is addressed today exactly as it was before.
_CURRENT_NAMES = [
    (None, "deploy", "deploy"),
    (None, "build_wheel", "build-wheel"),
    (None, "buildWheel", "build-wheel"),
    ("infra", "deploy", "infra.deploy"),
    ("infra", "provision_db", "infra.provision-db"),
    ("infra.aws", "provision", "infra.aws.provision"),
    ("data_ops", "run_etl", "data-ops.run-etl"),
]


@pytest.mark.parametrize(("group", "func_name", "expected"), _CURRENT_NAMES)
def test_registered_name_today(
    group: str | None, func_name: str, expected: str
) -> None:
    """The exact string a job is registered — and addressed — under."""
    assert qualified_name(group, func_name) == expected


class TestNormalizationPolicy:
    """The policy `qualified_name` applies to every registered name.

    Pinned separately from the names above so a change to the policy and a
    change to where it is applied stay distinguishable in a diff.
    """

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("deploy", "deploy"),
            ("build_wheel", "build-wheel"),
            ("buildWheel", "build-wheel"),
            ("BuildWheel", "build-wheel"),
            ("build wheel", "build-wheel"),
            ("build-wheel", "build-wheel"),
            # Acronyms stay whole — `h-t-t-p-server` is unrunnable in practice.
            ("HTTPServer", "http-server"),
            ("HTTP", "http"),
            ("parseHTTPResponse", "parse-http-response"),
            ("s3Bucket", "s3-bucket"),
        ],
    )
    def test_policy(self, raw: str, expected: str) -> None:
        assert normalize_segment(raw) == expected

    @pytest.mark.parametrize("raw", ["deploy", "build_wheel", "buildWheel", "a b_cD"])
    def test_is_idempotent(self, raw: str) -> None:
        """Normalizing a normalized name must not move it again — otherwise a
        name that round-trips through the cache drifts on every boot."""
        once = normalize_segment(raw)
        assert normalize_segment(once) == once


class TestGroupedNamesUsersActuallyType:
    """The addressing forms the CLI and `deps=` accept today.

    `func infra.deploy` and `deps=Deps("deploy")` resolving to `infra.deploy`
    are the two surfaces the flip must keep working, in whatever spelling it
    lands on.
    """

    def test_dotted_form_is_what_gets_registered(self) -> None:
        assert qualified_name("infra", "deploy") == "infra.deploy"

    def test_leaf_reference_resolves_through_the_graph(self) -> None:
        from functualize._types.naming import resolve_name

        known = ["infra.deploy", "build"]
        assert resolve_name("deploy", known) == "infra.deploy"
        assert resolve_name("infra.deploy", known) == "infra.deploy"
