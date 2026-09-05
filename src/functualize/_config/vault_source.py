"""The resolution-chain source backed by the local vault (ADR-016).

Sits between ``CliSource`` and ``EnvSource`` in the chain ``remote_first()``
produces, so a synced remote value outranks the environment and the config
file, while an explicit CLI argument still wins.

Reading is by **config key**, not by annotation. The vault row already records
which annotation and which provider produced a value, so answering
``database.password`` needs no re-parsing at read time — annotations matter
when *syncing*, which is where they are consulted.

This source is deliberately inert rather than fatal in two situations, because
both are reachable from ``func --help``:

* **No key available.** The vault cannot be opened, so it answers nothing.
* **No vault file yet.** Nobody has run ``vault sync``.

In both cases resolution continues to the next source. Making that fall-through
*visible* is task 3.2; making it silent would rebuild the very defect this
feature exists to remove, so the plumbing for the warning is carried here
(:attr:`VaultSource.misses`) even though the warning itself is not yet emitted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._config.vault import SecretsVault

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["VaultSource"]


class VaultSource:
    """Resolves config values from the project's encrypted vault."""

    def __init__(
        self,
        vault_path: Path,
        *,
        encryption_key: bytes | None,
        key_provider_id: str = "unknown",
    ) -> None:
        """Initialise the source.

        Args:
            vault_path: This project's vault file. It need not exist.
            encryption_key: The key, or None when no provider supplied one —
                in which case the source answers nothing rather than raising.
            key_provider_id: Which provider supplied the key, so a decryption
                failure can name it.
        """
        self._vault = SecretsVault(vault_path, key_provider_id=key_provider_id)
        self._key = encryption_key
        self._key_provider_id = key_provider_id
        self.misses: list[str] = []
        """Fully-qualified keys this source was asked for and did not hold.

        Read by task 3.2 to warn once per key per run. Recorded here rather
        than derived later because only this source knows it was asked.
        """

    @property
    def source_type(self) -> str:
        return "remote"

    @property
    def source_id(self) -> str:
        return "vault"

    @property
    def usable(self) -> bool:
        """Whether this source can answer anything at all."""
        return self._key is not None and self._vault.path.exists()

    def _qualified(self, key: str, section: str | None) -> str:
        return f"{section}.{key}" if section else key

    def get(self, key: str, section: str | None = None) -> Any | None:
        """Return a synced value, or None to defer to the next source.

        Raises:
            VaultDecryptionError: If a stored value will not authenticate. This
                is *not* softened into a miss: a vault that cannot be read is a
                different situation from one that does not hold the key, and
                collapsing them would hide a wrong-key configuration behind a
                silent fall-through.
        """
        if not self.usable:
            return None
        qualified = self._qualified(key, section)
        assert self._key is not None  # narrowed by `usable`
        # VaultDecryptionError deliberately propagates. A vault that cannot be
        # read is a different situation from one that does not hold the key,
        # and collapsing them would hide a wrong-key configuration behind a
        # silent fall-through -- the defect this feature exists to remove.
        value = self._vault.get(qualified, encryption_key=self._key)
        if value is None:
            self.misses.append(qualified)
            return None
        return value

    def has(self, key: str, section: str | None = None) -> bool:
        """Whether the vault holds this key, without decrypting it."""
        if not self.usable:
            return False
        return self._qualified(key, section) in {e.key for e in self._entries()}

    def keys(self, section: str) -> set[str]:
        """Every key the vault holds for a section, without decrypting any."""
        if not self.usable:
            return set()
        prefix = f"{section}."
        return {
            entry.key[len(prefix) :]
            for entry in self._entries()
            if entry.key.startswith(prefix)
        }

    def _entries(self) -> list[Any]:
        # Metadata only, so this never decrypts. It is still gated behind
        # `usable` by both callers: a source that answers `has() is True` and
        # then yields None from `get()` breaks the chain's contract, so with no
        # key this source must claim nothing rather than claim what it cannot
        # deliver.
        return self._vault.list_entries()
