"""``Vault`` — the job's explicit group secret read, as an injected capability.

A job declares ``vault: Vault`` and calls ``vault.read(group, field)``. The
engine owns injection and nothing else here: the reader is built by the
composition root (``_app/vault_reader.py``) over the config layer's vault
source, and handed to the engine as a typed
:class:`~functualize._types.protocols.VaultReaderFactory` at construction. This
module imports neither ``_config`` nor ``_app`` -- the peer-layer contract
forbids the first, the layer order the second -- so the only thing it knows is
the port.

No ``RunContext`` accessor (``rc_accessor=None``): the injected capability is
the single job call surface for this read.
"""

from __future__ import annotations

from typing import Any

from functualize._engine.capabilities.spec import CapabilitySpec
from functualize._primitives import MissingProviderError
from functualize._types.protocols import Vault, VaultReaderFactory

__all__ = ["CAPABILITY"]


def _make_vault(ctx: Any) -> Vault:
    """Open one invocation's reader from the factory the engine was handed.

    An engine built without one -- embedding, a unit test, anything that did
    not come through ``_app/boot.build_engine`` -- has no vault to read, and a
    reader that answered "missing" for everything would be indistinguishable
    from an empty vault. So the request fails as a resolution failure instead.
    """
    factory: VaultReaderFactory | None = ctx.engine.vault_reader_factory
    if factory is None:
        raise MissingProviderError(Vault, ctx.context.job_name, [])
    return factory.open()


CAPABILITY = CapabilitySpec(name="Vault", type=Vault, factory=_make_vault)
