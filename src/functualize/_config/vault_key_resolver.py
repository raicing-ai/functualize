"""The vault-key resolver: order, deadline, memo, and the one refusal message.

Policy lives here; the *sources* of a key stay in
:mod:`functualize._config.vault_keys`. The resolver decides three things the
providers cannot:

**Order** — ``FUNCTUALIZE_VAULT_KEY`` first; when it holds a key the keyring is
never touched. Providers that need a person at a terminal
(``interactive() is True``) are consulted only on a real TTY; everything else
is consulted regardless of terminal (a developer who unlocked their keyring
this morning gets their secret from a pipe, an agent's shell tool or a stdio
MCP job exactly as from a terminal).

**A deadline** — :class:`KeyAccess.BOUNDED` (the run path) asks every remaining
provider under one shared deadline. The wait is enforced by a daemon thread
that is abandoned when the deadline elapses — backend-agnostic, and the same
strategy ``gh`` uses for its keyring. Where no keyring can answer at all the
outcome is immediate, not waited out.

**A memo** — the outcome (found *or* failed) of a bounded lookup is retained
for the life of the resolver, so a run resolving many config fields waits at
most once against a locked keyring. functualize caches no key across
processes and runs no timer: when the keyring relocks, the next run finds it
locked.

Nothing here imports ``keyring`` or ``secretstorage`` at module scope; the
providers import lazily inside their methods, so a run that resolves no key
pays no import tax.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from enum import Enum
from functools import partial
from typing import TYPE_CHECKING, Final

from functualize._config.vault import (
    KeyringLockedError,
    KeyringUnavailableError,
)
from functualize._config.vault_keys import default_providers
from functualize._types.enums import KeyAvailability
from functualize._types.protocols import VaultKeyProbe

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._types.protocols import VaultKeyProvider

__all__ = [
    "KeyAccess",
    "KeyLookup",
    "KeyStatus",
    "VaultKeyResolver",
    "describe_key_failure",
    "resolve_vault_key",
]

#: How long a SILENT lookup may spend reading a provider that just probed
#: UNLOCKED. Short on purpose: it is a diagnostic path, and UNLOCKED means the
#: read should answer immediately.
_SILENT_READ_SECONDS: Final = 5.0


class KeyAccess(Enum):
    """How a caller may wait on the key."""

    BOUNDED = "bounded"
    """The run path: env, then the remaining providers under the deadline."""

    FOREGROUND = "foreground"
    """``vault unlock``: no deadline, because a person is there to answer one."""

    SILENT = "silent"
    """``vault status`` / ``inspect``: probe first; read only if UNLOCKED."""


class KeyStatus(Enum):
    """Why there is — or is not — a key. Four outcomes, four messages."""

    FOUND = "found"
    LOCKED = "locked"
    """Locked, or the deadline elapsed. The key may well exist."""

    NO_KEYRING = "no_keyring"
    """No backend, extra missing, or no session bus."""

    NOT_STORED = "not_stored"
    """A keyring answered; no entry. The key really is gone."""

    UNKNOWN = "unknown"
    """SILENT access only: the backend cannot say without risking a prompt."""


class KeyLookup:
    """The outcome of one key resolution, with the reason attached.

    Replaces ``KeyResolution | None`` — the type whose single ``None`` covered
    locked, absent, no-backend and not-stored, which is why the old refusal
    text was false. The key is present only when FOUND and never appears in
    the repr: this object is safe to log.
    """

    __slots__ = ("key", "provider_id", "status", "timed_out", "waited")

    def __init__(
        self,
        status: KeyStatus,
        *,
        key: bytes | None = None,
        provider_id: str | None = None,
        waited: float = 0.0,
        timed_out: bool = False,
    ) -> None:
        self.status = status
        self.key = key
        self.provider_id = provider_id
        self.waited = waited
        self.timed_out = timed_out

    def __repr__(self) -> str:
        """Never render the key — this object is safe to log."""
        key_desc = "None" if self.key is None else f"<{len(self.key)} bytes>"
        return (
            f"KeyLookup(status={self.status.value!r}, key={key_desc}, "
            f"provider_id={self.provider_id!r}, "
            f"waited={self.waited:.2f}s, timed_out={self.timed_out})"
        )


def _run_bounded(fn: Callable[[], KeyLookup], seconds: float) -> KeyLookup | None:
    """Run ``fn`` in a daemon thread, abandoning it after ``seconds``.

    Returns ``None`` when the deadline elapsed — the caller turns that into a
    timed-out LOCKED outcome. The blocked thread is abandoned and dies with
    the process; waiting for it would be the hang this exists to remove. An
    exception raised by ``fn`` is captured and re-raised on the caller, so a
    bad hex key stays a loud error instead of becoming thread-excepthook
    noise.
    """
    box: list[KeyLookup] = []
    error: list[BaseException] = []

    def run() -> None:
        try:
            box.append(fn())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller
            error.append(exc)

    thread = threading.Thread(
        target=run, daemon=True, name="functualize-vault-key-lookup"
    )
    thread.start()
    thread.join(seconds)
    if error:
        raise error[0]
    return box[0] if box else None


class VaultKeyResolver:
    """Resolves the vault key once, lazily, behind a deadline.

    Instance state only — the memo is a field, never a module global, so two
    apps in one process keep independent outcomes. Created once per app by
    boot and handed to :class:`~functualize._config.vault_source.VaultSource`,
    which asks for the key only when a run is about to open a stored entry.
    """

    def __init__(
        self,
        project_id: str,
        providers: Sequence[VaultKeyProvider] | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._project_id = project_id
        self._providers = tuple(default_providers() if providers is None else providers)
        self._timeout = timeout
        self._outcome: KeyLookup | None = None
        self._lock = threading.Lock()

    @classmethod
    def fixed(cls, key: bytes, provider_id: str = "fixed") -> VaultKeyResolver:
        """A resolver that already knows its key — tests, and "already known".

        The lookup is memoised as FOUND at construction, so no provider is
        ever consulted.
        """
        resolver = cls(project_id="", providers=(), timeout=0.0)
        resolver._outcome = KeyLookup(KeyStatus.FOUND, key=key, provider_id=provider_id)
        return resolver

    def lookup(self, access: KeyAccess = KeyAccess.BOUNDED) -> KeyLookup:
        """Resolve the key under the given :class:`KeyAccess`.

        Memo rules (``research.md`` R8): a BOUNDED outcome — found **or**
        failed — is retained for the resolver's life, so N lookups wait at
        most once. FOREGROUND and SILENT reuse a FOUND memo but never a
        failure: the person at ``vault unlock`` gets a fresh chance, and a
        SILENT probe never poisons a later bounded read. Two threads asking
        at once serialise on the lock, so a locked keyring costs one timeout
        total, not one per thread.
        """
        with self._lock:
            memo = self._outcome
            if memo is not None and (
                memo.status is KeyStatus.FOUND or access is KeyAccess.BOUNDED
            ):
                return memo
            result = self._resolve(access)
            if result.status is KeyStatus.FOUND or access is KeyAccess.BOUNDED:
                self._outcome = result
            return result

    # -- resolution ---------------------------------------------------------

    def _resolve(self, access: KeyAccess) -> KeyLookup:
        started = time.monotonic()

        if access is KeyAccess.SILENT:
            return self._resolve_silent(started)

        # A provider that can only work by prompting is still terminal-only;
        # everything else is read regardless of terminal (the point of this
        # feature) and, under BOUNDED, inside one shared deadline.
        on_tty = sys.stdin.isatty() and sys.stdout.isatty()
        candidates = [p for p in self._providers if on_tty or p.interactive() is False]

        def ask() -> KeyLookup:
            return self._ask(candidates, started)

        if access is KeyAccess.BOUNDED:
            outcome = _run_bounded(ask, self._timeout)
            if outcome is None:
                return KeyLookup(
                    KeyStatus.LOCKED,
                    waited=time.monotonic() - started,
                    timed_out=True,
                )
        else:
            outcome = self._ask(candidates, started)
        assert outcome is not None
        return outcome

    def _ask(self, providers: Sequence[VaultKeyProvider], started: float) -> KeyLookup:
        """Walk providers in order; typed errors map to typed statuses.

        Any other :class:`~functualize._config.vault.VaultError` — a key that
        is present but not valid hex — propagates unchanged: a mistyped key
        must not become "no key".
        """
        saw_answer = False
        for provider in providers:
            if not provider.is_available():
                continue
            try:
                key = provider.get_key(self._project_id)
            except KeyringLockedError:
                return self._finish(
                    KeyLookup(KeyStatus.LOCKED, provider_id=provider.identifier()),
                    started,
                )
            except KeyringUnavailableError:
                # Passed is_available() but the backend is gone: evidence for
                # NO_KEYRING, not an answer.
                continue
            # It answered. A live backend returning None is "nothing stored".
            saw_answer = True
            if key is not None:
                return self._finish(
                    KeyLookup(
                        KeyStatus.FOUND,
                        key=key,
                        provider_id=provider.identifier(),
                    ),
                    started,
                )
        if saw_answer:
            # A live backend answered; it holds no entry. The key really is
            # gone, which is what makes remove/clear honest advice here.
            return self._finish(KeyLookup(KeyStatus.NOT_STORED), started)
        # Nothing answered: unavailable, skipped, or absent altogether.
        return self._finish(KeyLookup(KeyStatus.NO_KEYRING), started)

    def _resolve_silent(self, started: float) -> KeyLookup:
        """Answer without ever risking a prompt (status/inspect).

        Env-shaped providers (no probe method) cannot prompt, so they are read
        under the short silent bound. Probe-capable providers answer LOCKED /
        UNLOCKED / UNKNOWN; only UNLOCKED is read. A provider that needs a
        terminal is never asked — the question itself is the prompt risk.
        """

        def ask_one(provider: VaultKeyProvider) -> KeyLookup:
            return self._ask([provider], started)

        quiet = [p for p in self._providers if p.interactive() is False]
        for provider in quiet:
            if isinstance(provider, VaultKeyProbe) or not provider.is_available():
                continue
            outcome = _run_bounded(partial(ask_one, provider), _SILENT_READ_SECONDS)
            if outcome is not None and outcome.status is KeyStatus.FOUND:
                return outcome
        for provider in quiet:
            if not isinstance(provider, VaultKeyProbe):
                continue
            availability = provider.probe()
            if availability is not KeyAvailability.UNLOCKED:
                status = (
                    KeyStatus.LOCKED
                    if availability is KeyAvailability.LOCKED
                    else KeyStatus.UNKNOWN
                )
                return self._finish(
                    KeyLookup(status, provider_id=provider.identifier()), started
                )
            outcome = _run_bounded(partial(ask_one, provider), _SILENT_READ_SECONDS)
            if outcome is None:
                return self._finish(
                    KeyLookup(KeyStatus.UNKNOWN, provider_id=provider.identifier()),
                    started,
                )
            return outcome
        # No probe-capable provider: the question "is a read safe?" has no
        # answer here, and guessing one way would either prompt or lie.
        return self._finish(KeyLookup(KeyStatus.UNKNOWN), started)

    @staticmethod
    def _finish(lookup: KeyLookup, started: float) -> KeyLookup:
        """Stamp the elapsed time onto a just-computed outcome."""
        if lookup.waited == 0.0:
            return KeyLookup(
                lookup.status,
                key=lookup.key,
                provider_id=lookup.provider_id,
                waited=time.monotonic() - started,
                timed_out=lookup.timed_out,
            )
        return lookup


def resolve_vault_key(
    project_id: str,
    providers: Sequence[VaultKeyProvider] | None = None,
    *,
    access: KeyAccess = KeyAccess.BOUNDED,
    timeout: float = 30.0,
) -> KeyLookup:
    """One-shot resolution — a fresh resolver, consulted once, no shared memo.

    For ``vault put`` / ``vault sync`` / ``vault status``: single-shot commands
    where the memo buys nothing (plan K-6). The long-lived run path uses a
    :class:`VaultKeyResolver` owned by the app instead.
    """
    return VaultKeyResolver(project_id, providers, timeout=timeout).lookup(access)


def describe_key_failure(
    lookup: KeyLookup,
    *,
    qualified: str | None = None,
    direct: bool | None = None,
    timeout: float | None = None,
) -> str:
    """The one refusal message for a key that could not be had (spec B3).

    Which next steps are offered follows the outcome, and one rule is
    absolute: for LOCKED and NO_KEYRING — states where the key may well exist
    — the message **never** offers ``vault remove`` or ``vault clear`` (they
    destroy an entry that is fine) and never offers ``vault sync`` for a
    ``direct`` entry (it is the only copy; sync cannot restore it). Only for
    NOT_STORED, where the key really is gone, may remove/clear appear, last,
    with the destroys-the-entry warning.

    Args:
        lookup: The failed lookup. FOUND is a programming error and raises.
        qualified: The config key the run was resolving, if any.
        direct: Whether the stored entry was written by hand — the only copy.
        timeout: The wait that was applied, for "did not answer within N s".
    """
    if lookup.status is KeyStatus.FOUND:
        msg = "describe_key_failure called on a FOUND lookup"
        raise ValueError(msg)

    prefix = f"Cannot open the stored vault entry {qualified!r}: " if qualified else ""
    waited = timeout if timeout is not None else lookup.waited

    if lookup.status is KeyStatus.LOCKED:
        return (
            f"{prefix}the OS keyring is locked or did not answer within "
            f"{waited:.0f}s. Unlock it, or run `func builtin vault unlock` in "
            f"another terminal, or export $FUNCTUALIZE_VAULT_KEY; then retry."
        )
    if lookup.status is KeyStatus.NO_KEYRING:
        return (
            f"{prefix}no OS keyring is reachable here, so the stored vault key "
            f"cannot be read. Export $FUNCTUALIZE_VAULT_KEY, or install "
            f"`functualize[keychain]`."
        )
    if lookup.status is KeyStatus.NOT_STORED:
        destroy = (
            " — it destroys the stored value"
            + (
                ", and for an entry typed in by hand that is the only copy"
                if direct
                else ""
            )
            + " —"
        )
        return (
            f"{prefix}no vault key is stored on this machine. Run "
            f"`func builtin vault init`, or export $FUNCTUALIZE_VAULT_KEY. "
            f"If the entry itself is stale, `func builtin vault remove` can "
            f"delete it{destroy} but init or the env var is the fix that "
            f"keeps the secret."
        )
    # UNKNOWN (SILENT access only)
    return (
        f"{prefix}it could not be determined whether the vault key is "
        f"available without risking an unlock prompt. Run "
        f"`func builtin vault status` for detail, or `func builtin vault "
        f"unlock` to resolve it in the foreground."
    )
