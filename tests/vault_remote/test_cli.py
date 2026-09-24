"""The verbs, driven the way a user drives them — against the mock origin.

`share`, `redeem` and `show` run through a real click group via CliRunner,
with the same `register_builtin_commands` mounting production uses, plus
the top-level `func vault` alias. Values appear exactly where the design
says they may (the receiver's export lines) and nowhere else — asserted,
including against the log record tape.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner

from functualize._cli.builtins import register_builtin_commands
from functualize._cli.vault_cmd import vault_app

if TYPE_CHECKING:
    from tests.vault_remote.mock_vault import MockVault

_SECRET = "correct-horse-battery-staple-9f3a"  # gitleaks:allow

_LINK_RE = re.compile(r"(https?://\S+/s/[0-9a-f]{32}#k1\.[A-Za-z0-9_-]{43})")


def _cli() -> Any:
    import click

    group = click.Group(name="func")
    register_builtin_commands(group)
    return group


def _share(
    mock_origin: MockVault, *extra: str, value: str = _SECRET
) -> str:
    result = CliRunner().invoke(
        _cli(),
        [
            "vault",
            "share",
            "--set",
            f"E2E_TOKEN={value}",
            "--labels",
            "eval",
            "--expires",
            "1h",
            "--origin",
            mock_origin.origin,
            *extra,
        ],
    )
    assert result.exit_code == 0, result.output
    match = _LINK_RE.search(result.output)
    assert match, result.output
    return match.group(1)


class TestShare:
    def test_prints_the_link_with_a_possession_warning(
        self, mock_origin: MockVault
    ) -> None:
        result = CliRunner().invoke(
            _cli(),
            [
                "vault",
                "share",
                "--set",
                f"E2E_TOKEN={_SECRET}",
                "--origin",
                mock_origin.origin,
            ],
        )
        assert result.exit_code == 0, result.output
        assert _LINK_RE.search(result.output)
        assert "Anyone with this complete link" in result.output
        assert _SECRET not in result.output

    def test_json_mode_carries_the_link_and_no_value(
        self, mock_origin: MockVault
    ) -> None:
        import json

        result = CliRunner().invoke(
            _cli(),
            [
                "vault",
                "share",
                "--set",
                f"E2E_TOKEN={_SECRET}",
                "--origin",
                mock_origin.origin,
                "--json",
            ],
        )
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert _LINK_RE.match(payload["link"])
        assert _SECRET not in result.output

    def test_a_malformed_set_pair_is_a_usage_error(
        self, mock_origin: MockVault
    ) -> None:
        result = CliRunner().invoke(
            _cli(),
            [
                "vault",
                "share",
                "--set",
                "NO-VALUE-HERE",
                "--origin",
                mock_origin.origin,
            ],
        )
        assert result.exit_code != 0
        assert "NAME=VALUE" in result.output

    def test_sharing_nothing_is_refused(
        self, mock_origin: MockVault
    ) -> None:
        result = CliRunner().invoke(
            _cli(), ["vault", "share", "--origin", mock_origin.origin]
        )
        assert result.exit_code != 0
        assert "nothing to share" in result.output

    def test_sub_hour_expiry_is_refused(self, mock_origin: MockVault) -> None:
        """90m is fine; 30s rounds to zero hours and must not become a
        share that dies before its link can be delivered."""
        ok = CliRunner().invoke(
            _cli(),
            [
                "vault",
                "share",
                "--set",
                "A=b",
                "--expires",
                "90m",
                "--origin",
                mock_origin.origin,
            ],
        )
        assert ok.exit_code == 0, ok.output
        refused = CliRunner().invoke(
            _cli(),
            [
                "vault",
                "share",
                "--set",
                "A=b",
                "--expires",
                "30s",
                "--origin",
                mock_origin.origin,
            ],
        )
        assert refused.exit_code != 0
        assert "outside the 1..168 hour window" in refused.output


class TestRedeem:
    def test_prints_export_lines_with_values(
        self, mock_origin: MockVault
    ) -> None:
        link = _share(mock_origin)
        result = CliRunner().invoke(_cli(), ["vault", "redeem", link])
        assert result.exit_code == 0, result.output
        assert f"export E2E_TOKEN={_SECRET}" in result.output
        assert "redemption 1 of 1" in result.output

    def test_explicit_export_lines_flag_matches_the_default(
        self, mock_origin: MockVault
    ) -> None:
        link = _share(mock_origin)
        result = CliRunner().invoke(
            _cli(), ["vault", "redeem", "--export-lines", link]
        )
        assert result.exit_code == 0, result.output
        assert f"export E2E_TOKEN={_SECRET}" in result.output

    def test_json_mode_never_carries_values(
        self, mock_origin: MockVault
    ) -> None:
        import json

        link = _share(mock_origin)
        result = CliRunner().invoke(
            _cli(), ["vault", "redeem", "--json", link]
        )
        payload = json.loads(result.output)
        assert payload["ok"] is True
        assert payload["names"] == ["E2E_TOKEN"]
        assert payload["redemptions_left_after"] == 0
        assert _SECRET not in result.output

    def test_a_spent_share_exits_nonzero_and_closed(
        self, mock_origin: MockVault
    ) -> None:
        link = _share(mock_origin)
        assert CliRunner().invoke(_cli(), ["vault", "redeem", link]).exit_code == 0
        again = CliRunner().invoke(_cli(), ["vault", "redeem", link])
        assert again.exit_code != 0
        assert "gone" in again.output
        assert _SECRET not in again.output

    def test_a_wrong_key_link_fails_as_one_closed_class(
        self, mock_origin: MockVault
    ) -> None:
        import base64

        link = _share(mock_origin)
        wrong = (
            link[: link.rindex("#")]
            + "#k1."
            + base64.urlsafe_b64encode(b"\x07" * 32).rstrip(b"=").decode()
        )
        result = CliRunner().invoke(_cli(), ["vault", "redeem", wrong])
        assert result.exit_code != 0
        assert "did not authenticate" in result.output
        assert _SECRET not in result.output

    def test_conflicting_materializations_are_a_usage_error(
        self, mock_origin: MockVault
    ) -> None:
        link = _share(mock_origin)
        result = CliRunner().invoke(
            _cli(), ["vault", "redeem", "--export-lines", "--into-vault", link]
        )
        assert result.exit_code != 0
        assert "exclusive" in result.output


class TestIntoVault:
    @pytest.fixture
    def key_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> Path:
        """A cwd with an env-provided vault key — the route that needs no
        keyring, so the test works on any machine."""
        from functualize._config.vault_keys import ENV_VAR, generate_key

        (tmp_path / ".functualize").mkdir()
        monkeypatch.setenv(ENV_VAR, generate_key())
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def test_stores_under_scope_and_prints_names_only(
        self, mock_origin: MockVault, key_project: Path
    ) -> None:
        link = _share(mock_origin)
        result = CliRunner().invoke(
            _cli(), ["vault", "redeem", "--into-vault", "--scope", "demo", link]
        )
        assert result.exit_code == 0, result.output
        assert "demo.E2E_TOKEN" in result.output
        assert _SECRET not in result.output

        from functualize._config.vault import SecretsVault
        from functualize._config.vault_keys import resolve_vault_key
        from functualize._config.vault_paths import vault_path_for_project

        resolution = resolve_vault_key("ignored")
        assert resolution is not None
        stored = SecretsVault(vault_path_for_project(key_project)).get(
            "demo.E2E_TOKEN", encryption_key=resolution.key
        )
        assert stored == _SECRET

    def test_without_a_scope_names_land_verbatim(
        self, mock_origin: MockVault, key_project: Path
    ) -> None:
        link = _share(mock_origin)
        result = CliRunner().invoke(
            _cli(), ["vault", "redeem", "--into-vault", link]
        )
        assert result.exit_code == 0, result.output
        assert "stored   E2E_TOKEN" in result.output

    def test_an_existing_entry_is_refused_not_overwritten(
        self, mock_origin: MockVault, key_project: Path
    ) -> None:
        link = _share(mock_origin, "--redemptions", "2")
        first = CliRunner().invoke(
            _cli(), ["vault", "redeem", "--into-vault", "--scope", "demo", link]
        )
        assert first.exit_code == 0, first.output
        second = CliRunner().invoke(
            _cli(), ["vault", "redeem", "--into-vault", "--scope", "demo", link]
        )
        assert second.exit_code != 0
        assert "already holds a value" in second.output


class TestDotenv:
    def test_writes_a_0600_file(
        self,
        mock_origin: MockVault,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        link = _share(mock_origin)
        env_file = tmp_path / "redeemed.env"
        result = CliRunner().invoke(
            _cli(), ["vault", "redeem", "--dotenv", str(env_file), link]
        )
        assert result.exit_code == 0, result.output
        assert f"Wrote {env_file}" in result.output
        assert (env_file.stat().st_mode & 0o777) == 0o600
        assert f"E2E_TOKEN={_SECRET}" in env_file.read_text()


class TestShow:
    def test_previews_without_burning(self, mock_origin: MockVault) -> None:
        link = _share(mock_origin, "--redemptions", "2")
        result = CliRunner().invoke(_cli(), ["vault", "show", link])
        assert result.exit_code == 0, result.output
        assert "2 of 2 left" in result.output
        # The preview spent nothing: both redemptions still succeed.
        for _ in range(2):
            assert CliRunner().invoke(
                _cli(), ["vault", "redeem", link]
            ).exit_code == 0

    def test_a_spent_share_previews_as_gone(
        self, mock_origin: MockVault
    ) -> None:
        link = _share(mock_origin)
        CliRunner().invoke(_cli(), ["vault", "redeem", link])
        result = CliRunner().invoke(_cli(), ["vault", "show", link])
        assert result.exit_code != 0
        assert "gone" in result.output


class TestOrigin:
    def test_a_foreign_origin_link_warns_but_redeems(
        self,
        mock_origin: MockVault,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        link = _share(mock_origin)
        monkeypatch.setenv("FUNC_VAULT_ORIGIN", "https://elsewhere.example")
        result = CliRunner().invoke(_cli(), ["vault", "redeem", link])
        assert result.exit_code == 0, result.output
        assert "not the configured" in result.output

    def test_the_env_origin_is_honored_for_sharing(
        self, mock_origin: MockVault, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FUNC_VAULT_ORIGIN", mock_origin.origin)
        result = CliRunner().invoke(
            _cli(), ["vault", "share", "--set", "A=b"]
        )
        assert result.exit_code == 0, result.output
        assert mock_origin.origin in result.output


class TestAliasMount:
    def test_vault_is_a_top_level_group_and_the_builtin_still_works(
        self, mock_origin: MockVault
    ) -> None:
        cli = _cli()
        assert "vault" in cli.commands
        # Same group object: the alias can never drift from the builtin.
        assert cli.commands["vault"] is vault_app
        result = CliRunner().invoke(
            cli, ["builtin", "vault", "--help"]
        )
        assert result.exit_code == 0
        assert "redeem" in result.output

class TestFragmentHygiene:
    def test_redeem_and_show_never_emit_the_fragment(
        self,
        mock_origin: MockVault,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        with caplog.at_level(logging.DEBUG, logger="functualize"):
            link = _share(mock_origin, "--redemptions", "2")
            for args in (["vault", "show", link], ["vault", "redeem", link]):
                result = CliRunner().invoke(_cli(), args)
                assert result.exit_code == 0, result.output
                assert "k1." not in result.output
        fragment = link[link.index("#") + 1 :]
        tape = "\n".join(record.getMessage() for record in caplog.records)
        assert fragment not in tape
        assert "k1." not in tape
