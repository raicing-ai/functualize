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

``keychain`` — silent, not terminal-gated
    Reads from the OS keyring. Better on a developer machine, where the key
    never sits in a shell profile.

Reading is not gated on a terminal, and never prompts
-----------------------------------------------------

The keyring is consulted **whether or not stdin and stdout are terminals**,
and always **silently**: a developer who unlocked their keyring this morning
gets their stored secret from a pipe, an agent's shell tool or a stdio MCP job
exactly as from a terminal, and a locked keyring is refused at once with no
dialog. Only ``func builtin vault unlock`` asks a keyring to unlock; even
``vault init`` reads and writes silently.

The terminal rule survives for *prompting*, not for *reading*: a provider
whose :meth:`~functualize.plugin.VaultKeyProvider.interactive` is True — one
that can only obtain the key by asking a person at a terminal — is still
consulted only on a real TTY, so an unattended run cannot block forever on a
prompt nobody can answer. :meth:`KeychainKeyProvider.interactive` is therefore
``False``: it needs no person, and the resolver's deadline bounds only a
backend that does not answer at all.

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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, NoReturn

from functualize._config.vault import (
    KEY_BYTES,
    KeyringLockedError,
    KeyringUnavailableError,
    KeyringUnverifiedError,
    VaultError,
)
from functualize._config.vault_keyring import AdapterOutcome, AdapterRead, UnlockHow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from functualize._config.vault_keyring import KeyringAdapter
    from functualize._types.enums import KeyAvailability
    from functualize._types.protocols import VaultKeyProvider

__all__ = [
    "ENV_VAR",
    "KEYCHAIN_ACCOUNT",
    "KEYCHAIN_SERVICE",
    "EnvKeyProvider",
    "KeychainKeyProvider",
    "UnlockedKey",
    "generate_key",
    "default_providers",
]

#: Where the non-interactive provider looks. Hex-encoded, 64 characters.
ENV_VAR = "FUNCTUALIZE_VAULT_KEY"

#: Service name under which the keychain provider stores the vault key.
KEYCHAIN_SERVICE = "functualize-vault"

