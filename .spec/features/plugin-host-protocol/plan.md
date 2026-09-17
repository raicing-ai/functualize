# Plan — plugin-host-protocol

**Base:** master `11d77f6`, branch `feat/plugin-host-protocol` @ `79545ef`.
**Revised 2026-09-17** after `.spec/scrutiny-reports/plugin-host-protocol-2026-09-16.md`
returned **REVISE** (6 blocking, 15 falsified claims) and two maintainer
decisions moved the design. The architecture gate was re-run; the AFTER diagram
below is the third, not a touch-up of the second.

## 0 · What the revision changed, and why

| Was | Now | Forced by |
|---|---|---|
| Port in `_app/host.py` | **`_types/host.py`** + 5 view protocols | `_types` may not import `_app`, so the framework's own `AdapterPlugin` could never name the port (scrutiny D-02) |
| `di.resolve(T)` in scope | **dropped** | Its only consumer is inside the block T1/T2 delete — no surviving production caller (DEPENDENCY-01) |
| Port omits `fresh_root` | **11 members** incl. `install_substrate`, `fresh_root` | Without them the SQLite plugin cannot adopt the port at all (INTERFACE-10) |
| Budget 303 → 306 | **303 → 305** | Re-measured: 7 lines now, 9 after (MEASUREMENT-05) |
| `uv run mypy plugins/*/src` green | **package-local / focused** | That command is already `120 errors in 22 files` (DEPENDENCY-05) |
| `on_ready` signature deferred | **specified and probed** | A behaviour table without a signature is unjudgeable (D-04) |
| — | `AdapterPlugin` retyped **+ a static conformance door** | The retype alone is provably inert; verified against mypy |

## 1 · Skills and prior art consulted

| Source | Used for |
|---|---|
| `design-patterns-refactoring` (user-level, Refactoring.Guru ch31–37) | The smell names below. The in-repo skill has none — see `.claude/rules/spec-workflow.md`. |
| `python-design-patterns` (in-repo) | KISS, *delete before abstracting* (item 8), composition over inheritance |
| `.spec/CONSTITUTION.md` → *Ports*, *Forbidden Patterns* | `@runtime_checkable`, no ABC, no shims |
| `contributor/architecture/layer-contract-blind-spot.md` | **§7 refuses the `TYPE_CHECKING` escape** — the decisive prior art for §3 |
| `contributor/guides/adding-public-api.md`, `adding-internal-module.md` | The bookkeeping T12/T13 were missing |
| `contributor/reference/public-api-example-coverage.md` | New this feature (AC-22) |
| `contributor/architecture/codemaps/*` | Layer vocabulary; **contradiction found** — see *Surviving smells* #5 |
| ADR-020 (`EngineHost`), ADR-022 (storage is a substrate) | The port's precedent, and why three paths are dead |
| `.spec/plans/dead-code-audit/SUMMARY.md` | Checked for overlap; **nothing folded in** — see §7 |

## 2 · BEFORE

