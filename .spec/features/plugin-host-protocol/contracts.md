# Contracts — plugin-host-protocol

External interfaces only. Measured against master `11d77f6`, re-verified
2026-09-17 after the scrutiny pass.

**Existing signatures are copied from live source, with file and line. Proposed
signatures are specified, and marked as such** — an earlier header claimed every
signature was copied from source, which was false of the central ones.

## 1 · `PluginHost` — the new port

**Home:** `src/functualize/_types/host.py` — a **new** module in `_types`,
beside the port it is a peer of.
**Export:** re-exported as `functualize.plugin.PluginHost`, added to that
package's `__all__`, and listed in `tests/test_public_api_surface.py` (AC-19).

**Third home, and the reasoning is in `spec.md` §E3.** In summary:

| Candidate | Rejected because |
|---|---|
| `plugin/protocols.py` | Holds ten display/extension protocols. A host port there gives one file two unrelated reasons to change — *divergent change* (ch34). |
| `_app/host.py` | Legal for the port itself, but `_types` may not import `_app` (`pyproject.toml:290`), so `AdapterPlugin.__call__` — the framework's own front door — could never name it. |
| `_types/protocols.py` | Already **882 lines / 12 protocols**, named a god module by the dead-code audit (W5). Six more protocols worsen a diagnosed smell. |
| `_types/host.py` **chosen** | `_types` is already 26 modules; a sibling file is idiomatic, costs no new edge, and leaves `protocols.py` alone. |

**The `TYPE_CHECKING` escape is refused, not unavailable.**
`exclude_type_checking_imports = true` (`pyproject.toml:244`) would let a
`_types → _app` import pass CI invisibly.
`contributor/architecture/layer-contract-blind-spot.md` §7 forbids it in terms:
*"Nothing here legalizes a TYPE_CHECKING import across a layer the contracts
refuse."* AC-1b holds the line.

```python
# src/functualize/_types/host.py                              PROPOSED
@runtime_checkable
class PluginHost(Protocol):
    """What a plugin needs from the application, and nothing else.

    Peer of `EngineHost` (`_types/protocols.py:332`) for the plugin boundary.
    Members ask; none of them lends.
    """

    # --- the five facades plugins use, as views (§2) ---
    @property
    def di(self) -> DependencyView: ...             # app/core.py:654  · 8 sites
    @property
    def extensions(self) -> ExtensionsView: ...     # app/core.py:672  · 13 sites
    @property
    def configuration(self) -> ConfigurationView: ...  # :681          · 4 sites
    @property
    def gates(self) -> GatesView: ...               # app/core.py:645  · 5 sites
    @property
    def hooks(self) -> HooksView: ...               # app/core.py:690  · AC-5 target

    # --- job lookup ---
    def get_jobs(self) -> list[JobDescriptor]: ...  # app/core.py:436  · 7 clients
    def get_job(self, name: str) -> JobDescriptor | None: ...  # :444  · 2 clients

    # --- execution ---
    def execute(self, request: RunRequest) -> JobResult: ...   # :500  · 6 clients

    # --- storage (after the §4 rename) ---
    @property
    def substrate(self) -> StoreSubstrate: ...      # the one IN EFFECT · 10 sites
    def install_substrate(self, substrate: StoreSubstrate) -> None: ...  # 1 client
    @property
    def fresh_root(self) -> Path: ...               # app/core.py:342  · 1 client
```

**Eleven members.** Every non-facade type it names already lives in `_types`
(`JobDescriptor`/`JobResult` → `_types/descriptors.py`, `RunRequest` →
`_types/run_request.py`, `StoreSubstrate` → `_types/protocols.py`, `Path` →
stdlib), so the module imports nothing it may not.

### The two storage members added 2026-09-17

`install_substrate` and `fresh_root` have **one client each** —
`functualize-state-sqlite/_plugin.py:78` and `:95` — below the ≥2 threshold, and
included anyway because without them that plugin cannot adopt the port at all
(`spec.md` AC-2b). Neither costs a facade line: both already exist on
`FunctualizeApp`, and `fresh_root` is already a declared member of the sibling
port `EngineHost` (`_types/protocols.py:421`).

The withdrawn alternative, recorded because it was written into this file:
*"the one client should be re-expressed against `substrate.describe()`."*
Unclosable — `describe(key)` returns a human-readable line about one document
(`_types/protocols.py:830`), not a joinable project root.