#: Account name under that service. **Fixed, not the project id** — the key is
#: user-scoped, so one entry serves every project (ADR-023 §4). See
#: :class:`KeychainKeyProvider` for why this changed.
KEYCHAIN_ACCOUNT = "vault-key"


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
    """Reads and creates the vault key in the OS keyring, through its platform adapter.

    **Reading never prompts.** :meth:`get_key` asks the platform adapter
    (:func:`~functualize._config.vault_keyring.select_adapter`) for a *silent*
    read: an unlocked keyring answers with the key, a locked one raises
    :class:`~functualize._config.vault.KeyringLockedError` at once. A run must
    never create an unlock prompt — a prompt the client later abandons can
    crash the keyring daemon and re-lock every keyring the user has — so
    unlocking is :meth:`unlock`, used only by ``func builtin vault unlock``.
    It is consulted whether or not stdin and stdout are terminals.

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

    def __init__(self, *, adapter: KeyringAdapter | None = None) -> None:
        """Initialise the provider.

        Args:
            adapter: The keyring adapter to use. Chosen for this platform's
                active ``keyring`` backend on first use unless given (tests).
        """
        self._adapter = adapter

    def identifier(self) -> str:
        return "keychain"

    def interactive(self) -> bool:
        """False: reading needs no person at this terminal, and never prompts."""
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
        """Return the vault key, read silently, or None when nothing is stored.

        Failure states are **typed**, not swallowed: a locked keyring raises
        :class:`~functualize._config.vault.KeyringLockedError`, a missing one
        :class:`~functualize._config.vault.KeyringUnavailableError`, and a
        backend nobody has proven silent
        :class:`~functualize._config.vault.KeyringUnverifiedError`. ``None``
        means an unlocked keyring answered and holds no entry.

        Args:
            project_id: Ignored. Kept for the protocol, which carries it so a
                third-party provider *may* scope per project; this one does not
                (see the class docstring).
        """
        return _key_from(self._keyring().read_silent())

    def probe(self) -> KeyAvailability:
        """Whether a silent read would succeed — never prompts, bounded."""
        return self._keyring().state()

    def adapter_name(self) -> str:
        """The neutral name of the keyring adapter in use, for messages."""
        return self._keyring().name

    def key_stored(self) -> bool | None:
        """Whether the vault key entry exists, asked without reading it.

        None when the adapter cannot tell without reading the secret.
        """
        has_entry = getattr(self._keyring(), "has_entry", None)
        return has_entry() if has_entry is not None else None

    def unlock(self) -> bool:
        """Ask the keyring to unlock (may prompt); True when a key is available after."""
        return self.unlock_key().key is not None

    def unlock_key(self, project_id: str = "") -> UnlockedKey:
        """Unlock and read in one step — the one call that may show a dialog.

        Waits for the dialog's own outcome and never cancels it. The key comes
        back with the outcome, because on a backend nobody has proven silent a
        later silent read would still refuse.
        """
        read = self._keyring().unlock()
        key = (
            _decode(read.secret, source=_SOURCE)
            if read.outcome is AdapterOutcome.FOUND and read.secret is not None
            else None
        )
        return UnlockedKey(read.outcome, read.how, key)

    def initialize_key(self, project_id: str) -> bytes:
        """Return the stored key, creating and persisting one if absent.

        Satisfies :class:`~functualize.plugin.VaultKeyInitializer`. Idempotent
        by construction: the read comes first, so a second call returns what the
        first one persisted. Generating a fresh key here instead would strand
        every value already written under the old one — silently, since nothing
        in the store records which key wrote a row.

        **Never prompts.** Both the read and the write are silent: a locked
        keyring refuses at once and points at ``func builtin vault unlock``,
        which stays the only command that asks a keyring to unlock (spec B4').
        ``keyring.set_password`` is not used — on Linux it unlocks a locked
        collection first, and creates a default one when none exists.

        Args:
            project_id: Ignored, as in :meth:`get_key`.

        Raises:
            VaultError: If no keyring is available, the keyring is locked, or
                it cannot be written without a possible prompt. `init` turns
                this into a refusal naming the routes forward; it is not a
                crash, and it never falls back to printing a key.
        """
        adapter = self._keyring()
        existing = adapter.read_silent()
        if existing.outcome is AdapterOutcome.FOUND and existing.secret is not None:
            return _decode(existing.secret, source=_SOURCE)
        if existing.outcome is AdapterOutcome.NOT_STORED:
            created = generate_key()
            stored = adapter.store_silent(created)
            if stored is AdapterOutcome.FOUND:
                return _decode(created, source=_SOURCE)
            _refuse_to_store(stored)
        _refuse_to_store(existing.outcome)

    def _keyring(self) -> KeyringAdapter:
        if self._adapter is None:
            from functualize._config.vault_keyring import select_adapter

            self._adapter = select_adapter(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        return self._adapter


#: How a key read from the keyring is named in a decoding error.
_SOURCE: Final = f"the keyring ({KEYCHAIN_SERVICE})"


@dataclass(frozen=True, slots=True)
class UnlockedKey:
    """The outcome of :meth:`KeychainKeyProvider.unlock_key`. The key never prints."""

    outcome: AdapterOutcome
    how: UnlockHow | None
    key: bytes | None = field(default=None, repr=False)


def _refuse_to_store(outcome: AdapterOutcome) -> NoReturn:
    """Why ``vault init`` cannot store a key, as the error it raises."""
    if outcome is AdapterOutcome.LOCKED:
        msg = (
            "The keyring is locked, so a vault key cannot be stored. Unlock it "
            "with your system's keyring manager, or run `func builtin vault "
            f"unlock` in a terminal, then retry — or set ${ENV_VAR} instead."
        )
        raise KeyringLockedError(msg)
    if outcome is AdapterOutcome.UNVERIFIED:
        msg = (
            "This keyring cannot be written without a possible prompt, and a "
            f"run could not read it either. Set ${ENV_VAR} instead — "
            "`func builtin vault keygen` prints one."
        )
        raise KeyringUnverifiedError(msg)
    msg = (
        "No keyring is available, so a vault key cannot be stored. "
        "Install it with `pip install 'functualize[keychain]'`, or set "
        f"${ENV_VAR} instead — `func builtin vault keygen` prints one."
    )
    raise KeyringUnavailableError(msg)


def _key_from(read: AdapterRead) -> bytes | None:
    """A silent read's outcome as the provider contract states it."""
    if read.outcome is AdapterOutcome.FOUND and read.secret is not None:
        return _decode(read.secret, source=_SOURCE)
    if read.outcome is AdapterOutcome.NOT_STORED:
        return None
    if read.outcome is AdapterOutcome.LOCKED:
        msg = f"The keyring ({KEYCHAIN_SERVICE}) is locked; it was not opened."
        raise KeyringLockedError(msg)
    if read.outcome is AdapterOutcome.UNVERIFIED:
        msg = (
            "This keyring cannot be read without a possible prompt, so a run "
            f"does not read it. Set ${ENV_VAR}, or run `func builtin vault "
            "unlock` in a terminal."
        )
        raise KeyringUnverifiedError(msg)
    msg = (
        "No keyring is reachable here, so the stored vault key cannot be read. "
        f"Install it with `pip install 'functualize[keychain]'`, or set ${ENV_VAR} "
        "instead — `func builtin vault keygen` prints one."
    )
    raise KeyringUnavailableError(msg)


def default_providers() -> Sequence[VaultKeyProvider]:
    """The two implementations that ship with core."""
    return (EnvKeyProvider(), KeychainKeyProvider())
