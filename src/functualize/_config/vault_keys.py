"""Where the vault's encryption key comes from (ADR-016).

The key source is a **seam**, not a fixed decision: an OS keychain, a cloud
KMS, a password manager and a hosted control plane are all the same shape.
Implementations satisfy :class:`~functualize.plugin.VaultKeyProvider`.

**There is no entry-point group for this.** One was declared
(``functualize.vault_key_providers``) and nothing ever read it — core imports
the two providers below directly — so it advertised an extension point that did
not exist. `plugin-taxonomy`/T5 removed the declaration rather than inventing a
reader, because a ``<x>_providers`` group is read by the domain registry out of
a live ``DomainMetadata`` and there is no ``vault_key`` domain. A third-party
key source is wired by the application that wants it.

Two ship here.

``env`` — needs no terminal
    Reads a hex key from ``FUNCTUALIZE_VAULT_KEY``. It is the only source that
    works identically on a laptop, in CI, in a container and in Lambda, and it
    matches the mandate ``RemoteProvider`` already states: *"Credentials MUST be
    resolved from environment variables only."*

``keychain`` — bounded, not terminal-gated
    Reads from the OS keyring. Better on a developer machine, where the key
    never sits in a shell profile.

Reading is not gated on a terminal
----------------------------------

The keyring is consulted **whether or not stdin and stdout are terminals**,
behind a deadline the resolver owns: a developer who unlocked their keyring
this morning gets their stored secret from a pipe, an agent's shell tool or a
stdio MCP job exactly as from a terminal. A locked keyring may show its own
unlock dialog inside the deadline window.

The terminal rule survives for *prompting*, not for *reading*: a provider
whose :meth:`~functualize.plugin.VaultKeyProvider.interactive` is True — one
that can only obtain the key by asking a person at a terminal — is still
consulted only on a real TTY, so an unattended run cannot block forever on a
prompt nobody can answer. :meth:`KeychainKeyProvider.interactive` is therefore
``False``: reading it may block on a backend, but it needs no person, and the
resolver's deadline — not a TTY check — is what bounds it.

``keyring`` is imported lazily and its absence is reported through
``is_available()`` rather than raised. It is an **optional extra**,
``functualize[keychain]`` — declared, where it used to be an undeclared
accident relied upon to be present transitively. Depending on that accident is
how a missing optional dependency turns into a crash instead of a degraded
feature; declaring it makes the degradation a supported state with a name.

Key scope
---------

Both shipped providers are **user-scoped**: one key opens every project's
vault, and isolation between projects is the separate vault files. The keychain
provider used to be project-scoped, which meant the effective scope depended on
whether ``$FUNCTUALIZE_VAULT_KEY`` was exported. See
:class:`KeychainKeyProvider` and ADR-023 §4.
"""

from __future__ import annotations

import binascii
import os
import sys
import threading
from typing import TYPE_CHECKING, Final

from functualize._config.vault import (
    KEY_BYTES,
    KeyringLockedError,
    KeyringUnavailableError,
    VaultError,
)
from functualize._types.enums import KeyAvailability

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from functualize._types.protocols import VaultKeyProvider

__all__ = [
    "ENV_VAR",
    "KEYCHAIN_ACCOUNT",
    "KEYCHAIN_SERVICE",
    "EnvKeyProvider",
    "KeychainKeyProvider",
    "KeyResolution",
    "generate_key",
    "resolve_vault_key",
]

#: Where the non-interactive provider looks. Hex-encoded, 64 characters.
ENV_VAR = "FUNCTUALIZE_VAULT_KEY"

#: Service name under which the keychain provider stores the vault key.
KEYCHAIN_SERVICE = "functualize-vault"

#: Account name under that service. **Fixed, not the project id** — the key is
#: user-scoped, so one entry serves every project (ADR-023 §4). See
#: :class:`KeychainKeyProvider` for why this changed.
KEYCHAIN_ACCOUNT = "vault-key"

