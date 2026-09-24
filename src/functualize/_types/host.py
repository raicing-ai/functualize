"""The plugin-facing host port — what a plugin is allowed to know about the app.

A peer of :class:`~functualize._types.protocols.EngineHost`, which says what the
*engine* needs from outside itself. This module says what a **plugin** needs,
and it is a different, wider list: a plugin registers jobs, reads config, hangs
commands off the CLI, and installs storage, none of which the engine does.

Its own file rather than another class in ``protocols.py`` because the two ports
have different audiences. ``EngineHost`` is read by one implementation inside
this repository; ``PluginHost`` is read by plugin authors outside it, who reach
it through the public ``functualize.plugin`` package. A port with an external
audience is worth a page a reader can open — and ``protocols.py`` is already
888 lines and twelve protocols, named a god module by the dead-code audit.

Stdlib and ``_types`` imports only, like the rest of this package: the whole
point of annotating against a port is that a plugin can name the type without
importing the application. **A ``TYPE_CHECKING`` import of ``_app`` would pass
CI** — ``exclude_type_checking_imports = true`` in `pyproject.toml` — and is
refused anyway, per ``contributor/architecture/layer-contract-blind-spot.md``
§7: *"Nothing here legalizes a TYPE_CHECKING import across a layer the
contracts refuse."* That refusal is why the five facades are described by
**views** below rather than named directly.

**Views, not the facades.** ``app.di`` is a ``DependencyFacade`` living in
``_app``, which this module may not name. Each view describes the part of one
facade that plugins actually call, from the layer allowed to describe it. The
concrete facades satisfy them structurally — nothing inherits, nothing is
registered.

Each view is **sized to measured use**, from ``plugins/*/*/src`` only::

    $ rg -o -N 'app\\.(di|extensions|configuration|gates|hooks)\\.[a-z_]+' \\
        plugins/*/*/src/ | sed 's/.*app\\.//' | sort | uniq -c | sort -rn
          8 extensions.register_plugin_command
          7 di.provide
          4 configuration.resolve_model
          3 gates.register_gate_preset
          3 extensions.extension_state
          2 gates.register_gate_strategy
          1 extensions.register_surface
          1 extensions.register_ambient_construct
          1 di.provide_named

Ten members across five views, against 33+ on the concrete facades — the tenth
being ``hooks.on_ready``, which has no plugin caller in that census because
``plugin-host-protocol``/T6 is what gave it one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from functualize._types.descriptors import JobDescriptor, JobResult
    from functualize._types.protocols import StoreSubstrate
    from functualize._types.run_request import RunRequest

# The four names above are `_types` describing `_types`, deferred only because
# nothing here needs them at runtime: a Protocol's annotations are never
# evaluated, and `from __future__ import annotations` keeps them strings.
# **Not** the TYPE_CHECKING escape §7 of `layer-contract-blind-spot.md`
# forbids — that one is about naming a layer the import contracts refuse, and
# no contract stands between `_types` and itself.

__all__ = [
    "ConfigurationView",
    "DependencyView",
    "ExtensionsView",
    "GatesView",
    "HooksView",
    "OnReadyHandler",
    "PluginHost",
]


OnReadyHandler: TypeAlias = Callable[["PluginHost"], None]
"""The shape of an ``APP_READY`` handler: takes the host, returns nothing.

``-> None`` rather than ``-> Any`` because the return value is discarded — both
firing sites in ``_app/boot.py`` call ``hook(app)`` and drop the result — so a
handler annotated as returning something is saying something untrue. All five
handlers that ship return None.

