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

**No prompt from a run** — :class:`KeyAccess.BOUNDED` (the run path) reads
every provider *silently*: an unlocked keyring answers with the key, a locked
one is reported LOCKED at once, with no wait and no unlock request. A run must
never create an unlock prompt: a prompt the client later abandons (a deadline
followed by exit, Ctrl-C, an agent killing its child) can crash the keyring
daemon and re-lock every keyring the user has. Only
:class:`KeyAccess.FOREGROUND` — ``func builtin vault unlock``, run by a person
— asks a keyring to unlock, and it waits for the prompt's own outcome.

**A hung-backend guard** — the silent read runs in a daemon thread under the
``vault.keyring_timeout`` deadline. That deadline only bounds a backend that
does not answer at all ("the keyring did not answer"); it is never the way an
active prompt is walked away from, because a silent read never creates one.

**A memo** — the outcome (found *or* failed) of a bounded lookup is retained
for the life of the resolver, so a run resolving many config fields asks the
keyring at most once. functualize caches no key across
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
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from functualize._config.vault import (
    KeyringLockedError,
    KeyringUnavailableError,
    KeyringUnverifiedError,
    app_keyring_timeout,
)
from functualize._config.vault_keyring import AdapterOutcome
from functualize._config.vault_keys import (
    EnvKeyProvider,
    KeychainKeyProvider,
    default_providers,
)
from functualize._types.enums import KeyAvailability
from functualize._types.protocols import VaultKeyProbe, VaultKeyUnlocker

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._config.vault_keyring import UnlockHow
    from functualize._types.protocols import VaultKeyProvider

__all__ = [
    "KeyAccess",
    "KeyLookup",
    "KeyStatus",
    "KeyringState",
    "VaultKeyResolver",
    "describe_key_failure",
    "resolve_vault_key",
]


class KeyAccess(Enum):
    """How a caller may wait on the key."""

    BOUNDED = "bounded"
    """The run path: env, then a silent read of the rest; never a prompt."""

    FOREGROUND = "foreground"
    """``vault unlock``: may prompt, and waits for the prompt's own outcome."""


class KeyStatus(Enum):
    """Why there is — or is not — a key. Four outcomes, four messages."""

    FOUND = "found"
    LOCKED = "locked"
    """Locked (not opened), or a hung backend did not answer. The key may well exist."""

    NO_KEYRING = "no_keyring"
    """No backend, extra missing, or no session bus."""

    NOT_STORED = "not_stored"
    """A keyring answered; no entry. The key really is gone."""

    UNVERIFIED = "unverified"
    """A keyring backend nobody has proven silent, so a run did not read it."""


@dataclass(frozen=True, slots=True)
class KeyringState:
    """What :meth:`VaultKeyResolver.key_state` found. Never carries a key."""

    availability: KeyAvailability
    reachable: bool = True
    """False when no keyring could be asked at all."""

    source: str | None = None
    """``"env"``, the keyring adapter's name, or None."""

    key_stored: bool | None = None
    """On an unlocked keyring: whether the vault key entry exists."""