### Members deliberately excluded

| Member | Clients | Why not on the port |
|---|---|---|
| `hook_registry` | 4 | 7 public methods, **four** are `invoke*` — the firing half. On the port, every plugin could fire arbitrary lifecycle events. That is the "lending" `EngineHost` forbids. AC-5 migrates all four clients to `hooks.on_ready`. |
| any `invoke*` | — | Same reason, stated separately so the exclusion is not read as incidental. |
| `workflows` | 0 | No first-party plugin client. A port lists what is needed, not what exists. |
| `run` | 1 | `-> None`, the CLI entrypoint. A plugin that calls it re-enters delivery from inside delivery. Excluded on purpose. |
| `execution_engine` | 5 → **1 real** | 4 of 5 are the chain `app.execution_engine.substrate`; only `materialize_job` (`_workflow_tools.py:447`) wants the engine. 1 < the threshold. Putting it on the port would bless handing plugins the whole engine to serve one call site. |
| `di.resolve` | **0 after AC-7** | Dropped 2026-09-17. The only consumer, `functualize-ai-pydantic/_plugin.py:144`, is inside the dead block AC-7 deletes. `spec.md` §C. |

## 2 · The five view protocols

**Why views exist:** the port must be nameable from `_types`, and the concrete
facades live in `_app`. A view describes a facade from the layer allowed to
describe it. The concrete facades already match structurally — nothing
inherits, nothing is registered.

**Sized to real use, measured from `plugins/*/src` only** (an earlier count
included test files and was wrong):

```
$ rg -o -N 'app\.(di|extensions|configuration|gates|hooks)\.[a-z_]+' plugins/*/src/ \
    | sed 's/.*app\.//' | sort | uniq -c | sort -rn
      8 extensions.register_plugin_command
      7 di.provide
      4 configuration.resolve_model
      3 gates.register_gate_preset
      3 extensions.extension_state
      2 gates.register_gate_strategy
      1 extensions.register_surface
      1 extensions.register_ambient_construct
      1 di.provide_named
```

Nine methods, plus `hooks.on_ready` as the AC-5 migration target: **10 members
across 5 views**, against 33+ on the concrete facades.

```python
# src/functualize/_types/host.py                              PROPOSED
class DependencyView(Protocol):                     # 2 of DependencyFacade's 3
    def provide(self, type_: type, instance: Any, qualifier: str | None = None) -> None: ...
    def provide_named(self, name: str, instance: Any) -> None: ...

class ExtensionsView(Protocol):                     # 4 of ExtensionsFacade's 12
    def register_plugin_command(
        self,
        name: str,
        callback: Callable[..., Any],
        help_text: str = "",
        namespace: str | None = None,
        needs_terminal: bool = False,
    ) -> None: ...
    @property
    def extension_state(self) -> dict[str, Any]: ...
    def register_surface(self, surface: Any) -> None: ...
    def register_ambient_construct(
        self, construct_factory: Any, *, name: str | None = None, predicate: Any = None
    ) -> None: ...

class ConfigurationView(Protocol):
    def resolve_model(self, section: str, model_class: type[object]) -> object: ...

class GatesView(Protocol):                          # 2 of GatesFacade's 3
    def register_gate_preset(self, name: str, strategies: list[str]) -> None: ...
    def register_gate_strategy(self, name: str, resolver: Any) -> None: ...
    #                                                          ^^^ see below

class HooksView(Protocol):                          # 1 of HooksFacade's 15
    @property
    def on_ready(self) -> Callable[[OnReadyHandler], OnReadyHandler]: ...
```

Each signature above is **copied from the live facade** —
`_app/di_facade.py:29,43`, `_app/extensions_facade.py:43,141,165,171`,
`_app/configuration_facade.py:98`, `_app/gates_facade.py:31,43` — except the
two deviations named next.

### Deviation 1 — `register_gate_strategy`'s `resolver` is `Any`

The live signature is `resolver: GateResolver` (`_app/gates_facade.py:31`), and
`GateResolver` is a `@runtime_checkable Protocol` at `_gate/_resolver.py:19`.
`_types` may not import `_gate`, so the view cannot name it.

**Priced, not assumed.** Re-homing `GateResolver` into `_types` — which
`CONSTITUTION.md` → *Ports* arguably requires, since it is a port — costs **86
references across 22 files**, and it is exported from `functualize/__init__.py`
and asserted in `tests/test_public_api_surface.py`. That is a public-API
feature of its own, not a line in this one.

