"""The resolution-chain source backed by the local vault (ADR-016).

Sits between ``CliSource`` and ``EnvSource`` in the chain ``remote_first()``
produces, so a synced remote value outranks the environment and the config
file, while an explicit CLI argument still wins.

Reading is by **scoped identity**, not by annotation. A lookup names
``(scope, target, field)``, encoded as a :class:`VaultIdentity` storage key,
so a group entry and a job entry with identical text are two entries and a
flat pre-scope key is nobody's entry. Annotations matter when *syncing*,
which is where declarations are consulted.

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
once per run, at the first declared value that falls through — the first
moment the key is actually needed — while the second warns per declared
key, because "run ``vault sync``" is advice only the second case can act on.
That fall-through is made *visible* by :meth:`VaultSource.note_fallthrough`,
which the chain calls on any source that answered nothing, naming the source
that answered instead. Leaving it silent would rebuild the very defect this
feature exists to remove.

Which misses are worth a warning
--------------------------------

Every source misses constantly — ``database.port`` is not in the vault and
never will be. Warning on each would bury the one miss that matters, so the
test is not "the vault did not hold it" but **"somebody declared it a vault
secret"**: the identity was named in a ``[[vault_secret]]`` block, and the
chain's files were bound to this source at boot. The declaration check runs
*before* the key is asked for, so an ordinary value that falls through never
touches the keyring; no resolved value is inspected to decide anything.

Staleness
---------

Separately from any single key, the vault as a whole can be *old*. The first
read of a run compares :meth:`SecretsVault.age` against the configured
``max_age`` and warns once, then the run proceeds on what is stored. The check
hangs off the first read rather than construction so that building a source
without consulting it — ``func --help``, a completion — stays silent.

Nothing but an identity, an annotation or a failure reason is ever rendered
(ADR-008). None of the three carries a credential; every value the chain
hands this source could be the secret itself, so none of them reach the log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NoReturn

from functualize._config.vault import (
    SecretsVault,
    VaultEntryUnreadableError,
    VaultOrigin,
    format_duration,
)
from functualize._config.vault_declarations import parse_vault_declarations
from functualize._config.vault_key_resolver import (
    KeyLookup,
    KeyStatus,
    VaultKeyResolver,
    describe_key_failure,
)
from functualize._primitives.vault_identity import VaultIdentity, VaultScope

if TYPE_CHECKING:
    from datetime import timedelta
    from pathlib import Path

    from functualize._config.chain import ResolvedValue
    from functualize._config.vault import VaultEntry

__all__ = ["VaultSource"]

logger = logging.getLogger(__name__)


class VaultSource:
    """Resolves config values from the project's encrypted vault."""

    def __init__(
        self,
        vault_path: Path,
        *,
        key: VaultKeyResolver,
        max_age: timedelta | None = None,
    ) -> None:
        """Initialise the source.

        Args:
            vault_path: This project's vault file. It need not exist.
            key: Resolves the vault key — consulted only when a stored entry
                is about to be opened, never at construction.
            max_age: How old the vault may be before the first read of the run
                warns. None disables the staleness check entirely.
        """
        # Metadata only until a lookup names the provider; see `_lookup`.
        self._vault = SecretsVault(vault_path)
        self._key = key
        self._lookup_result: KeyLookup | None = None
        self._max_age = max_age
        self._staleness_checked = False
        self._opens_asked = False
        self._opens: bool | None = None
        self._entries_seen: dict[str, VaultEntry] | None = None
        self._identities_seen: frozenset[VaultIdentity] | None = None
        self._warned: set[str] = set()
        self._warned_no_key = False
        self._declaration_files: list[tuple[str, dict[str, Any]]] = []
        self._declaration_identities: frozenset[VaultIdentity] | None = None
        self.misses: list[str] = []
        """Identities this source was asked for and did not hold, display-spelled.

        Recorded here rather than derived later because only this source knows
        it was asked. Distinct from ``_warned``: a miss is every unanswered
        key, a warning only the subset somebody declared.
        """

    @property
    def resolver(self) -> VaultKeyResolver:
        """The resolver this source asks, so a status surface can share its cache."""
        return self._key

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
        declaration check in :meth:`note_fallthrough`. Deliberately distinct
        from :attr:`usable`. "This machine cannot open the vault" and "nobody
        has synced yet" are different situations with different fixes, and
        conflating them is what let the most common first-run case — a key
        exported, ``vault sync`` never run — fall through in silence. See
        :meth:`note_fallthrough`.
        """
        return self._lookup().status is KeyStatus.FOUND

    @staticmethod
    def _identity(
        key: str, section: str | None, scope: VaultScope
    ) -> VaultIdentity | None:
        """The storage identity a lookup names, or None when it names none.

        Scope is the third component of identity, so ``(group, deploy,
        token)`` and ``(job, deploy, token)`` are two entries — the vault key
        encodes which. A sectionless lookup names no target and therefore no
        identity; the vault answers nothing for it rather than guessing a
        scope.
        """
        if section is None:
            return None
        return VaultIdentity(scope, section, key)

    @staticmethod
    def _display(identity: VaultIdentity) -> str:
        """The human spelling of an identity: ``deploy.api_token`` for a job,
        ``group deploy.api_token`` for a group. The scope prefix is what keeps
        the two from reading as one entry in a warning or an error."""
        prefix = "group " if identity.scope == "group" else ""
        return f"{prefix}{identity.target}.{identity.field}"

    @staticmethod
    def _remove_flags(identity: VaultIdentity) -> str:
        """What follows ``vault remove`` for this entry: its scoped flags."""
        flag = "--group" if identity.scope == "group" else "--job"
        return f"{flag} {identity.target} --field {identity.field}"

    @classmethod
    def _remove_command(cls, identity: VaultIdentity) -> str:
        """The exact command that drops this entry, no key needed."""
        return f"vault remove {cls._remove_flags(identity)}"

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

    def get(
        self,
        key: str,
        section: str | None = None,
        *,
        scope: VaultScope = "job",
    ) -> Any | None:
        """Return a stored value, or None to defer to the next source.

        **Presence decides, not origin** (ADR-023 §1). An absent entry falls
        through without resolving the key. An entry that *is* stored is the
        intended value, so failing to open it refuses the run rather than
        quietly selecting something weaker — the operator would otherwise get
        a different secret than they provisioned, with the run reporting
        success.

        Raises:
            VaultEntryUnreadableError: An entry exists for this identity and
                no usable key is available for it.
            VaultDecryptionError: A stored value will not authenticate.
        """
        # No file: nothing was ever stored — the common case, checked first.
        if not self._vault.path.exists():
            return None

        identity = self._identity(key, section, scope)
        if identity is None:
            return None

        # Not stored: nothing to open, so nothing to resolve — the line that
        # keeps a run reading no stored entry off the keyring.
        entry = self._stored_entries().get(identity.encode())
        if entry is None:
            self.misses.append(self._display(identity))
            return None

        display = self._display(identity)
        lookup = self._lookup()
        if lookup.status is not KeyStatus.FOUND:
            self._refuse(
                display,
                describe_key_failure(
                    lookup,
                    qualified=display,
                    direct=entry.origin is VaultOrigin.DIRECT,
                    remove_target=self._remove_flags(identity),
                ),
            )
        assert lookup.key is not None

        self._warn_if_stale()

        # The check value answers "is this the key this store was written
        # with?" without decrypting anybody's secret. `None` means the store
        # predates the check row, in which case the old behaviour stands and
        # `get` below is left to discover a wrong key the expensive way.
        if self._opens_with_key(lookup.key) is False:
            self._refuse(display, self._wrong_key_text(identity, entry, lookup))

        # VaultDecryptionError deliberately propagates. A vault that cannot be
        # read is a different situation from one that does not hold the key,
        # and collapsing them would hide a wrong-key configuration behind a
        # silent fall-through -- the defect this feature exists to remove.
        value = self._vault.get(identity.encode(), encryption_key=lookup.key)
        if value is None:
            self.misses.append(display)
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
        """Every entry the store holds, by encoded key, read once, key-free.

        Metadata is stored in clear precisely so "is something stored here?"
        is answerable on a machine that cannot decrypt anything. Read once per
        source. The source is built at boot and the chain is rebuilt on
        `refresh()`, so a `vault put` from a separate process is picked up by
        the next run — which is the only sequence that occurs.
        """
        if self._entries_seen is None:
            # Metadata only. Every caller checks the file exists first:
            # listing a non-existent SQLite path would create it.
            self._entries_seen = {e.key: e for e in self._vault.list_entries()}
        return self._entries_seen

    def _stored_identities(self) -> frozenset[VaultIdentity]:
        """The identities behind :meth:`_stored_entries`, decoded once.

        A key that does not decode — a flat ``section.field`` written before
        identities were scoped, or by a test reaching past the codec — is
        skipped rather than guessed at: it names no scoped identity, so no
        scoped lookup is it.
        """
        if self._identities_seen is None:
            seen: set[VaultIdentity] = set()
            for encoded in self._stored_entries():
                try:
                    seen.add(VaultIdentity.decode(encoded))
                except ValueError:
                    continue
            self._identities_seen = frozenset(seen)
        return self._identities_seen

    @staticmethod
    def _refuse(display: str, because: str) -> NoReturn:
        """Refuse a stored entry that cannot be opened (ADR-023 §1)."""
        msg = (
            f"{because}\n\n"
            f"Refusing rather than falling through to the environment or a "
            f"config file: the value stored for {display!r} is the one you "
            f"provisioned, and running on a different one would look like "
            f"success."
        )
        raise VaultEntryUnreadableError(msg)

    def _wrong_key_text(
        self, identity: VaultIdentity, entry: VaultEntry, lookup: KeyLookup
    ) -> str:
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
            f"The vault holds a value for {self._display(identity)!r}, but the "
            f"key supplied by the {lookup.provider_id!r} provider does not "
            f"open this vault.\n\nFix it with one of:\n"
            + "\n".join(fixes)
            + f"\nLast resort — these need no key, but each destroys stored "
            f"values{only_copy}:\n"
            f"  func builtin {self._remove_command(identity)}   drop this entry\n"
            f"  func builtin vault clear                drop the whole store"
        )

    def has(
        self, key: str, section: str | None = None, *, scope: VaultScope = "job"
    ) -> bool:
        """Whether the vault holds this identity — metadata only, never the key.

        A stored entry this machine cannot open answers True and :meth:`get`
        refuses it, so the two agree that the value is not silently absent.
        """
        if not self.usable:
            return False
        identity = self._identity(key, section, scope)
        return identity is not None and identity.encode() in self._stored_entries()

    def keys(self, section: str, *, scope: VaultScope = "job") -> set[str]:
        """Every field the vault holds for one scope's section — metadata only.

        So a section with a stored entry that cannot be opened refuses at that
        entry (ADR-023 §1) rather than silently leaving it out.
        """
        if not self.usable:
            return set()
        return {
            identity.field
            for identity in self._stored_identities()
            if identity.scope == scope and identity.target == section
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

    def set_declaration_files(self, files: list[tuple[str, dict[str, Any]]]) -> None:
        """Bind the parsed files after the chain is assembled, without fetching."""
        self._declaration_files = files
        self._declaration_identities = None

    def _declared_identities(self) -> frozenset[VaultIdentity]:
        """The identities ``[[vault_secret]]`` blocks declare, parsed lazily.

        Lazy because the source is constructed before the chain's files are
        read; a parse failure warns and answers nothing, so a malformed block
        breaks `vault sync` (where it is fatal) without breaking every
        ordinary command in the project.
        """
        if self._declaration_identities is None:
            try:
                identities = frozenset(
                    item.identity
                    for item in parse_vault_declarations(self._declaration_files)
                )
            except Exception as exc:
                logger.warning(
                    "Skipping the [[vault_secret]] declarations (%s). "
                    "`func builtin vault sync` reports the block it refuses; "
                    "this warning only means unsynced-declaration detection "
                    "is off for this run.",
                    exc,
                )
                identities = frozenset()
            self._declaration_identities = identities
        return self._declaration_identities

    def note_fallthrough(
        self,
        resolved: ResolvedValue,
        section: str | None = None,
        *,
        scope: VaultScope = "job",
    ) -> None:
        """Warn that a declared vault secret was answered by something else.

        Called by :class:`~functualize._config.chain.ResolutionChain` on every
        source that returned None, after the winner is known — which is the
        only moment "resolved from X instead" can be said truthfully.

        Fires at most once per identity per run, so a job reading one secret
        ten times warns once, and stays silent unless a matching explicit
        declaration appears in a discovered config file. See the module
        docstring for why those two conditions are the right ones.

        Args:
            resolved: The winning value and its provenance, including the
                alternatives from lower-priority sources.
            section: The section the key was resolved in, if any.
            scope: Whether that section names a group or a job.
        """
        identity = self._identity(resolved.key, section, scope)
        if identity is None or identity.encode() in self._warned:
            return

        # The declaration first, the key second. Asking `opens` resolves the
        # key, and an ordinary value that falls through — `database.port` —
        # must never be what touches the keyring.
        if identity not in self._declared_identities():
            return

        if not self.opens:
            # No key: warned once per run, at the first declared value that
            # needed it — never per identity, which would drown the message.
            # Gated on `opens` rather than `usable` on purpose. A vault file
            # that does not exist yet is the opposite case: the key is there,
            # nothing has been synced, and "run `vault sync`" is exactly the
            # advice the per-identity warning below gives. Silence there was
            # a real defect — every test used a vault that existed, so
            # nothing caught it until the documentation's own example was
            # executed.
            if not self._warned_no_key:
                self._warned_no_key = True
                logger.warning(
                    "Config key '%s' has a [[vault_secret]] declaration, but "
                    "the vault key is not available, so declared values fall "
                    "back to local sources. %s",
                    self._display(identity),
                    describe_key_failure(self._lookup()),
                )
            return

        self._warned.add(identity.encode())
        answered = f"{resolved.source_type} ({resolved.source_id})"
        logger.warning(
            "Config key '%s' has a [[vault_secret]] declaration, but the vault "
            "holds no synced value for it. It resolved from %s instead. "
            "Run `func builtin vault sync` to fill the vault.",
            self._display(identity),
            answered,
        )
