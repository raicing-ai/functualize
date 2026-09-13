"""Delivering a workflow's declared notifications — the port, and core's own.

`workflow-graph-semantics`/T6. Spec AC-13, AC-14.

Mirrors `_engine/agent_step.AgentStepRegistry` down to the registration door,
deliberately: a plugin that has registered one port already knows how to
register this one, and two ports that look alike and behave differently are
worse than two that look alike and do.

## What this is not

**Not a bus and not a broker** (decision **N8**). `to` is opaque: it is carried
from the declaration to the provider and nothing in between reads it. There is
no routing table, no fan-out, no retry policy and no dead-letter queue, and none
of them is a "later" — each is the first field of a broker, and the moment one
exists this stops being *a target and an effect*.

## Nothing is registered by default

Core ships `LogNotifier` and registers **nothing**. The same decision
`_app.boot` makes for the `cli-prompt` executor, for the same reason: a default
registration makes the refusal unreachable, and a workflow whose "page the
on-call on failure" quietly became a debug line is worse than one that refuses
to start. `check` runs in `WorkflowRunner.prelude`, before the walk, so a
declaration nobody can deliver fails where it is declared.

## A failed delivery does not fail the walk

`deliver` may raise and the walk logs it and carries on. A notification is an
account *of* what happened; letting it change what happened would mean a
workflow that succeeded reporting failure because a mail server was down.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from functualize._engine.notify_providers import missing_notifier_hint
from functualize._types.errors import NotifierUnavailableError
from functualize._types.protocols import Notifier

if TYPE_CHECKING:
    from functualize._types.workflow import (
        Notification,
        Notify,
        WorkflowDeclaration,
    )

__all__ = ["LogNotifier", "NotifierRegistry"]

logger = logging.getLogger(__name__)


class LogNotifier:
    """Core's own notifier: writes the notification to the log.

    Registered by nothing. It exists so that "no notifier is registered" is a
    state a user can leave without installing a package, and so the port has an
    implementation in core to test the registry against — a registry whose only
    implementations live in plugins is a registry core cannot check.

    ``to`` is written out and not interpreted, which is the whole port in one
    line.
    """

    name = "log"

    def deliver(self, notification: Notification) -> None:
        logger.warning(
            "workflow %s (%s) is %s — notifying %s%s",
            notification.scope_id,
            notification.workflow or "?",
            notification.status,
            notification.to,
            f" (at {notification.node})" if notification.node else "",
        )


class NotifierRegistry:
    """The notifiers this app will deliver `Notify` declarations through."""

    def __init__(self) -> None:
        self._notifiers: dict[str, Notifier] = {}

    def register(self, notifier: object) -> None:
        """Register ``notifier`` under its own name.

        ``notifier`` is typed ``object`` for `AgentStepRegistry.register`'s
        reason: this door is reached dynamically, so the runtime check *is* the
        contract.

        Raises:
            TypeError: ``notifier`` does not satisfy `Notifier`.
            ValueError: Its name is empty, or already registered. Refused
                rather than replaced — a `Notify` resolving to one of two
                implementations with one name is the ambiguity this port exists
                to eliminate.
        """
        if not isinstance(notifier, Notifier):
            raise TypeError(
                "A notifier must satisfy Notifier: a `name` and "
                f"`deliver(notification)`. Got {type(notifier).__name__}, which "
                "does not."
            )
        name = notifier.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"A notifier must declare a non-empty name, got {name!r}")
        if name in self._notifiers:
            raise ValueError(
                f"A notifier named '{name}' is already registered "
                f"({type(self._notifiers[name]).__name__}). Registration is "
                "refused rather than replaced, so a declaration naming it "
                "cannot silently reach a different implementation."
            )
        self._notifiers[name] = notifier

    def names(self) -> tuple[str, ...]:
        """Every registered notifier name, sorted — for diagnostics."""
        return tuple(sorted(self._notifiers))

    def resolve(self, declared: Notify) -> Notifier:
        """The notifier that delivers ``declared``, or a refusal saying why not.

        Raises:
            NotifierUnavailableError: The name is not registered, or none was
                named where exactly one cannot be identified — none registered,
                or several. Nothing is guessed: picking a deliverer the
                declaration did not name is how a page becomes a log line.
        """
        if declared.provider is None:
            if len(self._notifiers) == 1:
                return next(iter(self._notifiers.values()))
            raise NotifierUnavailableError(declared.to, None, registered=self.names())
        notifier = self._notifiers.get(declared.provider)
        if notifier is None:
            raise NotifierUnavailableError(
                declared.to,
                declared.provider,
                registered=self.names(),
                hint=missing_notifier_hint(declared.provider),
            )
        return notifier

    def check(self, declaration: WorkflowDeclaration) -> None:
        """Refuse every notification in ``declaration`` that cannot be delivered.

        Before the walk, so a declaration nobody can deliver fails where it is
        declared rather than at the end of a run that has already done its work
        — which is the one moment a missing notifier is least recoverable.

        Raises:
            NotifierUnavailableError: A declaration names no deliverable
                notifier.
        """
        for declared in declaration.notify:
            self.resolve(declared)

    def deliver(self, declared: Notify, notification: Notification) -> bool:
        """Deliver one notification. True when it was handed over.

        Never raises. A notifier that fails is logged and the walk carries on:
        a notification is an account *of* what happened, and letting it change
        what happened would report a workflow as failed because a mail server
        was down.
        """
        try:
            self.resolve(declared).deliver(notification)
        except Exception:  # noqa: BLE001 - an account never changes the outcome
            logger.warning(
                "could not deliver the %s notification for scope %s",
                declared.on,
                notification.scope_id,
                exc_info=True,
            )
            return False
        return True
