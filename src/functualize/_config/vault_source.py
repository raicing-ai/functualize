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

In both cases resolution continues to the next source, and the two are *not*
treated alike when it comes to saying so: the first is announced once at boot,
the second warns per declared key, because "run ``vault sync``" is advice only
the second case can act on. That fall-through is
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

Staleness
---------

Separately from any single key, the vault as a whole can be *old*. The first
read of a run compares :meth:`SecretsVault.age` against the configured
``max_age`` and warns once, then the run proceeds on what is stored. The check
hangs off the first read rather than construction so that building a source
without consulting it — ``func --help``, a completion — stays silent.

Nothing but an annotation is ever rendered (ADR-008). An annotation names
where a credential lives and carries no credential; every other value the
chain hands this method could be the secret itself, so none of them reach the
log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize._config.annotations import scan_annotations
from functualize._config.vault import SecretsVault, format_duration

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import timedelta
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
        max_age: timedelta | None = None,
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
            max_age: How old the vault may be before the first read of the run
                warns. None disables the staleness check entirely.
        """
        self._vault = SecretsVault(vault_path, key_provider_id=key_provider_id)
        self._key = encryption_key
        self._key_provider_id = key_provider_id
        self._providers = frozenset(providers)
        self._max_age = max_age
        self._staleness_checked = False
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
        """Whether this source can answer anything at all.

        Both halves matter, and for different reasons: with no key nothing
        decrypts, and with no file there is nothing to read — opening a
        non-existent SQLite path would *create* one.
        """
        return self._key is not None and self._vault.path.exists()

    @property
    def opens(self) -> bool:
        """Whether a key is available, regardless of what is stored.

        Deliberately distinct from :attr:`usable`. "This machine cannot open
        the vault" and "nobody has synced yet" are different situations with
        different fixes, and conflating them is what let the most common
        first-run case — a key exported, ``vault sync`` never run — fall
        through in silence. See :meth:`note_fallthrough`.
        """
        return self._key is not None

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
        self._warn_if_stale()
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

    def _warn_if_stale(self) -> None:
        """Warn once per run that the vault is older than its threshold.

        Deferred to the first *read* rather than done at construction, so the
        paths that build a source without consulting it — ``func --help``, a
        completion, a job that resolves no config at all — stay quiet. A stale
        vault is only worth mentioning to someone about to use it.

        Never raises and never blocks. ADR-016 rejected auto-syncing here
        precisely because it would put the network back on the run path; the
        run continues on what is stored, which is what keeps a developer on a
        plane working.
        """
        if self._staleness_checked or self._max_age is None:
            return
        self._staleness_checked = True
        age = self._vault.age()
        if age is None or age <= self._max_age:
            return
        logger.warning(
            "The vault was last synced %s ago, past the %s staleness "
            "threshold. Any value rotated since is stale here. Run "
            "`func builtin vault sync` to refresh it — continuing meanwhile "
            "with what is stored.",
            format_duration(age),
            format_duration(self._max_age),
        )

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
        if not self.opens:
            # No key: boot already warned once, and with no key *every* lookup
            # falls through, so a per-key warning would drown that message
            # rather than sharpen it.
            #
            # Gated on `opens` rather than `usable` on purpose. A vault file
            # that does not exist yet is the opposite case: the key is there,
            # nothing has been synced, and "run `vault sync`" is exactly the
            # advice this warning gives. Silence there was a real defect —
            # every test used a vault that existed, so nothing caught it until
            # the documentation's own example was executed.
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
