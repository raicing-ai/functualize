"""A vault key kept in a password manager — a key provider written outside functualize.

functualize ships two places the vault key can come from: the
`FUNCTUALIZE_VAULT_KEY` variable and the OS keyring. Anything else — a password
manager, a cloud KMS, a hardware token — is a *key provider*: a plain class with
the right methods. Nothing to inherit and nothing to register; the protocols in
`functualize.plugin` are structural, so having the methods is what counts.

Three of them matter for a backend that, like a password manager, has a lock:

- `VaultKeyProvider` — read the key. **Never prompt**: the reader may be a pipe,
  an agent or a cron job, and nobody there can answer a dialog. A locked
  backend answers "nothing" rather than asking to be opened.
- `VaultKeyProbe` — say whether a read would work, as a `KeyAvailability`,
  without reading the secret. Status surfaces call this.
- `VaultKeyUnlocker` — ask the backend to unlock. The one method that may show
  a prompt, called only because a person asked for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from functualize.plugin import KeyAvailability

if TYPE_CHECKING:
    from collections.abc import Callable


class PasswordManager:
    """Stands in for a password manager's client library: a store with a lock."""

    def __init__(self, master_password: str, items: dict[str, str]) -> None:
        self._master_password = master_password
        self._items = dict(items)
        self.locked = True
        self.secret_reads = 0

    def unlock(self, master_password: str) -> bool:
        self.locked = master_password != self._master_password
        return not self.locked

    def read(self, name: str) -> str | None:
        if self.locked:
            msg = "the password manager is locked"
            raise PermissionError(msg)
        self.secret_reads += 1
        return self._items.get(name)


class PasswordManagerKey:
    """The vault key, as the hex string stored under one password-manager item."""

    def __init__(
        self,
        manager: PasswordManager,
        *,
        item: str = "functualize vault key",
        ask_master_password: Callable[[], str | None],
    ) -> None:
        """Initialise the provider.

        Args:
            manager: The password manager's client.
            item: The item holding the key, as 64 hex characters.
            ask_master_password: Shows the person a prompt; None if they cancel.
                Only :meth:`unlock` calls it.
        """
        self._manager = manager
        self._item = item
        self._ask = ask_master_password

    # -- VaultKeyProvider --------------------------------------------------

    def identifier(self) -> str:
        return "password-manager"

    def interactive(self) -> bool:
        # Reading needs no person: a locked manager just answers "nothing".
        return False

    def is_available(self) -> bool:
        return True

    def get_key(self, project_id: str) -> bytes | None:
        """The key if the manager is unlocked; None, never a prompt, if not."""
        if self._manager.locked:
            return None
        stored = self._manager.read(self._item)
        return bytes.fromhex(stored) if stored else None

    # -- VaultKeyProbe -----------------------------------------------------

    def probe(self) -> KeyAvailability:
        """Locked or unlocked, without reading the secret."""
        return (
            KeyAvailability.LOCKED if self._manager.locked else KeyAvailability.UNLOCKED
        )

    # -- VaultKeyUnlocker --------------------------------------------------

    def unlock(self) -> bool:
        """Ask the person for the master password — the one call that prompts."""
        if not self._manager.locked:
            return True
        answer = self._ask()
        return answer is not None and self._manager.unlock(answer)
