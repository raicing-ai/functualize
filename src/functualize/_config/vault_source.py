"""The local vault source in the shared config resolution chain.

Stored scoped identities answer before environment and config file sources.
On a miss, only identities declared by ``[[vault_secret]]`` warn. The source
is bound to parsed file data after the chain is built and parses declarations
lazily, so ordinary boot remains cheap. A warning names the winning source
without logging its value or the provider reference.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from functualize._config.vault import (
    SecretsVault,
    VaultEntryUnreadableError,
    format_duration,
)
from functualize._config.vault_declarations import parse_vault_declarations
from functualize._primitives.vault_identity import VaultIdentity, VaultScope

if TYPE_CHECKING:
    from datetime import timedelta
    from pathlib import Path

    from functualize._config.chain import ResolvedValue

__all__ = ["VaultSource"]

logger = logging.getLogger(__name__)


class VaultSource:
    """Resolves config values from the project's encrypted vault."""

    def __init__(
        self,
        vault_path: Path,
        *,
        encryption_key: bytes | None,
        key_provider_id: str = "unknown",
        max_age: timedelta | None = None,
    ) -> None:
        """Initialise the source.

        Args:
            vault_path: This project's vault file. It need not exist.
            encryption_key: The key, or None when no provider supplied one —
                in which case the source answers nothing rather than raising.
            key_provider_id: Which provider supplied the key, so a decryption
                failure can name it.
            max_age: How old the vault may be before the first read of the run
                warns. None disables the staleness check entirely.
        """
        self._vault = SecretsVault(vault_path, key_provider_id=key_provider_id)
        self._key = encryption_key
        self._key_provider_id = key_provider_id
        self._max_age = max_age
        self._staleness_checked = False
        self._opens_asked = False
        self._opens: bool | None = None
        self._identities_seen: frozenset[VaultIdentity] | None = None
        self._warned: set[str] = set()
        self._declaration_files: list[tuple[str, dict[str, Any]]] = []
        self._declaration_identities: frozenset[VaultIdentity] | None = None
        self.misses: list[str] = []
        """Identities this source was asked for and did not hold, display-spelled.

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
    def _remove_command(identity: VaultIdentity) -> str:
        """The exact command that drops this entry, no key needed."""
        flag = "--group" if identity.scope == "group" else "--job"
        return f"vault remove {flag} {identity.target} --field {identity.field}"

    def get(
        self,
        key: str,
        section: str | None = None,
        *,
        scope: VaultScope = "job",
    ) -> Any | None:
        """Return a stored value, or None to defer to the next source.

        **Presence decides, not origin** (ADR-023 §1). An absent entry falls
        through, exactly as before. An entry that *is* stored is the intended
        value, so failing to open it refuses the run rather than quietly
        selecting something weaker — the operator would otherwise get a
        different secret than they provisioned, with the run reporting success.

        Raises:
            VaultEntryUnreadableError: An entry exists for this key and no
                usable key is available for it.
            VaultDecryptionError: A stored value will not authenticate.
        """
        # No file at all: nothing was ever stored, so there is nothing this
        # source could be hiding. Checked before anything else because it is
        # the common case for every project that does not use the vault.
        if not self._vault.path.exists():
            return None

        identity = self._identity(key, section, scope)
        if identity is None:
            return None

        if self._key is None:
            self._refuse_if_stored(
                identity,
                "no vault key is available on this machine",
            )
            return None

        self._warn_if_stale()

        # The check value answers "is this the key this store was written
        # with?" without decrypting anybody's secret. `None` means the store
        # predates the check row, in which case the old behaviour stands and
        # `get` below is left to discover a wrong key the expensive way.
        if self._opens_with_key() is False:
            self._refuse_if_stored(
                identity,
                f"the key supplied by the {self._key_provider_id!r} provider "
                f"does not open this vault",
            )
            return None

        # VaultDecryptionError deliberately propagates. A vault that cannot be
        # read is a different situation from one that does not hold the key,
        # and collapsing them would hide a wrong-key configuration behind a
        # silent fall-through -- the defect this feature exists to remove.
        value = self._vault.get(identity.encode(), encryption_key=self._key)
        if value is None:
            self.misses.append(self._display(identity))
            return None
        return value

    def _opens_with_key(self) -> bool | None:
        """Whether this key opens this store, asked once per run.

        A separate `_opens_asked` flag rather than a sentinel value, because
        `None` is already a real answer here — "this store has no check row, so
        the question cannot be answered" — and overloading it with "not yet
        asked" is how the two get confused.
        """
        if not self._opens_asked:
            assert self._key is not None
            self._opens = self._vault.opens_with(self._key)
            self._opens_asked = True
        return self._opens

    def _stored_identities(self) -> frozenset[VaultIdentity]:
        """Every identity the store holds, read once and without the vault key.

        Metadata is stored in clear precisely so this is possible: the question
        "is something stored here?" has to be answerable on a machine that
        cannot decrypt anything, or the refusal below could not be raised at
        all.

        A key that does not decode — a flat ``section.field`` written before
        identities were scoped, or by a test reaching past the codec — is
        skipped rather than guessed at: it names no scoped identity, so no
        scoped lookup is it.

        Read once per source. The source is built at boot and the chain is
        rebuilt on `refresh()`, so a `vault put` from a separate process is
        picked up by the next run — which is the only sequence that occurs.
        """
        if self._identities_seen is None:
            seen: set[VaultIdentity] = set()
            for entry in self._entries():
                try:
                    seen.add(VaultIdentity.decode(entry.key))
                except ValueError:
                    continue
            self._identities_seen = frozenset(seen)
        return self._identities_seen

    def _refuse_if_stored(self, identity: VaultIdentity, because: str) -> None:
        """Raise when this identity names something the store actually holds.

        Deliberately asked in this order: the store is only consulted on the
        path that was about to fall through, so an ordinary resolution that
        finds its value pays nothing for this.
        """
        if identity not in self._stored_identities():
            return
        display = self._display(identity)
        remove = self._remove_command(identity)
        msg = (
            f"The vault holds a value for {display!r}, but {because}. "
            f"Refusing rather than falling through to the environment or a "
            f"config file: a stored value is the one you provisioned, and "
            f"running on a different one would look like success.\n\n"
            f"Fix it with one of:\n"
            f"  func builtin vault sync                 refresh from upstream\n"
            f"  func builtin {remove:<39}drop this entry\n"
            f"  func builtin vault clear                drop the whole store\n"
            f"The last two need no key."
        )
        raise VaultEntryUnreadableError(msg)

    def has(
        self, key: str, section: str | None = None, *, scope: VaultScope = "job"
    ) -> bool:
        """Whether the vault holds this identity, without decrypting it."""
        if not self.usable:
            return False
        identity = self._identity(key, section, scope)
        return identity is not None and identity in self._stored_identities()

    def keys(self, section: str, *, scope: VaultScope = "job") -> set[str]:
        """Every field the vault holds for one scope's section, undecrypted."""
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

    def note_fallthrough(
        self,
        resolved: ResolvedValue,
        section: str | None = None,
        *,
        scope: VaultScope = "job",
    ) -> None:
        """Warn that a key declared remote was answered by something else.

        Called by :class:`~functualize._config.chain.ResolutionChain` on every
        source that returned None, after the winner is known — which is the
        only moment "resolved from X instead" can be said truthfully.

        Fires at most once per identity per run, so a job reading one secret
        ten times warns once, and stays silent unless a matching explicit
        declaration appears in a discovered config file.

        Args:
            resolved: The winning value and its provenance, including the
                alternatives from lower-priority sources.
            section: The section the key was resolved in, if any.
            scope: Whether that section names a group or a job.
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

        identity = self._identity(resolved.key, section, scope)
        if identity is None or identity.encode() in self._warned:
            return

        if self._declaration_identities is None:
            self._declaration_identities = frozenset(
                item.identity
                for item in parse_vault_declarations(self._declaration_files)
            )
        if identity not in self._declaration_identities:
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

    def set_declaration_files(self, files: list[tuple[str, dict[str, Any]]]) -> None:
        """Bind the parsed files after the chain is assembled, without fetching."""
        self._declaration_files = files
        self._declaration_identities = None

    def _entries(self) -> list[Any]:
        # Metadata only, so this never decrypts. It is still gated behind
        # `usable` by both callers: a source that answers `has() is True` and
        # then yields None from `get()` breaks the chain's contract, so with no
        # key this source must claim nothing rather than claim what it cannot
        # deliver.
        return self._vault.list_entries()
