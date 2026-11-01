"""`func builtin vault share|redeem|show`, driven the way a user drives them.

A real click group with production's `register_builtin_commands` mounting,
against the in-process mock origin and the sender/receiver projects from
`conftest.py`. Values appear exactly where the design says they may — export
lines from `--print-only`, and a `--dotenv` file — and nowhere else, asserted
including against the log record tape. Every refusal that the spec puts before
the burn is checked against the mock's request tape.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner

from functualize._cli.builtins import register_builtin_commands
from functualize.app.vault import VaultIdentity, vault_put
from tests.vault_remote.projects import (
    _APP_KEY,
    _MY_KEY,
    _REGION,
    _SECRET,
    _TOKEN,
    _app,
    _project,
)

if TYPE_CHECKING:
    from functualize.app import FunctualizeApp
    from tests.vault_remote.mock_vault import MockVault

_LINK_RE = re.compile(r"(https?://\S+/s/[0-9a-f]{32}#k1\.[A-Za-z0-9_-]{43})")

Project = tuple["FunctualizeApp", Path]


def _cli() -> Any:
    import click

    group = click.Group(name="func")
    register_builtin_commands(group)
    return group


def _run(project: Project, *args: str, input: str | None = None) -> Any:  # noqa: A002 - click's own name
    import contextlib

    app, root = project
    # The vault is the working directory's project's, as for every vault
    # command; a test runs from the project it is about.
    with contextlib.chdir(root):
        return CliRunner().invoke(
            _cli(), ["builtin", "vault", *args], obj={"app": app}, input=input
        )


def _share(mock: MockVault, sender: Project, *entries: str) -> str:
    args = [a for e in entries for a in ("--entry", e)] or ["--all"]
    result = _run(sender, "share", *args, "--origin", mock.origin)
    assert result.exit_code == 0, result.output
    match = _LINK_RE.search(result.output)
    assert match, result.output
    return match.group(1)


def _redeem_posts(mock: MockVault) -> int:
    return sum(
        1
        for r in mock.requests
        if r["method"] == "POST" and r["path"].endswith("/redeem")
    )


@pytest.fixture
def at_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """CliRunner is never a TTY; the checklist paths need one."""
    monkeypatch.setattr(
        "functualize._cli.vault_cmd._interactive", lambda json_out: not json_out
    )


class TestTheAliasIsGone:
    def test_vault_is_not_a_top_level_command(self) -> None:
        assert "vault" not in _cli().commands
        result = CliRunner().invoke(_cli(), ["vault", "share", "--all"])
        assert result.exit_code != 0


class TestShare:
    def test_an_entry_prints_the_link_and_a_possession_warning(
        self, mock_origin: MockVault, sender: Project
    ) -> None:
        result = _run(
            sender,
            "share",
            "--entry",
            "group=deploy,field=token",
            "--origin",
            mock_origin.origin,
        )
        assert result.exit_code == 0, result.output
        assert _LINK_RE.search(result.output)
        assert "Anyone with this complete link" in result.output
        assert "Sharing 1 entry:" in result.output

    def test_json_names_the_entries_and_carries_no_value(
        self, mock_origin: MockVault, sender: Project
    ) -> None:
        result = _run(
            sender,
            "share",
            "--entry",
            "group=deploy",
            "--json",
            "--origin",
            mock_origin.origin,
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert len(payload["entries"]) == 3
        assert "env:prod" in payload["labels"]
        assert _SECRET not in result.output

    def test_entry_and_all_together_is_a_usage_error(self, sender: Project) -> None:
        result = _run(sender, "share", "--all", "--entry", "group=deploy")
        assert result.exit_code == 2

    def test_no_selection_and_no_terminal_is_refused(
        self, mock_origin: MockVault, sender: Project
    ) -> None:
        result = _run(sender, "share", "--origin", mock_origin.origin)
        assert result.exit_code == 2
        assert "--entry" in result.output and "--all" in result.output
        assert mock_origin.requests == []

    def test_a_bad_selector_is_a_usage_error(self, sender: Project) -> None:
        result = _run(sender, "share", "--entry", "job=deploy.app")
        assert result.exit_code == 2
        assert "group=deploy,job=app" in result.output

    def test_a_selector_matching_nothing_shares_nothing(
        self, mock_origin: MockVault, sender: Project
    ) -> None:
        result = _run(
            sender, "share", "--entry", "group=nosuch", "--origin", mock_origin.origin
        )
        assert result.exit_code == 3
        assert mock_origin.requests == []

    def test_sub_hour_expiry_is_refused(self, sender: Project) -> None:
        result = _run(sender, "share", "--all", "--expires", "30m")
        assert result.exit_code == 2

    def test_the_checklist_starts_empty_and_shares_what_is_ticked(
        self, mock_origin: MockVault, sender: Project, at_a_terminal: None
    ) -> None:
        # Rows: 1 group deploy · 2 token · 3 job app · 4 api_key · 5 group
        # deploy.infra · 6 region_key · 7 job myjob · 8 api_key
        result = _run(sender, "share", "--json", "--origin", mock_origin.origin)
        assert result.exit_code == 2  # --json is never interactive

        result = _run(sender, "share", "--origin", mock_origin.origin, input="2\n\n")
        assert result.exit_code == 0, result.output
        assert "(nothing selected)" in result.output
        assert "[ ]" in result.output
        assert _LINK_RE.search(result.output)

    def test_ticking_nothing_shares_nothing(
        self, mock_origin: MockVault, sender: Project, at_a_terminal: None
    ) -> None:
        result = _run(sender, "share", "--origin", mock_origin.origin, input="\n")
        assert result.exit_code == 2
        assert mock_origin.requests == []


class TestRedeemIntoTheVault:
    def test_the_checklist_starts_with_every_storable_entry(
        self,
        mock_origin: MockVault,
        sender: Project,
        receiver: Project,
        at_a_terminal: None,
    ) -> None:
        from functualize.app.vault import _read_value

        link = _share(mock_origin, sender, "group=deploy")
        result = _run(receiver, "redeem", link, input="\n")

        assert result.exit_code == 0, result.output
        assert result.output.count("stored     ") == 3
        app, root = receiver
        assert _read_value(app, _TOKEN, cwd=root) == f"{_SECRET}-token"
        assert _SECRET not in result.output

    def test_an_existing_entry_starts_unticked_and_is_kept(
        self,
        mock_origin: MockVault,
        sender: Project,
        receiver: Project,
        at_a_terminal: None,
    ) -> None:
        from functualize.app.vault import _read_value

        app, root = receiver
        vault_put(app, _TOKEN, "bobs-own", cwd=root)
        link = _share(mock_origin, sender, "group=deploy,field=token")

        result = _run(receiver, "redeem", link, input="\n")

        assert "exists, would replace" in result.output
        assert "Nothing was stored" in result.output
        assert _read_value(app, _TOKEN, cwd=root) == "bobs-own"

    def test_yes_stores_everything_storable_without_a_terminal(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        link = _share(mock_origin, sender)
        result = _run(receiver, "redeem", link, "-y", "--json")

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert len(payload["stored"]) == 4
        assert _SECRET not in result.output

    def test_only_stores_a_subset(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        link = _share(mock_origin, sender)
        result = _run(receiver, "redeem", link, "--only", "job=myjob", "--json")

        payload = json.loads(result.stdout)
        assert payload["stored"] == ["prod: --job myjob --field api_key"]
        assert len(payload["skipped"]) == 3

    def test_no_terminal_and_no_flag_is_refused_before_the_burn(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        link = _share(mock_origin, sender)
        result = _run(receiver, "redeem", link)

        assert result.exit_code == 2
        assert "-y" in result.output and "--print-only" in result.output
        assert _redeem_posts(mock_origin) == 0

    def test_an_environment_mismatch_is_refused_before_the_burn(
        self,
        mock_origin: MockVault,
        sender: Project,
        receiver: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        link = _share(mock_origin, sender)
        monkeypatch.setenv("FUNCTUALIZE_ENV", "staging")
        _, root = receiver

        result = _run((_app(root), root), "redeem", link, "-y")

        assert result.exit_code == 3
        assert "FUNCTUALIZE_ENV=prod" in result.output
        assert _redeem_posts(mock_origin) == 0

    def test_no_project_is_refused_before_the_burn(
        self, mock_origin: MockVault, sender: Project, tmp_path: Path
    ) -> None:
        link = _share(mock_origin, sender)
        empty = _project(tmp_path / "empty")

        result = _run((_app(empty), empty), "redeem", link, "-y")

        assert result.exit_code == 2
        assert _redeem_posts(mock_origin) == 0

    def test_a_spent_share_exits_refused_without_a_second_burn(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        link = _share(mock_origin, sender)
        assert _run(receiver, "redeem", link, "-y").exit_code == 0

        result = _run(receiver, "redeem", link, "-y")
        assert result.exit_code == 3
        assert _redeem_posts(mock_origin) == 1

    def test_a_synced_entry_says_where_from_and_is_replaced_with_replace(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        from functualize._config.vault import SecretsVault
        from functualize._config.vault_key_resolver import resolve_vault_key
        from functualize._config.vault_paths import vault_path_for_project

        app, root = receiver
        key = resolve_vault_key("ignored").key
        assert key is not None
        SecretsVault(vault_path_for_project(root)).put(
            VaultIdentity("group", "deploy", "token", "prod").encode(),
            "from-aws",
            encryption_key=key,
            annotation="aws-sm://shared/deploy-token",
            provider="aws-sm",
        )
        link = _share(mock_origin, sender, "group=deploy,field=token")

        result = _run(receiver, "redeem", link, "-y", "--replace")

        assert result.exit_code == 0, result.output
        assert "was synced" in result.output

    @pytest.mark.parametrize(
        "flags",
        [
            ("--print-only", "--dotenv", "x.env"),
            ("-y", "--only", "job=myjob"),
            ("--print-only", "-y"),
        ],
    )
    def test_conflicting_options_are_usage_errors(
        self, receiver: Project, flags: tuple[str, ...]
    ) -> None:
        link = "https://example.test/s/" + "0" * 32 + "#k1." + "A" * 43
        assert _run(receiver, "redeem", link, *flags).exit_code == 2

    def test_yes_with_everything_existing_still_says_the_link_is_spent(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        from functualize.app.vault import _read_value

        app, root = receiver
        for identity, value in (
            (_TOKEN, "own-token"),
            (_APP_KEY, "own-app-key"),
            (_REGION, "own-region"),
            (_MY_KEY, "own-mine"),
        ):
            vault_put(app, identity, value, cwd=root)
        link = _share(mock_origin, sender)

        result = _run(receiver, "redeem", link, "-y")

        assert result.exit_code == 0, result.output
        assert (
            "Nothing was stored. The link's redemption was already used."
            in result.output
        )
        assert _read_value(app, _TOKEN, cwd=root) == "own-token"
        assert _redeem_posts(mock_origin) == 1

    def test_only_collisions_without_replace_still_say_the_link_is_spent(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        from functualize.app.vault import _read_value

        app, root = receiver
        vault_put(app, _TOKEN, "own-token", cwd=root)
        link = _share(mock_origin, sender)

        result = _run(
            receiver,
            "redeem",
            link,
            "--only",
            "group=deploy,field=token",
        )

        assert result.exit_code == 0, result.output
        assert (
            "Nothing was stored. The link's redemption was already used."
            in result.output
        )
        assert _read_value(app, _TOKEN, cwd=root) == "own-token"
        assert _redeem_posts(mock_origin) == 1


class TestRedeemElsewhere:
    def test_print_only_uses_the_run_time_variable_names(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        link = _share(mock_origin, sender, "group=deploy")
        result = _run(receiver, "redeem", link, "--print-only")

        assert result.exit_code == 0, result.output
        assert f"export DEPLOY__TOKEN={_SECRET}-token" in result.stdout
        assert f"export DEPLOY_APP_API_KEY={_SECRET}-api_key" in result.stdout
        assert f"export DEPLOY_INFRA__REGION_KEY={_SECRET}-region_key" in result.stdout

    def test_print_only_works_outside_a_project(
        self, mock_origin: MockVault, sender: Project, tmp_path: Path
    ) -> None:
        link = _share(mock_origin, sender, "job=myjob")
        empty = _project(tmp_path / "empty")

        result = _run((_app(empty), empty), "redeem", link, "--print-only")
        assert result.exit_code == 0, result.output
        assert "export MYJOB_API_KEY=" in result.stdout

    def test_json_print_only_never_carries_values(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        link = _share(mock_origin, sender)
        result = _run(receiver, "redeem", link, "--print-only", "--json")

        assert result.exit_code == 0, result.output
        assert _SECRET not in result.output
        assert "MYJOB_API_KEY" in json.loads(result.stdout)["names"]

    def test_dotenv_writes_a_0600_file_and_stores_nothing(
        self,
        mock_origin: MockVault,
        sender: Project,
        receiver: Project,
        tmp_path: Path,
    ) -> None:
        from functualize.app.utils import vault_entries

        link = _share(mock_origin, sender, "job=myjob")
        target = tmp_path / "out.env"

        result = _run(receiver, "redeem", link, "--dotenv", str(target))

        assert result.exit_code == 0, result.output
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert target.read_text() == f"MYJOB_API_KEY={_SECRET}-api_key\n"
        assert vault_entries(receiver[1]) == []

    @pytest.mark.parametrize(
        "value",
        ["alpha'beta", "two words", "a#b", "a$b", "line1\nline2"],
        ids=["quote", "space", "hash", "dollar", "newline"],
    )
    def test_a_dotenv_value_round_trips_through_the_products_reader(
        self,
        mock_origin: MockVault,
        sender: Project,
        receiver: Project,
        tmp_path: Path,
        value: str,
    ) -> None:
        """`--dotenv` output is consumed by functualize's own dotenv reader
        (`dotenv_values`), not by a shell. A value holding a quote, a space,
        `#`, `$` or a newline must come back byte for byte."""
        from dotenv import dotenv_values

        app, root = sender
        vault_put(app, _MY_KEY, value, cwd=root, replace=True)
        link = _share(mock_origin, sender, "job=myjob")
        target = tmp_path / "out.env"

        result = _run(receiver, "redeem", link, "--dotenv", str(target))

        assert result.exit_code == 0, result.output
        assert dotenv_values(target)["MYJOB_API_KEY"] == value

    @pytest.mark.parametrize("mode", ["--print-only", "--dotenv"])
    def test_a_value_with_metacharacters_round_trips_inertly(
        self,
        mock_origin: MockVault,
        sender: Project,
        receiver: Project,
        tmp_path: Path,
        mode: str,
    ) -> None:
        """A redeemed value may carry anything — a quote, a space, `#`, `$`,
        a newline. The consumer decides the encoding: `--print-only` lines
        are sourced by a POSIX shell and must stay inert; the `--dotenv`
        file is read by functualize's own dotenv reader and must round-trip
        byte for byte through it."""
        sentinel = "$(touch pwned) 'q s' \"d\" a#b $HOME\nline2; rm -rf x"
        app, root = sender
        vault_put(app, _MY_KEY, sentinel, cwd=root, replace=True)
        link = _share(mock_origin, sender, "job=myjob")

        if mode == "--dotenv":
            target = tmp_path / "out.env"
            result = _run(receiver, "redeem", link, mode, str(target))
            assert result.exit_code == 0, result.output
            from dotenv import dotenv_values

            parsed = dotenv_values(target)
            assert parsed["MYJOB_API_KEY"] == sentinel
            assert not (tmp_path / "pwned").exists()
            assert not (tmp_path / "pwned2").exists()
            return

        result = _run(receiver, "redeem", link, mode)
        text = result.stdout
        assert result.exit_code == 0, result.output

        words = shlex.split(text)
        assert words[::2] == ["export"] * (len(words) // 2)
        assignments = words[1::2]
        assert assignments == [f"MYJOB_API_KEY={sentinel}"]

        if shutil.which("sh"):
            sourced = tmp_path / "out.sh"
            sourced.write_text(text)
            probe = '. "$1"; printf %s "$MYJOB_API_KEY"'
            run = subprocess.run(
                ["sh", "-c", probe, "sh", str(sourced)],
                capture_output=True,
                cwd=tmp_path,
            )
            assert run.returncode == 0, run.stderr
            assert run.stdout == sentinel.encode()
            assert not (tmp_path / "pwned").exists()
            assert not (tmp_path / "pwned2").exists()


class TestShow:
    def test_previews_without_burning(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        link = _share(mock_origin, sender)
        result = _run(receiver, "show", link)

        assert result.exit_code == 0, result.output
        assert "env:prod" in result.output
        assert _redeem_posts(mock_origin) == 0

    def test_a_spent_share_previews_as_gone(
        self, mock_origin: MockVault, sender: Project, receiver: Project
    ) -> None:
        link = _share(mock_origin, sender)
        _run(receiver, "redeem", link, "-y")

        assert _run(receiver, "show", link).exit_code == 3


class TestOrigin:
    def test_a_foreign_origin_link_warns_but_redeems(
        self,
        mock_origin: MockVault,
        sender: Project,
        receiver: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        link = _share(mock_origin, sender)
        monkeypatch.delenv("FUNC_VAULT_ORIGIN", raising=False)

        result = _run(receiver, "redeem", link, "-y")
        assert result.exit_code == 0, result.output
        assert "not the configured" in result.output

    def test_the_env_origin_is_honored_for_sharing(
        self,
        mock_origin: MockVault,
        sender: Project,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FUNC_VAULT_ORIGIN", mock_origin.origin)
        result = _run(sender, "share", "--all")

        assert result.exit_code == 0, result.output
        assert mock_origin.origin in result.output


class TestFragmentHygiene:
    def test_redeem_and_show_never_emit_the_fragment(
        self,
        mock_origin: MockVault,
        sender: Project,
        receiver: Project,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        with caplog.at_level(logging.DEBUG, logger="functualize"):
            args = ("--all", "--redemptions", "2", "--origin", mock_origin.origin)
            result = _run(sender, "share", *args)
            link = _LINK_RE.search(result.output).group(1)  # type: ignore[union-attr]
            for verb in (("show", link), ("redeem", link, "-y")):
                result = _run(receiver, *verb)
                assert result.exit_code == 0, result.output
                assert "k1." not in result.output
        fragment = link[link.index("#") + 1 :]
        tape = "\n".join(record.getMessage() for record in caplog.records)
        assert fragment not in tape
        assert "k1." not in tape