```
                         PUBLIC
  ┌──────────────────────────────────────────────────────────────────┐
  │ functualize.plugin/__init__.py     re-exports 11 of 12 lines     │
  │   └── plugin/protocols.py    10 display/extension protocols      │
  │ functualize.app/adapters/    CliAdapter, TuiAdapter              │
  │   └── __call__(app: FunctualizeApp)  ← concrete, 2 sites         │
  └───────────────────┬──────────────────────────────────────────────┘
                      │ imports
  ┌───────────────────▼──────────── _app  (composition root) ────────┐
  │ app/core.py :71  FunctualizeApp     44 public members, 303 LOC   │
  │   ├ di ──────────► _app/di_facade.py        provide ×3, NO read  │
  │   ├ extensions ──► _app/extensions_facade.py         12 methods  │
  │   ├ configuration► _app/configuration_facade.py                  │
  │   ├ gates ───────► _app/gates_facade.py               3 methods  │
  │   ├ hooks ───────► _app/hooks_facade.py              15 methods  │
  │   ├ hook_registry──► _events/hooks.py  7 methods, 4 are invoke*  │
  │   ├ substrate      getter :320 → None │ setter :334              │
  │   └ execution_engine ─► _engine/executor.py                      │
  └───────────────────┬──────────────────────────────────────────────┘
                      │
  ┌───────────────────▼──────────── _types  (stdlib only) ───────────┐
  │ protocols.py  882 LOC, 12 protocols            ← god module (W5) │
  │   ├ EngineHost :332    .substrate :401  .fresh_root :421         │
  │   ├ AdapterPlugin :90   __call__(app: Any)   ← THE FRONT DOOR    │
  │   ├ PluginWithShutdown :124  on_shutdown(app: Any)               │
  │   └ StoreSubstrate :713                                          │
  └──────────────────────────────────────────────────────────────────┘

  plugins/*/src  ── 44 `app` params: 40 Any, 4 FunctualizeApp ────────
    ├ 4× app.hook_registry.register_global(APP_READY, …)   (lending)
    ├ 10× app.execution_engine.substrate                (message chain)
    ├ 1× app._di_registry.resolve(...)      DEAD — guard raises
    └ 2× hasattr(app,'resolve') / app._tasks   DEAD — both False
```

**Smells the BEFORE already carries** — catalogue names, with the symbol each
lives on:

| Smell (ch) | Where | Evidence |
|---|---|---|
| **Incomplete Library Class** (37) | `DependencyFacade` | Write-only: `provide`/`provide_factory`/`provide_named`, no read. Two plugins independently reached past it. *This is the root cause; the wrong annotation is a symptom.* |
| **Message Chains** (36) | `app.execution_engine.substrate` | 10 sites / 8 files, 6 inside `src/`. Core's own idiom, not a plugin wart. |
| **Inappropriate Intimacy** (36) | `app._di_registry`, `app._tasks` | Plugins reaching kernel privates; concrete `FunctualizeApp` legitimises it |
| **Dead Code** (35) | `_task_tools.py:66-76`, `_plugin.py:139-148` | `hasattr` → False; `import functualize_state` → ImportError |
| **Primitive Obsession** (32) | 40 `app: Any` params | `Any` as a stand-in for a type that does not exist yet |
| **Divergent Change** (34) | `plugin/protocols.py` | Why the port is *not* homed there |
| **God Module** | `_types/protocols.py` | 882 LOC / 12 protocols (dead-code audit W5) — why the port is not homed there either |

## 3 · AFTER

