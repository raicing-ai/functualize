"""The one list of injected capabilities (D-4, ADR-014).

Every capability declares a :class:`~functualize._engine.capabilities.spec.CapabilitySpec`
beside itself; this module collects them, and the executor derives from them:

- ``_per_invocation_types()``          → :data:`PER_INVOCATION_TYPES`
- ``_create_per_invocation_cap()``     → :data:`SPEC_BY_TYPE` + ``spec.factory``
- the ``Sources`` two-phase bind       → each spec's own ``preflight_bind``

**Why there is still a string set in `_primitives`.**

``_discovery/providers.py`` needs to know which parameter annotations the engine
injects, so it can strip them from the CLI surface. ``_discovery`` and
``_engine`` are peer layers under the *"Peer layers are independent"* import
contract, so ``_discovery`` may never import a capability module — it can match
on the *name* and nothing else. That is why
``_primitives/capability_names.INJECTED_PARAM_TYPE_NAMES`` is a set of strings,
and why it cannot derive from the registry: the derivation would have to run
somewhere ``_discovery`` can reach, and there is no such place.

So it stays, and it is made **non-drifting** instead: the check below runs at
import, on every process that resolves a capability, and refuses to start when
the two disagree. That is deliberately not a test. A test runs when somebody
runs it, and the failure this guards against — a name in one list and not the
other — produced, in the version of the code this replaced, a capability
parameter silently becoming a CLI flag, so the job worked cold and died on its
*second* invocation with ``Error: Missing argument 'SH'``. That is defect D8,
and it shipped.

Imported lazily by the executor, like every other capability import there: the
warm-boot path performs **zero** module imports until a job is actually
resolved, and importing eleven capability modules at engine-import time would
forfeit that.
"""

from __future__ import annotations

from functualize._engine.capabilities.invoke import CAPABILITY as _INVOKE
from functualize._engine.capabilities.job_context import CAPABILITY as _JOB_CONTEXT
from functualize._engine.capabilities.live import CAPABILITY as _LIVE
from functualize._engine.capabilities.log import CAPABILITY as _LOG
from functualize._engine.capabilities.perf import CAPABILITY as _PERF
from functualize._engine.capabilities.prompt import CAPABILITY as _PROMPT
from functualize._engine.capabilities.shell import CAPABILITY as _SHELL
from functualize._engine.capabilities.sources import CAPABILITY as _SOURCES
from functualize._engine.capabilities.spec import CapabilityContext, CapabilitySpec
from functualize._engine.capabilities.state import CAPABILITY as _STATE
from functualize._engine.capabilities.stdout import CAPABILITY as _STDOUT
from functualize._engine.capabilities.tty import CAPABILITY as _TTY
from functualize._primitives.capability_names import INJECTED_PARAM_TYPE_NAMES

__all__ = [
    "CAPABILITY_SPECS",
    "PER_INVOCATION_TYPES",
    "PREFLIGHT_BOUND_TYPES",
    "SPEC_BY_TYPE",
    "CapabilityContext",
    "CapabilitySpec",
]


#: ``RunContext`` is injected but not built by the factory path — the executor
#: constructs it at lifecycle step 5, because middleware needs it whether or not
#: the job asked for one. ``JobConfigView`` is injected but has no *static*
#: type: it is resolved by identity against ``engine._config_view_type``, a
#: value discovered at boot. Both are declared so the name invariant below
#: balances against the real set rather than against a hand-written exception.
_RUN_CONTEXT = CapabilitySpec(name="RunContext", per_invocation=False)
_JOB_CONFIG_VIEW = CapabilitySpec(name="JobConfigView", per_invocation=False)


CAPABILITY_SPECS: tuple[CapabilitySpec, ...] = (
    _LOG,
    _INVOKE,
    _PROMPT,
    _PERF,
    _SHELL,
    _STDOUT,
    _STATE,
    _SOURCES,
    _JOB_CONTEXT,
    _TTY,
    _LIVE,
    _RUN_CONTEXT,
    _JOB_CONFIG_VIEW,
)


#: Types the engine instantiates per invocation. One set, because there were
#: two — the resolution plan's ("is this parameter resolvable?") and the
#: resolver's ("instantiate it") — and a type present in one but not the other
#: resolved to nothing, with no error.
PER_INVOCATION_TYPES: frozenset[type] = frozenset(
    spec.type
    for spec in CAPABILITY_SPECS
    if spec.per_invocation and spec.type is not None
)

SPEC_BY_TYPE: dict[type, CapabilitySpec] = {
    spec.type: spec for spec in CAPABILITY_SPECS if spec.type is not None
}

#: Capabilities injected empty and completed once the pre-flight decision
#: exists. A declared property, not a call somebody has to remember. Exposed
#: for introspection and tests; the executor iterates `CAPABILITY_SPECS`
#: directly, because it needs each spec's own `preflight_bind`.
PREFLIGHT_BOUND_TYPES: frozenset[type] = frozenset(
    spec.type
    for spec in CAPABILITY_SPECS
    if spec.needs_preflight_bind and spec.type is not None
)


def _check_name_agreement() -> None:
    """Refuse to start when the registry and the low-layer name set disagree.

    See the module docstring for why the name set exists at all and why this is
    an import-time invariant rather than a test.
    """
    registered = {spec.name for spec in CAPABILITY_SPECS}
    if registered == set(INJECTED_PARAM_TYPE_NAMES):
        return
    missing_names = registered - set(INJECTED_PARAM_TYPE_NAMES)
    missing_specs = set(INJECTED_PARAM_TYPE_NAMES) - registered
    raise RuntimeError(
        "capability registry and INJECTED_PARAM_TYPE_NAMES disagree — "
        f"declared here but not named in _primitives: {sorted(missing_names)}; "
        f"named in _primitives but not declared here: {sorted(missing_specs)}. "
        "Add a CapabilitySpec beside the capability and the matching name to "
        "_primitives/capability_names.INJECTED_PARAM_TYPE_NAMES. The name set "
        "cannot derive from this registry because _discovery consumes it and "
        "may not import _engine (peer layers are independent); see ADR-014."
    )


_check_name_agreement()
