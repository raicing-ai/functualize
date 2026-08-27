"""The environment-variable name rule is spelled five times. It must agree.

`JOB_FIELD` (and `SCOPE__FIELD` for group options) is built independently in
five places, across three peer layers that may not import each other:

    _config/sources.py       EnvSource._build_env_key      — *resolves* the name
    _config/resolved_field.py env_name_for                 — reports it
    _config/resolved_field.py group_env_name_for           — reports it
    _engine/missing_value.py  env_var_for                  — names it in an error
    _engine/missing_value.py  group_env_var_for            — names it in an error

The layer separation is deliberate and correct. What was missing is any check
that the copies agree: each carried a docstring promising it "matches the rule
rather than importing", and a promise in a comment is not an enforcement.

The stakes are specific. `EnvSource` is the only one that actually reads the
environment; the others only *print* names. A drift means the tool tells an
operator to set a variable that resolves nothing — worse than telling them
nothing, because they will believe it and stop looking.

This module is the enforcement. It has no opinion about what the rule *is*;
it only insists there is one.
"""

from __future__ import annotations

import pytest

from functualize._config.resolved_field import env_name_for, group_env_name_for
from functualize._config.sources import EnvSource
from functualize._engine.missing_value import env_var_for, group_env_var_for

#: Cases chosen for the characters that actually differ between spellings:
#: hyphens (canonical job names), dots (group-qualified names), and the
#: unsectioned case.
CASES = [
    ("sync", "credential"),
    ("deploy", "api_url"),
    ("env-cfg", "api_url"),
    ("deploy", "api-key"),
    ("infra.deploy", "api_url"),
    ("infra.deploy-web", "api-key"),
    ("", "token"),
    ("sync", "a"),
    ("UPPER", "MiXeD_case"),
]

#: The group spellings, which keep `SCOPE__FIELD`. The empty scope is excluded:
#: a group option always has a scope, and the two group builders are documented
#: only for that case.
GROUP_CASES = [c for c in CASES if c[0]]


@pytest.mark.parametrize(("section", "field"), CASES)
def test_the_reported_job_name_is_the_one_that_resolves(section, field):
    """`env_name_for` prints; `EnvSource` reads. They must be the same string.

    This is the pairing that matters most: everything else is a name on a
    screen, but this one decides whether setting that name has any effect.
    """
    assert env_name_for(section, field) == EnvSource._build_env_key(field, section)


@pytest.mark.parametrize(("section", "field"), CASES)
def test_the_error_message_names_the_one_that_resolves(section, field):
    """A validation error naming an ineffective variable is a false lead."""
    assert env_var_for(section, field) == EnvSource._build_env_key(field, section)


@pytest.mark.parametrize(("scope", "field"), GROUP_CASES)
def test_the_two_group_spellings_agree(scope, field):
    """Group options keep `SCOPE__FIELD`; both builders must say so alike."""
    assert group_env_name_for(scope, field) == group_env_var_for(scope, field)


@pytest.mark.parametrize(("scope", "field"), GROUP_CASES)
def test_a_group_name_is_not_a_job_name(scope, field):
    """The two conventions are deliberately different — assert the difference.

    Without this, "make them agree" could be satisfied by collapsing group
    options onto `JOB_FIELD`, which would silently rename a second, unrelated
    feature's environment variables.
    """
    assert group_env_name_for(scope, field) != env_name_for(scope, field)
    assert "__" in group_env_name_for(scope, field)


class TestTheRuleItself:
    """A few anchors, so a rule change is a deliberate edit to this file."""

    def test_hyphens_and_dots_are_flattened(self):
        assert env_name_for("infra.deploy-web", "api-key") == "INFRA_DEPLOY_WEB_API_KEY"

    def test_an_empty_section_yields_the_bare_field(self):
        assert env_name_for("", "token") == "TOKEN"

    def test_a_group_keeps_its_double_underscore(self):
        assert group_env_name_for("deploy-web", "env") == "DEPLOY_WEB__ENV"