Rejected alternative: a `GateResolverView` mirror protocol, to avoid the bare
`Any`. It trades one `Any` on one parameter of a 2-site method for a sixth
mirror protocol, deepening the very smell §2 already accepts. Declared in
`plan.md` → *Surviving smells* instead.

### Deviation 2 — `get_plugin_commands` is not a view member

`ExtensionsFacade.get_plugin_commands() -> list[PluginCommand]` returns a type
from `_app/models.py:11`, unnameable from `_types`. It does not matter:
**no plugin source calls it.** Every caller is core (`app/commands.py:451`,
`_cli/main.py:565`, `app/adapters/cli.py:628`) or a test. The one apparent
plugin hit is `functualize-mcp/tests/test_terminal_affinity.py:31` — a test, not
plugin source. So the layer constraint and the usage measurement agree, which
is the only reason this exclusion is free.

## 3 · The lifecycle protocols, and the door that makes the retype bite

```python
# src/functualize/_types/protocols.py:90,124                   PROPOSED
class AdapterPlugin(Protocol):
    def __call__(self, app: PluginHost) -> None: ...      # was: app: Any

class PluginWithShutdown(Protocol):
    def on_shutdown(self, app: PluginHost) -> None: ...   # was: app: Any
```

**On its own this changes nothing, and that was verified rather than assumed.**
Nothing checks conformance today: `validate_adapter(obj: Any)`
(`app/adapters/_validation.py:28`) takes `Any` and is called only from tests,
and no `: AdapterPlugin` or `-> AdapterPlugin` annotation exists anywhere in
`src/`, `plugins/` or `tests/`. Probed against mypy — a structural adapter whose
`app` param is *narrower* than the protocol's produces **no error** unless
something statically accepts the protocol, or the class inherits from it.

So AC-18 requires a **static conformance assertion**, and it is part of this
contract rather than a test detail:

```python
# tests/spec/test_adapters_conform_to_the_port.py             PROPOSED
_: AdapterPlugin = CliAdapter(...)      # mypy-checked assignment, one per adapter
_: AdapterPlugin = TuiAdapter(...)
```

That assertion is what turns the four adapters annotated `app: FunctualizeApp`
into errors until they widen: `app/adapters/tui.py:39`,
`app/adapters/cli.py:823`, `functualize-http/__init__.py:371,443`,
`functualize-lambda/__init__.py:136`.

**Out of scope, stated:** the four display protocols at
`plugin/protocols.py:54,103,161,177` keep concrete `FunctualizeApp`. They are
display extensions, not lifecycle entry points.

## 4 · The substrate rename — three names, one meaning each

Maintainer decision, 2026-09-16. Today `substrate` names both the install slot
and the storage in effect; verified `SAME OBJECT: False`.

### 4a · `FunctualizeApp.substrate` — now the storage in effect

**File:** `src/functualize/app/core.py:320` (getter rewritten; **setter at :334
removed**).

```python
@property
def substrate(self) -> StoreSubstrate:
    """The storage in effect for this app. Resolved once, then held."""
    return self.execution_engine.substrate
```

Never `None`. Replaces all **10** `app.execution_engine.substrate` sites.
No recursion: the app delegates to the engine; the engine reads §4c.

### 4b · `FunctualizeApp.install_substrate` — the write door

```python
def install_substrate(self, substrate: StoreSubstrate) -> None:
    """Install a backend. **Boot only** — refused once the engine resolved one."""
```

Delegates to the existing `_app/impl.py:1546::install_substrate`, whose
`RuntimeError` guard is **preserved verbatim** — it is the thing that makes the
ordering hazard loud. Two call sites migrate:
`plugins/functualize-state-sqlite/…/_plugin.py:76` and
`tests/integration/test_substrate_durability.py:102`.

### 4c · `EngineHost.substrate` → `EngineHost.substrate_override`

**File:** `src/functualize/_types/protocols.py:401`.

```python
@property
def substrate_override(self) -> StoreSubstrate | None:
    """The override a plugin installed, or None for "resolve the default"."""
```

`_engine/executor.py:1525` changes from
`getattr(self.host, "substrate", None)` to the new name. `FunctualizeApp` grows
a matching `substrate_override` property returning `self._substrate` — the
engine must not reach a private, which is what the port exists to prevent.

