"""Where the vault's encryption key comes from (ADR-016).

The key source is a **seam**, not a fixed decision: an OS keychain, a cloud
KMS, a password manager and a hosted control plane are all the same shape.
Implementations satisfy :class:`~functualize.plugin.VaultKeyProvider` and
register through the ``functualize.vault_key_providers`` entry-point group.

Two ship here.

``env`` — non-interactive
    Reads a hex key from ``FUNCTUALIZE_VAULT_KEY``. It is the only source that
    works identically on a laptop, in CI, in a container and in Lambda, and it
    matches the mandate ``RemoteProvider`` already states: *"Credentials MUST be
    resolved from environment variables only."*

``keychain`` — interactive
    Reads from the OS keyring. Better on a developer machine, where the key
    never sits in a shell profile.

Resolution order is part of the contract
----------------------------------------

Non-interactive providers are consulted **first**, and interactive ones only
when no key was found *and* a TTY is present. Reversed, an unattended run — CI,
a Lambda invocation, ``builtin parallel`` — would block forever on a prompt
nobody can answer.

``keyring`` is imported lazily and its absence is reported through
``is_available()`` rather than raised. It is **not** a declared dependency of
functualize: it happens to be present in some environments transitively, and
depending on that accident is how a missing optional dependency turns into a
crash instead of a degraded feature (`.spec/STATUS.md` follow-up #1).
"""

from __future__ import annotations

import binascii
import os
import sys
from typing import TYPE_CHECKING

from functualize._config.vault import KEY_BYTES, VaultError

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from functualize._types.protocols import VaultKeyProvider

__all__ = [
    "ENV_VAR",
    "KEYCHAIN_SERVICE",
    "EnvKeyProvider",
    "KeychainKeyProvider",
    "KeyResolution",
    "generate_key",
    "resolve_vault_key",
]

#: Where the non-interactive provider looks. Hex-encoded, 64 characters.
ENV_VAR = "FUNCTUALIZE_VAULT_KEY"

#: Service name under which the keychain provider stores per-project keys.
KEYCHAIN_SERVICE = "functualize-vault"


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
    """Reads the vault key from the OS keyring. May prompt to unlock."""

    def identifier(self) -> str:
        return "keychain"

    def interactive(self) -> bool:
        return True

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
        """Return this project's key from the keyring, or None.

        Keys are stored per project, matching the per-project vault, so a
        keychain user's blast radius is one project rather than all of them.
        """
        try:
            import keyring
        except ImportError:
            return None
        try:
            raw = keyring.get_password(KEYCHAIN_SERVICE, project_id)
        except Exception:  # noqa: BLE001 - a locked or broken keyring defers
            return None
        if not raw:
            return None
        return _decode(raw, source=f"the OS keyring ({KEYCHAIN_SERVICE})")


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
        allow_interactive: Whether interactive providers may be consulted.
            ``None`` decides from the terminal, matching how the CLI decides
            elsewhere (``sys.stdin.isatty() and sys.stdout.isatty()``).

    Returns:
        The first key found, with the provider that supplied it, or ``None``
        when no provider has one. ``None`` is not an error here: the caller
        decides whether a missing key is fatal.
    """
    candidates = list(default_providers() if providers is None else providers)
    if allow_interactive is None:
        allow_interactive = sys.stdin.isatty() and sys.stdout.isatty()

    # Two passes rather than one sorted list: an interactive provider must not
    # be reached merely because it registered earlier.
    for interactive in (False, True):
        if interactive and not allow_interactive:
            return None
        for provider in candidates:
            if provider.interactive() is not interactive:
                continue
            if not provider.is_available():
                continue
            key = provider.get_key(project_id)
            if key is not None:
                return KeyResolution(key, provider.identifier())
    return None
