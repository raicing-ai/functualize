"""The job-facing group vault read, composed over the existing vault source.

``Vault.read(group, field)`` is a port defined in ``_types``; the engine injects
it and the config layer owns the source that answers it. Those two are peer
layers and may not import each other, so the adapter lives here, in the
composition root, and the engine is handed a :class:`LocalVaultReaderFactory`
at its one construction site (``boot.build_engine``).

**One lookup, not two.** The read is a single
``VaultSource.get(field, group, scope="group")`` call. That method already walks
``VaultIdentity.lookup_candidates`` -- active environment exact group through
nearest ancestors, then the shared slot in the same order -- and already treats
the first *stored* candidate as authoritative even when it cannot be opened
(ADR-023 §1). Re-walking the candidates here would be a second copy of that
policy, free to drift from the one config resolution uses.

**Never the chain's** ``resolve``. The chain would continue to the environment,
the config files and the defaults on a miss, which is right for config and is
exactly the substitution an explicit secret read must not make. Only the vault
source is asked; ``None`` from it becomes :class:`VaultEntryMissingError`.

**Which source.** The app's current resolution chain, read per invocation, so a
``refresh()`` that rebuilt the chain is observed. A chain without a vault
source -- an explicit chain from ``twelve_factor()``/``env_only()`` or a static
app's own chain -- gets the same source boot would have built, from
``build_vault_source``; with no vault file that is ``None``, which is a miss.

Imports of ``_config.vault*`` stay inside the read: ``_config.vault`` imports
``cryptography`` at module level, and this module is imported on every boot to
build the factory. A run that never reads the vault never pays for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._primitives.vault_identity import VaultIdentity
from functualize._types.redaction import Secret

if TYPE_CHECKING:
    from functualize._config.vault_source import VaultSource
    from functualize._types.protocols import Vault

__all__ = ["LocalVaultReaderFactory"]


class LocalVaultReaderFactory:
    """Opens a :class:`~functualize._types.protocols.Vault` over one app.

    Holds the app, never a source: the source is looked up when a job reads,
    so a chain rebuilt after boot is the one consulted.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    def open(self) -> Vault:
        """A reader for one invocation."""
        return _LocalVaultReader(self._app)


class _LocalVaultReader:
    """One invocation's ``Vault``. Resolves its source on first read."""

    def __init__(self, app: Any) -> None:
        self._app = app
        self._source: VaultSource | None = None
        self._resolved = False

    def read(self, group: str, field: str) -> Secret:
        """Return the first stored group candidate's value, wrapped.

        Raises:
            VaultEntryMissingError: No candidate is stored, or there is no
                vault file.
            VaultEntryUnreadableError: The first stored candidate cannot be
                opened with the available key. Propagated from the source.
            VaultDecryptionError: The first stored candidate will not
                authenticate. Propagated from the source.
            TypeError: ``group`` or ``field`` is not a string.
            ValueError: ``group`` or ``field`` is empty.
        """
        if not isinstance(group, str) or not isinstance(field, str):
            raise TypeError(
                "Vault.read takes a group address and a field name, both str; "
                f"got {type(group).__name__} and {type(field).__name__}"
            )
        # Validated before the vault is consulted, so malformed input is an
        # input error on every machine -- not a "missing" on one with no vault
        # file and an error on one with.
        VaultIdentity("group", group, field)

        from functualize._config.vault import VaultEntryMissingError

        source = self._vault_source()
        value = None if source is None else source.get(field, group, scope="group")
        if value is None:
            raise VaultEntryMissingError(group, field)
        # Wrapped before it crosses the boundary: from here on every rendering
        # of it is the mask.
        return Secret(value)

    def _vault_source(self) -> VaultSource | None:
        """The app's vault source: the live chain's, else the one boot builds."""
        if self._resolved:
            return self._source
        from functualize._config.vault_source import VaultSource

        chain = getattr(self._app, "_resolution_chain", None)
        found: VaultSource | None = next(
            (s for s in getattr(chain, "sources", ()) if isinstance(s, VaultSource)),
            None,
        )
        if found is None:
            # Local, not top-level: `boot` imports this module to build the
            # factory, so a top-level import back into `boot` is a cycle.
            from functualize._app.boot import build_vault_source

            found = build_vault_source(self._app)
        self._source = found
        self._resolved = True
        return found
