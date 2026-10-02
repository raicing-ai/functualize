"""The resolution-chain source backed by the local vault (ADR-016).

Sits between ``CliSource`` and ``EnvSource`` in the chain ``remote_first()``
produces, so a synced remote value outranks the environment and the config
file, while an explicit CLI argument still wins.

Reading is by **config key**, not by annotation. The vault row already records
which annotation and which provider produced a value, so answering
``database.password`` needs no re-parsing at read time — annotations matter
when *syncing*, which is where they are consulted.

The key is lazy
---------------

The source holds a resolver, not a key, and asks it only when a run is about
to **open a stored entry**. Which entries are stored is clear-text metadata
(ADR-023 §1), so ``has``, ``keys`` and "is this stored at all?" never need the
key, and a run reading nothing the vault holds never touches the keyring.

This source is deliberately inert rather than fatal in two situations, because
both are reachable from ``func --help``:

* **No key available.** Nothing stored is consulted, so nothing is resolved;
  a *stored* entry that cannot be opened refuses at the point of use.
* **No vault file yet.** Nobody has run ``vault sync``.

In both cases resolution of an unstored key continues to the next source, and
the two are *not* treated alike when it comes to saying so: the first warns
once per run, at the first declared-remote value that falls through — the
first moment the key is actually needed — while the second warns per declared
key, because "run ``vault sync``" is advice only the second case can act on.
That fall-through is made *visible* by :meth:`VaultSource.note_fallthrough`,
which the chain calls on any source that answered nothing, naming the source
that answered instead. Leaving it silent would rebuild the very defect this
feature exists to remove.

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
from typing import TYPE_CHECKING, Any, NoReturn

from functualize._config.annotations import scan_annotations
from functualize._config.vault import (
    SecretsVault,
    VaultEntryUnreadableError,
    VaultOrigin,
    format_duration,
)
from functualize._config.vault_key_resolver import (
    KeyLookup,
    KeyStatus,
    VaultKeyResolver,
    describe_key_failure,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import timedelta
    from pathlib import Path

    from functualize._config.chain import ResolvedValue
    from functualize._config.vault import VaultEntry

__all__ = ["VaultSource"]

logger = logging.getLogger(__name__)

#: Placeholder key used to reuse `scan_annotations` for a single value. The
#: classifier is shared rather than reimplemented so "is this an annotation?"
#: keeps exactly one answer, the same discipline ADR-008 applies to secrets.
_PROBE = "_"

#: Distinguishes "not passed" from an explicit ``encryption_key=None``.
_UNSET: Any = object()


class _NoKeyStored:
    """Live, holds nothing. TRANSITIONAL(4.1): goes with ``encryption_key=None``."""

    def identifier(self) -> str:
        return "none"

    def interactive(self) -> bool:
        return False

    def is_available(self) -> bool:
        return True

    def get_key(self, project_id: str) -> bytes | None:
        return None


class VaultSource:
    """Resolves config values from the project's encrypted vault."""

    def __init__(
        self,
        vault_path: Path,
        *,
        key: VaultKeyResolver | None = None,
        # TRANSITIONAL(4.1): the eager spelling, kept until every construction
        # site has moved to `key=` (3.1 for boot, 3.4 for the tests). Mutually
        # exclusive with `key=`; translated into a resolver below.
        encryption_key: bytes | None = _UNSET,
        key_provider_id: str = "unknown",
        providers: Iterable[str] = (),
        max_age: timedelta | None = None,
    ) -> None:
        """Initialise the source.

        Args:
            vault_path: This project's vault file. It need not exist.
            key: Resolves the vault key — consulted only when a stored entry
                is about to be opened, never at construction.
            encryption_key: Transitional eager spelling of ``key``, with
                ``key_provider_id`` naming its provider.
            providers: Identifiers of the registered remote providers. Used
                only to recognise an annotation when warning about a miss; a
                scheme absent here is not an annotation, exactly as in
                :func:`~functualize._config.annotations.scan_annotations`.
            max_age: How old the vault may be before the first read of the run
                warns. None disables the staleness check entirely.
        """
        if key is None:
            if encryption_key is _UNSET:
                msg = "VaultSource needs key= (a VaultKeyResolver)."
                raise TypeError(msg)
            key = (
                VaultKeyResolver("", providers=(_NoKeyStored(),))
                if encryption_key is None
                else VaultKeyResolver.fixed(encryption_key, key_provider_id)
            )
        elif encryption_key is not _UNSET:
            msg = "VaultSource takes key= or encryption_key=, not both."
            raise TypeError(msg)
        # Metadata only until a lookup names the provider; see `_lookup`.
        self._vault = SecretsVault(vault_path)
        self._key = key
        self._lookup_result: KeyLookup | None = None
        self._providers = frozenset(providers)
        self._max_age = max_age
        self._staleness_checked = False
        self._opens_asked = False
        self._opens: bool | None = None
        self._entries_seen: dict[str, VaultEntry] | None = None
        self._warned: set[str] = set()
        self._warned_no_key = False
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

        The file decides, not the key: which entries are stored is clear-text
        metadata, answerable on a machine that cannot decrypt anything. With
        no file there is nothing to read — and opening a non-existent SQLite
        path would *create* one.
        """
        return self._vault.path.exists()

    @property
    def opens(self) -> bool:
        """Whether a key is available, regardless of what is stored.

        **Resolves the key** (bounded), so it is asked only after the
        annotation check in :meth:`note_fallthrough`. Deliberately distinct from :attr:`usable`. "This machine cannot open
        the vault" and "nobody has synced yet" are different situations with
        different fixes, and conflating them is what let the most common
        first-run case — a key exported, ``vault sync`` never run — fall
        through in silence. See :meth:`note_fallthrough`.
        """
        return self._lookup().status is KeyStatus.FOUND

    def _qualified(self, key: str, section: str | None) -> str:
        return f"{section}.{key}" if section else key

    def _lookup(self) -> KeyLookup:
        """Resolve the key once per source, on first need."""
        if self._lookup_result is None:
            lookup = self._key.lookup()
            if lookup.status is KeyStatus.FOUND:
                # Rebuilt, not mutated: the provider id is only known after
                # the lookup, and `SecretsVault` stamps it on every write and
                # names it in a decryption failure. Construction is two
                # attribute assignments and no I/O, and the instance holds no
                # state between calls (plan S-3, reviewed).
                self._vault = SecretsVault(
                    self._vault.path,
                    key_provider_id=lookup.provider_id or "unknown",
                )
            self._lookup_result = lookup
        return self._lookup_result

    def get(self, key: str, section: str | None = None) -> Any | None:
        """Return a stored value, or None to defer to the next source.

        **Presence decides, not origin** (ADR-023 §1). An absent entry falls
        through without resolving the key. An entry that *is* stored is the
        intended value, so failing to open it refuses the run rather than
        quietly selecting something weaker — the operator would otherwise get a
        different secret than they provisioned, with the run reporting success.

        Raises:
            VaultEntryUnreadableError: An entry exists for this key and no
                usable key is available for it.
            VaultDecryptionError: A stored value will not authenticate.
        """
        # No file: nothing was ever stored — the common case, checked first.
        if not self._vault.path.exists():
            return None

        qualified = self._qualified(key, section)

        # Not stored: nothing to open, so nothing to resolve — the line that
        # keeps a run reading no stored entry off the keyring.
        entry = self._stored_entries().get(qualified)
        if entry is None:
            self.misses.append(qualified)
            return None

        lookup = self._lookup()
        if lookup.status is not KeyStatus.FOUND:
            self._refuse(
                qualified,
                describe_key_failure(
                    lookup,
                    qualified=qualified,
                    direct=entry.origin is VaultOrigin.DIRECT,
                ),
            )
        assert lookup.key is not None

        self._warn_if_stale()

        # The check value answers "is this the key this store was written
        # with?" without decrypting anybody's secret. `None` means the store
        # predates the check row, in which case the old behaviour stands and
        # `get` below is left to discover a wrong key the expensive way.
        if self._opens_with_key(lookup.key) is False:
            self._refuse(qualified, self._wrong_key_text(qualified, entry, lookup))

        # VaultDecryptionError deliberately propagates. A vault that cannot be
        # read is a different situation from one that does not hold the key,
        # and collapsing them would hide a wrong-key configuration behind a
        # silent fall-through -- the defect this feature exists to remove.
        value = self._vault.get(qualified, encryption_key=lookup.key)
        if value is None:
            self.misses.append(qualified)
            return None
        return value

    def _opens_with_key(self, key: bytes) -> bool | None:
        """Whether this key opens this store, asked once per run.

        A separate `_opens_asked` flag, because `None` is already a real
        answer: "this store has no check row, so it cannot say".
        """
        if not self._opens_asked:
            self._opens = self._vault.opens_with(key)
            self._opens_asked = True
        return self._opens

    def _stored_entries(self) -> dict[str, VaultEntry]:
        """Every entry the store holds, by key, read once and without the key.

        Metadata is stored in clear precisely so "is something stored here?"
        is answerable on a machine that cannot decrypt anything. Read once per
        source. The source is built at boot and the chain is
        rebuilt on `refresh()`, so a `vault put` from a separate process is
        picked up by the next run — which is the only sequence that occurs.
        """
        if self._entries_seen is None:
            # Metadata only. Every caller checks the file exists first:
            # listing a non-existent SQLite path would create it.
            self._entries_seen = {e.key: e for e in self._vault.list_entries()}
        return self._entries_seen

    @staticmethod
    def _refuse(qualified: str, because: str) -> NoReturn:
        """Refuse a stored entry that cannot be opened (ADR-023 §1)."""
        msg = (
            f"{because}\n\n"
            f"Refusing rather than falling through to the environment or a "
            f"config file: the value stored for {qualified!r} is the one you "
            f"provisioned, and running on a different one would look like "
            f"success."
        )
        raise VaultEntryUnreadableError(msg)

    @staticmethod
    def _wrong_key_text(qualified: str, entry: VaultEntry, lookup: KeyLookup) -> str:
        """A key that is not this store's. Recoveries that keep the secret come
        first; ``sync`` only for a provider entry; ``remove``/``clear`` last,
        with the warning that they destroy it (for a direct entry, the only copy).
        """
        direct = entry.origin is VaultOrigin.DIRECT
        fixes = [
            "  supply the key this vault was written with (export "
            "$FUNCTUALIZE_VAULT_KEY, or restore it to the OS keyring)",
        ]
        if not direct:
            fixes.append(
                "  func builtin vault sync                 refetch it from upstream"
            )
        only_copy = (
            ", and for this hand-typed entry that is the only copy" if direct else ""
        )
        return (
            f"The vault holds a value for {qualified!r}, but the key supplied "
            f"by the {lookup.provider_id!r} provider does not open this vault."
            f"\n\nFix it with one of:\n"
            + "\n".join(fixes)
            + f"\nLast resort — these need no key, but each destroys stored "
            f"values{only_copy}:\n"
            f"  func builtin vault remove {qualified}   drop this entry\n"
            f"  func builtin vault clear                drop the whole store"
        )

    def has(self, key: str, section: str | None = None) -> bool:
        """Whether the vault holds this key — metadata only, never the key.

        A stored entry this machine cannot open answers True and :meth:`get`
        refuses it, so the two agree that the value is not silently absent.
        """
        if not self.usable:
            return False
        return self._qualified(key, section) in self._stored_entries()

    def keys(self, section: str) -> set[str]:
        """Every key the vault holds for a section — metadata only.

        So a section with a stored entry that cannot be opened refuses at that
        entry (ADR-023 §1) rather than silently leaving it out.
        """
        if not self.usable:
            return set()
        prefix = f"{section}."
        return {
            name[len(prefix) :]
            for name in self._stored_entries()
            if name.startswith(prefix)
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
        qualified = self._qualified(resolved.key, section)
        if qualified in self._warned:
            return

        # The annotation first, the key second. Asking `opens` resolves the
        # key, and an ordinary value that falls through — `database.port` —
        # must never be what touches the keyring.
        annotation = self._annotation_in(resolved)
        if annotation is None:
            return

        if not self.opens:
            # No key: warned once per run, at the first declared value that
            # needed it — never per key, which would drown the message. Gated on `opens` rather than `usable` on purpose. A vault file
            # that does not exist yet is the opposite case: the key is there,
            # nothing has been synced, and "run `vault sync`" is exactly the
            # advice the per-key warning below gives. Silence there was a real
            # defect — every test used a vault that existed, so nothing caught
            # it until the documentation's own example was executed.
            if not self._warned_no_key:
                self._warned_no_key = True
                logger.warning(
                    "Config key '%s' is declared remotely as '%s', but the vault "
                    "key is not available, so declared remote values fall back "
                    "to local sources. %s",
                    qualified,
                    annotation,
                    describe_key_failure(self._lookup()),
                )
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