#: How long :meth:`KeychainKeyProvider.probe` may spend asking the Secret
#: Service "are you locked?" before answering ``UNKNOWN``. A probe must never
#: wedge a diagnostic surface on a dead D-Bus; two seconds is far more than a
#: property read on a live bus ever costs.
_PROBE_BOUND_SECONDS: Final = 2.0


def generate_key() -> str:
    """Return a fresh hex-encoded vault key, suitable for :data:`ENV_VAR`.

    64 hex characters for 32 bytes, the spelling Turso's vault uses and the
    one ``func builtin vault keygen`` prints.
    """
    return os.urandom(KEY_BYTES).hex()


def _decode(raw: str, *, source: str) -> bytes:
    """Decode a hex key, failing loudly rather than producing a short key.

    A truncated or mistyped key must not silently become a *different valid
    key* — it must not decode at all.
    """
    cleaned = raw.strip()
    try:
        key = bytes.fromhex(cleaned)
    except (ValueError, binascii.Error) as exc:
        msg = (
            f"The vault key from {source} is not valid hex. Expected "
            f"{KEY_BYTES * 2} hex characters; run "
            f"`func builtin vault keygen` to generate one."
        )
        raise VaultError(msg) from exc
    if len(key) != KEY_BYTES:
        msg = (
            f"The vault key from {source} is {len(key)} bytes, expected "
            f"{KEY_BYTES}. A {KEY_BYTES * 2}-character hex string is required; "
            f"run `func builtin vault keygen` to generate one."
        )
        raise VaultError(msg)
    return key


class EnvKeyProvider:
    """Reads the vault key from the environment. Never prompts."""

    def identifier(self) -> str:
        return "env"

    def interactive(self) -> bool:
        return False

    def is_available(self) -> bool:
        return bool(os.environ.get(ENV_VAR, "").strip())

    def get_key(self, project_id: str) -> bytes | None:
        """Return the key, or None when the variable is unset.

        The key is shared across a user's projects here: the environment holds
        one value, while vaults are per-project. Isolation comes from the
        separate files, not from separate keys — a provider that wants
        per-project keys (the keychain does) can supply them.
        """
        raw = os.environ.get(ENV_VAR, "")
        if not raw.strip():
            return None
        return _decode(raw, source=f"${ENV_VAR}")


