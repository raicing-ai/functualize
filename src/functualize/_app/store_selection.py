"""Boot step 6.5 — select the one runtime store from ``runtime_store.url``.

Every store arrives by one door. A backend registers a
:class:`~functualize._types.persistence.RuntimeStoreFactory` under a URL
scheme (``PluginHost.register_runtime_store_factory``), and boot registers the
built-in ``documents`` factory the same way, first, on both boot paths. Step
6.5 resolves the URL — unset reads as ``documents:`` — looks the scheme up and
calls ``prepare`` **uncaught**: a store that cannot open, migrate or pass its
health check aborts boot, and nothing falls back to another backend.

Installing a plugin therefore no longer selects its store; configuration
does. The one exception is a refusal, not a fallback: when nothing is
configured and a registered backend says it already holds runtime data for
this project, boot stops and says so rather than coming up on the document
store with that data unread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from functualize._app import boot
from functualize._config.errors import MissingKeyError
from functualize._primitives.document_store import (
    DOCUMENT_PROFILE,
    DocumentRuntimeStore,
)
from functualize._primitives.substrate import substrate_for_project
from functualize._types.errors import RuntimeStoreSelectionError
from functualize._types.persistence import PreparedStore, RuntimeStoreConfig

if TYPE_CHECKING:
    from pathlib import Path

    from functualize._types.persistence import (
        RuntimeStore,
        RuntimeStoreFactory,
        StoreProfile,
    )
    from functualize._types.protocols import StoreSubstrate

__all__ = ["DocumentRuntimeStoreFactory", "select_runtime_store"]

CONFIG_KEY = "runtime_store.url"
DEFAULT_URL = "documents:"


class DocumentRuntimeStoreFactory:
    """The built-in ``documents`` scheme: today's store, selected as before.

    ``prepare`` is what step 6.5 did before there was a registry: settle the
    substrate claims, take the installed override or the project's default
    substrate, and wrap it in a ``DocumentRuntimeStore``.
    """

    scheme = "documents"
    profile: StoreProfile = DOCUMENT_PROFILE

    def __init__(self, app: Any) -> None:
        self._app = app

    def prepare(self, config: RuntimeStoreConfig) -> PreparedStore:
        boot._resolve_substrate_claim(self._app)
        substrate = self._app.substrate_override or substrate_for_project(
            config.project_root
        )
        return PreparedStore(store=DocumentRuntimeStore(substrate), substrate=substrate)

    def unselected_data(self, project_root: Path) -> str | None:
        # The default store is what an unset key selects; it is never stranded.
        return None


def select_runtime_store(app: Any) -> tuple[RuntimeStore, StoreSubstrate]:
    """Resolve the URL, find its one factory, prepare it — all uncaught."""
    configured = _configured_url(app)
    url = DEFAULT_URL if configured is None else configured
    scheme = _scheme_of(url)
    registered: list[tuple[str, RuntimeStoreFactory]] = list(
        getattr(app, "_runtime_store_factories", ())
    )
    if configured is None:
        _refuse_stranded_data(registered, app.fresh_root)

    claimants = [(name, f) for name, f in registered if f.scheme == scheme]
    if not claimants:
        schemes = ", ".join(sorted({f.scheme for _, f in registered})) or "none"
        raise RuntimeStoreSelectionError(
            f"{CONFIG_KEY} = {url!r} names the scheme {scheme!r}, which no "
            f"registered runtime store serves (registered: {schemes}). Install "
            f"and enable the plugin that provides it, or set {CONFIG_KEY} to one "
            f"of the registered schemes."
        )
    if len(claimants) > 1:
        names = ", ".join(sorted(name for name, _ in claimants))
        raise RuntimeStoreSelectionError(
            f"{len(claimants)} runtime stores claim the scheme {scheme!r} "
            f"({names}) selected by {CONFIG_KEY}. Choosing between them here "
            f"would make storage depend on plugin load order; disable all but one."
        )
    config = RuntimeStoreConfig(
        url=url, scheme=scheme, project_root=app.fresh_root, config_key=CONFIG_KEY
    )
    prepared = claimants[0][1].prepare(config)
    boot.check_required_capabilities(
        prepared.store.profile, boot._required_capabilities(app)
    )
    substrate = prepared.substrate or substrate_for_project(app.fresh_root)
    return prepared.store, substrate


def _configured_url(app: Any) -> str | None:
    """``runtime_store.url`` as configured, or ``None`` when nothing sets it."""
    chain = getattr(app, "_resolution_chain", None)
    resolve = getattr(chain, "resolve", None)
    if resolve is None:
        # A stand-in app may carry a chain-like object that resolves nothing:
        # that is "nothing sets it", not a boot failure. Read by probing the
        # attribute, never by catching `AttributeError` — the latter would
        # also swallow a `resolve` that raises it for its own reasons.
        return None
    try:
        value = resolve("url", "runtime_store").value
    except MissingKeyError:
        return None
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeStoreSelectionError(
            f"{CONFIG_KEY} must be a string such as 'documents:' or 'sqlite:', "
            f"not {type(value).__name__}."
        )
    return value


def _scheme_of(url: str) -> str:
    scheme, separator, _rest = url.partition(":")
    if not separator or not scheme:
        raise RuntimeStoreSelectionError(
            f"{CONFIG_KEY} = {url!r} has no scheme; write it as '<scheme>:...', "
            f"for example 'documents:' or 'sqlite:'."
        )
    return scheme


def _refuse_stranded_data(
    registered: list[tuple[str, RuntimeStoreFactory]], project_root: Path
) -> None:
    """Nothing configured, but a backend already holds this project's runs.

    Coming up on the document store would leave that data unread behind an
    app that looks healthy — a silent fallback by another name.
    """
    for _name, factory in registered:
        held = factory.unselected_data(project_root)
        if held:
            raise RuntimeStoreSelectionError(
                f"{held} Nothing sets {CONFIG_KEY}, so this boot would start on "
                f"the document store and leave that data unread. Set "
                f'{CONFIG_KEY} = "{factory.scheme}:" to keep using it, or '
                f'"{DEFAULT_URL}" to start fresh.'
            )
