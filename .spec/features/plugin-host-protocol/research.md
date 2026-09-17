# Research: plugin-host-protocol

## Research question

What is the smallest typed extension contract that lets plugin and provider authors
write against the current Functualize application surface without creating a
speculative "god protocol" — and can it give plugin authors IntelliSense, so they
stop guessing what a host offers?

## Baseline correction — this branch is measuring the wrong tree

This branch starts at `origin/master` `aed582e`. **Master is now `d850dfb`**
("the run model", PR #39), one commit ahead, and that commit rewrote most of
what the earlier draft of this file described.

```
git rev-list --count HEAD..master      # -> 1
```

Everything below re-measures against `master`. The previous findings, written
against `aed582e`, are superseded — including the concrete defect they rested
on (`app.resolve(StateBackend)` in `functualize-tasks-local`, which no longer
exists on master). **Rebase before specifying.**

## Prior art that now governs this feature

PR #39 landed three ADRs this feature must build on, none present on this branch:

| ADR | What it decided |
|---|---|
| ADR-020 | Engine entrypoint encapsulation — introduced `EngineHost` |
| ADR-021 | Capability duality — `rc.X` and `x: X` are two names for one lookup |
| ADR-022 | Storage is a substrate, not a key-value domain |

`EngineHost` (`src/functualize/_types/protocols.py:332` on master) is the repo's
own answer to "how do we type a host", and its docstring states the rules this
feature should inherit rather than re-derive:

- *"Everything the engine needs from outside itself, wired once."*
- *"A port lists what must come **from outside**, not what it was handed at birth."*
- *"Members ask; none of them lends."* — read-only returns, no handing out
  private mutable state.

Per *Retrieval discipline* → *prior art outranks a fresh argument*, the shape
of `PluginHost` is therefore already constrained: same file, same naming, same
`@runtime_checkable`, membership derived from measured need.

## Finding 1 — the DX half is already shipped; the naming half is not

Master replaced the flat kernel surface with six typed facades:

| Accessor | Type | Members |
|---|---|---|
| `app.di` | `DependencyFacade` | 3 |
| `app.gates` | `GatesFacade` | 3 |
| `app.configuration` | `ConfigurationFacade` | 6 |
| `app.extensions` | `ExtensionsFacade` | 12 |
| `app.hooks` | `HooksFacade` | 15 |
| `app.workflows` | `WorkflowScopeFacade` | 2 |

`FunctualizeApp`'s public surface fell from 61 members to **38**.

**None of that typing reaches a plugin author.** Annotations on `app` across
`plugins/*/src`:

```
rg -oN --no-filename "app: *[A-Za-z_|\" ]+" plugins/*/src -g '*.py' \
  | sed 's/  */ /g' | sort | uniq -c | sort -rn
```

| Annotation | Count |
|---|---|
| `app: Any` | 41 |
| `app: FunctualizeApp` | 4 |

So **91% of plugin entry points are typed `Any`**, and an author there gets zero
completions, zero signature help, and zero diagnostics. The facades exist; the
plugins cannot see them. That is the actual gap this feature should close.

## Finding 2 — `Any` hides real mistakes, measured not asserted

PoC at `scratchpad/master-probe/exp_pluginhost.py`, checked with the repo's own
mypy. Three lines, each a mistake a plugin author plausibly makes:

| Line | `app: Any` | `app: PluginHost` |
|---|---|---|
| `app.extensions.register_plugin_comand(...)` (typo) | silent | `has no attribute … maybe "register_plugin_command"?` |
| `app._di_registry.resolve(...)` (private reach) | silent | `"PluginHost" has no attribute "_di_registry"` |
| `app.configuration.resolve_model(TaskProvider)` (wrong signature) | silent | `Missing positional argument "model_class"` |

The typo case answers the DX goal directly: mypy does not merely reject it, it
**names the member the author meant**. The third was an error I made writing the
PoC, caught by the port — evidence that the port covers signatures, not just
member names.

`app._di_registry` is not hypothetical. It survives on master at
`plugins/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py:144`,
reaching past the public `app.di` facade into the kernel's private registry —
exactly what `EngineHost`'s *"members ask; none of them lends"* forbids. A port
deletes this class of access structurally rather than by review.

## Finding 3a — `HooksFacade` has zero plugin clients, and cannot replace `hook_registry`

Counting which first-party plugins reach each facade on master:

| Facade accessor | Plugin clients |
|---|---|
| `app.extensions` | 4 — flow-viz, http, inline, mcp |
| `app.configuration` | 4 — ai, ai-pydantic, mcp, state-sqlite |
| `app.di` | 3 — ai-pydantic, mcp, tasks-local |
| `app.gates` | 2 — ai, mcp |
| **`app.hooks`** | **0** |
| `app.workflows` | 0 |

`app.hooks` has no plugin clients because four plugins — ai-pydantic, mcp,
state-sqlite, tasks-local — reach `app.hook_registry` instead, all with the
same call:

```python
app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)
```

**An earlier draft of this section claimed `HooksFacade` could not serve them.
That was wrong.** `HooksFacade` has `on_ready` — *"Decorator: register APP_READY
hook (global only)"* — and a decorator is just a callable, so it takes a bound
method directly. Proven equivalent by running both and firing the hook the way
`_app/boot.py:463` fires it:

```python
app.hooks.on_ready(A()._on_app_ready)                                     # facade
app.hook_registry.register_global(HookEvent.APP_READY, B()._on_app_ready) # today
for hook in app._hook_registry._global_hooks[HookEvent.APP_READY]:
    hook(app)
# -> ['via-facade', 'via-raw-registry']   both fired
```

So **`HooksFacade` already covers 100% of measured plugin hook usage**, and no
new `register_global` method is needed. What is left is a migration choice, and
a typing defect that decides it.

### The typing defect: the facade is currently the *weaker* path

Four mistakes, checked with the repo's mypy (`exp_hooks_typing.py`):

| Mistake | `app.hooks.on_ready` | `app.hook_registry.register_global` |
|---|---|---|
| accessor/method typo | caught, with suggestion | caught, with suggestion |
| handler is not callable | **missed** | caught |
| handler has wrong arity | **missed** | missed |
| event name misspelled | n/a | **missed** |

`on_ready` is a `@property` returning `Callable[..., Any]`, which accepts
anything at all — so the narrower, prettier path currently type-checks *less*
than the raw registry it would replace.

The event-name gap is separate and affects only the registry path: `HookEvent`
is a plain class of `str` constants (`_events/hooks.py:96`), not a `StrEnum`, so
`register_global("APP_REDY", ...)` satisfies `event: str` and passes. Fixing
that is a one-line change with 15 constants behind it.

### What the registry exposes that a plugin must never use

`HookRegistry` has 7 public methods. Plugins call exactly **one**:

| Method | Who calls it |
|---|---|
| `register_global` | the 4 plugins |
| `register_for_job` | no plugin |
| `invoke`, `invoke_pre_execute`, `invoke_job_registered`, `invoke_config_event` | framework only — `_app/boot.py`, `_app/impl.py`, `_engine/executor.py`, `_discovery/registry.py` |
| `has_callbacks` | no plugin |

Four of the seven are the *firing* half. Putting `hook_registry` on the port
hands every plugin the ability to fire arbitrary lifecycle hooks — precisely the
*"members ask; none of them lends"* rule `EngineHost` states.

## Finding 3 — the port costs no kernel change

Membership is the hit set of the query in Finding 3a, not a composed guess:

```python
@runtime_checkable
class PluginHost(Protocol):
    @property
    def di(self) -> DependencyFacade: ...
    @property
    def extensions(self) -> ExtensionsFacade: ...
    @property
    def configuration(self) -> ConfigurationFacade: ...
    @property
    def gates(self) -> GatesFacade: ...
    @property
    def hooks(self) -> HooksFacade: ...      # see Finding 3a — needs on_ready typed
```

Verified both ways against master's shipped app:

- runtime — `isinstance(FunctualizeApp("probe"), PluginHost)` → `True`
- static — a `FunctualizeApp` passed to a `PluginHost` parameter type-checks clean

`FunctualizeApp` satisfies it **unchanged**. The feature is purely additive: one
protocol plus annotation changes in plugins. No kernel edit, so no
`src/functualize/**` spec gate is triggered by the protocol itself.

## Finding 4 — measured completion surface

The DX metric the goal actually names: how many candidates does the IDE offer,
and are they the right ones?

| Annotation | Completions at `app.` | Catches typo | Catches private reach |
|---|---|---|---|
| `app: Any` | 0 | no | no |
| `app: FunctualizeApp` | 38 | yes | **no** — `_di_registry` is genuinely there |
| `app: PluginHost` | **5** | yes | yes |

Then one more keystroke narrows to the capability: `app.di.` → 3, `app.gates.`
→ 3, `app.configuration.` → 6. Two-level discovery, 5 then 3–15, instead of one
flat list of 38 or nothing at all.

`FunctualizeApp` is not a substitute. It is the concrete kernel, so annotating
with it both over-exposes (38 members, of which a plugin reaches ~8) and
*legitimises* the private reach — `_di_registry` is a real attribute of the real
class, so the checker has no reason to object.

## Finding 5 — rejected alternatives, with the reason each failed

Tested in `scratchpad/poc/`, not argued from taste.

| Alternative | Result |
|---|---|
| Per-role protocols (`ConfigHost`, `LifecycleHost`, …) composed pairwise | Works, but Python has no intersection type, so every new combination needs a declared `class ConfigLifecycleHost(ConfigHost, LifecycleHost, Protocol)`. Master's facades already group these; this would be a second grouping of the same thing. |
| `app.capability(ConfigHost)` — generic accessor keyed by protocol class | **Rejected by mypy**: `Only concrete class can be given where "type[ConfigHost]" is expected [type-abstract]`. A Protocol class may not be passed as a value. |
| `app.capability(CONFIG)` — generic accessor keyed by a typed token | Type-checks cleanly and infers correctly, but adds a token registry and a second lookup idiom for something `app.di` already spells. |

The last two are also the shape ADR-021 settled *for jobs* (`rc._cap`), and T12
of that feature explicitly deleted a parallel namespace API on the grounds that
*"a framework namespace is a second concept for something a string prefix
already does"*. Introducing one for plugins would contradict a recorded
decision. The plain-property port is the option consistent with both ADRs.

## Design-principle audit

Against `.claude/skills/python-design-patterns` and `improve`'s smell taxonomy:

- **Interface segregation.** `app: FunctualizeApp` makes a provider plugin depend
  on gates, surfaces and workflow scopes it never touches. The port is the
  segregation.
- **Rule of Three.** Honoured by deriving membership from measured use — every
  member on the port is reached by ≥2 first-party plugins (Finding 3a), and the
  two facades with no plugin client, `hooks` and `workflows`, are excluded.
  Nothing speculative is added. This is what keeps it from being the "god
  protocol" the original question warns about.
- **God object.** Largely already addressed by master's facade split (61 → 38).
  Residual: `ExtensionsFacade` at 12 members and `HooksFacade` at 15 are the two
  that could still be over-broad — worth measuring before the port fixes their
  shape in a published type.
- **Leaking internal types.** `app.substrate -> Any` (`app/core.py:320`) is an
  `EngineHost` member with no type, and `extension_state -> dict[str, Any]` is
  an untyped bag. Both defeat IntelliSense on the very path a plugin uses.

## FuncCloud alignment

From *01 — Functualize Foundations and the FuncCloud Extension Boundary*:

> Plugin commands/adapters — *"provides extension points for MCP, remote
> execution, cloud control-plane commands, and other interfaces without
> replacing the core runtime."*

FuncCloud is specified to arrive as a plugin-layer `managed team/remote source`
alongside `package/plugin sources`, not as a fork of the kernel. That makes the
plugin host contract load-bearing commercially, not merely a DX nicety: it is
the seam the paid layer is supposed to attach to.

From *03 — Capability Model and Delegated Authority*:

> *"A typed function is easier to govern than arbitrary shell text. Policy can
> reason about the operation's declared arguments rather than attempting to
> parse an unrestricted command line."*

The same argument applies one level up. A typed **host** contract is easier to
govern than `Any`: policy, audit, and capability attenuation can reason about
which host capabilities a plugin declares it needs. `app: Any` makes a plugin's
required authority unanalysable — the exact property page 03 says is the
strategic advantage.

Page 03's *hidden owner context* ("the visible callable surface can be smaller
than the internal implementation") is structurally the same move as a narrow
port over a wide kernel.

## Recommended scope — SUPERSEDED (kept for the record)

> **Historical. Do not implement from this section.** Written before the
> 2026-09-16 rebase and the 2026-09-17 revision. Three of its
> recommendations are now wrong: the port goes in **`_types/host.py`**, not
> `_types/protocols.py` (a god module at 882 lines / 12 protocols); membership
> is **11 members via five view protocols**, not "the five facade accessors";
> and `HookEvent → StrEnum` is out of scope (`spec.md` §E). The live contract is
> `contracts.md`; the live reasoning is *Revision after scrutiny* at the end of
> this file. Kept because the path the thinking took is evidence about the
> design, and deleting it would make the revision look like it had no premise.


1. **Rebase onto `d850dfb` first.** Non-negotiable — the current artifacts
   describe a tree that no longer exists.
2. Add `PluginHost` to `src/functualize/_types/protocols.py` beside `EngineHost`,
   membership limited to the five facade accessors measured above.
3. Re-export from `functualize.plugin` (the namespace that already publishes the
   author-facing vocabulary).
4. Convert the 41 `app: Any` annotations in `plugins/*/src`, and fix
   `ai-pydantic:144` to use `app.di` — the port makes the private reach a type
   error, so the conversion and the fix are one change.
4b. Type `HooksFacade.on_ready`, make `HookEvent` a `StrEnum`, then migrate the
   four `app.hook_registry.register_global(HookEvent.APP_READY, h)` call sites
   to `app.hooks.on_ready(h)`. Order matters: migrating first would lose the
   handler-type check the registry gives today (Finding 3a).
5. Update `_cli/scaffold/templates/plugin.py.j2`, which currently emits
   `app: FunctualizeApp`, so new plugins start on the port.
6. Add a static negative test proving a misspelled facade member fails mypy.
7. Type `app.substrate` and `extension_state`, or record why they stay `Any`.
8. **Do not** add a `capability()` accessor, a token registry, or role protocols.
   Measured, and each contradicts a shipped decision.

## Open decisions — SUPERSEDED (all four are settled)

> **Historical.** Every question below was answered: `execution_engine`
> excluded and the substrate renamed (2026-09-16); the storage members added
> and the port re-homed to `_types/host.py` (2026-09-17). `spec.md` §H carries
> the settled list. Kept for the record.


- Does the port belong in `functualize.plugin` only, or also `functualize.types`?
- Is `ExtensionsFacade` (12 members) the right granularity to freeze into a
  published type, or should the port expose a narrower view?
- **Decided by Finding 3a, pending maintainer sign-off:** `hooks` goes on the
  port and `hook_registry` does not, conditional on two fixes landing with it —
  type `HooksFacade.on_ready` as
  `Callable[[Callable[[Any], None]], Callable[[Any], None]]` instead of
  `Callable[..., Any]`, and make `HookEvent` a `StrEnum`. Without the first fix
  the migration *reduces* type safety; the raw registry catches a non-callable
  handler today and the facade does not.
- Does `hook_registry` stay public on `FunctualizeApp` after the four plugins
  migrate? Nothing outside the framework would call it, but removing a public
  accessor is a breaking change even pre-1.0.
- Does `RemoteProvider` move to a public namespace in this feature or in
  `vault-sync-providers`? The provider path is entry-point based and independent
  of `PluginHost` — it may not belong here at all.
- Should loading enforce the port at runtime (`isinstance`), or stay duck-typed
  and static-only? Master's app already passes, so enforcement is cheap — but it
  is a behaviour change and needs a demonstrated runtime error to justify.

## Reproducing this

```
scratchpad/poc/                 # role protocols, capability accessor, token variants
scratchpad/master-probe/        # git worktree at d850dfb + exp_pluginhost.py
uv run mypy exp_pluginhost.py   # the three-mistake table
```

The `master-probe` worktree is disposable: `git worktree remove <path>`.

---

## Re-verification against master `11d77f6` (2026-09-16, post-rebase)

The branch is now rebased onto `11d77f6` (includes #39 `d850dfb` "the run model"
and #40 "post-merge CI"). Every count above was re-run against the live tree.
**Four numbers changed and three new findings appeared.** Each row names the
command that produced it.

### Corrected counts

| Claim as written | Measured on `11d77f6` | Verdict |
|---|---|---|
| `app: Any` = 42, `app: FunctualizeApp` = 4 | **40 Any-typed, 4 concrete, 44 total, 0 unannotated** | regex was contaminated |
| "91% of plugin entry points are `Any`" | **91%** (40/44) | **holds** |
| surface "fell from 61 members to 38" | **66 → 44** (63+3 attrs → 41+3) | both numbers wrong |
| "a plugin that reaches ~8" members | **15 distinct members** | understated |
| `HookRegistry`: 7 public, four `invoke*` | 7 public, 4 `invoke*` | **holds** |
| four plugins register `APP_READY` | 4 sites | **holds** |
| `on_ready` is `@property -> Callable[..., Any]` | `_app/hooks_facade.py:122` | **holds** |
| `EngineHost` at `_types/protocols.py:332` | line 332 | **holds** |

The `app: Any` regex in §"Finding 2" counts **docstring lines** — Google-style
`app: The FunctualizeApp instance` matches it. Annotations must be counted from
the AST, not from `rg`:

```
python3 - <<'PY'   # counts ast parameter annotations named `app`
# see .spec/features/plugin-host-protocol/count_app_annots.py
PY
-> TOTAL 44 | 39 `Any` | 1 `Any | None` | 4 `FunctualizeApp` | 0 unannotated
```

`FunctualizeApp` also **moved**: it is `src/functualize/app/core.py:71-782`, not
`_app/impl.py`. All six facades are confirmed present as properties —
`gates:645 di:654 workflows:663 extensions:672 configuration:681 hooks:690` —
and `_di_registry:117` is a real attribute, which is the premise for rejecting
the concrete class as the annotation.

### New finding A — there is no public read path out of DI

`app.di` is `DependencyFacade` with **exactly three** public members:

```
di public: ['provide', 'provide_factory', 'provide_named']
hasattr(app.di, 'resolve') = False
```

This re-frames the private reach. `plugins/functualize-ai-pydantic/…/_plugin.py:144`
does `app._di_registry.resolve(StateBackend)` **because the public facade cannot
read**. Annotating against a port cannot close that reach — a port may only
declare members that exist. Closing it requires a public read path to be
*added*. This is a scope change, not an annotation change, and it is the one
finding that moves `spec.md`.

### New finding B — a second private reach, and two members that do not exist

The AST scan of attribute access on `app` / `self._app` in `plugins/*/src`
found **two** private reaches, not one, and two probes for members that were
never on the class:

| site | reaches | exists? |
|---|---|---|
| `functualize-ai-pydantic/…/_plugin.py:144` | `app._di_registry` | yes (private) |
| `functualize-mcp/…/_task_tools.py:73` | `app._tasks` | **no** |
| `functualize-mcp/…/_task_tools.py:71` | `app.resolve` | **no** |

Verified at runtime:

```
hasattr(app, 'resolve') = False
hasattr(app, '_tasks')  = False
```

`_task_tools.py:66-76` is therefore **dead in both branches** — it `hasattr`-probes
two absent members inside a bare `except Exception: pass`, then silently falls
back to an in-memory `Tasks`. The MCP plugin has always used the fallback. This
is the strongest available evidence for the feature: `app: Any` did not merely
fail to help, it concealed a permanently-dead resolution path for two releases.

It also **contradicts ADR-022** (`contributor/adr/022:84`): *"nothing about a
scope record's shape reaches the backend, so nothing about the backend has to be
discovered by `hasattr`."* The same principle indicts this block.

### New finding C — the official guide teaches the defect, and is itself broken

`contributor/guides/plugin-development.md:53-70` is the canonical "write a
plugin" example. It teaches `from typing import Any` / `def __call__(self, app: Any)`,
and its three commented examples name **two members that do not exist**:

```
hasattr(app, 'provide')                 = False   # guide line 70
hasattr(app, 'register_plugin_command') = False   # guide line 71
hasattr(app, 'event_bus')               = True
```

`app.provide` moved to `app.di.provide`. So the guide is both the *source* of the
`app: Any` convention and stale in the same example. Any fix that does not
update this guide leaves the defect being actively taught.

### The tension this exposes — a plugin *writes* to the host

`docs/guides/workflows.md:382-392` documents installing a substrate from a
plugin's `APP_READY` hook:

```python
def _on_app_ready(self, app):
    app.substrate = MySubstrate(...)
```

`substrate` is a **settable property** (`app/core.py:320` getter, `:334` setter,
"Boot only, and before the engine resolves one"). A documented, supported plugin
write to the host.

`EngineHost`'s stated rule is *"Members ask; none of them lends"* — and a
read-only `Protocol` member cannot type an assignment. So `PluginHost` either
carries a settable `substrate` (departing from the `EngineHost` rule it claims
to inherit) or the documented install path changes to a method. **This is an
open decision, not a detail** — it is the one place where the two ports cannot
have the same shape.

> **Resolved 2026-09-16 (Plan architecture gate).** The maintainer chose to fix
> the naming inside this feature. `app.substrate` becomes the storage *in
> effect*, `app.install_substrate(sub)` becomes the write door, and
> `EngineHost.substrate` is renamed `substrate_override`. So the two ports do
> end up the same shape — both ask, neither lends — because the *write* left the
> property and became a method. See `spec.md` §E2 and `contracts.md` §3.

### Prior art located by the prose pass

The prose pass (zvec-grep, index built for this worktree) surfaced four
governing documents this feature inherits rather than re-derives:

- `contributor/architecture/run-model/05-engine-seal.md:105` — §E.1 `EngineHost`
  as *"a narrow port, wired once"*, citing `.spec/CONSTITUTION.md` → *Ports*:
  `@runtime_checkable Protocol`, no ABC, no forced inheritance.
- `contributor/architecture/audit-engine-encapsulation.md:323` — §3.3, including
  *"Why this and not Mediator"*. The same argument applies unchanged here.
- `contributor/architecture/run-model/11-boundaries.md` — the three-way
  core/plugin/job split. A plugin owns *"how a run is reached, and how its
  outcome is rendered"*; it does not own the five run authorities.
- `contributor/architecture/run-model/09-agent-step-port.md:141` — §F *"What this
  feature does not do"*, the precedent for a port declining auto-discovery and
  default implementations.

### Reproducing the re-verification

```
.spec/features/plugin-host-protocol/count_app_annots.py                      # annotation census (AST)
rg -n "register_global\(HookEvent\.APP_READY" plugins/ -g '*.py'
uv run python -c "from functualize.app.core import FunctualizeApp; \
  app=FunctualizeApp(name='p'); print(hasattr(app,'resolve'), hasattr(app,'_tasks'))"
```

---

# Revision after scrutiny — 2026-09-17

`.spec/scrutiny-reports/plugin-host-protocol-2026-09-16.md` returned **REVISE**:
64 claims adjudicated, 41 confirmed, 15 falsified, 6 blocking. Its two
directional decisions — a measured structural port, and the substrate rename —
came out SOUND on every lens. What failed was the package around them.

## Claims of mine it falsified, and which were mine to own

| Claim | Verdict | Owned |
|---|---|---|
| The port can type every `Any` param | FALSIFIED | **Yes.** `contracts.md:91` excluded `fresh_root` and deferred re-expressing it via `substrate.describe()`. The deferral was never closeable: `describe(key)` returns a human-readable line about one document, not a joinable root. An unclosed deferral I wrote. |
| `uv run mypy plugins/*/src` can be green | FALSIFIED | **Yes.** Re-ran: `Found 120 errors in 22 files`. |
| `di.resolve` has a production path | FALSIFIED | **Yes.** Its only consumer is inside the block T2 deletes. |
| Net +3 → 306 | FALSIFIED | **Yes.** 7 lines now, 9 after: +2 → 305. 306 added unargued headroom. |
| 44 → 45 members | FALSIFIED | **Yes.** One name becomes three: 46. |
| 55 `HookEvent` files / 78 literals | FALSIFIED | **Yes.** Live count is 42 files; no command was retained that produced 78. Both withdrawn. |
| 10 chain sites across 9 files | PARTIALLY TRUE | **Yes.** 8 files, not 9. The six-in-`src/` half was right. |
| Runtime `isinstance` proves compatibility | PARTIALLY TRUE | **Yes.** It proves presence, not signatures. AC-3 now requires both checks. |
| Files-to-change list complete | FALSIFIED | **Yes.** Missing the domain-plugin template, the custom-state-backend example, the dependency graph, an ADR, and `test_public_api_surface.py`. |
| "Always dead for two releases" | UNTESTABLE | Fair but thin — a user with the retired package installed is the only way the path lives, and ADR-022 retired it. Wording softened; the deletion stands. |

## Findings of the report I corrected

- **`install_substrate` is not called at `_plugin.py:76`.** Line 78 is
  `app.substrate = self._substrate`, the setter. The conclusion holds — T3/T4
  turn that into `install_substrate`, so the port needs the member — but the
  mechanism was mis-stated.
- **C5 in the dead-code audit mis-attributes `WiringFacade.with_plugin_config`
  to this feature.** It is `RunContext.wiring.with_plugin_config`
  (`_engine/capabilities/wiring_facade.py:61`), ~20 test references, docstring
  citations at `_types/redaction.py:106` and `runcontext.py:218`. This feature
  never touches it. Not blocked on feature completion.

## Two things measurement settled that reasoning had not

**1. The two-tier port is impossible, not merely awkward.** A 6-member port in
`_types` for `AdapterPlugin` plus an 11-member one in `_app` looked like the way
to satisfy both layers. Probed with mypy: adapters use facades *inside*
`__call__` (`functualize-mcp/_plugin.py:88` → `app.di.provide`), and a protocol
promising the narrow host cannot be implemented by a method demanding the wide
one — parameter contravariance. Adapters would be strictly worse off than with
`Any`. Dropped before it reached the user as an option.

**2. Retyping `AdapterPlugin` is inert without a static door.** Probed, four
cases:

| Case | mypy |
|---|---|
| structural adapter, narrower `app`, nothing accepts the protocol — **today** | **no error** |
| same, plus one function typed `register(a: AdapterPlugin)` | error, Expected `PluginHost` vs Got `FunctualizeApp` |
| `class A(AdapterPlugin)` with a narrower param | error — "violates the Liskov substitution principle" |
| `class A(AdapterPlugin)` with the param unannotated | `no-untyped-def` — mypy does **not** inherit the type |

`validate_adapter(obj: Any)` takes `Any` and is called only from tests; no
`: AdapterPlugin` annotation exists in the tree. So AC-18 carries the retype
**and** the conformance assertion as one criterion.

## The layer question, and the prior art that closed it

`_types` may not import `_app` (`pyproject.toml:290`).
`exclude_type_checking_imports = true` (`:244`) would have hidden such an import
from CI. `contributor/architecture/layer-contract-blind-spot.md` refuses it in
terms — §7 *"not an exemption"*, §5 *"a layer decision, not a typing
convenience… pick a layer that can hold the type (`_types`)"* — and its §4
independently names the chosen remedy: *"a `_types` re-export or protocol."*
That document measures the hole at 155 hidden imports, 8 direct violations, and
`1 kept / 5 broken` on a flip.

So the port went to a **new `_types/host.py`** with five view protocols, and not
into `_types/protocols.py`, which the dead-code audit (W5) names a god module at
882 lines / 12 protocols.

**Two obstacles found while writing the views**, neither reachable from the
layer rule alone:

- `GatesView.register_gate_strategy`'s `resolver` must be `Any`. The live type
  `GateResolver` is a `@runtime_checkable Protocol` in `_gate/_resolver.py:19`,
  and re-homing it to `_types` — arguably correct under *Ports* — costs **86
  references across 22 files**, is exported from `functualize/__init__.py`, and
  is asserted in `test_public_api_surface.py`. Declared as surviving smell #2.
- `ExtensionsFacade.get_plugin_commands() -> list[PluginCommand]` returns an
  `_app/models.py` type and cannot be named from `_types`. It does not matter:
  **no plugin source calls it** — every caller is core or a test. The layer
  constraint and the usage measurement agree, which is the only reason the
  exclusion is free. The apparent plugin hit
  (`functualize-mcp/tests/test_terminal_affinity.py:31`) is a test.

The plugin-facing facade census was also re-measured from `plugins/*/src` only;
an earlier count included test files. Nine methods, plus `hooks.on_ready`: **10
of 33+**.

## The dead-code audit: five findings declined

`plan.md` §7 records this in full. In summary: `FunctualizeApp.cache_stats` and
`.domain_registry`, and the three facade doors `HooksFacade.pre_execute`,
`ExtensionsFacade.instrument`, `ConfigurationFacade.resolved_job_config`, all
stay. All five are public surface — the first two directly, the other three
through the public `app.hooks` / `app.extensions` / `app.configuration`
properties — and the audit's own `CONTRACT.md` excludes public API by design:
*"public folders are stable API even if unreferenced internally."*

All three facade doors do have **zero** non-`def` references in `src/`,
`plugins/` and `tests/`. That is evidence they are unused *here*, not evidence
they are unused.

**The argument that these deletions were load-bearing for this feature was
wrong**, and it was wrong independently of the public-API question. It ran: the
view protocols would enshrine dead doors in a new public contract. They would
not — the views describe only the ~10 methods plugins call, so the other 23 are
excluded whether alive or dead. The justification was built on top of a
conclusion already reached, which is the wrong direction for evidence to travel.

**What came out of it instead**: the maintainer's rule that every public API
must be exercised by an example
(`contributor/reference/public-api-example-coverage.md`, 2026-09-17). It
dissolves the whole category of finding — once every public symbol has an
example caller, zero references means *dead* again for public API too, because
the caller that should exist is the example. Measured backlog: **108 of 161**
public symbols have none, and four of the six typed facades are among them.
AC-22 makes `PluginHost` the first symbol to satisfy it.