A forward reference because :class:`PluginHost` is declared at the bottom of
this module, after the views it names.
"""


# ─── The five views ───────────────────────────────────────────────────────


class DependencyView(Protocol):
    """``app.di`` — two of ``DependencyFacade``'s three methods.

    ``provide_factory`` is absent because no plugin source calls it. Reading is
    absent too, and deliberately: this facade is **write-only**, which is what
    drove two plugins to reach past it into ``app._di_registry`` — both of
    those reaches were dead code, deleted by T1 and T2, and a ``resolve``
    member was dropped from this port for want of a surviving caller.
    """

    def provide(self, type_: type, instance: Any, qualifier: str | None = None) -> None:
        """Register a singleton instance in the DI registry."""
        ...

    def provide_named(self, name: str, instance: Any) -> None:
        """Register a string-keyed value in the DI registry."""
        ...


class ExtensionsView(Protocol):
    """``app.extensions`` — four of ``ExtensionsFacade``'s twelve members.

    ``get_plugin_commands()`` is **not** here. It returns ``PluginCommand``
    from ``_app/models.py``, unnameable from this layer — and it does not
    matter, because no plugin source calls it: every caller is core
    (``app/commands.py``, ``_cli/main.py``, ``app/adapters/cli.py``) or a test.
    The layer constraint and the usage census agree, which is the only reason
    that exclusion is free rather than a hole.
    """

    def register_plugin_command(
        self,
        name: str,
        callback: Callable[..., Any],
        help_text: str = "",
        namespace: str | None = None,
        needs_terminal: bool = False,
    ) -> None:
        """Register a command from a plugin."""
        ...

    @property
    def extension_state(self) -> dict[str, Any]:
        """Mutable namespace for consumer-owned state, keyed by consumer name.

        The sanctioned alternative to monkey-patching private attributes onto
        the app — which is what a port is for.
        """
        ...

    def register_surface(self, surface: Any) -> None:
        """Register something that renders a job's events, answers its prompts, or both."""
        ...

    def register_ambient_construct(
        self,
        construct_factory: Any,
        *,
        name: str | None = None,
        predicate: Any = None,
    ) -> None:
        """Register a live construct that renders by default for eligible jobs."""
        ...


class ConfigurationView(Protocol):
    """``app.configuration`` — the one member plugins call.

    ``ConfigurationFacade`` also resolves a *job's* config model; that one is
    core's, and no plugin asks for it.
    """

    def resolve_model(self, section: str, model_class: type[object]) -> object:
        """Resolve a configuration model through the resolution chain."""
        ...


class GatesView(Protocol):
    """``app.gates`` — two of ``GatesFacade``'s three methods.

    ``resolve_gate`` is core's side of the same registry and has no plugin
    caller.
    """

    def register_gate_preset(self, name: str, strategies: list[str]) -> None:
        """Register an ordered fallback list of strategies under a preset name."""
        ...

    def register_gate_strategy(self, name: str, resolver: Any) -> None:
        """Register a gate resolution strategy by name.

        ``resolver: Any`` is a **declared deviation** from the live signature,
        which is ``resolver: GateResolver`` (``_app/gates_facade.py:31``).
        ``GateResolver`` is itself a ``@runtime_checkable`` Protocol, but it
        lives in ``_gate/_resolver.py`` and ``_types`` may not import ``_gate``.

        Priced rather than assumed: re-homing ``GateResolver`` into ``_types``
        — which the constitution's *Ports* rule arguably requires, since it is
        one — is **86 references across 22 files**, it is exported from
        ``functualize/__init__.py``, and it is asserted in
        ``tests/test_public_api_surface.py``. That is a public-API feature of
        its own, not a line in this one. A mirror ``GateResolverView`` was
        rejected for trading one ``Any`` on one parameter of a two-site method
        for a sixth mirror protocol — deepening the very smell these views
        already accept. Recorded in ``plan.md`` → *Surviving smells*.
        """
        ...


