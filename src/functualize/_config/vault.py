"""The encrypted local secrets vault (ADR-016).

Remote configuration values — an AWS Secrets Manager secret, an SSM parameter,
a Bitwarden item — are **synced into** this store, and jobs resolve against the
store rather than the network.

Why a cache and not a live fetch
--------------------------------

``FunctualizeApp()`` construction is ~73 ms, and ``RemoteSource`` carries a
30-second timeout. Resolving annotations live would put that timeout between
the operator and *every* job run, including runs of jobs that use no secret at
all. Here the network is touched when someone runs ``vault sync``, never
because a job ran, and a developer offline keeps working from what they last
synced.

What is encrypted, and what is not
----------------------------------

Only the **value**. ``key``, ``annotation``, ``provider`` and ``synced_at``
are stored in clear on purpose, so ``vault list`` can report what is held and
how fresh it is without the key being present. None of them is the secret —
knowing that ``database.password`` came from ``aws-sm://prod/db`` at 12:04
reveals nothing that the config file did not already say out loud. This is the
same split Turso's secrets vault makes between queryable metadata and an
unreadable value.

``audit_log`` never holds a value either.

Staleness
---------

``synced_at`` is what makes "how old is this?" answerable without the key, and
:meth:`SecretsVault.age` answers it from the **oldest** entry: a vault is only
as fresh as the value most likely to have been rotated behind it. Past
``[vault] max_age`` (default 24h) every run warns and **still runs** --
auto-syncing when stale was rejected in ADR-016 because it puts the network
back on the run path, which is the thing this store exists to remove.

Scope
-----

One vault per project, keyed by the same ``compute_project_id`` the discovery
cache uses. A repository you cloned to look at cannot read the secrets of a
project you actually work on.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from functualize._primitives.locator import _xdg_data_dir, compute_project_id

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "DEFAULT_MAX_AGE",
    "KEY_BYTES",
    "MAX_AGE_VAR",
    "InvalidDurationError",
    "SecretsVault",
    "VaultDecryptionError",
    "VaultEntry",
    "VaultError",
    "format_duration",
    "parse_duration",
    "resolve_max_age",
    "vault_path_for_project",
]

logger = logging.getLogger(__name__)

#: AES-256 takes a 32-byte key. `VaultKeyProvider.get_key` returns exactly this.
KEY_BYTES = 32

#: Default staleness threshold (``contracts.md`` §5, ADR-016). A vault whose
#: oldest entry is older than this makes every run warn -- and still run.
DEFAULT_MAX_AGE = "24h"

#: Environment override for :data:`DEFAULT_MAX_AGE`.
#:
#: Spelled exactly as the settings store would generate for a ``vault.max_age``
#: setting (``FUNCTUALIZE_<SECTION>_<KEY>``), so registering it in the catalog
#: later adds a file path without renaming anything an operator already uses.
MAX_AGE_VAR = "FUNCTUALIZE_VAULT_MAX_AGE"

#: Duration units, smallest first. Deliberately stops at weeks: months and
#: years are not fixed-length, and a staleness threshold that silently means
#: something different in February is worse than one that will not parse.
_DURATION_UNITS: tuple[tuple[str, int], ...] = (
    ("w", 604800),
    ("d", 86400),
    ("h", 3600),
    ("m", 60),
    ("s", 1),
)
_SECONDS_PER_UNIT = dict(_DURATION_UNITS)
_DURATION_TERM = re.compile(r"(\d+)([wdhms])")
_DURATION_RE = re.compile(r"(?:\d+[wdhms])+$")

#: AES-GCM's standard nonce width. A fresh one is drawn per write and stored
#: beside the ciphertext; reusing a nonce under one key destroys the security
#: of the mode entirely, so it is never derived from the key or the row.
_NONCE_BYTES = 12

_SCHEMA = """
CREATE TABLE IF NOT EXISTS secrets (
    key         TEXT PRIMARY KEY,
    annotation  TEXT NOT NULL,
    provider    TEXT NOT NULL,
    nonce       BLOB NOT NULL,
    ciphertext  BLOB NOT NULL,
    synced_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    ts        TEXT NOT NULL,
    key       TEXT NOT NULL,
    provider  TEXT,
    action    TEXT NOT NULL,
    outcome   TEXT NOT NULL
);
"""


class VaultError(Exception):
    """Base class for vault failures."""


class VaultDecryptionError(VaultError):
    """A stored value could not be authenticated with the supplied key.

    AES-GCM is authenticated, so a wrong key *fails* rather than returning
    plausible garbage. The message names the key provider in use, because "it
    did not decrypt" without saying which key was tried is the least useful
    thing this error could say.
    """


@dataclass(frozen=True)
class VaultEntry:
    """One stored secret's metadata. Deliberately carries no value.

    Returned by listing and status surfaces, which must be able to describe the
    vault without opening it.
    """

    key: str
    annotation: str
    provider: str
    synced_at: datetime


class InvalidDurationError(VaultError):
    """A duration string could not be read.

    Never fatal in practice: :func:`resolve_max_age` catches it, says which
    setting was unusable, and carries on. A misspelled *warning threshold* must
    not be more disruptive than the warning it governs.
    """


def parse_duration(text: str) -> timedelta:
    """Read a duration string such as ``"24h"``, ``"7d"`` or ``"1d12h"``.

    Args:
        text: One or more ``<integer><unit>`` terms, units ``w d h m s``.
            Case and internal whitespace are ignored, with one exception:
            an uppercase ``M`` is refused rather than folded to minutes.

    Returns:
        The total duration.

    Raises:
        InvalidDurationError: Empty, misspelled, or missing a unit. A bare
            number is refused rather than assumed: ``max_age = "3600"`` reads
            as an hour to whoever wrote it and as an hour of *seconds* or of
            *days* to whoever guesses, and the two disagree by a factor of 24.
            ``1M`` is refused for the same reason.
    """
    stripped = text.strip()
    if not stripped:
        msg = "A vault max_age cannot be empty."
        raise InvalidDurationError(msg)
    if "M" in stripped:
        # Case-folding is a convenience for `24H`, and it must not become a
        # trap: `1M` means one month to most people who write it, and folding
        # it to `m` would silently make it one minute -- a factor of 43,200.
        # Months are not a fixed length, so the answer is a refusal, not a unit.
        msg = (
            f"Cannot read {text!r} as a duration. 'M' is not a unit: a month "
            f"has no fixed length, and reading it as 'm' would silently mean "
            f"minutes. Write the number of days or weeks instead."
        )
        raise InvalidDurationError(msg)
    cleaned = stripped.lower().replace(" ", "")
    if not _DURATION_RE.fullmatch(cleaned):
        units = ", ".join(unit for unit, _ in _DURATION_UNITS)
        detail = (
            " A duration needs a unit."
            if cleaned.isdigit()
            else " Expected terms like '24h', '7d' or '1d12h'."
        )
        msg = f"Cannot read {text!r} as a duration.{detail} Units: {units}."
        raise InvalidDurationError(msg)
    seconds = sum(
        int(amount) * _SECONDS_PER_UNIT[unit]
        for amount, unit in _DURATION_TERM.findall(cleaned)
    )
    return timedelta(seconds=seconds)


def format_duration(delta: timedelta) -> str:
    """Render a duration the way the staleness warning says it aloud.

    Two units at most -- ``"2d 3h"``, not ``"2d 3h 14m 9s"``. The reader is
    deciding whether to re-sync, and the seconds never change that answer.
    """
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return f"-{format_duration(-delta)}"
    parts: list[str] = []
    for unit, size in _DURATION_UNITS:
        amount, seconds = divmod(seconds, size)
        if amount:
            parts.append(f"{amount}{unit}")
        if len(parts) == 2:
            break
    return " ".join(parts) if parts else "0s"


def resolve_max_age(configured: str | None = None) -> timedelta:
    """The staleness threshold in force, from the environment or the app.

    Precedence is ``$FUNCTUALIZE_VAULT_MAX_AGE`` > the app's
    ``remote_first(max_age=...)`` > :data:`DEFAULT_MAX_AGE`, matching the
    settings store's documented ``default < project < env`` order so that
    registering ``vault.max_age`` in the catalog later changes no behaviour.

    An unusable value is **warned about and skipped**, not raised. This
    threshold governs a warning that never fails a run; letting a typo in it
    stop the tool would trade a small problem for a total one. The offending
    text is named, so it is loud without being fatal.

    Args:
        configured: ``ConfigSources.vault_max_age``, or None when unset.

    Returns:
        How old the vault may be before every run warns.
    """
    candidates = (
        (os.environ.get(MAX_AGE_VAR), f"${MAX_AGE_VAR}"),
        (configured, "remote_first(max_age=...)"),
    )
    for text, origin in candidates:
        if not text:
            continue
        try:
            return parse_duration(text)
        except InvalidDurationError as exc:
            logger.warning("Ignoring the vault max_age from %s: %s", origin, exc)
    return parse_duration(DEFAULT_MAX_AGE)


def vault_path_for_project(cwd: str | Path | None = None) -> Path:
    """Return the vault file path for a project directory.

    Mirrors the discovery cache's per-project layout, using the same
    ``compute_project_id``, so the two agree on what "this project" means.
    """
    project_id = compute_project_id(cwd if cwd is not None else Path.cwd())
    return _xdg_data_dir() / "functualize" / "vaults" / project_id / "vault.db"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_ts(text: str) -> datetime:
    """Read a stored ``synced_at``, always as an aware UTC instant.

    Everything this module writes is aware, but a row can also arrive from a
    hand-edited database or an older file. A naive value is read as UTC rather
    than left naive, because the alternative is a ``TypeError`` deep inside the
    age comparison rather than an answer.
    """
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class SecretsVault:
    """A project's encrypted secret store.

    The key is supplied per operation rather than held for the object's
    lifetime, so metadata operations (:meth:`list_entries`, :meth:`age`) work
    with no key at all — which is what lets ``vault list`` and ``vault status``
    answer on a machine where the key is not available.
    """

    def __init__(self, path: Path, *, key_provider_id: str = "unknown") -> None:
        """Initialise a vault over a file path.

        Args:
            path: The vault database. Parent directories are created on demand.
            key_provider_id: Which :class:`~functualize.plugin.VaultKeyProvider`
                supplied the key, used only to make a decryption failure
                legible.
        """
        self._path = path
        self._key_provider_id = key_provider_id

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path)
        # WAL: `builtin parallel` runs several jobs at once, so concurrent
        # readers against a single writer is the normal access pattern, not an
        # edge case. Reads are frequent; writes happen only during `vault sync`.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        return conn

    def _audit(
        self,
        conn: sqlite3.Connection,
        key: str,
        action: str,
        outcome: str,
        provider: str | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO audit_log (ts, key, provider, action, outcome)"
            " VALUES (?, ?, ?, ?, ?)",
            (_utcnow().isoformat(), key, provider, action, outcome),
        )

    def put(
        self,
        key: str,
        value: str,
        *,
        annotation: str,
        provider: str,
        encryption_key: bytes,
    ) -> None:
        """Encrypt and store one value, replacing any previous entry.

        Args:
            key: Config key, e.g. ``"database.password"``.
            value: The plaintext secret. Never logged, never audited.
            annotation: The ``provider://reference`` it was declared as.
            provider: Which provider actually answered.
            encryption_key: 32 bytes.

        Raises:
            VaultError: If the key is not exactly :data:`KEY_BYTES` long.
        """
        _require_key(encryption_key)
        nonce = _random_nonce()
        ciphertext = AESGCM(encryption_key).encrypt(
            nonce, value.encode("utf-8"), key.encode("utf-8")
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO secrets"
                " (key, annotation, provider, nonce, ciphertext, synced_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET"
                " annotation=excluded.annotation, provider=excluded.provider,"
                " nonce=excluded.nonce, ciphertext=excluded.ciphertext,"
                " synced_at=excluded.synced_at",
                (
                    key,
                    annotation,
                    provider,
                    nonce,
                    ciphertext,
                    _utcnow().isoformat(),
                ),
            )
            self._audit(conn, key, "sync", "ok", provider)

    def get(self, key: str, *, encryption_key: bytes) -> str | None:
        """Decrypt and return one value, or None when it is not stored.

        A miss is not an error here — the caller decides what to do about it,
        and the configured behaviour is to fall through to the next config
        source with a warning (ADR-016).

        Raises:
            VaultDecryptionError: If the stored value does not authenticate
                under this key.
        """
        _require_key(encryption_key)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT nonce, ciphertext FROM secrets WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                self._audit(conn, key, "read", "miss")
                return None
            try:
                plaintext = AESGCM(encryption_key).decrypt(
                    row[0], row[1], key.encode("utf-8")
                )
            except InvalidTag as exc:
                self._audit(conn, key, "read", "error")
                msg = (
                    f"Could not decrypt {key!r} from {self._path}. The stored "
                    f"value did not authenticate under the key supplied by the "
                    f"{self._key_provider_id!r} key provider — most likely the "
                    f"vault was written under a different key. Re-run "
                    f"`func builtin vault sync` with the correct key."
                )
                raise VaultDecryptionError(msg) from exc
            self._audit(conn, key, "read", "ok")
            return plaintext.decode("utf-8")

    def list_entries(self) -> list[VaultEntry]:
        """Every stored entry's metadata. Requires **no** key."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, annotation, provider, synced_at FROM secrets ORDER BY key"
            ).fetchall()
        return [
            VaultEntry(
                key=r[0],
                annotation=r[1],
                provider=r[2],
                synced_at=_parse_ts(r[3]),
            )
            for r in rows
        ]

    def oldest_sync(self) -> datetime | None:
        """When the least-recently-synced entry was written, or None if empty.

        Staleness is judged on the oldest entry rather than the newest: a vault
        is only as fresh as the value most likely to have been rotated behind
        it.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT MIN(synced_at) FROM secrets").fetchone()
        return _parse_ts(row[0]) if row and row[0] else None

    def age(self, *, now: datetime | None = None) -> timedelta | None:
        """How long ago the least-recently-synced entry was written.

        Returns None for an empty vault: nothing stored cannot be out of date,
        and warning about the freshness of no values would be noise on a first
        run, before anyone has had the chance to sync.

        A clock that has moved backwards produces a *negative* age, which is
        deliberately left as-is rather than clamped -- it compares as fresh, so
        skew cannot manufacture a staleness warning.
        """
        oldest = self.oldest_sync()
        if oldest is None:
            return None
        return (now if now is not None else _utcnow()) - oldest

    def audit_records(self) -> Iterator[tuple[str, str, str | None, str, str]]:
        """Every audit row, oldest first. Values never appear here."""
        with self._connect() as conn:
            yield from conn.execute(
                "SELECT ts, key, provider, action, outcome FROM audit_log"
                " ORDER BY rowid"
            ).fetchall()

    def clear(self) -> None:
        """Delete the vault file. Values live authoritatively in the remote."""
        self._path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            self._path.with_name(self._path.name + suffix).unlink(missing_ok=True)


def _require_key(key: bytes) -> None:
    if len(key) != KEY_BYTES:
        msg = (
            f"Vault key must be exactly {KEY_BYTES} bytes for AES-256, got {len(key)}."
        )
        raise VaultError(msg)


def _random_nonce() -> bytes:
    return os.urandom(_NONCE_BYTES)
