# Plugin host protocol — a name a plugin author can annotate

**Base:** master `11d77f6` (includes #39 `d850dfb` "the run model" and #40).
The branch has been rebased onto it; every count below was re-measured against
that tree on 2026-09-16 and the commands are in `research.md` →
*Re-verification*.

## A · Why

Master shipped the hard half of plugin DX already. `FunctualizeApp`
(`src/functualize/app/core.py:71`) was split into six typed facades — `app.di`,
`app.extensions`, `app.configuration`, `app.gates`, `app.hooks`,
`app.workflows` — and its public surface fell from **66 members to 44**
(63 methods + 3 attrs → 41 + 3).

**None of that typing reaches a plugin author.** Counted from the AST, not from
a regex:

| `app` parameter annotation in `plugins/*/src` | Count |
|---|---|
| `Any` | 39 |
| `Any \| None` | 1 |
| `FunctualizeApp` | 4 |
| unannotated | 0 |
| **total** | **44** |

**91% of plugin entry points are `Any`.** An author there gets no completions,
no signature help, and no diagnostics — so they guess, and the guesses are not
caught. Three such guesses are live on master, and all three are **dead code**:

| site | reaches | exists? | consequence |
|---|---|---|---|
| `functualize-mcp/…/_task_tools.py:71` | `app.resolve` | **no** | branch never taken |
| `functualize-mcp/…/_task_tools.py:73` | `app._tasks` | **no** | branch never taken |
| `functualize-ai-pydantic/…/_plugin.py:144` | `app._di_registry` | yes, private | line never reached — its `from functualize_state import StateBackend` guard raises `ImportError` (that domain was retired by ADR-022 and no `plugins/functualize-state` exists) |

Verified: `hasattr(app,'resolve') == False`, `hasattr(app,'_tasks') == False`,
`import functualize_state → ImportError`. So `functualize-mcp` has **always**
used its in-memory `Tasks` fallback, and `functualize-ai-pydantic` has **always**
passed `backend=None`. Two plugins independently tried to read a capability out
of DI; both failed silently, for two releases, because `app: Any` reports
nothing and both sites swallow the failure in a bare `except`.

This is the argument for the feature in one line: **`Any` did not merely fail to
help — it concealed three permanently-dead resolution paths.**

`FunctualizeApp` is not the fix either. Annotating with the concrete kernel
exposes 44 members to a plugin that reaches 15, and it *legitimises* the private
reach — `_di_registry` is a real attribute (`app/core.py:117`), so no checker
objects.

## B · Prior art this must obey

`EngineHost` (`src/functualize/_types/protocols.py:332`, ADR-020) is the same
shape for the engine boundary. This feature inherits its rules rather than
re-deriving them:

- *"Everything the engine needs from outside itself, wired once."*
- *"A port lists what must come **from outside**, not what it was handed at birth."*
- *"Members ask; none of them lends."*

Four documents govern the design and are not contradicted here:
`contributor/architecture/run-model/05-engine-seal.md:105` (§E.1, the narrow
port, citing `.spec/CONSTITUTION.md` → *Ports*: `@runtime_checkable`, no ABC),
`contributor/architecture/audit-engine-encapsulation.md:323` (§3.3, including
*"Why this and not Mediator"*), `run-model/11-boundaries.md` (the core/plugin/job
split), and `run-model/09-agent-step-port.md:141` (the precedent for a port that
declines auto-discovery and defaults).

ADR-022:84 — *"nothing about the backend has to be discovered by `hasattr`"* —
independently indicts `_task_tools.py:66-76`.

## C · There is no public read path out of DI — and it does not matter

`app.di` is `DependencyFacade` with exactly three public members:

```
['provide', 'provide_factory', 'provide_named']
hasattr(app.di, 'resolve') -> False
```

It can write and cannot read. That is *why* both plugins in §A reached past it.

**`di.resolve(T)` was in scope and is now dropped.** The scrutiny pass
(`.spec/scrutiny-reports/plugin-host-protocol-2026-09-16.md`, DEPENDENCY-01)
asked which production caller would reach it *after* the §A deletions land, and
the answer is none. Re-measured on the live tree — the only
`_di_registry.resolve` outside the kernel is
`functualize-ai-pydantic/_plugin.py:144`, which is inside the dead block AC-7
deletes:

```
$ rg -n '_di_registry|\.di\.resolve' plugins/
plugins/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py:144
```

So adding the read path would create public surface whose entire justification
is removed one wave earlier. That is speculative generality by the definition
this feature is using elsewhere, and the maintainer's original decision to add
it was taken against a premise (a surviving consumer) that measurement did not
support. Recorded here rather than silently reversed.

`app.di` remains a port member: the write door is what plugins actually use
(`di.provide`, `di.provide_named` — five sites). A future feature that finds a
real reader can add `resolve` then, with a production path and a sabotage test.

## D · The hooks decision, and why it is not the obvious one

Four plugins register a startup hook with the same call:

```python
app.hook_registry.register_global(HookEvent.APP_READY, self._on_app_ready)
```

`hook_registry` is the raw internal registry (`_events/hooks.py:158`): 7 public
methods, of which **four** are `invoke*` — the *firing* half. Putting it on the
port would hand every plugin the ability to fire arbitrary lifecycle events,
which is the "lending" `EngineHost` forbids.

`app.hooks.on_ready` already does the job — a decorator is a callable, so it
takes a bound method directly; both forms were run and both fired.

**But migrating as-is would reduce type safety.** `on_ready` is a `@property`
returning `Callable[..., Any]` (`_app/hooks_facade.py:122`), which accepts
anything:

| Mistake | `on_ready` today | `register_global` today | `on_ready` retyped |
|---|---|---|---|
| member typo | caught (statically) | caught | caught |
| handler not callable | **runtime `TypeError`**, missed by mypy | runtime | **caught statically** |
| handler wrong arity | **missed entirely** — accepted at registration, fails when the hook fires at boot | **missed entirely** | **caught statically** |

Corrected during the Plan architecture gate: `make_on_ready_decorator`
(`_app/impl.py:517-527`) *does* validate callability, but at **runtime** —
`raise TypeError(f"on_ready expects a callable, got …")`. Verified:

```
app.hooks.on_ready('not a function') -> TypeError: on_ready expects a callable, got str
app.hooks.on_ready(lambda a, b, c: None) -> ACCEPTED at registration
```

So the retype's value is not "adds a check that was missing" but **moves two
checks earlier**: non-callable from boot-time to edit-time, and wrong arity from
*never* to edit-time. Arity is the one that matters — today a wrong-arity
handler registers cleanly and fails during `APP_READY`, which is the hardest
place in the lifecycle to attribute a failure to its cause.

So the retype is a *prerequisite*, not a follow-up.

## E · Scope decision: `HookEvent` stays a plain class

Dropped on evidence. `on_ready` takes no event argument, so after the migration
no plugin passes an event name at all — the gap closes for plugins without the
change. Meanwhile **42** files reference `HookEvent`
(`rg -l '\bHookEvent\b' src tests plugins | wc -l` → 42, re-measured
2026-09-16). An earlier draft of this spec recorded 55 files and 78 raw
event-name literals; neither number reproduced, and no command was retained
that would have produced the 78 — so both are withdrawn rather than re-cited.
42 files for zero plugin-facing benefit. Recorded so the omission is a
decision, not an oversight.

## E2 · The `substrate` name is disambiguated here

**Maintainer decision, 2026-09-16: fix the naming inside this feature** rather
than leave the chain as a surviving smell.

One word names two things today, and the ambiguity is measured, not stylistic:

```
app.substrate             -> None               (the install slot; app/core.py:320)
app.execution_engine.sub  -> JsonFileSubstrate  (resolved; _engine/executor.py:1510)
SAME OBJECT: False
```

The consequence is a two-hop chain at every site that wants the *effective*
storage — **10 of them, 6 inside `src/` itself**
(`_app/boot.py:129,146`, `_app/impl.py:1047`, `app/_workflow_control.py:124`,
`app/adapters/workflow_flags.py:238`, `_cli/builtins.py:1066`) and 4 in plugins.
This is the repo's own idiom, not a plugin wart, which is why the port cannot
simply decline to mention storage.

### The three names after this feature

| Name | Role | Cost of reading it |
|---|---|---|
| `app.substrate` | **the storage in effect** — always a real object. Replaces all 10 chain sites. | Resolves on first access (lazy, then held) |
| `app.install_substrate(sub)` | the **write door**. Replaces the `app.substrate = …` setter. | — |
| `EngineHost.substrate_override` | what the **engine** asks the host for: the override, or `None` for "resolve the default". Renamed from `EngineHost.substrate`. | Cheap; never resolves |

The common word gets the common meaning. No name means two things.

### The ordering hazard, and why it is acceptable

Reading `app.substrate` now triggers resolution. A plugin that read it *before*
installing would lock in the filesystem default. That path already exists today
via the chain, and it **fails loudly** rather than silently — verified:

```
app2.execution_engine.substrate        # resolves
app2.substrate = SQLiteSubstrate(...)  # RuntimeError: "the substrate is already
                                       #   in use by this app's engine …"
```

`install_substrate` (`_app/impl.py:1546`) already refuses a late install
precisely to prevent the split brain. Also verified: constructing the engine
does **not** resolve the substrate, so merely touching `app.execution_engine`
is still safe.

### Typing, fixed in passing

`EngineHost.substrate` is declared `StoreSubstrate | None`
(`_types/protocols.py:401`) while **both implementations return `Any`**
(`app/core.py:320`, `_engine/executor.py:1510`). The new members carry the real
types, so the port's precision reaches the implementations.

## E3 · The port's home, and the framework's own front door

**Maintainer decision, 2026-09-17.** Two earlier homes were proposed and both
were wrong. This section records the third and why it is different in kind.

### What the port must reach

`AdapterPlugin` (`_types/protocols.py:90`) is the protocol every delivery
surface implements — four ship (`CliAdapter`, `TuiAdapter`,
`functualize-http`, `functualize-lambda`) plus `MCPAdapterPlugin` as an entry
point, and `app/adapters/_validation.py:30` checks it at runtime. Its setup
member is:

```python
def __call__(self, app: Any) -> None:          # ← the framework's front door
```

A port that cannot be named *there* leaves the defect at the one place the
framework defines the contract. An author who copies an existing plugin never
learns the type exists.

### Why `_app/` cannot be that home

`PluginHost`'s members return the facade objects, which live in `_app/`. So a
port housed in `_app` cannot be referenced from `_types`:

```toml
name = "Types import nothing internal"          # pyproject.toml:290
source_modules = ["functualize._types"]
forbidden_modules = [..., "functualize._app", ...]
```

**And the `TYPE_CHECKING` escape is refused, not unavailable.**
`exclude_type_checking_imports = true` (`pyproject.toml:244`) means such an
import is invisible to `import-linter` and would pass CI green. It is ruled out
by prior art: `contributor/architecture/layer-contract-blind-spot.md` §7 —
*"It is **not an exemption**. Nothing here legalizes a TYPE_CHECKING import
across a layer the contracts refuse"* — and §5 — *"A new `TYPE_CHECKING` import
is a **layer decision, not a typing convenience**. Ask what the runtime import
would be. If the answer is 'a violation', the annotation-only form is the same
violation with the gate switched off — pick a layer that can hold the type
(`_types`)."* That document measures the hole at 155 hidden imports, 8 of them
direct violations, and `1 kept / 5 broken` when the flag is flipped.

### The home: `_types/host.py`, with view protocols

`PluginHost` and five **view protocols** live in a new `src/functualize/_types/host.py`.
A view protocol describes a facade from the layer allowed to describe it:

```python
class DependencyView(Protocol):                 # _types — legal, no _app import
    def provide(self, type_: type, instance: Any, qualifier: str | None = None) -> None: ...
    def provide_named(self, name: str, instance: Any) -> None: ...
```

The concrete `DependencyFacade` already matches structurally; nothing inherits.
`AdapterPlugin.__call__(app: PluginHost)` then becomes legal.

**A new file rather than `_types/protocols.py`.** That module is already
**882 lines carrying 12 protocols**, which the dead-code audit
(`.spec/plans/dead-code-audit/SUMMARY.md`, W5) names a god module. Adding six
more would worsen a smell this repo has already diagnosed. `_types/` is 26
modules, so a sibling file is the idiomatic answer.

### The retype is inert without a door — measured

This is the part an earlier draft got wrong. Typing `AdapterPlugin.__call__`
changes **nothing** on its own, because nothing checks conformance: `validate_adapter(obj: Any)`
takes `Any` and is called from tests only, and no `: AdapterPlugin` annotation
exists anywhere in `src/`, `plugins/` or `tests/`. Probed against mypy directly:

| Case | mypy |
|---|---|
| Structural adapter, narrower `app` param, nothing accepts the protocol — **today** | **no error** |
| Same, plus one function typed `register(a: AdapterPlugin)` | **error**, naming Expected `PluginHost` vs Got `FunctualizeApp` |
| `class A(AdapterPlugin)` with a narrower param | **error** — "violates the Liskov substitution principle" |
| `class A(AdapterPlugin)` with the param unannotated | `no-untyped-def` — mypy does **not** inherit the type |

So the feature needs a **static conformance assertion** (AC-18) or the retype is
decoration that passes CI. That assertion is what makes the four adapters
currently annotated `app: FunctualizeApp` — `app/adapters/tui.py:39`,
`app/adapters/cli.py:823`, `functualize-http:371,443`,
`functualize-lambda:136` — into errors until they widen to `PluginHost`, which
is the feature working.

## F · Acceptance criteria

- **AC-1** `PluginHost` exists in **`src/functualize/_types/host.py`**, is
  `@runtime_checkable`, and is re-exported from `functualize.plugin`. Its five
  facade members return **view protocols** declared in the same module, so the
  port carries no `_app` import (§E3, `contracts.md` §1).
- **AC-1b** `uv run lint-imports` reports all **seven** contracts kept, 0 broken.
  No `TYPE_CHECKING` block is used to hide an edge (§E3; the count is seven, not
  the six `pyproject.toml:236` and `CONSTITUTION.md` still say — corrected by
  AC-21).
- **AC-2** Membership is derived from the measured hit set, not from memory: the
  members with ≥2 first-party plugin clients. Measured — `extensions` 9,
  `get_jobs` 7, `execute` 6, `gates` 5, `di` 5, `execution_engine` 5,
  `configuration` 4, `get_job` 2 — plus `hooks`, the migration target of AC-5,
  and the storage trio of AC-2b. `hook_registry` is **not** a member; neither is
  any `invoke*` method, nor `workflows` (0 clients), nor `execution_engine` (§H).
- **AC-2b** The storage members are included on measured need, not on the ≥2
  rule: `substrate` (10 sites once §E2 renames it), `install_substrate` and
  `fresh_root`. The latter two have one client each —
  `functualize-state-sqlite/_plugin.py:78,95` — and are included because
  **without them that plugin cannot adopt the port at all** (maintainer
  decision, 2026-09-17). `fresh_root` is additionally already a declared member
  of the sibling port `EngineHost` (`_types/protocols.py:421`), and both already
  exist on `FunctualizeApp`, so neither costs a facade line. `run` (1 client)
  stays excluded.
  - An earlier draft excluded `fresh_root` and deferred re-expressing its one
    client against `substrate.describe()`. That deferral is **withdrawn as
    unclosable**: `describe(key)` returns a human-readable line about one
    document (`_types/protocols.py:830`), not a joinable project root.
- **AC-3** An unmodified `FunctualizeApp` satisfies `PluginHost` both at runtime
  (`isinstance`) and **statically** (assignable to a `PluginHost` parameter).
  Both are required and neither substitutes: `@runtime_checkable` validates
  member *presence* only, never signatures.
- **AC-4** `HooksFacade.on_ready` is typed so a non-callable argument and a
  wrong-arity handler are both mypy errors, while the bound-method form and the
  bare-decorator form stay clean. `contracts.md` §2 carries the exact callable
  Protocol and the four cases it must decide.
- **AC-5** No plugin calls `hook_registry.register_global`; all four sites use
  `app.hooks.on_ready`, and the registered hooks still fire at boot.
- **AC-6** No plugin reaches a private kernel member. `app._di_registry` and
  `app._tasks` are both gone.
- **AC-7** The three dead blocks named in §A are **deleted, not re-annotated** —
  `_task_tools.py:66-76` and the `StateBackend` probe at `_plugin.py:139-148`.
  A comment or a test records that each was dead, so the deletion is not read
  later as a removed feature.
- **AC-7b** Deleting them changes no observable behaviour: the MCP task tools
  still return the in-memory `Tasks`, and ai-pydantic still resolves its
  ephemeral state backend. Proven by a test that passes before and after.
- **AC-8** Every `app` parameter in `plugins/*/src` and `src/functualize/app/adapters/`
  that receives the application is annotated `PluginHost`, not `Any` and not
  concrete `FunctualizeApp` — **44 sites** (40 `Any`, 4 `FunctualizeApp`). The
  four concrete ones are the adapters AC-18 forces to widen.
- **AC-9** A static negative test fails when a misspelled `PluginHost` member is
  used: the rule is executable, not prose.
- **AC-10** `contributor/guides/plugin-development.md:53-70` is corrected. It
  currently teaches `app: Any` **and** names two members that do not exist
  (`app.provide` → now `app.di.provide`; `app.register_plugin_command`). The
  canonical example must type-check against the port.
- **AC-11** `func scaffold`'s plugin templates emit the port, so a new plugin
  starts typed. **Both** templates:
  `_cli/scaffold/templates/plugin.py.j2:18` (`app: FunctualizeApp`) and
  `_cli/scaffold/templates/domain-plugin/_plugin.py.j2:20` (`app: Any`). The
  locator gate must match `(Any|FunctualizeApp)`, not `FunctualizeApp` alone,
  or it silently misses the second.
- **AC-13** `app.substrate` returns the substrate **in effect** (never `None`),
  and all 10 `app.execution_engine.substrate` chain sites use it — 6 in `src/`,
  4 in `plugins/`, across **8** files. `rg -c "execution_engine\.substrate"`
  returns no match.
- **AC-14** `app.install_substrate(sub)` is the write door and the
  `app.substrate = …` setter is **gone**. The late-install refusal is preserved
  and still raises `RuntimeError` naming the split brain.
- **AC-15** `EngineHost.substrate` is renamed `substrate_override`, typed
  `StoreSubstrate | None`, and `_engine/executor.py:1525`'s
  `getattr(self.host, "substrate", None)` reads the new name. No recursion:
  `app.substrate` delegates to the engine, the engine reads the override.
- **AC-16** `app.substrate` and `app.substrate_override` both carry real types
  (`StoreSubstrate`, `StoreSubstrate | None`), not `Any` — the port's declared
  precision reaches both implementations.
- **AC-17** `FunctualizeApp`'s facade budget is raised **deliberately and by
  exactly what fits**, with the two cheaper answers tried first and recorded in
  `tests/test_facade_loc_limits.py` the way the 300→302 and 302→303 raises were.
  Measured need: **+2** executable lines (**303 → 305**). Measured with the
  test's own rule — the current getter+setter is 7 executable lines
  (`app/core.py:319-339`), the three members that replace them are 9.
  - **No member is deleted to pay for this.** The dead-code audit proposed
    removing `FunctualizeApp.cache_stats` and `.domain_registry` (0 internal
    references), which would have made the raise unnecessary. Rejected
    2026-09-17: both are public members of a public class, which the audit's own
    `CONTRACT.md` excludes by design — *"public folders are stable API even if
    unreferenced internally"* — and an end user's call site is not in this
    repository. See §G.
- **AC-18** `AdapterPlugin.__call__` and `PluginWithShutdown.on_shutdown` take
  `app: PluginHost`, and a **static conformance assertion** exists so that the
  retype is enforced rather than decorative (§E3): each shipped adapter is
  statically assigned to `AdapterPlugin` in a type-checked test. The retype and
  the assertion are one criterion because the retype without the assertion is
  provably inert (§E3's table).
- **AC-19** `tests/test_public_api_surface.py` lists `PluginHost`. A new public
  name that the surface test does not know about is a name the test would fail
  on later, for the wrong reason.
- **AC-20** Verification commands are green **as written**. The plugin
  type-check is **package-local or focused**, never the aggregate
  `uv run mypy plugins/*/src` — that command reports
  **`Found 120 errors in 22 files`** on an untouched tree (missing `fastmcp`
  stubs, untyped defs, unused ignores), so an all-green claim over it is false
  and a "no new errors" claim over it has no recorded baseline.
- **AC-21** `pyproject.toml:236` and `.spec/CONSTITUTION.md` say **six**
  import-linter contracts; `grep -c '^\[\[tool.importlinter.contracts\]\]'`
  returns **7**. `contributor/architecture/codemaps/dependencies.md:25` says
  *five*. This feature adds a layer decision that cites the contracts by count,
  so it corrects them rather than adding a fourth number to the set.
- **AC-22** `PluginHost` is exercised by an example under `examples/`, per the
  rule added to `contributor/guides/adding-public-api.md` step 8 and
  `contributor/reference/public-api-example-coverage.md` (maintainer,
  2026-09-17). This feature adds the first public symbol subject to that rule,
  so it is the first to satisfy it. The example must *call* the port, not merely
  name it — an example that imports `PluginHost` and annotates a plugin
  function with it, which then registers and runs.
  - The example doubles as the port's end-to-end test: `examples/` is
    pytest-collected via `examples/conftest.py`, so this is the only AC here
    that proves the port works through a user's door rather than a test's.
  - Measured context, so the AC is not read as routine: **108 of 161** public
    symbols have no example today, and four of the six typed facades
    (`di`, `gates`, `extensions`, `configuration`) are among them. This AC
    does not fix that backlog — it declines to add to it.

- **AC-12** The three suites stay green, run separately: `tests/`, `examples/`,
  and each `plugins/*/tests` package (per the #39 handoff — they cannot be
  collected together). Plus the **second substrate pass**
  (`FUNCTUALIZE_TEST_SUBSTRATE=sqlite`), which exercises the renamed install
  path that `functualize-state-sqlite` uses.

## G · Out of scope

- `HookEvent` → `StrEnum` (§E).
- **`di.resolve(T)`** — in scope until 2026-09-17, dropped for want of a
  surviving production caller (§C).
- **Deleting any member the dead-code audit flags.** Five were considered and
  all five stay: `FunctualizeApp.cache_stats`, `FunctualizeApp.domain_registry`
  (public members of a public class, AC-17), and `HooksFacade.pre_execute`,
  `ExtensionsFacade.instrument`, `ConfigurationFacade.resolved_job_config`
  (reached through public properties — `app.hooks.pre_execute` is user-visible
  surface even though the facade class is internal). All three facade doors
  have **zero** non-`def` references in `src/`, `plugins/` or `tests/`,
  verified; that is evidence they are unused *here*, not evidence they are
  unused. The view protocols of §E3 describe only the ~10 facade methods
  plugins call, so none of these appears in a new contract either way — the
  deletions were never required by this feature.
- Removing `hook_registry` from `FunctualizeApp`'s public surface. After AC-5
  nothing outside the framework calls it, but deleting a public accessor is a
  breaking change and no criterion here needs it.
- The four public display protocols in `plugin/protocols.py:54,103,161,177`,
  which take concrete `FunctualizeApp`. They are display extensions, not
  lifecycle entry points; AC-18 covers the two lifecycle protocols only.
- `RemoteProvider`'s public namespace — entry-point based, belongs to
  `vault-sync-providers`.
- Runtime enforcement of the port in the plugin loader. It would be cheap, but
  it is a behaviour change and no concrete runtime error justifies it.
- Typing `extension_state` (`-> dict[str, Any]`). A real gap, recorded in
  `research.md`, not on the port.
- Renaming anything else in the substrate region. §E2 disambiguates **one**
  name; `StoreSubstrate`, `substrate_for_project` and the four stores keep
  theirs.
- Everything `plugin-taxonomy` owns — see §I.

## H · Decisions taken

All four questions this section carried are settled.

- **Is `execution_engine` a port member? — no** (Plan 3a, 2026-09-16). Its 5
  clients are not 5 uses. **Four** are the same two-hop *message chain*
  `app.execution_engine.substrate` (`functualize-mcp/_history_tools.py:54`,
  `_workflow_tools.py:147,162`, `functualize-tasks-local/_plugin.py:66`)
  reaching for the **resolved** substrate. Only one —
  `execution_engine.materialize_job(workflow_name)` (`_workflow_tools.py:447`)
  — genuinely wants the engine, which is 1 client and below AC-2's ≥2
  threshold. Excluded: putting it on the port would bless handing plugins the
  whole engine to serve one call site, and would fossilise the chain.
- **The substrate naming is fixed here, not deferred** (2026-09-16, §E2).
- **The storage members join the port** (2026-09-17, AC-2b).
- **The port lives in `_types/host.py` with view protocols** (2026-09-17, §E3).

**Why shortening the chain required a rename first.** `app.substrate` and
`app.execution_engine.substrate` were **two different things with one name**,
measured:

```
app.substrate             -> None               (the install slot; core.py:320)
app.execution_engine.sub  -> JsonFileSubstrate   (the resolved one; executor.py:1510)
SAME OBJECT: False
```

So the chain sites were **correct as written** — a naive shortening to
`app.substrate` would have silently handed them `None`. The front door had to be
freed before it could be used, which is what §E2 does. Kept because it is the
reason the fix is a rename and not a find-and-replace.

## I · Boundary with `plugin-taxonomy`

`.spec/features/plugin-taxonomy/` is the second feature folder on this branch.
Its §G already splits the defects; these three rows are the seam this feature's
2026-09-17 decisions created, and they are mirrored there.

**This feature lands first.** `plugin-taxonomy` `git mv`s all twelve plugin
directories; this one makes line edits inside them. An annotation survives a
move; a file list does not survive a rename. Its own §H reaches the same
conclusion.

| Site | This feature changes | `plugin-taxonomy` changes |
|---|---|---|
| `functualize-state-sqlite/_plugin.py:74-78` | the **call spelling** — `app.substrate = …` becomes `app.install_substrate(…)` (AC-14) | the **error handling** — its AC-4, stop swallowing the install failure. Applies to the new spelling. |
| `functualize-tasks-local/_plugin.py:66` | the **spelling only** — `app.execution_engine.substrate` → `app.substrate` (AC-13). Behaviour is identical: the new property returns `self.execution_engine.substrate`. | the **ordering bug** — its F4/AC-8. It survives this feature untouched, by design. This feature must not claim to have fixed it. |
| `functualize.vault_key_providers` (dead entry-point group) | nothing | owns it — its §A.1, and dead-code audit finding #3 |

One input offered to that feature's **Q2** (*which group does a substrate
register in?*): after AC-2b, `PluginHost` declares `install_substrate` and
`fresh_root`, and that pair is effectively the substrate-plugin contract. A
type-level answer to Q2 is therefore available. Recorded in its `research.md`;
the decision stays theirs.