class KeychainKeyProvider:
    """Reads and creates the vault key in the OS keyring.

    Reading **may block** on the keyring's own unlock dialog, but it needs no
    person at *this* process's terminal, so :meth:`interactive` is False and
    the resolver's deadline — not a TTY check — bounds it. It is consulted
    whether or not stdin and stdout are terminals.

    **One key for every project**, stored at a fixed account rather than one per
    project id (ADR-023 §4). This changed: the provider used to be
    project-scoped, while :class:`EnvKeyProvider` — which cannot be anything
    else, since the environment holds one value — has always been user-scoped.

    Two providers disagreeing about scope meant *which* scope applied depended
    on whether ``$FUNCTUALIZE_VAULT_KEY`` happened to be exported, because
    the environment provider was always consulted first. Exporting it once and
    syncing re-encrypted each project's store under the shared key; unsetting it
    later left every one of them unopenable by the keychain, with nothing
    recording which key had written what.

    Isolation between projects is the separate vault files, not separate keys —
    the position :meth:`EnvKeyProvider.get_key` already documented. This is not
    a reopening of ADR-006's rejected "secrets in the XDG config directory":
    that was *plaintext* secrets in one shared file. Here the secrets stay in
    per-project encrypted stores and only the key is shared.

    The cost is stated rather than elided: one lost or compromised key now
    reaches every project's vault instead of one.
    """

    def identifier(self) -> str:
        return "keychain"

    def interactive(self) -> bool:
        """False: reading may block on the backend, but never needs a terminal.

        The keyring's own unlock dialog is answered wherever the desktop
        session shows it, not at this process's stdin — so a pipe is not a
        reason to skip the read, and the resolver's deadline is the bound.
        """
        return False

    def is_available(self) -> bool:
        """Whether a usable keyring backend exists.

        Reports capability rather than raising: an absent ``keyring``, or one
        resolving to the null backend, is a normal state on a server.
        """
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring
        except ImportError:
            return False
        try:
            return not isinstance(keyring.get_keyring(), FailKeyring)
        except Exception:  # noqa: BLE001 - a broken backend is unavailable
            return False

    def get_key(self, project_id: str) -> bytes | None:
        """Return the vault key from the keyring, or None when nothing is stored.

        Failure states are **typed**, not swallowed: a locked keyring raises
        :class:`~functualize._config.vault.KeyringLockedError` and a missing
        one :class:`~functualize._config.vault.KeyringUnavailableError`, so the
        resolver can refuse with a message that is true. ``None`` means a live
        backend answered and holds no entry.

        Args:
            project_id: Ignored. Kept for the protocol, which carries it so a
                third-party provider *may* scope per project; this one does not
                (see the class docstring).
        """
        try:
            import keyring
            from keyring.errors import InitError, KeyringLocked, NoKeyringError
        except ImportError as exc:
            msg = (
                "No OS keyring is available on this machine, so the stored "
                "vault key cannot be read. Install it with `pip install "
                f"'functualize[keychain]'`, or set ${ENV_VAR} instead — "
                "`func builtin vault keygen` prints one."
            )
            raise KeyringUnavailableError(msg) from exc
        try:
            raw = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        except KeyringLocked as exc:
            msg = (
                f"The OS keyring ({KEYCHAIN_SERVICE}) is locked and did not "
                "release the vault key."
            )
            raise KeyringLockedError(msg) from exc
        except (InitError, NoKeyringError, RuntimeError) as exc:
            # RuntimeError is what keyring raises when no backend could be
            # initialized at all — read from the installed source, not guessed.
            msg = (
                "No OS keyring is reachable here, so the stored vault key "
                "cannot be read. Install it with `pip install "
                f"'functualize[keychain]'`, or set ${ENV_VAR} instead."
            )
            raise KeyringUnavailableError(msg) from exc
        if not raw:
            return None
        return _decode(raw, source=f"the OS keyring ({KEYCHAIN_SERVICE})")

    def probe(self) -> KeyAvailability:
        """Ask the Secret Service whether a read would prompt — without prompting.

        Imports ``secretstorage`` lazily (it arrives with the ``keychain``
        extra) and asks the question the real read would ask — the default
        collection's ``Locked`` property, the same call ``keyring``'s own
        SecretService backend makes before it calls ``unlock()`` — without the
        ``unlock()`` that follows it. Bound to :data:`_PROBE_BOUND_SECONDS`;
        any failure, including a missing Secret Service or D-Bus, answers
        ``UNKNOWN`` rather than raising, because the surfaces that ask are
        diagnostics and must never crash on a dead bus.
        """
        try:
            import secretstorage
        except ImportError:
            return KeyAvailability.UNKNOWN

        locked: list[bool] = []

        def ask() -> None:
            try:
                bus = secretstorage.dbus_init()
                collection = secretstorage.get_default_collection(bus)
                if collection is not None:
                    locked.append(bool(collection.is_locked()))
            except Exception:  # noqa: BLE001 - a probe never raises
                return

        thread = threading.Thread(
            target=ask, daemon=True, name="functualize-vault-key-probe"
        )
        thread.start()
        thread.join(_PROBE_BOUND_SECONDS)
        if not locked:
            return KeyAvailability.UNKNOWN
        return KeyAvailability.LOCKED if locked[0] else KeyAvailability.UNLOCKED

    def initialize_key(self, project_id: str) -> bytes:
        """Return the stored key, creating and persisting one if absent.

        Satisfies :class:`~functualize.plugin.VaultKeyInitializer`. Idempotent
        by construction: the read comes first, so a second call returns what the
        first one persisted. Generating a fresh key here instead would strand
        every value already written under the old one — silently, since nothing
        in the store records which key wrote a row.

        Args:
            project_id: Ignored, as in :meth:`get_key`.

        Raises:
            VaultError: If no keyring backend is available. `init` turns this
                into a refusal naming both routes forward; it is not a crash,
                and it never falls back to printing a key.
        """
        existing = self.get_key(project_id)
        if existing is not None:
            return existing

        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - guarded by is_available
            msg = (
                "No OS keyring is available, so a vault key cannot be stored. "
                "Install it with `pip install 'functualize[keychain]'`, or set "
                f"${ENV_VAR} instead — `func builtin vault keygen` prints one."
            )
            raise VaultError(msg) from exc

        created = generate_key()
        try:
            keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, created)
        except Exception as exc:  # noqa: BLE001 - a locked backend is a refusal
            msg = (
                f"The OS keyring ({KEYCHAIN_SERVICE}) refused to store the "
                f"vault key: {type(exc).__name__}. Unlock it and retry, or set "
                f"${ENV_VAR} instead."
            )
            raise VaultError(msg) from exc
        return _decode(created, source=f"the OS keyring ({KEYCHAIN_SERVICE})")


