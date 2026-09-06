"""V6 — a vault miss falls through, but never quietly (ADR-016).

The defect this feature exists to close is a job receiving a local value while
its author believes they are reading a secret store. Task 3.1 closed the
loudest form of that (a preset that silently *was* ``classic()``); this closes
the per-key form: the vault is wired, the provider is installed, and one key
was simply never synced.

The value that then reaches the job is usually the annotation itself —
``aws-sm://prod/db`` handed to a database driver as a password. That failure is
noisy at the far end and mute at the near one, which is precisely backwards.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from functualize._config.chain import ResolutionChain
from functualize._config.vault import KEY_BYTES, SecretsVault
from functualize._config.vault_source import VaultSource

_KEY = b"\x11" * KEY_BYTES
_PROVIDERS = ("fake-sm", "fake-ssm")

#: Long and distinctive on purpose. A short value like "s3cret" can pass a leak
#: assertion by coincidence — it is a substring of nothing and a substring of
#: everything is what we need to rule out. If this string appears anywhere in
#: the log record, something rendered a secret.
_CONSPICUOUS = "PLAINTEXT-e7c41d9a-must-never-be-logged"  # gitleaks:allow

_ANNOTATION = "fake-sm://prod/db-password"


class _StaticSource:
    """A minimal lower-priority source, standing in for env or file."""

    def __init__(self, source_type: str, source_id: str, values: dict[str, Any]):
        self.source_type = source_type
        self.source_id = source_id
        self._values = values

    def _qualified(self, key: str, section: str | None) -> str:
        return f"{section}.{key}" if section else key

    def get(self, key: str, section: str | None = None) -> Any | None:
        return self._values.get(self._qualified(key, section))

    def has(self, key: str, section: str | None = None) -> bool:
        return self._qualified(key, section) in self._values

    def keys(self, section: str) -> set[str]:
        prefix = f"{section}."
        return {k[len(prefix) :] for k in self._values if k.startswith(prefix)}


@pytest.fixture
def synced_vault(tmp_path: Path) -> Path:
    """A vault that opens and holds one unrelated key, so it is `usable`."""
    path = tmp_path / "vault.db"
    SecretsVault(path).put(
        "database.username",
        "app",
        annotation="fake-sm://prod/db-username",
        provider="fake-sm",
        encryption_key=_KEY,
    )
    return path


def _source(vault_path: Path, *, key: bytes | None = _KEY) -> VaultSource:
    return VaultSource(vault_path, encryption_key=key, providers=_PROVIDERS)


def _chain(vault: VaultSource, below: _StaticSource) -> ResolutionChain:
    return ResolutionChain([vault, below])  # type: ignore[list-item]


class TestTheFallThroughStillHappens:
    """Warning is the point; blocking is not. Offline work must keep working."""

    def test_the_next_sources_value_is_returned(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = _chain(_source(synced_vault), below)
        with caplog.at_level(logging.WARNING):
            resolved = chain.resolve("password", "database")
        assert resolved.value == _ANNOTATION
        assert resolved.source_type == "file"

    def test_a_warning_is_emitted_naming_the_annotation(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        with caplog.at_level(logging.WARNING):
            _chain(_source(synced_vault), below).resolve("password", "database")
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert _ANNOTATION in message
        assert "database.password" in message

    def test_the_warning_names_the_source_that_answered_instead(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """'It fell through' is not actionable; 'it fell through to X' is."""
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        with caplog.at_level(logging.WARNING):
            _chain(_source(synced_vault), below).resolve("password", "database")
        assert "config.dev.toml" in caplog.records[0].getMessage()

    def test_the_warning_names_the_fix(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        with caplog.at_level(logging.WARNING):
            _chain(_source(synced_vault), below).resolve("password", "database")
        assert "vault sync" in caplog.records[0].getMessage()

    def test_it_says_the_job_gets_the_annotation_not_the_secret(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The consequence is the part an operator acts on."""
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        with caplog.at_level(logging.WARNING):
            _chain(_source(synced_vault), below).resolve("password", "database")
        assert "literal annotation string" in caplog.records[0].getMessage()