class KeyLookup:
    """The outcome of one key resolution, with the reason attached.

    Replaces the old key-or-``None`` result — whose single ``None`` covered
    locked, absent, no-backend and not-stored, which is why the old refusal
    text was false. The key is present only when FOUND and never appears in
    the repr: this object is safe to log.
    """

    __slots__ = ("key", "provider_id", "status", "timed_out", "unlock_how", "waited")

    def __init__(
        self,
        status: KeyStatus,
        *,
        key: bytes | None = None,
        provider_id: str | None = None,
        waited: float = 0.0,
        timed_out: bool = False,
        unlock_how: UnlockHow | None = None,
    ) -> None:
        self.status = status
        self.key = key
        self.provider_id = provider_id
        self.waited = waited
        self.timed_out = timed_out
        self.unlock_how = unlock_how
        """How a FOREGROUND unlock ended (already unlocked, cancelled, …)."""

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
    timed-out "did not answer" outcome. This guards a *hung backend* only:
    ``fn`` is a silent read, which never creates an unlock prompt, so nothing
    a person could see is abandoned. The blocked thread dies with the
    process; waiting for it would be the hang this exists to remove. An
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
        self._timeout: float | None = timeout
        self._timeout_app: Any = None
        self._outcome: KeyLookup | None = None
        self._lock = threading.Lock()
        self._state: tuple[float, KeyringState] | None = None
        self._state_lock = threading.Lock()

    @classmethod
    def for_app(cls, project_id: str, app: Any) -> VaultKeyResolver:
        """The resolver boot builds: the app's keyring wait, read on first need.

        The wait is read through :func:`app_keyring_timeout` only when a
        keyring is about to be consulted — so a run whose key comes from
        ``$FUNCTUALIZE_VAULT_KEY``, or that opens nothing, never reads the
        setting and never warns about a bad one (spec A12a).
        """
        resolver = cls(project_id)
        resolver._timeout = None
        resolver._timeout_app = app
        return resolver

    def _deadline(self) -> float:
        if self._timeout is None:
            self._timeout = app_keyring_timeout(self._timeout_app)
        return self._timeout

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
        failed — is retained for the resolver's life, so N lookups ask the
        keyring once. FOREGROUND reuses a FOUND memo but never a failure: the
        person at ``vault unlock`` gets a fresh chance. Two threads asking at
        once serialise on the lock, so a hung backend costs one timeout total,
        not one per thread.
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

    def key_state(self, *, cap: float = 0.25, ttl: float = 2.0) -> KeyringState:
        """Whether a run would get the key, without ever reading it (spec B8).

        Never prompts, never unlocks, never reads the secret, never raises.
        The environment answers without touching a keyring; otherwise the
        keyring is asked whether it is locked, within ``cap`` seconds (UNKNOWN
        past it). The answer is held for ``ttl`` seconds on this instance, so a
        surface polling it costs one probe per window.
        """
        with self._state_lock:
            cached = self._state
            if cached is not None and time.monotonic() - cached[0] < ttl:
                return cached[1]
        state = self._key_state_now(cap)
        with self._state_lock:
            self._state = (time.monotonic(), state)
        return state

    def _key_state_now(self, cap: float) -> KeyringState:
        for provider in self._providers:
            if isinstance(provider, EnvKeyProvider) and provider.is_available():
                return KeyringState(KeyAvailability.UNLOCKED, source="env")
        answer: list[KeyringState] = []

        def ask() -> None:
            try:
                answer.append(self._probe_keyrings())
            except Exception:  # noqa: BLE001 - a state probe never raises
                answer.append(KeyringState(KeyAvailability.UNKNOWN))

        thread = threading.Thread(
            target=ask, daemon=True, name="functualize-vault-key-state"
        )
        thread.start()
        thread.join(cap)
        return answer[0] if answer else KeyringState(KeyAvailability.UNKNOWN)

    def _probe_keyrings(self) -> KeyringState:
        for provider in self._providers:
            if (
                isinstance(provider, EnvKeyProvider)
                or provider.interactive() is not False
            ):
                continue
            if not provider.is_available():
                continue
            if isinstance(provider, KeychainKeyProvider):
                availability = provider.probe()
                stored = (
                    provider.key_stored()
                    if availability is KeyAvailability.UNLOCKED
                    else None
                )
                return KeyringState(
                    availability, source=provider.adapter_name(), key_stored=stored
                )
            if isinstance(provider, VaultKeyProbe):
                return KeyringState(provider.probe(), source=provider.identifier())
            return KeyringState(KeyAvailability.UNKNOWN, source=provider.identifier())
        return KeyringState(KeyAvailability.UNKNOWN, reachable=False)

    # -- resolution ---------------------------------------------------------

    def _resolve(self, access: KeyAccess) -> KeyLookup:
        started = time.monotonic()

        # A provider that can only work by prompting is still terminal-only;
        # everything else is read regardless of terminal (the point of this
        # feature). Two passes rather than one filtered list: a provider that
        # needs a terminal is asked last, and only when nothing that cannot
        # prompt had a key — never merely because it was registered earlier.
        on_tty = sys.stdin.isatty() and sys.stdout.isatty()
        candidates = [p for p in self._providers if p.interactive() is False]
        if on_tty:
            candidates += [p for p in self._providers if p.interactive() is not False]

        # Env first and outside every deadline: reading a variable cannot
        # block, and when it holds a key neither the keyring nor the wait
        # setting is touched at all.
        env = [p for p in candidates if isinstance(p, EnvKeyProvider)]
        rest = [p for p in candidates if not isinstance(p, EnvKeyProvider)]
        if env:
            first = self._ask(env, started)
            if first.status is KeyStatus.FOUND or not rest:
                return first

        if access is KeyAccess.FOREGROUND:
            return self._unlock(rest, started)

        def ask() -> KeyLookup:
            return self._ask(rest, started)

        outcome = _run_bounded(ask, self._deadline())
        if outcome is None:
            return KeyLookup(
                KeyStatus.LOCKED,
                waited=time.monotonic() - started,
                timed_out=True,
            )
        return outcome

    def _unlock(
        self, providers: Sequence[VaultKeyProvider], started: float
    ) -> KeyLookup:
        """FOREGROUND: ask each keyring to unlock — the one path that may prompt.

        No deadline: a person ran ``vault unlock`` and is answering the
        keyring's own dialog, and ending an active prompt from this side can
        crash the keyring daemon. The keychain provider hands back the key with
        the outcome; any other :class:`~functualize.plugin.VaultKeyUnlocker` is
        unlocked and then read; anything else is just read.
        """
        fallback = KeyLookup(KeyStatus.NO_KEYRING)
        for provider in providers:
            if not provider.is_available():
                continue
            ident = provider.identifier()
            if isinstance(provider, KeychainKeyProvider):
                unlocked = provider.unlock_key(self._project_id)
                if unlocked.key is not None:
                    return self._finish(
                        KeyLookup(
                            KeyStatus.FOUND,
                            key=unlocked.key,
                            provider_id=ident,
                            unlock_how=unlocked.how,
                        ),
                        started,
                    )
                if unlocked.outcome is AdapterOutcome.LOCKED:
                    return self._finish(
                        KeyLookup(
                            KeyStatus.LOCKED, provider_id=ident, unlock_how=unlocked.how
                        ),
                        started,
                    )
                if unlocked.outcome is AdapterOutcome.NOT_STORED:
                    fallback = KeyLookup(
                        KeyStatus.NOT_STORED, provider_id=ident, unlock_how=unlocked.how
                    )
                continue
            if isinstance(provider, VaultKeyUnlocker) and not provider.unlock():
                return self._finish(
                    KeyLookup(KeyStatus.LOCKED, provider_id=ident), started
                )
            outcome = self._ask([provider], started)
            if outcome.status is KeyStatus.FOUND:
                return outcome
            if outcome.status is not KeyStatus.NO_KEYRING:
                fallback = outcome
        return self._finish(fallback, started)

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
            except KeyringUnverifiedError:
                # A backend nobody has proven silent: not read, and said so.
                return self._finish(
                    KeyLookup(KeyStatus.UNVERIFIED, provider_id=provider.identifier()),
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
                unlock_how=lookup.unlock_how,
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
    remove_target: str | None = None,
) -> str:
    """The one refusal message for a key that could not be had (spec B3).

    Messages are provider-neutral: they say "keyring", never a product name.

    Which next steps are offered follows the outcome, and one rule is
    absolute: for LOCKED, NO_KEYRING and UNVERIFIED — states where the key may
    well exist — the message **never** offers ``vault remove`` or ``vault clear`` (they
    destroy an entry that is fine) and never offers ``vault sync`` for a
    ``direct`` entry (it is the only copy; sync cannot restore it). Only for
    NOT_STORED, where the key really is gone, may remove/clear appear, last,
    with the destroys-the-entry warning.

    Args:
        lookup: The failed lookup. FOUND is a programming error and raises.
        qualified: The config key the run was resolving, if any.
        direct: Whether the stored entry was written by hand — the only copy.
        timeout: The hung-backend bound, for "did not answer within N s".
        remove_target: What follows ``vault remove`` in the last-resort line —
            a scoped identity's flags (``--job deploy --field token``), so the
            command the message prints is one the CLI accepts. Falls back to
            ``qualified``, then the generic ``<key>``.
    """
    if lookup.status is KeyStatus.FOUND:
        msg = "describe_key_failure called on a FOUND lookup"
        raise ValueError(msg)

    prefix = f"Cannot open the stored vault entry {qualified!r}: " if qualified else ""
    waited = timeout if timeout is not None else lookup.waited

    if lookup.status is KeyStatus.LOCKED and lookup.timed_out:
        return (
            f"{prefix}the keyring did not answer within {waited:.0f}s. Check "
            f"that it is running, or set `FUNCTUALIZE_VAULT_KEY`, then retry."
        )
    if lookup.status is KeyStatus.LOCKED:
        return (
            f"{prefix}the keyring is locked. Unlock it with your system's "
            f"keyring manager, or run `func builtin vault unlock` in a "
            f"terminal, or set `FUNCTUALIZE_VAULT_KEY`, then retry."
        )
    if lookup.status is KeyStatus.UNVERIFIED:
        return (
            f"{prefix}this keyring cannot be read without a possible prompt, "
            f"so a run does not read it. Set `FUNCTUALIZE_VAULT_KEY` for runs "
            f"without a terminal; `func builtin vault unlock` reads it in a "
            f"terminal."
        )
    if lookup.status is KeyStatus.NO_KEYRING:
        return (
            f"{prefix}no OS keyring is reachable here, so the stored vault key "
            f"cannot be read. Export $FUNCTUALIZE_VAULT_KEY (`func builtin "
            f"vault keygen` prints one), or install `functualize[keychain]`."
        )
    if lookup.status is KeyStatus.NOT_STORED:
        only_copy = (
            ", and for an entry typed in by hand that is the only copy"
            if direct
            else ""
        )
        target = remove_target or qualified or "<key>"
        return (
            f"{prefix}no vault key is stored on this machine. Run "
            f"`func builtin vault init`, or export $FUNCTUALIZE_VAULT_KEY. "
            f"Last resort, if the entry itself is stale: "
            f"`func builtin vault remove {target}` or `func builtin vault "
            f"clear` — they need no key, but each destroys stored "
            f"values{only_copy}; init or the env var is the fix that keeps "
            f"the secret."
        )
    msg = f"describe_key_failure has no text for {lookup.status!r}"
    raise ValueError(msg)
