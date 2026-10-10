"""The provider against a fake ``bw`` executable (spec A2–A4).

The fake is on ``PATH``, because the subprocess surface is the subject: which
argv is issued, in what order, how many times ``status`` is probed, and what
never appears on a command line. The single most load-bearing property — the
one the secrecy tests exist for — is that **the session key travels only
through the inherited environment** and **the report's specificity travels
only through the exception class names**, because core's sync report echoes
class names and never provider message text.
"""

from __future__ import annotations

from typing import Any

import pytest
from functualize_secrets_bitwarden import (
    AmbiguousFieldError,
    AmbiguousItemError,
    BwBinaryMissingError,
    BwCommandError,
    BwNotLoggedInError,
    BwSessionLockedError,
    FieldNotFoundError,
    InvalidReferenceError,
    ItemNotFoundError,
    PasswordManagerProvider,
    clear_cli_state_cache,
)

from tests.conftest import (
    ITEM_ID,
    OTHER_ITEM_ID,
    PASSWORD_VALUE,
    SESSION_KEY,
    pm_item,
)

#: The class name is what a `vault sync` report shows (core deliberately does
#: not echo provider exception text), so each state's class is pinned here by
#: name — the message is incidental.
_LOCKED_STATE = "locked"


def _provider() -> PasswordManagerProvider:
    return PasswordManagerProvider()


def _argvs(shim: Any) -> list[list[str]]:
    return [call["argv"] for call in shim.invocations]


class TestTheRefusalsNameTheirState:
    def test_a_missing_binary_is_its_own_error(self, monkeypatch: Any) -> None:
        """Empty PATH: no shim, no real CLI — the state is 'not installed'."""
        monkeypatch.setenv("PATH", "")
        with pytest.raises(BwBinaryMissingError, match="'bw'"):
            _provider().fetch("deploy-token/password")

    def test_a_signed_out_vault_is_its_own_error(self, bw_shim: Any) -> None:
        bw_shim(state="unauthenticated", items=[pm_item()])
        with pytest.raises(BwNotLoggedInError, match="bw login"):
            _provider().fetch(f"{ITEM_ID}/password")

    def test_a_locked_session_is_its_own_error(self, bw_shim: Any) -> None:
        bw_shim(state=_LOCKED_STATE, items=[pm_item()], session=SESSION_KEY)
        with pytest.raises(BwSessionLockedError, match="bw unlock"):
            _provider().fetch(f"{ITEM_ID}/password")

    def test_the_locked_refusal_never_carries_the_session_key(
        self, bw_shim: Any
    ) -> None:
        bw_shim(state=_LOCKED_STATE, items=[pm_item()], session=SESSION_KEY)
        with pytest.raises(BwSessionLockedError) as exc:
            _provider().fetch(f"{ITEM_ID}/password")
        assert SESSION_KEY not in str(exc.value)

    def test_a_refusal_spawns_no_item_call(self, bw_shim: Any) -> None:
        """The state probe decides; the vault is never touched."""
        shim = bw_shim(state=_LOCKED_STATE, items=[pm_item()])
        with pytest.raises(BwSessionLockedError):
            _provider().fetch(f"{ITEM_ID}/password")
        assert [argv[1:3] for argv in _argvs(shim)] == [["status", "--raw"]]

    def test_a_failed_status_probe_is_a_command_error(self, bw_shim: Any) -> None:
        bw_shim(status_stderr="keyring unavailable", items=[pm_item()])
        with pytest.raises(BwCommandError, match="keyring unavailable"):
            _provider().fetch(f"{ITEM_ID}/password")

    def test_an_unknown_status_word_is_a_command_error(self, bw_shim: Any) -> None:
        bw_shim(state="logging-in", items=[pm_item()])
        with pytest.raises(BwCommandError, match="logging-in"):
            _provider().fetch(f"{ITEM_ID}/password")


class TestFetchingByUuid:
    def test_a_uuid_resolves_in_two_calls_probe_then_get(self, bw_shim: Any) -> None:
        shim = bw_shim(items=[pm_item()], session=SESSION_KEY)
        assert _provider().fetch(f"{ITEM_ID}/password") == PASSWORD_VALUE
        assert [argv[1:3] for argv in _argvs(shim)] == [
            ["status", "--raw"],
            ["get", "item"],
        ]
        assert _argvs(shim)[1][3] == ITEM_ID

    def test_a_uuid_never_lists(self, bw_shim: Any) -> None:
        """The whole point of the id form: no listing call."""
        shim = bw_shim(items=[pm_item()])
        _provider().fetch(f"{ITEM_ID}/notes")
        assert ["list", "items"] not in [argv[1:3] for argv in _argvs(shim)]

    def test_a_missing_item_surfaces_bws_own_words(self, bw_shim: Any) -> None:
        """A uuid miss is decided by `bw` itself; its words are the reason."""
        bw_shim(items=[], get_stderr="Not found. no-such-id")
        with pytest.raises(BwCommandError, match="Not found"):
            _provider().fetch(f"{ITEM_ID}/password")


