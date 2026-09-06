"""V6 — the `builtin vault` family (ADR-016).

Until this landed, every piece of the remote layer worked and none of it was
reachable: the chain was wired, three provider plugins were installed, and
nothing ever *filled* the vault, so every declared remote value fell through
with the 3.2 warning. `sync` is what makes the feature exist.

The governing constraint is ADR-008, and it is met structurally rather than by
care. `list` and `status` are never handed a decrypted value — they read the
cleartext metadata columns, which is also what lets them answer on a machine
with no key. `sync` writes values and returns none. So the surfaces cannot
render a secret, rather than being trusted not to.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
import pytest
from click.testing import CliRunner, Result

from functualize._app.state import AppState
from functualize._cli.builtins import (
    BUILTIN_COMMANDS,
    register_builtin_commands,
)
from functualize._config.registry import ProviderRegistry
from functualize._config.vault import KEY_BYTES, SecretsVault
from functualize.app.core import FunctualizeApp
from functualize.app.presets import remote_first
from functualize.app.utils import ExitCode, vault_location

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_KEY = b"\x2b" * KEY_BYTES
_KEY_HEX = _KEY.hex()

#: If this appears in any surface's output, a secret was rendered. Long and
#: distinctive on purpose: a short value can satisfy a leak assertion by
#: coincidence.
_CONSPICUOUS = "PLAINTEXT-91c40de2-must-never-be-printed"  # gitleaks:allow

_CONFIG = """
[report]
password = "fake-sm://prod/db-password"
username = "app"
endpoint = "https://api.example.com"
"""


class _FakeProvider:
    """Stands in for `functualize-aws`, registered where entry points would put
    it so these tests do not depend on which plugins happen to be installed."""

    def __init__(
        self,
        identifier: str = "fake-sm",
        *,
        ready: bool = True,
        raises: Exception | None = None,
        value: str = _CONSPICUOUS,
    ) -> None:
        self._identifier = identifier
        self._ready = ready
        self._raises = raises
        self._value = value
        self.fetched: list[str] = []

    def identifier(self) -> str:
        return self._identifier

    def is_ready(self) -> bool:
        return self._ready

    def fetch(self, reference: str) -> str:
        self.fetched.append(reference)
        if self._raises is not None:
            raise self._raises
        return self._value


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """An isolated project with its own XDG data dir and a vault key."""
    root = tmp_path / "project"
    (root / ".functualize").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("FUNCTUALIZE_VAULT_KEY", _KEY_HEX)
    monkeypatch.delenv("FUNCTUALIZE_VAULT_MAX_AGE", raising=False)
    monkeypatch.chdir(root)
    (root / "config.dev.toml").write_text(_CONFIG)
    AppState.reset()
    yield root
    AppState.reset()


@pytest.fixture
def register(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[_FakeProvider]]:
    """Install fake providers where the entry-point scan would find them."""

    def _install(*providers: _FakeProvider) -> list[_FakeProvider]:
        chosen = list(providers) or [_FakeProvider()]

        def _discover(self: ProviderRegistry) -> None:
            for provider in chosen:
                self.register_remote_provider(provider)

        monkeypatch.setattr(
            ProviderRegistry, "_discover_remote_entry_points", _discover
        )
        return chosen

    return _install


def _cli() -> click.Group:
    group = click.Group(name="func")
    register_builtin_commands(group)
    return group


def _app() -> FunctualizeApp:
    return FunctualizeApp("vaulttest", config_sources=remote_first())


def _run(args: list[str], *, app: Any = None, stdin: str | None = None) -> Result:
    return CliRunner().invoke(
        _cli(),
        ["builtin", "vault", *args],
        obj={"app": app} if app else {},
        input=stdin,
    )


def _seed_vault(**entries: str) -> Path:
    """Write straight to the store, so `list`/`status` tests need no sync."""
    path = vault_location()
    vault = SecretsVault(path)
    for key, annotation in entries.items():
        vault.put(
            key.replace("__", "."),
            _CONSPICUOUS,
            annotation=annotation,
            provider="fake-sm",
            encryption_key=_KEY,
        )
    return path


class _PretendTerminal:
    """A stand-in for the `sys` module `resolve_vault_key` reads.

    It consults `sys.stdin.isatty() and sys.stdout.isatty()` to decide whether
    an interactive key provider may be consulted at all, and under `CliRunner`
    neither is a tty. Tests that need the *explicit* non-interactive argument
    to be the thing doing the work substitute this.
    """

    class _Tty:
        @staticmethod
        def isatty() -> bool:
            return True

    stdin = _Tty()
    stdout = _Tty()


def _backdate(path: Path, delta: timedelta) -> None:
    stamp = (datetime.now(UTC) - delta).isoformat()
    conn = sqlite3.connect(path)
    with conn:
        conn.execute("UPDATE secrets SET synced_at = ?", (stamp,))
    conn.close()


# ---------------------------------------------------------------------------
# The family is declared, not just mounted
# ---------------------------------------------------------------------------


class TestTheFamilyIsRegistered:
    def test_vault_is_a_builtin_child(self) -> None:
        assert "vault" in {command.name for command in BUILTIN_COMMANDS}

    def test_every_declared_subcommand_exists(self) -> None:
        """Derived from the table, so declaring a subcommand and forgetting to
        build it fails here rather than at a user's terminal."""
        declared = next(c for c in BUILTIN_COMMANDS if c.name == "vault")
        group = _cli().commands["builtin"].commands["vault"]  # type: ignore[attr-defined]
        assert set(declared.subcommand_map) == set(group.commands)

    def test_it_requires_a_subcommand(self) -> None:
        declared = next(c for c in BUILTIN_COMMANDS if c.name == "vault")
        assert declared.requires_subcommand is True

    def test_nothing_here_takes_the_terminal(self) -> None:
        """`keygen` writes to stdout so it can be piped, and the interactive
        key provider is the OS keychain, which prompts outside this process."""
        declared = next(c for c in BUILTIN_COMMANDS if c.name == "vault")
        assert declared.terminal_subcommands == ()

    def test_the_five_documented_names(self) -> None:
        declared = next(c for c in BUILTIN_COMMANDS if c.name == "vault")
        assert set(declared.subcommand_map) == {
            "sync",
            "list",
            "status",
            "clear",
            "keygen",
        }