```
                         PUBLIC
  ┌──────────────────────────────────────────────────────────────────┐
  │ functualize.plugin/__init__.py                                   │
  │   └── PluginHost ◄── re-export from _types/host.py  (legal)      │
  │ examples/…/plugin_host/            AC-22: calls the port         │
  │ functualize.app/adapters/  __call__(app: PluginHost)  ← widened  │
  └───────────────────┬──────────────────────────────────────────────┘
                      │ imports (public → internal: the house idiom)
  ┌───────────────────▼──────────── _app  (composition root) ────────┐
  │ app/core.py  FunctualizeApp   46 members, 305 LOC (+2, argued)   │
  │   ├ substrate ──────────► self.execution_engine.substrate        │
  │   │                        (IN EFFECT, never None — 10 sites)    │
  │   ├ install_substrate() ─► _app/impl.py:1546  (guard preserved)  │
  │   ├ substrate_override ──► self._substrate  (what the engine asks)│
  │   ├ fresh_root            unchanged, now named by BOTH ports     │
  │   └ the five facades      unchanged; they now *satisfy* views    │
  │        │                            ▲ structural, nothing inherits│
  └────────┼────────────────────────────┼───────────────────────────-┘
           │ implements                 │ described by
  ┌────────▼────────────────────────────┼──── _types (stdlib only) ──┐
  │ host.py   ◄── NEW MODULE            │                            │
  │   PluginHost         11 members ────┘                            │
  │     ├ di ───────────► DependencyView      2 of 3                 │
  │     ├ extensions ──► ExtensionsView       4 of 12                │
  │     ├ configuration► ConfigurationView    1                      │
  │     ├ gates ───────► GatesView            2 of 3                 │
  │     ├ hooks ───────► HooksView            1 of 15  (on_ready)    │
  │     ├ get_jobs / get_job / execute                               │
  │     └ substrate / install_substrate / fresh_root                 │
  │   OnReadyHandler = Callable[[PluginHost], None]                  │
  │                                                                  │
  │ protocols.py   (882 LOC, unchanged size — port did NOT go here)  │
  │   ├ EngineHost      .substrate → .substrate_override  (renamed)  │
  │   ├ AdapterPlugin        __call__(app: PluginHost)     ◄── FIXED │
  │   └ PluginWithShutdown   on_shutdown(app: PluginHost)  ◄── FIXED │
  └──────────────────────────────────────────────────────────────────┘
           ▲
           │ static conformance door — without this the retype is inert
  ┌────────┴─────────────────────────────────────────────────────────┐
  │ tests/spec/test_adapters_conform_to_the_port.py                  │
  │   _: AdapterPlugin = CliAdapter(...)   ← mypy-checked assignment  │
  └──────────────────────────────────────────────────────────────────┘

  plugins/*/src  ── 44 `app` params, all PluginHost ──────────────────
    ├ 4× app.hooks.on_ready(self._on_app_ready)     (asks, no lending)
    ├ 10× app.substrate                              (chain collapsed)
    ├ 1× app.install_substrate(sub)                  (write door)
    └ the two dead probe blocks: DELETED
```

**Layer legality of every new edge** — checked against the **seven**
`[[tool.importlinter.contracts]]`, not assumed:

| Edge | Verdict | Rule |
|---|---|---|
| `_types.host → _types.protocols` | legal | intra-package; `_types` may reference itself |
| `_types.host → stdlib` (`Path`, `Callable`) | legal | `_types` is stdlib-only and stays so |
| `_types.protocols → _types.host` (to type `AdapterPlugin`) | legal | intra-package |
| `functualize.plugin → _types.host` | legal | the existing re-export idiom; *Internal never imports public* points the other way |
| `_types → _app` | **would be forbidden** | not taken — this is the whole reason for the view protocols |
| `_types → _app` under `TYPE_CHECKING` | **refused** | invisible to the gate, forbidden by `layer-contract-blind-spot.md` §7 |
| `app.adapters → _types.host` | legal | public may import internal |

Baseline is `7 kept, 0 broken`; AC-1b requires it unchanged.

## 4 · Candidate AFTERs rejected

| # | Candidate | Rejected because |
|---|---|---|
| 1 | Port in `plugin/protocols.py` | *Divergent change* — that file holds 10 display protocols |
| 2 | Port in `_app/host.py` | Legal, but `AdapterPlugin` in `_types` can never name it. Leaves the framework's front door saying `Any`. |
| 3 | Port in `_types/protocols.py` | Worsens a god module the audit already named (882 LOC / 12 protocols) |
| 4 | `_types → _app` under `TYPE_CHECKING` | Prior art refuses it (§3). Would pass CI, which is what makes it worse, not better. |
| 5 | **Two tiers** — 6-member port in `_types`, 11-member in `_app` | **Disproved with mypy.** Adapters use facades inside `__call__` (`functualize-mcp/_plugin.py:88`). A protocol promising a 6-member host cannot be implemented by a method demanding the 11-member one — parameter contravariance. Adapters would be worse off than with `Any`. |
| 6 | Mirror **all 33** facade methods into `_types` | No narrower-than-reality problem, but the facades' signatures written twice, docstrings split from declarations, and every new facade method a two-layer change |
| 7 | `GateResolverView` mirror, to avoid one `Any` | Trades one `Any` on one param of a 2-site method for a sixth mirror protocol — deepens the smell it dodges |
| 8 | Re-home `GateResolver` into `_types` | Correct by the *Ports* rule, but **86 references / 22 files**, exported from `functualize/__init__.py` and asserted in `test_public_api_surface.py`. A public-API feature of its own. |
| 9 | Delete `cache_stats` / `domain_registry` to pay the budget | Public members of a public class; the audit's own `CONTRACT.md` excludes them. See §7. |
| 10 | Keep `hook_registry` on the port | Hands every plugin four `invoke*` methods — the "lending" `EngineHost` forbids |
| 11 | ABC instead of Protocol | `CONSTITUTION.md` → *Ports* forbids it; would force plugin authors to inherit |
| 12 | Runtime enforcement in the plugin loader | Behaviour change, no concrete error justifies it |