class TestFetchingByName:
    def _items(self) -> list[dict[str, Any]]:
        return [pm_item()]

    def test_a_name_resolves_through_the_listing(self, bw_shim: Any) -> None:
        shim = bw_shim(items=self._items())
        assert _provider().fetch("deploy-token/password") == PASSWORD_VALUE
        gets = [argv[3] for argv in _argvs(shim) if argv[1:3] == ["get", "item"]]
        assert gets == [ITEM_ID]

    def test_the_match_is_exact_not_fuzzy(self, bw_shim: Any) -> None:
        """`bw list items --search` fuzzes; this provider lists and matches
        itself, so a name that only fuzzy-matches is a refusal, not the
        wrong credential."""
        items = [pm_item(), pm_item(id=OTHER_ITEM_ID, name="deploy-tokens")]
        bw_shim(items=items)
        with pytest.raises(ItemNotFoundError, match="deploy-toke"):
            _provider().fetch("deploy-toke/password")

    def test_an_unknown_name_raises_not_found(self, bw_shim: Any) -> None:
        bw_shim(items=self._items())
        with pytest.raises(ItemNotFoundError, match="no-such-item"):
            _provider().fetch("no-such-item/password")

    def test_an_ambiguous_name_raises_naming_every_candidate(
        self, bw_shim: Any
    ) -> None:
        """A wrong pick would be a working run with the wrong credential."""
        items = [
            pm_item(),
            pm_item(id=OTHER_ITEM_ID, name="deploy-token"),
        ]
        bw_shim(items=items)
        with pytest.raises(AmbiguousItemError) as exc:
            _provider().fetch("deploy-token/password")
        assert ITEM_ID in str(exc.value)
        assert OTHER_ITEM_ID in str(exc.value)


class TestFieldSemantics:
    def _fetch(self, bw_shim: Any, reference: str) -> str:
        bw_shim(items=[pm_item()], session=SESSION_KEY)
        return _provider().fetch(reference)

    def test_the_five_builtin_slots(self, bw_shim: Any) -> None:
        assert self._fetch(bw_shim, f"{ITEM_ID}/password") == PASSWORD_VALUE
        assert self._fetch(bw_shim, f"{ITEM_ID}/username") == "fixture-user"
        assert self._fetch(bw_shim, f"{ITEM_ID}/notes") == "fixture notes line"
        assert self._fetch(bw_shim, f"{ITEM_ID}/uri") == "https://fixture.example.com"
        assert (
            self._fetch(bw_shim, f"{ITEM_ID}/totp")
            == "otpauth://totp/example:fixture?secret=JBSWY3DPEHPK3PXP"
        )

    def test_totp_is_the_stored_seed_never_a_generated_code(self, bw_shim: Any) -> None:
        """A generated code is a 30-second credential; baked into the vault
        it would silently expire. `bw get totp` is therefore never issued."""
        shim = bw_shim(items=[pm_item()])
        _provider().fetch(f"{ITEM_ID}/totp")
        assert all(argv[1:3] != ["get", "totp"] for argv in _argvs(shim))

    def test_uri_returns_the_first_uri(self, bw_shim: Any) -> None:
        """`bw get uri`'s own convention — the first entry is primary."""
        item = pm_item(
            login={
                **pm_item()["login"],
                "uris": [
                    {"uri": "https://first.example.com"},
                    {"uri": "https://second.example.com"},
                ],
            }
        )
        bw_shim(items=[item])
        assert _provider().fetch(f"{ITEM_ID}/uri") == "https://first.example.com"

    def test_a_custom_field_resolves_by_exact_name(self, bw_shim: Any) -> None:
        assert self._fetch(bw_shim, f"{ITEM_ID}/field:api-key") == (
            "PM-FIXTURE-api-key-value"
        )

    def test_an_empty_stored_value_refuses(self, bw_shim: Any) -> None:
        item = pm_item(login={**pm_item()["login"], "password": ""})
        bw_shim(items=[item])
        with pytest.raises(FieldNotFoundError, match="stores no value"):
            _provider().fetch(f"{ITEM_ID}/password")

    def test_a_null_stored_value_refuses(self, bw_shim: Any) -> None:
        item = pm_item(login={**pm_item()["login"], "totp": None})
        bw_shim(items=[item])
        with pytest.raises(FieldNotFoundError):
            _provider().fetch(f"{ITEM_ID}/totp")

    def test_a_login_field_on_a_non_login_item_refuses(self, bw_shim: Any) -> None:
        item = pm_item()
        del item["login"]
        bw_shim(items=[item])
        with pytest.raises(FieldNotFoundError, match="no login block"):
            _provider().fetch(f"{ITEM_ID}/password")

    def test_a_missing_custom_field_refuses(self, bw_shim: Any) -> None:
        bw_shim(items=[pm_item()])
        with pytest.raises(FieldNotFoundError, match="no custom field named"):
            _provider().fetch(f"{ITEM_ID}/field:no-such-field")

    def test_duplicate_custom_field_names_refuse(self, bw_shim: Any) -> None:
        """Bitwarden allows duplicate field names within one item; picking a
        winner would depend on which field a colleague added last."""
        item = pm_item(
            fields=[
                {"name": "api-key", "value": "first", "type": 0},
                {"name": "api-key", "value": "second", "type": 0},
            ]
        )
        bw_shim(items=[item])
        with pytest.raises(AmbiguousFieldError, match="2 custom fields"):
            _provider().fetch(f"{ITEM_ID}/field:api-key")