**This is an `EngineHost` change, so ADR-020 is touched.** The rename is
recorded there rather than left to be rediscovered.

### 4d · Facade budget — 303 → 305

Measured with `tests/test_facade_loc_limits.py`'s own rule (decorators count;
docstrings, comments and blanks do not):

| | Executable lines |
|---|---|
| now — `substrate` getter + setter (`app/core.py:319-339`) | **7** |
| after — `substrate`, `substrate_override`, `install_substrate` | **9** |
| net | **+2 → 305** |

An earlier draft said +3 → 306. Wrong on both halves, and 306 would have added a
line of unargued headroom, which that file's *"No headroom added on top"* rule
forbids.

The raise must be argued with the two cheaper answers tried first:

1. *Make the write a setter on `substrate_override` instead of a method* — same
   line count, and the maintainer chose a method.
2. *Drop `substrate_override` and let the engine read `app._substrate`* —
   refused: the engine reaching a private is exactly what `EngineHost` exists
   to prevent.

**A third answer was offered and rejected.** The dead-code audit reports
`FunctualizeApp.cache_stats` and `.domain_registry` as having zero internal
references (6 executable lines between them), which would have taken the class
to 299 and removed the need to raise at all. Rejected 2026-09-17: both are
public members of a public class, which the audit's own `CONTRACT.md` excludes
by design — *"public folders are stable API even if unreferenced internally"* —
and an end user's call site is not in this repository. The ceiling is raised to
**exactly 305** instead.

## 5 · `HooksFacade.on_ready` — retyped, with an exact signature

**File:** `src/functualize/_app/hooks_facade.py:122`.

```python
# today — accepts anything, including a non-callable and a wrong-arity handler
@property
def on_ready(self) -> Callable[..., Any]: ...
```

The signature is **no longer deferred to Plan** — scrutiny (INTERFACE-04,
D-04) was right that a behaviour table without a signature is unjudgeable:

```python
# PROPOSED — _types/host.py for the alias, _app/hooks_facade.py for the property
OnReadyHandler: TypeAlias = Callable[[PluginHost], None]

@property
def on_ready(self) -> Callable[[OnReadyHandler], OnReadyHandler]: ...
```

Returning the handler matches the runtime: `_make_global_only_decorator`
(`_app/decorators.py:98-100`) registers `fn` and `return fn` unchanged, so the
decorator form leaves the name bound.

**Verified against mypy `--strict`, all eight cases:**

| Case | Required | Result |
|---|---|---|
| typed handler `(app: PluginHost) -> None` | pass | pass |
| bound method — the AC-5 migration form | pass | pass |
| existing handler annotated `app: Any` | pass | **pass** — all four real handlers are `app: Any`, so AC-5 does not force a same-wave retype |
| bare `@app.hooks.on_ready` decorator | pass | pass |
| non-callable (`"not a function"`) | **fail** | fail |
| wrong arity (`lambda a, b, c: None`) | **fail** | fail |
| wrong param type (`app: int`) | **fail** | fail |
| handler returning a value (`-> str`) | — | **fail** |

The last row is a deliberate consequence: `APP_READY`'s return is discarded, so
a handler that returns something is saying something untrue. None of the four
real handlers is affected — all are `-> None`.

## 6 · Call sites that change shape