class HooksView(Protocol):
    """``app.hooks`` — one of ``HooksFacade``'s fifteen members.

    One, not fifteen, because ``on_ready`` is the only lifecycle hook a plugin
    registers: the census above finds no other, and T6 migrated all five
    ``APP_READY`` registrations to it. The other fourteen remain on the facade
    for job and invoke hooks, whose audience is application code rather than
    plugins.
    """

    @property
    def on_ready(self) -> Callable[[OnReadyHandler], OnReadyHandler]:
        """Decorator: register an ``APP_READY`` handler, returning it unchanged."""
        ...


# ─── The port ─────────────────────────────────────────────────────────────


@runtime_checkable
class PluginHost(Protocol):
    """What a plugin needs from the application, and nothing else.

    Peer of :class:`~functualize._types.protocols.EngineHost` for the plugin
    boundary. **Members ask; none of them lends** — the rule that port inherits.
    A member that hands a plugin a mutable internal, or the machinery to fire
    lifecycle events at the rest of the app, is not a narrowing of
    ``app: Any``; it is the same reach with a type on it.

    Eleven members. What is *absent* is as deliberate as what is present:

    ``hook_registry``
        Four plugin clients, and refused. Seven public methods, of which four
        are ``invoke*`` — the *firing* half. On the port, every plugin could
        fire arbitrary lifecycle events at every other. T6 migrated all four
        clients to ``hooks.on_ready``, which registers and cannot fire.
    ``execution_engine``
        Five apparent clients, **one real**: four were the chain
        ``app.execution_engine.substrate``, collapsed to ``substrate`` by T4.
        The survivor wants ``materialize_job``
        (``functualize-mcp/…/_workflow_tools.py:447``). One call site does not
        buy handing plugins the whole engine.
    ``run``
        One client, ``-> None``, and it is the CLI entrypoint. A plugin calling
        it re-enters delivery from inside delivery.
    ``workflows``
        Zero plugin clients. A port lists what is needed, not what exists.
    ``di.resolve``
        Zero clients after T1 and T2. Its only consumer was inside a
        permanently dead block, which is why this port has no read side for DI.
    """

    # --- the five facades plugins use, as views ---

    @property
    def di(self) -> DependencyView:
        """Register what jobs can ask for, by type or by name."""
        ...

    @property
    def extensions(self) -> ExtensionsView:
        """Hang commands, surfaces and constructs off the application."""
        ...

    @property
    def configuration(self) -> ConfigurationView:
        """Read this project's resolved configuration."""
        ...

    @property
    def gates(self) -> GatesView:
        """Register gate strategies and presets."""
        ...

    @property
    def hooks(self) -> HooksView:
        """Register lifecycle callbacks — for a plugin, ``on_ready``."""
        ...

    # --- job lookup ---

    def get_jobs(self) -> list[JobDescriptor]:
        """Every discovered job descriptor."""
        ...

    def get_job(self, name: str) -> JobDescriptor | None:
        """One descriptor by name, or None when nothing is registered."""
        ...

    # --- execution ---

    def execute(self, request: RunRequest) -> JobResult:
        """Run a job. Takes a :class:`RunRequest` and nothing else."""
        ...

    # --- storage ---

    @property
    def substrate(self) -> StoreSubstrate:
        """The storage **in effect** — never ``None``, boot's one selection.

        Renamed from the install slot by T3, which is what lets this member be
        declared without ``| None``. The slot is ``substrate_override`` and
        FUN-17/T12 settled who reads it: **boot**, at step 6.5, which hands the
        answer to the engine — so the slot is absent here.
        """
        ...

    def install_substrate(self, substrate: StoreSubstrate) -> None:
        """Install a backend. Before boot selects a store — refused after.

        One client, ``functualize-substrate-sqlite``, which is below the two-client
        threshold the other members meet. Included anyway: without it that
        plugin cannot adopt this port at all, and a port a shipped plugin
        cannot adopt is not a port.
        """
        ...

    @property
    def fresh_root(self) -> Path:
        """Where this project's derived run state lives.

        The other single-client member, for the same reason — and already a
        declared member of the sibling port ``EngineHost``.
        """
        ...