class TestOncePerKeyPerRun:
    def test_ten_reads_warn_once(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = _chain(_source(synced_vault), below)
        with caplog.at_level(logging.WARNING):
            for _ in range(10):
                chain.resolve("password", "database")
        assert len(caplog.records) == 1

    def test_two_different_keys_warn_twice(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Deduplication is per key, not a one-shot latch for the whole run."""
        below = _StaticSource(
            "file",
            "config.dev.toml",
            {
                "database.password": _ANNOTATION,
                "api.token": "fake-ssm://prod/api-token",
            },
        )
        chain = _chain(_source(synced_vault), below)
        with caplog.at_level(logging.WARNING):
            chain.resolve("password", "database")
            chain.resolve("token", "api")
        assert len(caplog.records) == 2

    def test_introspect_shares_the_same_ledger(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`resolve` and `introspect` walk one body, so they cannot diverge."""
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = _chain(_source(synced_vault), below)
        with caplog.at_level(logging.WARNING):
            chain.resolve("password", "database")
            chain.introspect("password", "database")
        assert len(caplog.records) == 1

    def test_introspect_alone_warns(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Asserting only that the pair together warn *once* is vacuous — it
        passes just as well when `introspect` never warns at all. Caught by
        sabotage: giving `introspect` its own notification-free body left the
        shared-ledger test green.
        """
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = _chain(_source(synced_vault), below)
        with caplog.at_level(logging.WARNING):
            chain.introspect("password", "database")
        assert len(caplog.records) == 1
        assert _ANNOTATION in caplog.records[0].getMessage()


class TestNothingSecretIsRendered:
    """ADR-008 — `is_secret_field` stays the only redaction opinion, and this
    method sidesteps the question by rendering only annotations."""

    def test_a_secret_from_a_lower_source_never_reaches_the_log(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The annotation is in the file; an env var beats it with the secret.

        The key *is* declared remote, so this warns — and the warning must
        name the annotation while saying nothing about the value that won.
        """
        env = _StaticSource("env", "environ", {"database.password": _CONSPICUOUS})
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = ResolutionChain([_source(synced_vault), env, below])  # type: ignore[list-item]
        with caplog.at_level(logging.WARNING):
            resolved = chain.resolve("password", "database")
        assert resolved.value == _CONSPICUOUS
        assert len(caplog.records) == 1
        message = caplog.records[0].getMessage()
        assert _CONSPICUOUS not in message
        assert _ANNOTATION in message
        assert "env (environ)" in message

    def test_the_whole_log_record_is_clean_not_just_the_message(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A %s-style record carries its args separately from the message.

        Asserting only on `getMessage()` would miss a value smuggled in as an
        unused argument, which a formatter or a structured handler would then
        happily render.
        """
        env = _StaticSource("env", "environ", {"database.password": _CONSPICUOUS})
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = ResolutionChain([_source(synced_vault), env, below])  # type: ignore[list-item]
        with caplog.at_level(logging.WARNING):
            chain.resolve("password", "database")
        record = caplog.records[0]
        assert _CONSPICUOUS not in repr(record.args)
        assert _CONSPICUOUS not in record.msg


class TestOnlyDeclaredKeysWarn:
    """Precision is what keeps the warning readable. A vault misses on almost
    every key it is ever asked about."""

    def test_an_ordinary_key_is_silent(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        below = _StaticSource("file", "config.dev.toml", {"database.port": 5432})
        with caplog.at_level(logging.WARNING):
            _chain(_source(synced_vault), below).resolve("port", "database")
        assert caplog.records == []

    def test_an_ordinary_url_is_silent(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`https://…` parses as provider 'https' on shape alone. It is not
        an annotation, because `https` is not a registered provider."""
        below = _StaticSource(
            "file", "config.dev.toml", {"api.url": "https://api.example.com"}
        )
        with caplog.at_level(logging.WARNING):
            _chain(_source(synced_vault), below).resolve("url", "api")
        assert caplog.records == []

    def test_a_key_the_vault_holds_is_silent(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        below = _StaticSource("file", "config.dev.toml", {"database.username": "wrong"})
        with caplog.at_level(logging.WARNING):
            resolved = _chain(_source(synced_vault), below).resolve(
                "username", "database"
            )
        assert resolved.value == "app"
        assert resolved.source_type == "remote"
        assert caplog.records == []

    def test_an_unusable_vault_warns_per_run_not_per_key(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """With no key every lookup falls through. Boot already said so once;
        repeating it per key would drown the message rather than sharpen it."""
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = _chain(_source(synced_vault, key=None), below)
        with caplog.at_level(logging.WARNING):
            resolved = chain.resolve("password", "database")
        assert resolved.value == _ANNOTATION
        assert caplog.records == []

    def test_a_missing_key_everywhere_raises_rather_than_warning(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """MissingKeyError is louder than any warning this could emit."""
        from functualize._config.errors import MissingKeyError

        below = _StaticSource("file", "config.dev.toml", {})
        with caplog.at_level(logging.WARNING), pytest.raises(MissingKeyError):
            _chain(_source(synced_vault), below).resolve("password", "database")
        assert caplog.records == []


class TestTheFirstRunIsTheLoudestCase:
    """A key exported, `vault sync` never run — and nothing warned.

    Found by executing this feature's own documentation, not by a test. Every
    test in this file used the `synced_vault` fixture, whose docstring says
    outright that it exists "so it is `usable`" — so the one situation every
    new user meets first was the one situation no test covered.

    The cause was a single gate: `note_fallthrough` returned early on
    `usable`, which is `a key is available AND the file exists`. Its comment
    reasoned only about the missing-key half. The missing-*file* half is the
    opposite case: the key is there, nothing has been synced, and
    "run `vault sync`" is precisely the advice the warning gives.
    """

    def test_a_vault_that_was_never_synced_still_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = _chain(_source(tmp_path / "never-synced.db"), below)
        with caplog.at_level(logging.WARNING):
            resolved = chain.resolve("password", "database")

        assert resolved.value == _ANNOTATION
        assert len(caplog.records) == 1
        assert _ANNOTATION in caplog.records[0].getMessage()

    def test_the_warning_names_the_command_that_would_fix_it(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The whole reason this case must not be silent: unlike a missing
        key, it has a one-command fix that the message can name."""
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        with caplog.at_level(logging.WARNING):
            _chain(_source(tmp_path / "never-synced.db"), below).resolve(
                "password", "database"
            )
        assert "vault sync" in caplog.records[0].getMessage()

    def test_no_file_and_no_key_stays_silent(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The half that was right. Boot already warned; with no key every
        lookup falls through, so per-key warnings would drown it."""
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        chain = _chain(_source(tmp_path / "never-synced.db", key=None), below)
        with caplog.at_level(logging.WARNING):
            chain.resolve("password", "database")
        assert caplog.records == []

    def test_an_unsynced_vault_is_still_silent_about_ordinary_keys(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Opening the gate must not open it for everything: without the
        annotation test, a project that never synced would warn about every
        key it resolves."""
        below = _StaticSource("file", "config.dev.toml", {"database.port": "5432"})
        chain = _chain(_source(tmp_path / "never-synced.db"), below)
        with caplog.at_level(logging.WARNING):
            chain.resolve("port", "database")
        assert caplog.records == []

    def test_it_still_answers_nothing_and_creates_no_file(self, tmp_path: Path) -> None:
        """`usable` keeps both halves: opening a non-existent SQLite path
        would create one, and a source that reports `has()` and then yields
        None breaks the chain's contract."""
        path = tmp_path / "never-synced.db"
        source = _source(path)
        assert source.get("password", "database") is None
        assert source.has("password", "database") is False
        assert not path.exists()


class TestTheChainStaysGeneric:
    def test_a_source_without_the_hook_is_not_called(self, tmp_path: Path) -> None:
        """The hook is opt-in and duck-typed; `_StaticSource` lacks it."""
        a = _StaticSource("file", "a", {})
        b = _StaticSource("file", "b", {"x": 1})
        assert ResolutionChain([a, b]).resolve("x").value == 1  # type: ignore[list-item]

    def test_resolve_and_introspect_agree(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Including the alternatives, which is the whole point of the pair.

        Two sources below the vault both answer, so a body that stops at the
        winner returns an empty `alternatives` and fails here.
        """
        env = _StaticSource("env", "environ", {"database.password": _CONSPICUOUS})
        below = _StaticSource(
            "file", "config.dev.toml", {"database.password": _ANNOTATION}
        )
        with caplog.at_level(logging.WARNING):
            one = ResolutionChain([_source(synced_vault), env, below]).resolve(  # type: ignore[list-item]
                "password", "database"
            )
            two = ResolutionChain([_source(synced_vault), env, below]).introspect(  # type: ignore[list-item]
                "password", "database"
            )
        assert one == two
        assert one.alternatives == [("file", "config.dev.toml", _ANNOTATION)]


class TestFallthroughRecordsStillFeedDiagnostics:
    def test_misses_records_every_unanswered_key_not_just_warned_ones(
        self, synced_vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`misses` and the warning answer different questions; 4.1 renders
        the former, an operator reads the latter."""
        source = _source(synced_vault)
        below = _StaticSource(
            "file",
            "config.dev.toml",
            {"database.port": 5432, "database.password": _ANNOTATION},
        )
        chain = _chain(source, below)
        with caplog.at_level(logging.WARNING):
            chain.resolve("port", "database")
            chain.resolve("password", "database")
        assert source.misses == ["database.port", "database.password"]
        assert len(caplog.records) == 1