class TestSecrecy:
    def test_the_session_reaches_the_child_only_through_the_environment(
        self, bw_shim: Any
    ) -> None:
        """Inherited env is the ambient-session contract; argv is skipped on
        purpose because `ps` makes it world-readable."""
        shim = bw_shim(items=[pm_item()], session=SESSION_KEY)
        _provider().fetch(f"{ITEM_ID}/password")
        calls = shim.invocations
        assert calls and all(call["session_env"] for call in calls)
        for argv in _argvs(shim):
            assert "--session" not in argv
            assert SESSION_KEY not in argv

    def test_no_error_message_carries_a_value_or_the_session(
        self, bw_shim: Any
    ) -> None:
        item = pm_item(login={**pm_item()["login"], "password": None})
        bw_shim(items=[item], session=SESSION_KEY)
        provider = _provider()

        with pytest.raises(FieldNotFoundError) as empty:
            provider.fetch(f"{ITEM_ID}/password")
        with pytest.raises(FieldNotFoundError) as missing:
            provider.fetch(f"{ITEM_ID}/field:no-such-field")
        with pytest.raises(ItemNotFoundError) as absent:
            provider.fetch("no-such-item/password")

        for refusal in (empty, missing, absent):
            assert PASSWORD_VALUE not in str(refusal.value)
            assert SESSION_KEY not in str(refusal.value)

    def test_the_provider_holds_no_fetched_state(self, bw_shim: Any) -> None:
        bw_shim(items=[pm_item()], session=SESSION_KEY)
        provider = _provider()
        provider.fetch(f"{ITEM_ID}/password")
        assert vars(provider) == {}


class TestTheProbeCache:
    def test_one_probe_per_process(self, bw_shim: Any) -> None:
        shim = bw_shim(items=[pm_item()])
        provider = _provider()
        provider.fetch(f"{ITEM_ID}/password")
        provider.fetch(f"{ITEM_ID}/username")
        probes = [argv for argv in _argvs(shim) if argv[1:3] == ["status", "--raw"]]
        assert len(probes) == 1

    def test_clearing_the_cache_probes_again(self, bw_shim: Any) -> None:
        shim = bw_shim(items=[pm_item()])
        provider = _provider()
        provider.fetch(f"{ITEM_ID}/password")
        clear_cli_state_cache()
        provider.fetch(f"{ITEM_ID}/password")
        probes = [argv for argv in _argvs(shim) if argv[1:3] == ["status", "--raw"]]
        assert len(probes) == 2


class TestTheEntryPointContract:
    def test_the_identifier_matches_the_annotation_scheme(self) -> None:
        assert _provider().identifier() == "bwpm"

    def test_it_satisfies_the_protocol(self) -> None:
        from functualize._config.protocols import RemoteProvider

        assert isinstance(_provider(), RemoteProvider)

    def test_the_entry_point_resolves_to_this_class(self) -> None:
        """The production path is real entry-point discovery — a typo in the
        pyproject string would register nothing and every sync would report
        'bwpm: not installed'. This is the wiring proof."""
        from importlib.metadata import entry_points

        discovered = [
            ep
            for ep in entry_points(group="functualize.remote_providers")
            if ep.name == "bwpm"
        ]
        assert len(discovered) == 1
        assert discovered[0].load() is PasswordManagerProvider

    def test_is_ready_is_true_even_without_the_binary(self, monkeypatch: Any) -> None:
        """Pinned, not incidental: the sync report speaks in exception class
        names, so every state — including 'binary missing' — must reach
        `fetch` and refuse there by class, never flatten into a generic
        'not ready'."""
        monkeypatch.setenv("PATH", "")
        assert _provider().is_ready() is True

    def test_a_bad_reference_spawns_nothing(self, bw_shim: Any) -> None:
        """A typo costs a clear message, not a `bw` invocation."""
        shim = bw_shim(items=[pm_item()])
        with pytest.raises(InvalidReferenceError):
            _provider().fetch("deploy-token/api-key")
        assert shim.invocations == []
