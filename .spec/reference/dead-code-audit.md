<!-- Copied from Confluence page 3637249: Research — Codebase Extensibility & Hygiene Audit (2026-09-16). Historical snapshot; revalidate findings against the live repository. -->

| Field | Value |
| --- | --- |
| Document type | Research |
| Status | Accepted |
| Authority | Historical — point-in-time evidence at commit `79545ef` |
| Owner | Mohammad Hakim Adiprasetya |
| Product | Functualize |
| Last reviewed | 2026-09-17 |
| Review by | Re-run after a material architecture change or before the next major cleanup initiative |
| Related work | [Repository](https://github.com/raicing-ai/functualize); branch `feat/plugin-host-protocol`; source bundle `.spec/plans/dead-code-audit/` |

> This page preserves a completed audit snapshot. The repository remains authoritative for current implementation. Findings should be revalidated against the live codebase before delivery work is committed.

**Question this research informs:** Which dead-code, migration-cleanup, and structural-hygiene opportunities should Functualize prioritize, and which apparent candidates are intentional or still in flight?

Repo: functualize @ `feat/plugin-host-protocol`, commit `79545ef`. Date: 2026-09-16.
Method: orchestrator + 11 deepseek-v4-flash subagents + 1 aggregation pass; serena + zvec-grep +
graphify as evidence backbone; design-patterns KB for smell→technique routing. Read-only.

## Headline numbers

| Metric | Count |
| --- | --- |
| Unique findings (deduplicated) | **155** (108 high / 24 medium / 9 low / 1 disputed / 13 info) |
| Findings confirmed by ≥2 independent agents | 61 |
| Conflicts adjudicated by orchestrator | 9 |
| Rejected candidates (documented with reasons) | 160+ across reports |
| Mechanical raw signal triaged | 774 vulture hits, 280 ruff deep-rule hits, 8,608 graph nodes |

## Verdict table — top 20, post-vetting

| # | Finding | Cat | Evidence (verified) | Impact | Effort | Risk | Conf | Technique |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `@app.hooks.run_middleware` silently never executes — registry write-only | dead | boot.py:350/351 dual objects; executor takes chain only; 0 readers of `_middleware_registry` | HIGH: public API no-op | S | low | high | wire consumer or delete door (ch35) |
| 2 | `ToolScope.approval_*` documented safety flag, no enforcer | dead | `functualize-ai/_tool_scope.py:193`; translator drops it | HIGH: user contract | M | low | high | wire or remove |
| 3 | `functualize.vault_key_providers` entry-point group declared, never read | dead | pyproject.toml:49; `resolve_vault_key` hardcodes defaults | HIGH: 3rd-party contract | S | low | high | wire resolve or drop group |
| 4 | `[ai] budget_usd`/`timeout_seconds` config ignored (docs ai.md:138) | dead | AIConfig→AILimits flow absent; only tests construct limits | HIGH: spend limits silent | M | low | high | feed config into limits |
| 5 | `[cli] output/show_timing` + 5 `tui.*` keys unread | dead | W2 config census | MED: user contract | S | low | high | delete keys or implement |
| 6 | Dead TUI generation \~1,905 LOC (`ui/fullscreen/`, EditableTable, PathFieldEditor, focus\_state, panel\_ring\_controller, config\_target\_discovery, type\_hint\_formatter) | dead | AST import-closure from inline\_tui entry + serena | HIGH: bulk deletion | M | low | high | delete + migrate pinned tests (P6) |
| 7 | `HooksFacade.pre_execute` door unwired (pipeline live) | dead | M1+W1+SYN agree | MED | S | low | high | delete decorator |
| 8 | Migration shim layer: settings\_validator, resolved\_value\_compat, `_engine/errors.py`, `_engine/result.py`, 3-hop runcontext chain, hierarchy re-exports, 5 stale `state_format` citations | migration | W1/W2/W3/W5 agree; d850dfb deletion confirmed | MED | S-M | low | high | Inline Class / Remove Middle Man (ch39); clean cutover |
| 9 | Decorative re-export facades (\~110 lines, 8 files): `tui/__init__` 34 syms + side effect, completions, data, panels, `_gate`, `_app` | dead | W8 AST export graph, 0 through-importers | MED | S | low | high | delete layer |
| 10 | `register_builtin_commands` 2,496-line god function | smell | AST long-method census | HIGH maintenance | L | med | high | Extract Method per command family (ch38) |
| 11 | `FunctualizeInlineTUI` god class 2,753 LOC / 127 methods (graph: 199 edges) | smell | W3 + M3 god-node | HIGH maintenance | L | med | high | Extract Class per panel domain (ch39) |
| 12 | `app/utils.py` god module 2,380 LOC, 130 `__all__` (93 re-exports), 5 sections | smell | W4 | HIGH maintenance | L | med | high | Extract Class ×3 behind facade |
| 13 | `JobRegistry` three dead doors: `create_job_command` (raises always), `scan_and_register`, `extract_descriptors` test-only; `registry.py:509` discards dependency hash | dead | W6 serena; method body verified | MED | S | low | high | shrink to exercised door (P9) |
| 14 | `boot.py` consolidation: duplicated 30-line agent-step comment ×2 paths, duplicated scaffolding, `boot_standard` 402 lines | migration+smell | W1+M2 agree | MED | M | low | high | Extract Method; dedupe comment (ch35) |
| 15 | Write-only telemetry: `get_tool_calls`, `_write_label`, cache `generated_at`, `JobDescriptor.dependencies`, vault audit ledger | dead | W5/W6 agree | MED | S | low | high | delete writer or build reader |
| 16 | Docs-lie cluster (8 one-liners): `TUI_STARTED` never emitted (git pickaxe), core.py phantom methods, `build_routes` docstring, `Setting.cli_flag/phase` stale claims, PRESET\_NAMES/PresetNotFoundError | docs/dead | W1/W2/W5 verified | LOW-MED each | S | none | high | fix claim or code |
| 17 | MCP stale core twins `_bound_values`/`_resolve_bound` + 4× `_error_response` byte-identical | duplication | W7 difflib + serena | MED | S | low | high | delegate to core; extract shared helper |
| 18 | Bitwarden `SecretsManagerProvider` misnamed from AWS scaffold — name collision when both load | migration | W7 | MED correctness | S | low | high | lsp rename |
| 19 | Speculative machinery \~600 LOC: 5 unregistered transforms, `pre_filter.py`, `cli_adapter.py` (CLI tier never carries values), `hierarchy_errors.py`, ini template, `create_project` legacy path, orphan `config.base.ini.j2` | dead | W6/W8 serena + render-scan | MED | S | low | high | delete (ch35) |
| 20 | Engine/events unwired-surface sweep: 12 dead symbols (A1-001..025) incl. `ExecutionContext` twins, `forget_live_step_values`, `OperationPoint`, `RunContextMetadata`, `instrument_point` module | dead | M1+W1 serena | MED cumulative | M | low | high | coherent deletion PR |

## Conflict adjudications (orchestrator, code-verified)

| # | Symbol | Verdict | Basis |
| --- | --- | --- | --- |
| C1 | `RunContext.set_result_metadata` | **ALIVE** — M1 rejected | documented API (run-context.md:502); executor harvests `rc._result_metadata` |
| C2 | `InteractivityConfig` | **DEAD** — W6 upheld | zero refs incl. docs/contributor (my grep) |
| C3 | `NormalizingGroup.format_commands` | **ALIVE** — M1 FP | click `Group.format_options` dispatches it (verified vs click source) |
| C4 | `apply_overrides_to_targets` | **DEAD** — W2/W8 upheld | only refs are def + re-export; re-export ≠ caller |
| C5 | `WiringFacade.with_plugin_config` | **NOT DEAD (in-flight)** | this branch's plugin-host-protocol feature; revisit at feature completion |
| C6 | `JobRegistry.create_job_command` | **PROD-DEAD** — W6 upheld | both prod construction sites pass no factory; method can only raise |
| C7 | `_events/catalog.py` EventCatalog | **DUP SMELL** (not "dead module") | M1/M3/W1 converge; severity not verdict |
| C8 | `declared_job` / `parse_pep723_deps` | **TEST-ONLY** | fold into test helpers or delete; maintainer call |
| C9 | `SessionState` placeholder | **SMELL** — exported empty placeholder in stable API | flesh out or unexport |

## Cross-wave patterns (the systemic story)

1. **Registered-but-never-consumed** (9 sites) — the repo's signature failure mode; two variants break *user* contracts: silent no-op decorators (#1, #7) and set-but-ignored knobs (#3, #4, #5).
2. **Forked duplicates left by finished migrations** (7 site families + 7 standing shims).
3. **God units at every scale** — function (2,496 L), class (2,753 L/127 m), module (2,380 L), plus 9 long methods \>130 L.
4. **Cross-plugin duplication** — shared-SDK extraction candidate (`functualize-plugin-sdk`).
5. **Docs/state that lie** — 8 one-liners.
6. **Test-pinned corpses** (A1) — \~6 test files pin superseded implementations; deletion plans must migrate them or the code returns.
7. **Decorative re-export layers** (A1) — one uniform fix.
8. **Three-doors-one-used registries** (A1) — JobRegistry, PluginConfigRegistry, GateRegistry, DIRegistry, DisplayRing.
9. **Live twins** (A1) — two config resolvers, two scaffold paths + drifted templates, two validation tables.

## What was NOT audited / known limits

- `tests/` suite itself (only as evidence for/against prod code), `skills/`+`.agents/skills/` prose (covered by `tests/skills/`), plugin `tests/` dirs.
- graphify graph was 8 days stale — used for discovery only; every claim was serena/rg-confirmed on the live worktree.
- Baseline before audit: ruff clean; mypy 8 pre-existing errors in 2 files (not audit findings).
- W6 agent crashed post-evidence pre-report; recovered from its transcript with 6 borderline claims re-verified against live code.

## Per-agent results (copied verbatim from each agent's return)

### M1Vulture — vulture sweep (62 confirmed dead)

Raw hits conf 80: 95 (91 test-mock params; 4 non-test FP noise); conf 60: 679 (430 distinct names). After whitelisting FP classes (Textual hooks, click commands, protocol members, `__all__`), 127 symbols resolved via serena find\_referencing\_symbols + word-boundary negatives. **62 confirmed dead** (some test-only, marked medium): PresetNotFoundError never raised; SmartBar.RequestExecute never posted; HooksFacade.pre\_execute wired to nothing; FunctualizeApp.cache\_stats/.domain\_registry never called; DisplaySlot.update\_cwd/update\_job/set\_textual\_app/unregister\_display unreachable; EditableTable set\_columns/set\_rows/update\_row/is\_editing unused; Ring model methods, PanelRingState/ThemeState never instantiated; ResourceLocator.when\_env/resolve\_first\_candidate test-only; ExecutionContext.is\_blocked/set\_result\_metadata superseded. 66 verified rejects + \~410 class-skips.

### M2Ruff — ruff deep-rule sweep (280 hits)

`ruff check src/ plugins/ --select ERA,ARG,F401,F841,PIE,RET,SIM,B,C4,PLW,TD,FIX` (all codes accepted): 280 hits / 132 files / 19 rules. Dominant: ARG002 162, ARG001 24, RET505 17, PIE790 13, ERA001 13, PLW0603 11, RET504 10. F401/F841/TD/FIX/SIM/B zero. Four genuinely dead params (builtins.py:430, main.py:1515, \_cli/config.py:374, main.py:473); duplicated commented AgentStep block (boot.py:382+598); placeholder stub plugin/protocols.py:36; three PLW2901 loop-overwrite hits flagged as possible bugs. \~120 ARG002 hits classified by-design noise.

### M3Graph — graphify orphan hunt (8 confirmed orphans)

Graph: 8,608 nodes / 17,052 edges (95% EXTRACTED), commit 78d9ff4 2026-09-07, \~9 days stale. Structural in-degree over EXTRACTED edges, top-30 candidates live-confirmed via serena+rg. Confirmed: WiringFacade.with\_plugin\_config (test-only; RunContext twin removed in d850dfb), FocusState duplicate FSM, PanelRingController, declared\_job+parse\_pep723\_deps, resolve\_first\_candidate, \_handle\_unknown, func\_settings registry-mutation helpers ×4, AppStateKeys TypedDict. God nodes: FunctualizeApp (214 edges) and FunctualizeInlineTUI (199) flagged god-object; 8 others cohesive hubs. \~40 rejected with reasons; stale-graph notes recorded (\_migrations.py ghost).

### W1Engine — \_app/\_engine/\_events/\_gate (12 dead, 6 migration, 13 smells)

17,303 LOC (assignment slice incl. \_engine). Every dead claim serena `{}` + repo-wide negative. Dead: AppStateKeys, JobExecutionEngine.forget\_live\_step\_values, ExecutionContext.is\_blocked/.set\_result\_metadata, FrontierWalk.completed\_steps, HookRegistry.has\_callbacks, OperationPoint, ConfigurationFacade.resolved\_job\_config, HooksFacade.pre\_execute, ExtensionsFacade.instrument, RunContextMetadata, HookEvent.TUI\_STARTED (never emitted in any commit since v0.1.0, git pickaxe). 15 test-only rows (GateRegistry getters, instrument\_point module, CliPromptExecutor — several rejected as young/documented job-author API). Migration: duplicated agent-step comment in both boot paths, \_engine/errors.py+result.py shims, orphaned EventCatalog, half-dead \_obs\_types. Smells: boot\_standard 402 L, \_execute\_lifecycle 361 L/16 params, WiredInvoke.**call** 197, impl.py 1,571 L god module, JobExecutionEngine god class, GateRegistry mixed concerns.

### W2CLI — \_cli minus tui (24 findings)

register\_builtin\_commands 2,496-line god function (builtins.py:687); 5 duplicated FunctualizeApp boot preambles in main.py (311/538/1216/1340/1695); ScriptMetadata.skill parsed-not-consumed TRANSITIONAL (pep723.py:72,142); dead param file\_path (main.py:1515); 6 config keys with no consumer (cli.output, cli.show\_timing, 4× tui.\*); compat shims settings\_validator.py + resolved\_value\_compat.py; TRANSITIONAL residue dispatch.py:87/196; apply\_overrides\_to\_targets documented-but-unwired; \_handle\_unknown + pep723 wrappers test-only. Method: serena absolute-path, symbols overview ×8 files, AST long-method census (21 \>80 L).

### W3TUI — tui/ + ui/ (28 findings, \~1,905 LOC dead)

ui/fullscreen/ (431 LOC) fully orphaned from orchestrator/surface stack; EditableTable (406), PathFieldEditor (390), type\_hint\_formatter (118), config\_target\_discovery (148), panel\_ring\_controller (150), models/focus\_state.py (206) dead in prod, kept alive by tui/**init** re-exports + own tests; SmartBar.RequestExecute never posted; ConfigTablePanel.apply\_source\_edit + SourceChanged unreachable; ShortcutSaveModal messages duplicated; DisplaySlot dead API cluster + DisplayRing nav; god class FunctualizeInlineTUI 2,753 LOC/127 methods/22+ collaborators; 9 long methods \>80 L (SmartBar.evaluate 218, build\_command\_panels 290); \_engine shell logic duplicated in shell\_mode; settings\_validator.py finished-migration shim still standing.

### W4Public — public API folders (18 findings)

FunctualizeApp.cache\_stats (core.py:601) + .domain\_registry (core.py:387) — serena 0 refs; \_convention\_subdir\_name (utils.py:408) def-only, mapping dict duplicated inline at utils.py:843; **MiddlewareRegistry write-only** — @app.hooks.run\_middleware registers into a registry nothing reads (executor runs \_execution\_middleware\_chain); app/utils.py god module 2,380 LOC/130 **all**/5 sections; auto\_discover 192 L with duplicated search\_ancestors branches; CliAdapter.\_register\_callback 211 L; FunctualizeApp 712 L vs 300 cap; runcontext 3-hop shim chain; builtins.py:1754 backdoor-imports app.\_workflow\_control.reclaim\_scope; SessionState exported empty placeholder; core.py docstring advertises nonexistent methods. Rejected notable: NormalizingGroup.format\_commands (click dispatches), resolve\_effective\_directories (exported → low-conf).

### W5Primitives — \_primitives + \_types (33 findings)

Dead (22): ResourceLocator dead features (when\_env + env\_gate, resolve\_first\_candidate, introspect/LocateResult, write-only \_write\_label); primitives MiddlewareChain fully unreferenced (engine forked ExecutionMiddlewareChain); ScopeStore.check\_scope\_generation, get\_tool\_calls (write-only audit trail), FreshStore.delete\_fingerprint/clear\_session, RunStore.recent\_runs, DIRegistry.available\_qualifiers/is\_frozen, fingerprint.compute\_declaration\_hash/FINGERPRINT\_METHODS, FRESH\_MODES, 3 ×\_FILENAME constants shadowed by substrate path\_for, WorkflowShape.gate\_names/step\_names, PromptResponse.was\_timeout/is\_user\_input, AppSettingsSchema.section\_in\_file, NodeKind.PLUGIN/GROUP. Migration (4): five files cite deleted \_primitives/state\_format.py (d850dfb); TRANSITIONAL dead fields AgentStepResult.tool\_calls, AgentStepContext.inputs; Setting.cli\_flag/phase docstrings stale. Smells (7): \_types/protocols.py god module (14 ports, 882 L), ScopeStore god class (923 L/\~45 m), middleware duplication, PromptRequest 6 never-read fields, JobPhase enum shadowed by TypedDict. Store/format pairs mostly clean; real drift inside pairs; recurring "write-only auditor" pattern. 20 rejected with evidence.

### W6Infra — \_discovery + \_config + \_plugins (26 findings; crashed pre-report, recovered)

Dead (18): registry.create\_job\_command production-dead (boot never injects cli\_wiring\_factory); scan\_and\_register/extract\_descriptors test-only; registry.py:509 discards extract\_first\_level\_dependencies result; ResolutionChain.introspect exact alias of resolve (test-only); CliSource always constructed with {} in prod — the never-resolving tier is CLI, not remote; \_config/cli\_adapter.py zero production callers; ResolutionPipeline.transform\_count unused; transforms GroupByModuleTransform/Identity/GroupFilter/Visibility production-unregistered; RemoteSource, interactivity\_backend, plugin\_for\_section, ChildPathError, get\_default\_pre\_filter confirmed 0-ref on recovery. Migration (2), smells (6): \_load\_cache \>80 L, CachedDirectoryScanProvider god-class shape, plus 10 rejected with reasons.

### W7Plugins — all 12 plugins (24 findings)

ToolScope approval\_required/requires\_approval/approval\_gate declared via documented API, enforced by no consumer (translator drops it); MCP \_workflow\_tools.py:435 \_bound\_values + :400 \_resolve\_bound stale copies of core app/\_workflow\_control.py (production delegates to call\_gate\_tool); \_error\_response byte-identical 4× in MCP tool modules; AIConfig.budget\_usd registered but read by nothing; HttpServerCore.build\_routes zero prod callers, docstring falsely claims internal use; Bitwarden SecretsManagerProvider misnamed from AWS scaffold, collides with real AWS class; PydanticAI.run\_agent\_loop/run\_with\_history prod-dead; 23× **name**/**qualname**/**doc** triple = decorator candidate; \_metadata/\_events/\_errors template family \~0.96 similarity AI↔Tasks SDKs; flow-viz self-documented unreachable lifecycle branch. Rejected 19 (RemoteProvider dispatch, substrate port method, Textual dispatch, MCPConfig keys all consumed).

### W8CrossAPI — entry points / re-exports / scaffold (6 findings)

templates/config.base.ini.j2 orphan template (ADR-007 made TOML only); ScaffoldGenerator.create\_project legacy pre-registry path (tests only) pulling root templates; **functualize.vault\_key\_providers entry-point group declared + documented but never read** — resolve\_vault\_key hardcodes default\_providers(); \_gate/**init** ResolveResolver re-export imported by nobody; duplicate scaffold paths + two drifted config.base.toml templates; \_cli/tui 34-symbol pass-through facade with import-time side effect + 3 same-pattern facades (completions, data, panels). Entry points verified clean both directions (18 declared resolve; 9 read groups accounted); completions data.py zero drift vs BUILTIN\_COMMANDS/click; AST export graph over 44 **init** files vs 1,335-file corpus.

### A1Aggregate — aggregation (155-row master matrix)

Read all 12 inputs; deduped \~47 multi-report hits into 155 unique rows (IDs A1-001…A1-155); confidence unioned per serena-evidence rule (108 high / 24 medium / 9 low / 1 disputed / 13 info); 4 new cross-wave patterns registered (test-pinned corpses, user-set-but-unread config keys, decorative re-export layers, three-doors-one-used registries, live-twins); 9 CONFLICTS preserved with both citations for orchestrator adjudication (adjudicated above); top-20 priority list led by the never-executing run\_middleware decorator; count reconciliation table included.

## Recommended execution order (for follow-up work)

1. **Contract repairs first** (#1–#5): wire or delete each silent no-op; these are correctness bugs wearing dead-code clothes. Each is S–M effort.
2. **One deletion PR per coherent cluster**: dead TUI generation (#6), shim cutover (#8), re-export facades (#9), engine/events sweep (#20), speculative machinery (#19) — migrate pinned tests in the same PR.
3. **Refactors last** (#10–#12): god units, only after 1–2 shrink the blast radius; each needs its own PR + characterization tests.
4. Docs-lie cluster (#16) can ride along anywhere.

