"""Plugin kind is read off the group name, not off a list of package names.

The distinction users need before installing: an adapter adds commands anyone
might want, a domain publishes a protocol, an implementation is a backend you
pick because of the infrastructure you already run.

The rule that matters here is *derivation*. `_cli/plugin_cmd` already scans
whatever `functualize.*` groups happen to be installed rather than enumerating
them, because domains declare new provider groups at runtime. A classifier that
enumerated instead would be stale the first time that happened.
"""

from __future__ import annotations

import pytest

from functualize.app.utils import PluginKind, classify_group


class TestKnownGroups:
    @pytest.mark.parametrize(
        ("group", "kind"),
        [
            ("functualize.plugins", PluginKind.ADAPTER),
            ("functualize.domains", PluginKind.DOMAIN),
            ("functualize.remote_providers", PluginKind.IMPLEMENTATION),
            ("functualize.state_providers", PluginKind.IMPLEMENTATION),
            ("functualize.ai_providers", PluginKind.IMPLEMENTATION),
            ("functualize.tasks_providers", PluginKind.IMPLEMENTATION),
            ("functualize.interactivity_providers", PluginKind.IMPLEMENTATION),
            ("functualize.format_providers", PluginKind.IMPLEMENTATION),
        ],
    )
    def test_shipped_groups(self, group: str, kind: PluginKind) -> None:
        assert classify_group(group) is kind


class TestDerivation:
    def test_unknown_provider_group_needs_no_code_change(self) -> None:
        """AC-B4 — the whole point of deriving rather than enumerating.

        No such group exists in this repository. A domain that declares one
        tomorrow must classify correctly without anyone editing the classifier.
        """
        assert classify_group("functualize.zzz_providers") is (
            PluginKind.IMPLEMENTATION
        )

    @pytest.mark.parametrize(
        "group",
        [
            "other.plugins",  # not ours
            "functualize.",  # prefix with nothing after it
            "functualize.a.b",  # groups are one segment
            "functualize._providers",  # `_providers` with no domain in front
            "functualize.something-else",
        ],
    )
    def test_unrecognised_groups_are_unknown(self, group: str) -> None:
        assert classify_group(group) is PluginKind.UNKNOWN

    def test_jobs_group_is_not_special_cased_here(self) -> None:
        """`functualize.jobs` is a job source, and filtering it is the caller's
        job — `_cli/plugin_cmd` excludes it by name and says why. Answering
        UNKNOWN keeps that decision in one place rather than two."""
        assert classify_group("functualize.jobs") is PluginKind.UNKNOWN


class TestSerialisation:
    def test_kind_is_its_own_json_value(self) -> None:
        """StrEnum, so `func builtin plugin --format json` needs no encoder."""
        import json

        assert json.dumps({"kind": PluginKind.ADAPTER}) == '{"kind": "adapter"}'