# ---------------------------------------------------------------------------
# keygen
# ---------------------------------------------------------------------------


class TestKeygen:
    def test_it_prints_a_64_character_hex_key(self) -> None:
        result = _run(["keygen"])
        assert result.exit_code == 0
        assert re.fullmatch(r"[0-9a-f]{64}", result.output.strip())

    def test_that_is_32_bytes(self) -> None:
        assert len(bytes.fromhex(_run(["keygen"]).output.strip())) == KEY_BYTES

    def test_each_call_is_different(self) -> None:
        assert _run(["keygen"]).output != _run(["keygen"]).output

    def test_nothing_but_the_key_is_printed(self) -> None:
        """It has to be pipeable — `export FUNCTUALIZE_VAULT_KEY=$(… keygen)`
        breaks the moment a friendly banner joins it."""
        assert len(_run(["keygen"]).output.strip().splitlines()) == 1

    def test_the_key_it_prints_actually_opens_a_vault(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A generator that emits a well-shaped key the store rejects would
        pass every test above."""
        generated = _run(["keygen"]).output.strip()
        path = vault_location()
        vault = SecretsVault(path)
        vault.put(
            "a.b",
            "value",
            annotation="fake-sm://x",
            provider="fake-sm",
            encryption_key=bytes.fromhex(generated),
        )
        assert vault.get("a.b", encryption_key=bytes.fromhex(generated)) == "value"

    def test_it_needs_no_project_and_no_app(self) -> None:
        assert _run(["keygen"], app=None).exit_code == 0


# ---------------------------------------------------------------------------
# list — the acceptance criterion
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("project")
class TestList:
    def test_an_empty_vault_says_so_and_names_the_fix(self) -> None:
        result = _run(["list"])
        assert result.exit_code == 0
        assert "vault sync" in result.output

    def test_it_renders_the_key_provider_and_timestamp(self) -> None:
        _seed_vault(report__password="fake-sm://prod/db-password")
        result = _run(["list"])
        assert "report.password" in result.output
        assert "fake-sm" in result.output
        assert str(datetime.now(UTC).year) in result.output

    def test_no_value_appears_in_the_text_output(self) -> None:
        _seed_vault(report__password="fake-sm://prod/db-password")
        assert _CONSPICUOUS not in _run(["list"]).output

    def test_json_renders_names_providers_and_synced_at(self) -> None:
        """The acceptance criterion's first half."""
        _seed_vault(
            report__password="fake-sm://prod/db-password",
            report__token="fake-sm://prod/token",
        )
        payload = json.loads(_run(["list", "--json"]).output)
        entries = {e["key"]: e for e in payload["entries"]}
        assert set(entries) == {"report.password", "report.token"}
        for entry in entries.values():
            assert entry["provider"] == "fake-sm"
            assert entry["annotation"].startswith("fake-sm://")
            datetime.fromisoformat(entry["synced_at"])

    def test_no_value_appears_anywhere_in_the_json_payload(self) -> None:
        """The acceptance criterion's second half, asserted against the *whole*
        serialised document rather than field by field — a leak that arrives
        through a field nobody thought to check is exactly the kind this must
        catch."""
        _seed_vault(report__password="fake-sm://prod/db-password")
        raw = _run(["list", "--json"]).output
        assert _CONSPICUOUS not in raw
        assert "value" not in json.loads(raw)["entries"][0]

    def test_the_json_names_the_vault_file(self) -> None:
        _seed_vault(report__password="fake-sm://prod/db")
        assert json.loads(_run(["list", "--json"]).output)["path"].endswith("vault.db")

    def test_it_works_with_no_key_at_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The headline reason the metadata columns are cleartext: a machine
        that cannot open the vault can still be told what is in it."""
        _seed_vault(report__password="fake-sm://prod/db-password")
        monkeypatch.delenv("FUNCTUALIZE_VAULT_KEY")
        result = _run(["list"])
        assert result.exit_code == 0
        assert "report.password" in result.output

    def test_it_needs_no_app(self) -> None:
        _seed_vault(report__password="fake-sm://prod/db")
        assert _run(["list"], app=None).exit_code == 0

    def test_it_is_ordered_by_key(self) -> None:
        _seed_vault(
            z__last="fake-sm://z", a__first="fake-sm://a", m__middle="fake-sm://m"
        )
        keys = [
            e["key"] for e in json.loads(_run(["list", "--json"]).output)["entries"]
        ]
        assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("project")
class TestStatus:
    def test_a_project_that_never_synced(self) -> None:
        result = _run(["status"])
        assert result.exit_code == 0
        assert "Exists:       no" in result.output
        assert "never" in result.output

    def test_it_names_the_key_provider_in_use(self) -> None:
        _seed_vault(report__password="fake-sm://prod/db")
        assert "env" in _run(["status"]).output

    def test_it_says_when_no_key_is_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FUNCTUALIZE_VAULT_KEY")
        _seed_vault(report__password="fake-sm://prod/db")
        assert "(none available)" in _run(["status"]).output

    def test_it_counts_the_entries(self) -> None:
        _seed_vault(a__one="fake-sm://a", b__two="fake-sm://b")
        assert "Entries:      2" in _run(["status"]).output

    def test_a_stale_vault_is_marked_and_says_what_to_do(self) -> None:
        path = _seed_vault(report__password="fake-sm://prod/db")
        _backdate(path, timedelta(days=3))
        output = _run(["status"]).output
        assert "stale" in output
        assert "vault sync" in output

    def test_a_fresh_vault_is_not_marked(self) -> None:
        _seed_vault(report__password="fake-sm://prod/db")
        assert "stale" not in _run(["status"]).output

    def test_json_carries_the_report(self) -> None:
        path = _seed_vault(report__password="fake-sm://prod/db")
        _backdate(path, timedelta(days=3))
        payload = json.loads(_run(["status", "--json"]).output)
        assert payload["exists"] is True
        assert payload["entries"] == 1
        assert payload["key_provider"] == "env"
        assert payload["stale"] is True
        assert payload["age_seconds"] >= 3 * 86400
        assert payload["max_age_seconds"] == 86400

    def test_no_value_appears_in_either_rendering(self) -> None:
        _seed_vault(report__password="fake-sm://prod/db")
        assert _CONSPICUOUS not in _run(["status"]).output
        assert _CONSPICUOUS not in _run(["status", "--json"]).output

    def test_it_answers_without_an_app(self) -> None:
        """The moment you most want to ask 'what is in my vault?' is when the
        app will not boot."""
        _seed_vault(report__password="fake-sm://prod/db")
        result = _run(["status"], app=None)
        assert result.exit_code == 0
        assert "Entries:      1" in result.output

    def test_with_an_app_it_names_the_registered_providers(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register(_FakeProvider("fake-sm"), _FakeProvider("fake-ssm"))
        result = _run(["status"], app=_app())
        assert "fake-sm" in result.output
        assert "fake-ssm" in result.output

    def test_the_app_threshold_reaches_the_report(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        app = FunctualizeApp("vaulttest", config_sources=remote_first(max_age="30d"))
        payload = json.loads(_run(["status", "--json"], app=app).output)
        assert payload["max_age_seconds"] == 30 * 86400

    def test_it_never_consults_an_interactive_key_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A status command that can raise a keychain prompt is a status
        command that can hang a script.

        The terminal is **forced on** for this test, and that is the whole
        point: without it the test was vacuous. `CliRunner` supplies a stdin
        that is not a tty, so `resolve_vault_key`'s own default already
        declines to go interactive — and the test passed with
        `allow_interactive=False` deleted. Sabotage caught it. Pretending to be
        a terminal is what makes the explicit argument the only thing standing
        between `status` and a prompt.
        """
        monkeypatch.delenv("FUNCTUALIZE_VAULT_KEY")
        calls: list[str] = []

        class _Prompting:
            def identifier(self) -> str:
                return "prompting"

            def interactive(self) -> bool:
                return True

            def is_available(self) -> bool:
                return True

            def get_key(self, project_id: str) -> bytes:
                calls.append(project_id)
                return _KEY

        monkeypatch.setattr(
            "functualize._config.vault_keys.default_providers",
            lambda: (_Prompting(),),
        )
        monkeypatch.setattr("functualize._config.vault_keys.sys", _PretendTerminal())
        _run(["status"])
        assert calls == []

    def test_the_forced_terminal_really_would_reach_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The control for the test above. If pretending to be a terminal did
        not actually enable interactive resolution, the assertion there would
        be vacuous again for a new reason."""
        monkeypatch.delenv("FUNCTUALIZE_VAULT_KEY")
        calls: list[str] = []

        class _Prompting:
            def identifier(self) -> str:
                return "prompting"

            def interactive(self) -> bool:
                return True

            def is_available(self) -> bool:
                return True

            def get_key(self, project_id: str) -> bytes:
                calls.append(project_id)
                return _KEY

        monkeypatch.setattr(
            "functualize._config.vault_keys.default_providers",
            lambda: (_Prompting(),),
        )
        monkeypatch.setattr("functualize._config.vault_keys.sys", _PretendTerminal())
        from functualize._config.vault_keys import resolve_vault_key

        assert resolve_vault_key("project") is not None
        assert calls == ["project"]


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("project")
class TestClear:
    def test_it_asks_first(self) -> None:
        path = _seed_vault(report__password="fake-sm://prod/db")
        result = _run(["clear"], stdin="n\n")
        assert result.exit_code == 0
        assert path.exists()
        assert "Left alone" in result.output

    def test_confirming_deletes_it(self) -> None:
        path = _seed_vault(report__password="fake-sm://prod/db")
        result = _run(["clear"], stdin="y\n")
        assert result.exit_code == 0
        assert not path.exists()

    def test_yes_skips_the_prompt(self) -> None:
        path = _seed_vault(report__password="fake-sm://prod/db")
        result = _run(["clear", "--yes"])
        assert result.exit_code == 0
        assert not path.exists()

    def test_the_default_answer_is_no(self) -> None:
        """A bare newline must not delete the vault."""
        path = _seed_vault(report__password="fake-sm://prod/db")
        _run(["clear"], stdin="\n")
        assert path.exists()

    def test_the_wal_sidecars_go_too(self) -> None:
        """A `-wal` left behind holds the rows the main file was checkpointed
        from; deleting only `vault.db` leaves the secrets on disk."""
        path = _seed_vault(report__password="fake-sm://prod/db")
        sidecars = [path.with_name(path.name + s) for s in ("-wal", "-shm")]
        assert any(s.exists() for s in sidecars), "no sidecar to test against"
        _run(["clear", "--yes"])
        assert not any(s.exists() for s in sidecars)

    def test_no_vault_is_not_an_error(self) -> None:
        result = _run(["clear", "--yes"])
        assert result.exit_code == 0
        assert "No vault to clear" in result.output


# ---------------------------------------------------------------------------
# sync — the command that makes the feature exist
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("project")
class TestSync:
    def test_it_fetches_a_declared_annotation_and_stores_it(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        providers = register()
        result = _run(["sync"], app=_app())

        assert result.exit_code == 0
        assert providers[0].fetched == ["prod/db-password"]
        assert (
            SecretsVault(vault_location()).get("report.password", encryption_key=_KEY)
            == _CONSPICUOUS
        )

    def test_the_reference_reaches_the_provider_untouched(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        """Core must stay opaque to the reference — that opacity is what makes
        the AWS provider's `?profile=` and role ARNs possible."""
        providers = register()
        (project / "config.dev.toml").write_text(
            '[report]\nkey = "fake-sm://p/db?role=arn:aws:iam::1:role/D&region=eu-west-1"\n'
        )
        _run(["sync"], app=_app())
        assert providers[0].fetched == [
            "p/db?role=arn:aws:iam::1:role/D&region=eu-west-1"
        ]

    def test_an_ordinary_url_is_not_synced(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        """`https://api.example.com` is annotation-*shaped*. Syncing it would
        make every URL in a config file a credential lookup."""
        register()
        _run(["sync"], app=_app())
        stored = {e.key for e in SecretsVault(vault_location()).list_entries()}
        assert stored == {"report.password"}

    def test_a_literal_is_not_synced(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        _run(["sync"], app=_app())
        assert "report.username" not in {
            e.key for e in SecretsVault(vault_location()).list_entries()
        }

    def test_an_annotation_in_an_environment_variable_is_not_synced(
        self,
        monkeypatch: pytest.MonkeyPatch,
        register: Callable[..., list[_FakeProvider]],
    ) -> None:
        """Files only, deliberately. The vault sits *above* Env in the chain
        `remote_first()` builds, so syncing an env-declared annotation would
        make the vault answer instead — and re-exporting the variable would
        silently stop changing anything. A file annotation has no such
        surprise: the file is below Env either way."""
        register()
        monkeypatch.setenv("FUNCTUALIZE_REPORT_TOKEN", "fake-sm://prod/token")
        _run(["sync"], app=_app())
        stored = {e.key for e in SecretsVault(vault_location()).list_entries()}
        assert "report.token" not in stored

    def test_it_records_the_annotation_and_the_provider_that_answered(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        _run(["sync"], app=_app())
        entry = SecretsVault(vault_location()).list_entries()[0]
        assert entry.annotation == "fake-sm://prod/db-password"
        assert entry.provider == "fake-sm"

    def test_it_reports_what_it_did(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        output = _run(["sync"], app=_app()).output
        assert "report.password" in output
        assert "1 synced" in output

    def test_no_value_reaches_the_output(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        result = _run(["sync"], app=_app())
        assert _CONSPICUOUS not in result.output

    def test_no_value_reaches_the_json_output(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        result = _run(["sync", "--json"], app=_app())
        assert _CONSPICUOUS not in result.output
        payload = json.loads(result.output)
        assert payload["synced"] == [{"key": "report.password", "provider": "fake-sm"}]
        assert payload["ok"] is True

    def test_re_syncing_refreshes_the_timestamp(
        self, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        _run(["sync"], app=_app())
        _backdate(vault_location(), timedelta(days=5))
        _run(["sync"], app=_app())
        age = SecretsVault(vault_location()).age()
        assert age is not None
        assert age < timedelta(minutes=1)


@pytest.mark.usefixtures("project")
class TestSyncFailures:
    def test_an_unregistered_provider_is_reported_and_fails_the_command(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        (project / "config.dev.toml").write_text(
            '[report]\nkey = "nope-sm://somewhere"\n'
        )
        result = _run(["sync"], app=_app())
        assert result.exit_code == ExitCode.REFUSED
        assert "nope-sm" in result.output

    def test_a_provider_error_is_collected_not_raised(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register(_FakeProvider(raises=RuntimeError("access denied")))
        result = _run(["sync"], app=_app())
        assert result.exit_code == ExitCode.REFUSED
        assert "access denied" in result.output

    def test_one_failure_does_not_abandon_the_others(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        """The whole reason failures are collected: an unreachable provider
        must not cost the twelve secrets that would have synced fine."""
        register(
            _FakeProvider("good-sm", value="ok"),
            _FakeProvider("bad-sm", raises=RuntimeError("boom")),
        )
        (project / "config.dev.toml").write_text(
            '[report]\nfirst = "bad-sm://a"\nsecond = "good-sm://b"\n'
        )
        result = _run(["sync"], app=_app())
        stored = {e.key for e in SecretsVault(vault_location()).list_entries()}
        assert stored == {"report.second"}
        assert result.exit_code == ExitCode.REFUSED

    def test_a_provider_that_is_not_ready_says_why(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register(_FakeProvider(ready=False))
        result = _run(["sync"], app=_app())
        assert "not ready" in result.output
        assert "credentials" in result.output

    def test_a_provider_that_is_not_ready_is_never_fetched_from(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        providers = register(_FakeProvider(ready=False))
        _run(["sync"], app=_app())
        assert providers[0].fetched == []

    def test_a_fallback_chain_moves_on_after_a_failure(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        providers = register(
            _FakeProvider("first-sm", raises=RuntimeError("nope")),
            _FakeProvider("second-sm", value="from-second"),
        )
        (project / "config.dev.toml").write_text(
            '[report]\nkey = "first-sm://a | second-sm://b"\n'
        )
        result = _run(["sync"], app=_app())

        assert result.exit_code == 0
        assert providers[1].fetched == ["b"]
        assert (
            SecretsVault(vault_location()).get("report.key", encryption_key=_KEY)
            == "from-second"
        )

    def test_an_exhausted_chain_reports_every_reason(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        """'It did not work' with only the last why makes the first provider
        look innocent."""
        register(
            _FakeProvider("first-sm", raises=RuntimeError("first-reason")),
            _FakeProvider("second-sm", raises=RuntimeError("second-reason")),
        )
        (project / "config.dev.toml").write_text(
            '[report]\nkey = "first-sm://a | second-sm://b"\n'
        )
        output = _run(["sync"], app=_app()).output
        assert "first-reason" in output
        assert "second-reason" in output

    def test_no_key_refuses_rather_than_pretending(
        self,
        monkeypatch: pytest.MonkeyPatch,
        register: Callable[..., list[_FakeProvider]],
    ) -> None:
        """With no key there is nothing to write into, and reporting a
        successful sync would leave an operator believing one happened."""
        register()
        app = _app()
        monkeypatch.delenv("FUNCTUALIZE_VAULT_KEY")
        monkeypatch.setattr(
            "functualize._config.vault_keys.default_providers", lambda: ()
        )
        result = _run(["sync"], app=app)

        assert result.exit_code == ExitCode.REFUSED
        assert "keygen" in result.output
        assert not vault_location().exists()

    def test_no_app_is_a_usage_error(self) -> None:
        result = _run(["sync"], app=None)
        assert result.exit_code == ExitCode.USAGE
        assert "app context" in result.output

    def test_nothing_declared_is_not_a_failure(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        register()
        (project / "config.dev.toml").write_text('[report]\nusername = "app"\n')
        result = _run(["sync"], app=_app())
        assert result.exit_code == 0
        assert "Nothing to sync" in result.output

    def test_nothing_declared_writes_no_vault(
        self, project: Path, register: Callable[..., list[_FakeProvider]]
    ) -> None:
        """A sync that stored nothing must not leave an empty file behind, or
        `status` reports a vault that exists and holds nothing."""
        register()
        (project / "config.dev.toml").write_text('[report]\nusername = "app"\n')
        _run(["sync"], app=_app())
        assert not vault_location().exists()