| File | Line | Today | After |
|---|---|---|---|
| `functualize-mcp/…/_plugin.py` | 70 | `app.hook_registry.register_global(HookEvent.APP_READY, …)` | `app.hooks.on_ready(…)` |
| `functualize-state-sqlite/…/_plugin.py` | 58 | same | same |
| `functualize-tasks-local/…/_plugin.py` | 54 | same | same |
| `functualize-ai-pydantic/…/_plugin.py` | 62 | `hook_registry.register_global(…)` (local name) | same |
| `functualize-ai-pydantic/…/_plugin.py` | 139-148 | `StateBackend` probe → `app._di_registry.resolve` | **deleted** (dead: `functualize_state` does not exist) |
| `functualize-mcp/…/_task_tools.py` | 66-76 | `hasattr(app,'resolve')` / `app._tasks` probe | **deleted** (dead: both `False`) |
| 40 sites across `plugins/*/src` | — | `app: Any` | `app: PluginHost` |
| `app/adapters/tui.py` | 39 | `app: FunctualizeApp` | `app: PluginHost` (AC-18 forces it) |
| `app/adapters/cli.py` | 823 | `app: FunctualizeApp` | `app: PluginHost` (AC-18) |
| `functualize-http/__init__.py` | 371, 443 | `app: FunctualizeApp` | `app: PluginHost` (AC-18) |
| `functualize-lambda/__init__.py` | 136 | `app: FunctualizeApp` | `app: PluginHost` (AC-18) |
| `_types/protocols.py` | 103 | `AdapterPlugin.__call__(app: Any)` | `app: PluginHost` |
| `_types/protocols.py` | 124 | `PluginWithShutdown.on_shutdown(app: Any)` | `app: PluginHost` |
| `_cli/scaffold/templates/domain-plugin/_plugin.py.j2` | 20 | `app: Any` | `app: PluginHost` (AC-11) |
| `tests/test_public_api_surface.py` | — | no `PluginHost` | lists it (AC-19) |
| `_app/boot.py` | 129, 146 | `app.execution_engine.substrate` | `app.substrate` |
| `_app/impl.py` | 1047 | same | `app.substrate` |
| `app/_workflow_control.py` | 124 | same | `app.substrate` |
| `app/adapters/workflow_flags.py` | 238 | same | `app.substrate` |
| `_cli/builtins.py` | 1066 | same | `app.substrate` |
| `functualize-mcp/…/_history_tools.py` | 54 | same | `app.substrate` |
| `functualize-mcp/…/_workflow_tools.py` | 147, 162 | same | `app.substrate` |
| `functualize-tasks-local/…/_plugin.py` | 66 | same | `app.substrate` |
| `functualize-state-sqlite/…/_plugin.py` | 78 | `app.substrate = …` | `app.install_substrate(…)` |
| `tests/integration/test_substrate_durability.py` | 102 | `app.substrate = …` | `app.install_substrate(…)` |
| `_engine/executor.py` | 1525 | `getattr(host,"substrate")` | `…"substrate_override"` |
| `_types/protocols.py` | 401 | `EngineHost.substrate` | `substrate_override` |

## 7 · Documentation surfaces that are part of the contract

| File | Line | Defect |
|---|---|---|
| `contributor/guides/plugin-development.md` | 53-70 | Canonical example teaches `app: Any`; its comments name `app.provide` (moved to `app.di.provide`) and `app.register_plugin_command` — **neither exists** (`hasattr` → `False`). graphify's stale graph confirms `provide` was a real `FunctualizeApp` member before #39. |
| `docs/guides/hooks.md` | 257-261 | **Second** surface teaching the raw registry: `app.hook_registry.register_global(HookEvent.APP_READY, on_ready)`. Found by `rg`, not by serena — the LSP cannot see through a dynamically-typed `@property`, so `find_referencing_symbols` on `HooksFacade/on_ready` returned nothing. |
| `func scaffold` plugin templates | — | Emit `app: FunctualizeApp`; must emit `PluginHost`. |
| `docs/guides/workflows.md` | 382 | `app.substrate = MySubstrate(...)` — **must become** `app.install_substrate(MySubstrate(...))` per §4b. This is the documented install path, so it is part of the contract, not a comment. |
| `contributor/adr/020-engine-entrypoint-encapsulation.md` | — | Records `EngineHost`. The `substrate` → `substrate_override` rename (§4c) is recorded there rather than left to be rediscovered. |

## 8 · No change to

- `EngineHost`'s **shape** — one member is renamed (§4c) but nothing is added or
  removed. `PluginHost` remains a peer, not a replacement or a subtype.
- `FunctualizeApp`'s member **count** moves 44 → **46**: one public name
  (`substrate`) becomes three (`substrate`, `install_substrate`,
  `substrate_override`). `fresh_root` is already counted. An earlier draft said
  45.
- The substrate **resolution rule** (`chosen or substrate_for_project(...)`),
  the lazy-once-then-held behaviour, and the late-install refusal. All three are
  preserved exactly; only the names change.
- `HookEvent` — stays a plain class (`spec.md` §E).
- Plugin loader behaviour — the port is not enforced at runtime (`spec.md` §G).
- **Every member the dead-code audit flags.** `cache_stats`, `domain_registry`,
  `HooksFacade.pre_execute`, `ExtensionsFacade.instrument` and
  `ConfigurationFacade.resolved_job_config` all stay (`spec.md` §G).
- `GateResolver`'s home, despite §2's deviation 1 arguing it is mis-placed.
