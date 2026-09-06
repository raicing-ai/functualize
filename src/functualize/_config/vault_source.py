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

In both cases resolution continues to the next source. That fall-through is
made *visible* by :meth:`VaultSource.note_fallthrough`, which the chain calls
on any source that answered nothing, naming the source that answered instead.
Leaving it silent would rebuild the very defect this feature exists to remove.

Which misses are worth a warning
--------------------------------

Every source misses constantly — ``database.port`` is not in the vault and
never will be. Warning on each would bury the one miss that matters, so the
test is not "the vault did not hold it" but **"somebody declared it remote"**:
the winning value, or one of the alternatives beneath it, is annotation-shaped
for a *registered* provider. That fires exactly when a job is about to receive
``aws-sm://prod/db`` where it expected a password.

The cost of that precision is a blind spot, stated plainly: a key declared
remote in a config file that an environment variable also supplies, where the
config file was never discovered at all, has no annotation anywhere in the
chain and so warns about nothing. Filling it needs the annotation map from a
config pre-scan, which boot does not build yet.

Nothing but an annotation is ever rendered (ADR-008). An annotation names
where a credential lives and carries no credential; every other value the
chain hands this method could be the secret itself, so none of them reach the
log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize._config.annotations import scan_annotations
from functualize._config.vault import SecretsVault

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from functualize._config.chain import ResolvedValue

__all__ = ["VaultSource"]

logger = logging.getLogger(__name__)

#: Placeholder key used to reuse `scan_annotations` for a single value. The
#: classifier is shared rather than reimplemented so "is this an annotation?"
#: keeps exactly one answer, the same discipline ADR-008 applies to secrets.
_PROBE = "_"


class VaultSource:
    """Resolves config values from the project's encrypted vault."""

    def __init__(
        self,
        vault_path: Path,
        *,
        encryption_key: bytes | None,
        key_provider_id: str = "unknown",
        providers: Iterable[str] = (),
    ) -> None:
        """Initialise the source.

        Args:
            vault_path: This project's vault file. It need not exist.
            encryption_key: The key, or None when no provider supplied one —
                in which case the source answers nothing rather than raising.
            key_provider_id: Which provider supplied the key, so a decryption
                failure can name it.
            providers: Identifiers of the registered remote providers. Used
                only to recognise an annotation when warning about a miss; a
                scheme absent here is not an annotation, exactly as in
                :func:`~functualize._config.annotations.scan_annotations`.
        """
        self._vault = SecretsVault(vault_path, key_provider_id=key_provider_id)
        self._key = encryption_key
        self._key_provider_id = key_provider_id
        self._providers = frozenset(providers)
        self._warned: set[str] = set()
        self.misses: list[str] = []
        """Fully-qualified keys this source was asked for and did not hold.

        Recorded here rather than derived later because only this source knows
        it was asked. Distinct from ``_warned``: a miss is every unanswered
        key, a warning only the subset somebody declared remote.
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

    def note_fallthrough(
        self, resolved: ResolvedValue, section: str | None = None
    ) -> None:
        """Warn that a key declared remote was answered by something else.

        Called by :class:`~functualize._config.chain.ResolutionChain` on every
        source that returned None, after the winner is known — which is the
        only moment "resolved from X instead" can be said truthfully.

        Fires at most once per key per run, so a job reading one secret ten
        times warns once, and stays silent unless an annotation is present
        somewhere in the chain for that key. See the module docstring for why
        those two conditions are the right ones.

        Args:
            resolved: The winning value and its provenance, including the
                alternatives from lower-priority sources.
            section: The section the key was resolved in, if any.
        """
        if not self.usable:
            # Boot already warned once that no key is available; repeating it
            # per key would drown the message rather than sharpen it.
            return

        qualified = self._qualified(resolved.key, section)
        if qualified in self._warned:
            return

        annotation = self._annotation_in(resolved)
        if annotation is None:
            return

        self._warned.add(qualified)
        answered = f"{resolved.source_type} ({resolved.source_id})"
        if annotation == resolved.value:
            consequence = (
                f"The job will receive the literal annotation string from "
                f"{answered}, not the secret it names."
            )
        else:
            consequence = f"It resolved from {answered} instead."
        logger.warning(
            "Config key '%s' is declared remotely as '%s', but the vault holds "
            "no synced value for it. %s Run `func builtin vault sync` to fill "
            "the vault.",
            qualified,
            annotation,
            consequence,
        )

    def _annotation_in(self, resolved: ResolvedValue) -> str | None:
        """The first annotation among the winner and its alternatives, if any.

        The winner is checked first because it is the value the job actually
        receives, and therefore the one whose annotation describes what went
        wrong most directly.
        """
        candidates = [resolved.value, *(value for _, _, value in resolved.alternatives)]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            scan = scan_annotations({_PROBE: candidate}, self._providers)
            if _PROBE in scan.annotations:
                return candidate
        return None

    def _entries(self) -> list[Any]:
        # Metadata only, so this never decrypts. It is still gated behind
        # `usable` by both callers: a source that answers `has() is True` and
        # then yields None from `get()` breaks the chain's contract, so with no
        # key this source must claim nothing rather than claim what it cannot
        # deliver.
        return self._vault.list_entries()
