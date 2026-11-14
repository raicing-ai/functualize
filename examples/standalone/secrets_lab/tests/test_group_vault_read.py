"""A job reading one target's group secret, through the published API only.

Everywhere else in this lab a secret reaches a job because the job *declared* a
field for it. ``publish`` cannot: it learns its target while it runs, so it asks
the injected ``Vault`` for that target's entry by address. This file drives that
through the same plain ``FunctualizeApp`` the rest of the lab uses, with no
``func`` process anywhere.

Three outcomes of the read differ in kind, and each is pinned here. An address
with nothing stored is recoverable — the job reports the skip and the run
succeeds. An entry that is stored and whose key does not open the store stops
the run, because a credential that exists but will not decrypt is a broken key,
not an absent one. And a store whose stored bytes no longer authenticate stops
it too, since damage to the file is not something a key can be corrected into.

No assertion names the stored value: the evidence is its length and the fact
that the marker appears in neither what the run returns nor what it raises.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from functualize.app import FunctualizeApp, JobSources
from functualize.app.core import request_for
from functualize.app.vault import (
    VaultDecryptionError,
    VaultEntryUnreadableError,
    VaultIdentity,
    vault_init,
    vault_put,
)
from functualize.types import JobResult, RunStatus

_ROOT = Path(__file__).parent.parent

#: Distinctive, so an assertion about absence is not satisfied by coincidence.
_MARKER = "lab-group-token-3d58c1-not-a-real-credential"  # gitleaks:allow

#: Stored for the group every target beneath it inherits.
_GROUP = "cloudflare.d1"

#: A target under that group, and one outside it.
_TARGET = "cloudflare.d1.main"
_ELSEWHERE = "cloudflare.eu.main"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """This lab's jobs, in a throwaway project with its own key and store.

    The **environment** key route, deliberately: it needs no OS keyring, so this
    runs identically on a laptop, in CI and in a container.
    """
    work = tmp_path / "lab"
    (work / ".functualize").mkdir(parents=True)
    (work / "jobs").mkdir()
    for name in ("sync.py", "report.py", "publish.py"):
        (work / "jobs" / name).write_text((_ROOT / "jobs" / name).read_text())
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("FUNCTUALIZE_VAULT_KEY", "ab" * 32)
    monkeypatch.chdir(work)
    return work


def _app(project: Path) -> FunctualizeApp:
    return FunctualizeApp(
        "secrets-lab",
        job_sources=JobSources(directories=[str(project / "jobs")], lazy=False),
    )


def _provision(app: FunctualizeApp) -> None:
    """Store a credential for the group, which is what every target inherits."""
    vault_init(key_source="env")
    vault_put(app, VaultIdentity("group", _GROUP, "api_token"), _MARKER)
    app.refresh()


def _store(project: Path) -> Path:
    """The file the app just wrote, found where the platform keeps it."""
    stores = sorted((project.parent / "data").rglob("vault.db"))
    assert len(stores) == 1, stores
    return stores[0]


def _succeeded(result: JobResult) -> JobResult:
    assert result.status is RunStatus.SUCCESS, result.exception
    return result


def test_the_job_reads_the_credential_its_target_inherits(project: Path) -> None:
    """The default target stores nothing itself; the group above it does."""
    app = _app(project)
    _provision(app)

    result = _succeeded(app.execute(request_for("publish")))

    assert result.return_value == (
        f"published to {_TARGET} with a {len(_MARKER)}-character credential"
    )
    assert _MARKER not in str(result.return_value)


def test_the_target_is_chosen_for_each_run(project: Path) -> None:
    """A second target reads the same stored entry, and is named by the run."""
    app = _app(project)
    _provision(app)

    result = _succeeded(
        app.execute(request_for("publish", target="cloudflare.d1.canary"))
    )

    assert result.return_value == (
        f"published to cloudflare.d1.canary with a {len(_MARKER)}-character credential"
    )


def test_an_address_with_nothing_stored_is_skipped(project: Path) -> None:
    """No entry for the target or any ancestor: recoverable, and reported."""
    app = _app(project)
    _provision(app)

    result = _succeeded(app.execute(request_for("publish", target=_ELSEWHERE)))

    assert result.return_value == f"skipped {_ELSEWHERE}"
    assert _MARKER not in str(result.return_value)


def test_a_stored_entry_that_cannot_be_opened_stops_the_run(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The entry is there and the key is wrong: absence handling must not hide it.

    The target outside the group still runs — its lookup never reaches the
    stored entry — so what fails below is the stored entry, not the vault.
    """
    app = _app(project)
    _provision(app)
    monkeypatch.setenv("FUNCTUALIZE_VAULT_KEY", "09" * 32)
    unreadable = _app(project)

    _succeeded(unreadable.execute(request_for("publish", target=_ELSEWHERE)))
    result = unreadable.execute(request_for("publish"))

    assert result.status is not RunStatus.SUCCESS
    assert isinstance(result.exception, VaultEntryUnreadableError)
    assert _MARKER not in str(result.exception)
    assert _MARKER not in str(result)


def test_a_store_whose_bytes_do_not_authenticate_stops_the_run(
    project: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """A damaged file, not a wrong key: nothing is skipped, and nothing leaks.

    A copy taken mid-write, or a restore that lost bytes, leaves the entry
    present while its ciphertext no longer authenticates. The key is the one
    that wrote it, so the wrong-key refusal above never runs and the decrypt
    fails on the value itself — a state no alternate key or retry resolves.
    Staging it means damaging the file, deliberately: no public call corrupts a
    store on purpose.
    """
    app = _app(project)
    _provision(app)

    with sqlite3.connect(_store(project)) as conn:
        rows = conn.execute("SELECT key, length(ciphertext) FROM secrets").fetchall()
        assert len(rows) == 1, rows
        key, size = rows[0]
        conn.execute(
            "UPDATE secrets SET ciphertext = ? WHERE key = ?",
            (b"\x00" * size, key),
        )

    damaged = _app(project)
    result = damaged.execute(request_for("publish"))

    assert result.status is not RunStatus.SUCCESS
    assert isinstance(result.exception, VaultDecryptionError)
    assert _MARKER not in str(result.exception)
    assert _MARKER not in str(result)
    captured = capfd.readouterr()
    assert _MARKER not in captured.out
    assert _MARKER not in captured.err
