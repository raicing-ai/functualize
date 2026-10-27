"""The outbox tier's composition: receivers, the capability they declare, the drain.

`_primitives.outbox.OutboxDispatcher` claims, delivers and acknowledges; this
module is the composition root's half — it answers the three questions boot
asks about effect receivers and owns none of the delivery mechanics:

* **Who is registered?** :func:`registered_receivers` — the registry
  ``impl.register_effect_receiver`` writes, read here and nowhere else.
* **What does that require of the store?**
  :func:`receiver_requirements` — registering a receiver *is* the declaration
  that this configuration needs ``durable_outbox=True`` (spec §3.6); no
  configuration key exists for it and none is added.
* **What runs?** :func:`drain` — build a dispatcher over the selected store's
  queue iff the profile declares the outbox and receivers exist, and drain it
  once. The deployment is in-process and synchronous (spec §5): one drain at
  the end of boot, one after each answer-surface commit (task 3.1), no thread
  and no worker.

And the one check that holds the two halves together:
:func:`check_outbox_agreement` refuses a store whose profile and its type
disagree about ``durable_outbox``, so the capability has one meaning — a
profile that says ``True`` is a store that can actually be drained.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from functualize._app.boot import RequiredCapability
    from functualize._primitives.outbox import DrainReport
    from functualize._types.persistence import (
        EffectReceiver,
        OutboxStore,
        RuntimeStore,
    )

__all__ = [
    "check_outbox_agreement",
    "drain",
    "receiver_requirements",
    "registered_receivers",
]

logger = logging.getLogger(__name__)


def registered_receivers(app: Any) -> Mapping[str, EffectReceiver]:
    """The receivers registered before boot selected the store, by topic.

    Empty when none registered — the ordinary configuration, and the one that
    requires nothing: a store without an outbox serves it fine as long as
    nothing consumes effects.
    """
    receivers = getattr(app, "_effect_receivers", None)
    return dict(receivers) if receivers else {}


def receiver_requirements(app: Any) -> Mapping[str, RequiredCapability]:
    """The capability registering a receiver declares: ``durable_outbox=True``.

    Returned only when at least one receiver is registered, keyed as
    ``boot.check_required_capabilities`` expects. The refusal this feeds names
    ``runtime_store.url`` — the setting to change — and the receivers' topics
    in ``because``, so the operator sees both halves of the mismatch: what
    needs the capability and what the selected store declares.
    """
    receivers = registered_receivers(app)
    if not receivers:
        return {}
    from functualize._app.boot import RequiredCapability
    from functualize._app.store_selection import CONFIG_KEY

    topics = ", ".join(sorted(receivers))
    return {
        "durable_outbox": RequiredCapability(
            field="durable_outbox",
            value=True,
            config_key=CONFIG_KEY,
            because=f"effect receivers are registered for: {topics}",
        )
    }


def check_outbox_agreement(store: RuntimeStore) -> None:
    """Refuse a store whose profile and its type disagree about the outbox.

    ``durable_outbox=True`` is a promise the profile makes about the store's
    *type* — that it satisfies ``OutboxStore`` and hands out an effects queue
    — so a store that declares the capability without the queue (or carries
    the queue while denying the capability) has misdescribed itself, and
    selecting it would push the lie onto the first dispatcher — or the first
    transition — that believed the profile. Refused here, at selection, in
    both directions.
    """
    from functualize._types.errors import RuntimeStoreSelectionError
    from functualize._types.persistence import OutboxStore

    declared = bool(store.profile.durable_outbox)
    provides = isinstance(store, OutboxStore)
    if declared == provides:
        return
    if declared:
        detail = (
            "declares durable_outbox=True but provides no effects queue (OutboxStore)"
        )
    else:
        detail = (
            "provides an effects queue (OutboxStore) but declares durable_outbox=False"
        )
    raise RuntimeStoreSelectionError(
        f"Store {store.profile.name!r} {detail}. The profile is the one "
        f"meaning of a capability, so a store whose profile and type disagree "
        f"cannot be selected — fix the store until they agree."
    )


def drain(app: Any, store: RuntimeStore) -> DrainReport | None:
    """Build the dispatcher over ``store`` and drain it once — or not at all.

    A dispatcher exists only when both halves are present: receivers
    registered for at least one topic, and a store whose profile declares
    ``durable_outbox=True``. Anything else returns ``None`` without touching
    the store — a document store has no ``effects`` member to touch, and the
    capability refusal already stopped the mismatched combination from
    reaching boot's end. Called once at the end of both boot paths; the
    answer-surface drains (task 3.1) call it after each commit.
    """
    from functualize._primitives.outbox import OutboxDispatcher

    receivers = registered_receivers(app)
    if not receivers or not store.profile.durable_outbox:
        return None
    dispatcher = OutboxDispatcher(cast("OutboxStore", store).effects, receivers)
    return dispatcher.drain()