# TRANSITIONAL(4.1): KeyResolution and resolve_vault_key below are the old
# key-resolution API, kept only until every caller has moved to
# _config.vault_key_resolver.VaultKeyResolver. Until then resolve_vault_key
# swallows the new typed provider errors to keep its "KeyResolution | None"
# contract — and, the keychain being non-interactive now, it consults the
# keyring even without a TTY, without a deadline. Both differences close when
# the callers migrate and this API is deleted (task 4.1).
class KeyResolution:
    """Which provider supplied the key, and the key itself.

    Carries the provider id so a later decryption failure can name the key that
    was actually tried.
    """

    __slots__ = ("key", "provider_id")

    def __init__(self, key: bytes, provider_id: str) -> None:
        self.key = key
        self.provider_id = provider_id

    def __repr__(self) -> str:
        """Never render the key — this object is safe to log."""
        return f"KeyResolution(provider_id={self.provider_id!r}, key=<{len(self.key)} bytes>)"


def default_providers() -> Sequence[VaultKeyProvider]:
    """The two implementations that ship with core."""
    return (EnvKeyProvider(), KeychainKeyProvider())


def resolve_vault_key(
    project_id: str,
    providers: Iterable[VaultKeyProvider] | None = None,
    *,
    allow_interactive: bool | None = None,
) -> KeyResolution | None:
    """Find a vault key, non-interactive sources first.

    Args:
        project_id: The project whose vault is being opened.
        providers: Providers to consult, in order. Defaults to the two shipped
            implementations.
        allow_interactive: Whether providers needing a terminal may be
            consulted. ``None`` decides from the terminal, matching how the
            CLI decides elsewhere (``sys.stdin.isatty() and
            sys.stdout.isatty()``).

    Returns:
        The first key found, with the provider that supplied it, or ``None``
        when no provider has one. ``None`` is not an error here: the caller
        decides whether a missing key is fatal.
    """
    candidates = list(default_providers() if providers is None else providers)
    if allow_interactive is None:
        allow_interactive = sys.stdin.isatty() and sys.stdout.isatty()

    # Two passes rather than one sorted list: a terminal-needing provider must
    # not be reached merely because it registered earlier.
    for interactive in (False, True):
        if interactive and not allow_interactive:
            return None
        for provider in candidates:
            if provider.interactive() is not interactive:
                continue
            if not provider.is_available():
                continue
            try:
                key = provider.get_key(project_id)
            except (KeyringLockedError, KeyringUnavailableError):
                # TRANSITIONAL(4.1): the old API reports "no key", never why;
                # the resolver replaces it with typed outcomes.
                continue
            if key is not None:
                return KeyResolution(key, provider.identifier())
    return None