## 5 · Approach — deletions first, then names, then the port

1. **Delete** the two dead blocks (T1, T2). Nothing downstream should be shaped
   around code that cannot run. This is *delete before abstracting* applied to
   the feature's own ordering.
2. **Rename** the substrate trio (T3) before anything declares `substrate`
   non-optional — the port's `-> StoreSubstrate` is only true afterwards.
3. **Collapse** the 10 chain sites onto the new front door (T4).
4. **Retype** `on_ready` (T5) *before* migrating callers to it, so the migration
   lands on the safer signature rather than widening then narrowing.
5. **Migrate** the four `APP_READY` registrations (T6).
6. **Write** the port and its views (T7), then re-export and cover the public
   surface test (T8).
7. **Retype** the lifecycle protocols and add the conformance door (T9) — the
   door is in the same task as the retype because the retype without it is inert.
8. **Widen** the four concrete adapters (T10), which T9 turns into errors.
9. **Annotate** the 40 `Any` sites (T11).
10. **Prove** the rules are executable, not prose (T12), **document** (T13),
    **scaffold** (T14), **example** (T15), then **verify** (T16).

## 6 · Risks

| Risk | Handling |
|---|---|
| Widening `CliAdapter.__call__` to `PluginHost` needs members the port lacks — `cli.py:823` has a large body | **Measure before writing T10.** If it needs a member nothing else wants, the port does not grow: `CliAdapter` is core, not a plugin, and may keep `FunctualizeApp` with the conformance assertion scoped to the plugin adapters. Decide with data, and record it. |
| The view protocols are narrower than the facades — an 11th method blocks a plugin | Declared smell #1. The fix is one line in `_types/host.py`; the cost is that it is a two-layer change. |
| `graphify-out/graph.json` is stale — it contains neither `EngineHost` nor `DependencyFacade` | Used for discovery only. Every claim here is serena- or `rg`-confirmed on the live worktree. |
| `plugin-taxonomy` `git mv`s all 12 plugin directories | This feature lands first (`spec.md` §I). Its file lists are paths. |
| The `examples/` suite is separate from `tests/` | AC-12 runs three suites separately, plus the `FUNCTUALIZE_TEST_SUBSTRATE=sqlite` pass |
| `install_substrate` on the port lets any plugin install storage | Not a widening: today every plugin is `app: Any` and can already call it. The port narrows from *anything* to *these eleven*. |
| A wrong-arity `on_ready` handler today fails at `APP_READY`, the hardest place to attribute | That is the defect T5 fixes; the probe in `contracts.md` §5 shows the new type catches it at edit time |

## 7 · Overlap with the dead-code audit — nothing folded in

`.spec/plans/dead-code-audit/SUMMARY.md` was checked against this feature's file
set. Five findings touch files this feature opens, and **all five are declined**:

| Audit | Member | Declined because |
|---|---|---|
| W4 | `FunctualizeApp.cache_stats`, `.domain_registry` | Public members of a public class. The audit's `CONTRACT.md` excludes them by design; serena's zero is not evidence for public surface. |
| #7/W1 | `HooksFacade.pre_execute` | Reached via the public `app.hooks` property — same category, merely undocumented |
| W1 | `ExtensionsFacade.instrument` | Same |
| W1 | `ConfigurationFacade.resolved_job_config` | Same |

All three facade doors do have **zero non-`def` references** in `src/`,
`plugins/` and `tests/` — verified. That is evidence they are unused *here*, not
that they are unused.

