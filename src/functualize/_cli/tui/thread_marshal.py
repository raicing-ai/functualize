"""Cross-thread UI marshaling helpers for the inline TUI.

Textual widgets may only be mutated from the app's event-loop thread. Work
that runs on a thread worker (job execution, display refresh) must therefore
route every UI write through ``app.call_from_thread(...)``.

``needs_marshal`` is the shared predicate for "am I off the loop thread right
now, and is there a loop to marshal onto?" — the same condition Textual's own
``call_from_thread`` requires (it raises if the app isn't running, or if it is
called from the loop thread itself).

This module is in the ``_cli/`` layer — stdlib only, no Textual import.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

__all__ = ["marshal", "needs_marshal"]


def needs_marshal(app: Any) -> bool:
    """Return True if a UI write from this thread must go through
    ``app.call_from_thread(...)`` instead of writing directly.

    False when the app has no running event loop (e.g. a unit test that
    constructs the TUI without ``run_test()``) — there, writing directly is
    both safe and necessary, since ``call_from_thread`` would raise.
    """
    loop = getattr(app, "_loop", None)
    if loop is None:
        return False
    return threading.get_ident() != getattr(app, "_thread_id", None)


def marshal(app: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Run ``fn`` on the app's loop thread, or inline when already safe.

    Never raises: marshaling is best-effort UI work called from worker threads,
    and an app torn down between the check and the call must not take down the
    caller's worker.
    """
    if app is None:
        fn(*args, **kwargs)
        return
    try:
        if needs_marshal(app):
            app.call_from_thread(fn, *args, **kwargs)
        else:
            fn(*args, **kwargs)
    except RuntimeError:
        # Textual raises RuntimeError when the app is no longer running — the
        # normal shutdown race for in-flight worker callbacks. Nothing to do:
        # there is no UI left to update.
        logger.debug("marshal: app no longer running, dropping UI update")