**And the argument that they were load-bearing for this feature was wrong.** It
ran: the view protocols would enshrine dead doors in a new public contract.
They would not — the views describe the ~10 methods plugins call, so the other
23 are excluded whether alive or dead. No deletion was ever required.

**Two corrections owed back to the audit:**

1. **C5 is mis-attributed.** It records `WiringFacade.with_plugin_config` as
   *"NOT DEAD (in-flight) — this branch's plugin-host-protocol feature; revisit
   at feature completion."* This feature never touches it. It is
   `RunContext.wiring.with_plugin_config` (`_engine/capabilities/wiring_facade.py:61`)
   with ~20 test references and docstring citations at `_types/redaction.py:106`
   and `runcontext.py:218`. Not blocked on this feature; re-adjudicate on its
   own merits.
2. **The rule that would have prevented the `cache_stats` finding now exists** —
   `contributor/reference/public-api-example-coverage.md` (maintainer,
   2026-09-17). Once every public symbol has an example caller, zero references
   means *dead* again for public API too. Measured backlog: **108 of 161**.

Finding **#3** (`functualize.vault_key_providers` declared and never read) is
real and HIGH, and belongs to `plugin-taxonomy` (its §A.1). Not touched here.

## 8 · Surviving smells

Five. None is on `CONSTITUTION.md` → *Forbidden Patterns*.

**#1 · Incomplete Library Class (ch37) — the view protocols describe 10 of 33+
facade methods.** `_types/host.py`. Deliberate: membership is measured from
`plugins/*/src`, and `spec.md` AC-2 forbids speculative members. The cost is a
standing obligation — a plugin that later needs an 11th facade method needs a
one-line addition in `_types/host.py` *before* it can call it, and that is a
two-layer change. Accepted because the alternative (mirror all 33) writes the
facades twice and still has the obligation for anything new.
**Needs maintainer review: NO** — the maintainer chose this shape on
2026-09-17 with the 10-of-33 figure in front of them.

**#2 · Primitive Obsession (ch32) — one surviving `Any`.**
`GatesView.register_gate_strategy(name: str, resolver: Any)`. The live type is
`GateResolver`, a `@runtime_checkable Protocol` in `_gate/_resolver.py:19`, and
`_types` may not import `_gate`. Re-homing it is the correct fix and costs 86
references across 22 files including a public export — priced in §4 #8.
**Needs maintainer review: NO**, but it is the strongest candidate for the
follow-up feature.

**#3 · Raised ceiling — `FunctualizeApp` 303 → 305.** A ceiling raised never
falls on its own. Argued in `contracts.md` §4d with the two cheaper answers
tried first and the third (deleting public members) refused. The next addition
argues against 305.
**Needs maintainer review: NO** — raised deliberately, exactly to fit.

**#4 · `hook_registry` stays public on `FunctualizeApp`.** After T6 nothing
outside the framework calls it, but deleting a public accessor is a breaking
change and no criterion needs it (`spec.md` §G). It remains a door through
which a plugin can fire lifecycle events.
**Needs maintainer review: NO** — explicitly out of scope, recorded.

**#5 · Codemap contradiction — the contract count.** `pyproject.toml:236` and
`.spec/CONSTITUTION.md` say **six** import-linter contracts;
`contributor/architecture/codemaps/dependencies.md:25` says **five**; there are
**seven**. This feature's layer argument cites them by count, so AC-21 corrects
all three rather than adding a fourth number. The deeper drift —
`codemaps/overview.md` claiming 13 plugins including the retired `state` SDK —
belongs to `/sync-docs`.
**Needs maintainer review: NO** — AC-21 fixes what this feature relies on.

**Explicitly not a surviving smell any more:** the `app.execution_engine.substrate`
message chain. The second plan listed it as accepted; the maintainer overruled
that on 2026-09-16 and T3/T4 fix it. Recorded here because a smell that moves
from *accepted* to *fixed* should be visible as a decision, not silently absent.
