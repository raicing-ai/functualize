# Plan: one parameter contract behind every surface

## Alignment

- **Shape authority:** *Shape Intent — Collections Earn Repeatable Flags (list[T], tuple[T, ...], and
  one verdict behind every surface)*, Confluence `SD/28901379` **version 5**, read live 2026-11-22
  (`Status: Approved`, `Authority: Approved`, `Last reviewed: 2026-11-22 (v5, DC-1 resolution)`).
- **Surfaces in scope, in the page's words (§8):**
  - "signature parameters of `@job` functions and `@job` class methods";
  - "every delivery surface: CLI, completion, SmartBar, the TUI's parse-and-execute door, info schema,
    MCP (schema, registration, call), HTTP, Lambda";
  - "config-model fields: their flag, their refusal (F-29), their binding";
  - "`GroupOptions` fields: repeatable lists (F-10), schema parity (F-13)";
  - "DI *classification* (F-21) and the injection override (F-20)";
  - "the dead code in §3.4 that re-derives parameters".
- **Out of scope, in the page's words:**
  - "workflow `Step` / `AgentStep` inputs";
  - "Textual rendering and key handling; the AWS Lambda runtime itself";
  - "the config ladder's precedence, which is measured correct and unchanged";
  - "DI provider registration and lifetimes";
  - "other `vulture` findings";
  - "Windows behaviour (NOT_MEASURED)".
- **Decisions, as approved and amended:**
  - **D1:** absent optional list → `None`.
  - **D2:** the annotated container.
  - **D3:** required repeatable option.
  - **D4:** schema from the contract.
  - **D5 = B′:** `INVOCATION_ONLY`.
  - **D6 = Arch-2.**
  - **D7:** deletions in this change.
  - **D8:** the TUI uses the CLI grammar.
  - **DC-1 = B,** page §5.7 v5 amendment: "reported, not unregistered … refuses on every call naming
    the job, the parameter and the remedy". Member comment `01a2012e-723d-7822-9fc6-b4dcc3ab1ec6`,
    2026-11-22T02:55:50Z: "spec confirmed, DC-1 = B".
- **Spec:** `spec.md`, confirmed with DC-1 = B. It was revised by this plan in two places (§*Spec
  revisions*), and both revisions are now confirmed.
- **Step-11 answers (member):** comment `01a201b6-3d91-7eb2-8587-df5f212bf69f`,
  2026-11-22T05:24:10Z, verbatim: *"plan approved: S-1 yes, S-2 yes, SS-3 B, SS-4 A"*.
  - **S-1 yes:** the AI tool scope is in scope (task 7.2).
  - **S-2 yes:** B-23 is narrowed to values a surface supplies.
  - **SS-3 B:** `FieldDescriptor.type_annotation` is **removed** in this change (waves 9 and 10).
  - **SS-4 A:** `JobExecutionEngine` is "not grown"; its decomposition remains ADR-020's debt.
- **Execute context anchor: A** (member comment `01a203b0-55ec-7393-85b3-a3a3c55172f0`,
  2026-11-22T14:36:57Z, verbatim *"Anchor A"*).
  - **What changes.** The anchor is widened to the six workflow files plus this feature's own
    `spec.md`, `plan.md`, `schema.md`, `contracts.md` and `matrix/**`. Another feature's specs, this
    feature's `research.md`, chat history and unrelated files stay forbidden.
  - **Where.** All four places that stated it: `.claude/commands/agentic-execute.md`;
    `.claude/agents/spec-driven-developer.md` (the anchor block, step 1, and the *Critical Rules*
    line "Execute reads only the 6 anchor files"); and `.claude/rules/spec-workflow.md`.
  - **Why the six-file anchor was too narrow.** It forbade the feature's own artifacts, which the
    tasks are written against, while Verify mandates reading two of them (`spec.md` and
    `contracts.md`, `agentic-verify.md` steps 2 and 2b).
  - **Verified mechanically** with `matrix/anchor_check.py` over every task's `Input:` block: 32
    tasks, 0 inputs outside the new anchor (16 outside the old one).

Workflow mode: repository-native (`.claude/rules/spec-workflow.md`). Phase: Plan, steps 1–10. Step 11
(the task review with the member) follows this file. `.spec/STATE.md` is absent: no work in flight.

## Architecture gate — retrieval record (step 2)

| question | tool, how | what it answered |
| --- | --- | --- |
| what does the prose say | **zvec-grep** `/usr/local/bin/zg`, index built for this worktree (`zg status`: root = this worktree, 968 files); queries in `matrix/evidence/zg-queries.txt` | `_engine/validation.py:43-47` (caller may supply a DI parameter); `job-config.md:47` (registration-time refusal); `functualize-ai/_tool_scope.py:408` (a seventh schema renderer) |
| what is in these modules | **serena**, activated by this worktree's absolute path; `get_symbols_overview` on `_types/descriptors.py`, `_discovery/providers.py`, `_primitives/job_schema.py`, `_engine/validation.py`, `_types/flag_grammar.py`; `find_referencing_symbols` on `parse_annotation`, `build_click_params`, `build_click_params_from_fields`, `coerce_kwargs` | `build_click_params` also builds **plugin command callbacks** (`create_callback_click_command`, `click_params.py:1571`); `coerce_kwargs` has **no production caller**, only tests |
| which way the dependencies point | **graphify** `get_neighbors("FieldDescriptor")` on `graphify-out/graph.json`, built at `2269b8d3`, **60 commits behind HEAD**, so used for shape only | 26 production modules read `FieldDescriptor`, including `app/commands.py` `JobNode.params()` (ADR-004 command nodes) and `_types/flag_grammar.py` |
| codemaps | `overview.md`, `modules.md`, `dependencies.md`, `data-flow.md`, `entry-points.md` | `data-flow.md` §2 states "Resolution priority … DI > RunContext > Config > Default" — **contradicted by the code** (`executor.py:1432-1434`: the caller wins; F-20). The codemap is corrected in task 11.1. `data-flow.md` §7: the TUI flow runs backwards through `sync.py`'s emitter (`emit(resolve(text)) == text`) |
| prior art | ADR-004, 010, 018, 020, 033; `pitfalls.md` §4, §5, §19, §23, §25 (`research.md`) | DC-1 resolved by ADR-018; ADR-020 already moved binding into `engine.run(request)` |

### Measurements this phase added (all in `matrix/evidence/`)

- **F-07 located (`f07-trace.txt`, `f07-click.txt`).** `func d094` *is* parsed by click, with
  `--p` `required=True`. Click 8.4.1 treats an explicitly passed `default=None` as a value, so
  `required` is never enforced:

  ```text
  default omitted:      UsageError -> Missing option '--p'.
  default=None passed:  no error   (callback got {'p': None})
  ```

  The marker builder always passes it (`click_params.py:693`:
  `default = param.default if has_default else None`). The page's risk R3 is closed.
- **F-34 located.** On a cold boot the descriptor holds the `Enum` member, which
  `job_schema._is_json_native` drops. On a warm boot the cache has already encoded it as `"red"`
  (`_types/descriptors.py:650` `_serialize_default`), which passes.
- **H3, binder cost (`binder-cost.txt`).** Inside a real `func` process, after boot:

  | | measured |
  | --- | --- |
  | first `TypeAdapter` | **0.3–0.6 ms** |
  | seven more adapters | 1.2–2.3 ms |
  | binding 15 arguments per call | ~18 µs (median) |
  | a whole `func` invocation | ~1.7 s |

  In a fresh interpreter that has *not* built a pydantic schema, the first adapter costs 450–1,100 ms.
  Today's `ArgValidator` pays the same for any job with a `Field()` parameter, and boot pays it today.
  Risk R-4 below records what would change that.
- **Authoring-time gate runs (`gates-authoring.txt`)** fix every count in `tasks.md`.

## BEFORE

Layers, by both axes (`overview.md`):

- **Audience:** public `app/ job/ plugin/ types/ testing/ workflow/` against the underscore internals.
- **Internal order:** `_types` → `_primitives` → `_events` → the independent peers `_discovery`,
  `_config`, `_engine`, `_plugins` and `_gate` → `_app` (the composition root) → `_cli`, which uses
  public API only.

Arrows are calls that coverage saw execute (`cov_census.txt`), except where marked *(static)*.

```text
 FOUNDATION                                            PEERS (independent)                          PUBLIC / DELIVERY
 ─────────                                             ───────────────────                          ─────────────────
 _types/descriptors.FieldDescriptor                    _discovery/providers                         app/adapters/click_params
   { type_annotation: str, positional, short_flag }  ◄── extract_parameters_from_signature ──┐       ├ build_click_params (live sig) ─► func <job>, plugin callbacks
   _field_to_dict / _serialize_default ─► cache.json     _annotation_to_type_str ─► "list[str]"│       │   _option_from_marker: default=None ⇒ required ignored (F-07)
                                                       _discovery/schema_extractor (config)   │       ├ build_click_params_from_fields ◄─ _resolve_type_string("…")
 _primitives/job_schema                                  _JSON_SCHEMA_TYPE_MAP, own Optional   │       │                                 ─► completion, SmartBar groups,
   TYPE_MAP["…"] or "string" (F-02)  ◄─────────────────── type string ─────────────────────────┘       │                                    lazy (warm) command
   job_input_schema ─► _cli/info ─► info schema                                                         app/utils: _resolve_type + coerce_kwargs (no prod caller)
                    └► functualize_mcp/_translator ─► +group options (F-13) ─► _server: JSON type → "str" + exec (F-12, F-23, F-24)
                    (functualize_ai/_tool_scope: its own _python_type_to_json_type — 7th map)
 _cli/annotation_utils.parse_annotation (kind #1; in _cli, read by app/adapters)
 _cli/tui/cli_arg_parser.parse_cli_args_to_kwargs (dict[str,str], last wins) ─► RunRequest(tui.inline)
 _cli/tui/smart_bar_autocomplete._candidates_flag (kind #5: names "rc","run_context","log"; "list[" prefix)
 _cli/tui/sync, bar, _cli/dispatch.walk_group_path:  type_annotation == "bool"  (7 string reads)
                                                       _engine/resolution.build_resolution_plan  kind #3: base_type in registered_types (F-21)
 HTTP / Lambda ─ _types/run_request.request_from_envelope ─ arguments as-is ─► _engine/executor._execute_lifecycle
                                                         unexpected_keyword_error (workflows only) ─ ArgValidator (Field() params only)
                                                         ─ DI fills names the caller did not send (:1432, F-20) ─ PRE_EXECUTE hooks ─ job(**kwargs)
 _config/job_config.validate_job_config_types ── reached only from JobRegistry._extract_descriptors_from_module (0/58 under func; F-29)
```

**Smells the BEFORE carries** (Refactoring.Guru catalogue, from the `design-patterns-refactoring`
skill):

| smell | where | measured evidence |
| --- | --- | --- |
| **Shotgun Surgery** | adding one value type touches the classifier (`annotation_utils.py:259`), the click mapper (`click_params.py:142`), the string writer (`providers.py:348`), the string reader (`click_params.py:219`), `TYPE_MAP` (`job_schema.py:53`), the MCP map (`_server.py:39`), the AI map (`_tool_scope.py:528`), the SmartBar list test (`smart_bar_autocomplete.py:559`) and the config validator (`job_config.py:439`) | `timedelta` reached two of the nine (F-05) |
| **Duplicate Code** | 5 `Optional` unwrappers, 3 list unwrappers, 4 flag derivations, 5 kind deciders, 7 type maps | `gates-authoring.txt`: optional-unwrappers 5 hits, list-unwrappers 3, type-maps 30 |
| **Primitive Obsession** | `FieldDescriptor.type_annotation: str` (`_types/descriptors.py:74`) is re-parsed by every reader | 7 behaviour-from-string sites (`job-param-string-reads`), plus 3 injection-by-type-name sites |
| **Feature Envy** | `functualize_mcp/_server._build_tool_function` (`:170-261`) rebuilds a signature out of the schema | F-12, F-23, F-24 |
| **Dead Code** | `SwappableCompleter`, `format_type_hint` + `_TYPE_MAP`, `AnnotationInfo.field_metadata`, `coerce_kwargs` + `_resolve_type`, and `validate_job_config_types` on `func`'s boot path | `dead-symbols` gate: 17 hits; coverage 0 executed statements |

**Pre-existing forbidden pattern in the region:** "God-object growth — if a class exceeds ~500 LOC,
decompose it" (`.spec/CONSTITUTION.md:95`). `JobExecutionEngine` is already far past it (2,747 lines at `da912d76`). This plan does not decompose it, which would be out of scope. It **must not grow
it**: task 5.2's gate measures the class's line count before and after. Measured at `da912d76` with
an `ast` walk: `JobExecutionEngine` spans `executor.py:213-2959`, **2,747 lines**. ADR-020's 2,401 is
older.

## Candidate AFTERs and the iteration (steps 4–6)

1. **The page's Arch-2 as drawn**, with a contract and a binder, keeping the live builder for the
   cold command and for plugin callbacks. *Rejected.* Two click builders survive, so the cold/warm
   split survives with them: F-33 and F-34 are that split on this branch today
   (`cold-vs-warm.txt`). It trades nothing for Duplicate Code.
2. **Contract dataclasses in `_primitives`.** *Illegal.* `FieldDescriptor` lives in `_types`, and
   "Types import nothing internal" (`pyproject.toml` import-linter). The data moves to `_types`; the
   builder stays in `_primitives`.
3. **A binder that rebuilds Python types from `ValueShape` alone**, to bind without the job module.
   *Rejected.* It cannot produce an `Enum` member or a marked custom class without importing the
   module, and the engine has always imported it by the time it binds. So the binder takes the live
   function and uses the contract only for verdicts and defaults. That keeps one type source, the
   annotation, rather than inventing a second.
4. **Settled (below).** The data is in `_types`, the builder in `_primitives`, one click renderer in
   `app/adapters` (cold, warm and plugin callbacks), one schema renderer in `_primitives/job_schema`,
   and one binder in `_primitives`, called at the engine door. The TUI parses with the rendered click
   command, and MCP registers from the schema with no `exec`.

**Smells the settled AFTER introduces, checked:**

- **Data Class.** `ParameterContract` is a record that renderers act on. It is accepted as a
  surviving smell, because it is the serialised cache record by necessity: the warm path imports no
  job module.
- **Shotgun Surgery, residual.** A new scalar type now touches two places, the contract builder (its
  `Scalar` member) and the click renderer (its click type). Schema and binding come from pydantic
  automatically. Down from nine, and accepted as a surviving smell, because click may not be imported
  into the kernel layers (constitution, *Forbidden Patterns*).
- **Large Class.** Avoided by placing the builder and the binder in separate modules
  (`_primitives/parameter_contract.py`, `_primitives/argument_binding.py`), each under the ~500-LOC cap
  (gate in tasks 1.1 and 2.1).
- **Peer-layer cross-import, ABC port, global mutable state:** none. `_discovery`, `_engine` and
  `_config` import only `_primitives` and `_types`. The `TypeAdapter` cache is an instance attribute
  of the binder the engine owns, not a module-level singleton.

## Spec revisions found here (step 6; confirmed at step 11, comment `01a201b6`)

- **S-1 · One surface was missing.** `functualize-ai`'s `ToolScope` (`_tool_scope.py:242`
  `to_tool_defs`, `:408` `_fields_to_schema`) publishes job parameters to LLM tool calls through its
  own type map. It is a delivery surface under the page's own principle ("every delivery surface"),
  though the page does not name it. `spec.md` adds it to B-21 (it reads the one schema). Its calls go
  through the engine door like every other `invoke`.
- **S-2 · B-23 overstated.** "Binding is the only place a supplied value becomes the job's argument"
  is false for the documented `PRE_EXECUTE` hook, which "can BLOCK or MODIFY kwargs"
  (`data-flow.md` §2). `spec.md` B-23 now says binding governs every value **a surface supplies**,
  and in-process hooks keep their documented power. That is a plugin's decision, not a caller's.
- **DC-1 recorded as decided** (B, comment `01a2012e`).

## AFTER

```text
 FOUNDATION                                   PEERS                                   PUBLIC / DELIVERY
 ─────────                                    ─────                                   ─────────────────
 _types/parameter_contract   (NEW; stdlib)    _discovery/providers                    app/adapters/click_params
   Verdict, ValueShape, CliSpelling,            extract_parameters_from_signature       render_click_params(contracts)  ◄── THE click renderer
   Injection, ParameterContract                   └─ build_contract(...) per param        ├─► func <job> (cold and warm, same object)
 _types/descriptors.FieldDescriptor            _discovery/schema_extractor (config)        ├─► plugin command callbacks (contracts built on the fly)
   + contract  (type_annotation = display)        └─ build_contract(config field)        ├─► _cli/completions/data      (bash, zsh)
   _field_to_dict/_from_dict encode contract   _discovery/group_options_extractor         ├─► _cli/tui/smart_bar_autocomplete (same params' opts)
   CACHE_VERSION 25 → 26                          └─ build_contract(group field)         └─► _cli/tui: bar text parsed by the same click command
 _primitives/parameter_contract (NEW)          (REJECTED → DiscoveryFailure, ADR-018 form)   _cli/dispatch.walk_group_path: arity/repeat from contract
   build_contract(param, hints, markers)
     ← resolved_hints (PEP 563 both ways)     _engine/executor._execute_lifecycle     functualize_mcp: Tool(parameters=job_input_schema(...)).run(args)
     ← capability_names, di.Provide, FromJob     bind(function, contracts, raw)  ◄──┐    HTTP / Lambda: envelope unchanged ─► RunRequest
     → json_schema via TypeAdapter(...)          (refuse unknown/injected/missing;   │   functualize_ai/_tool_scope: reads job_input_schema
 _primitives/argument_binding (NEW)              convert; defaults) ── BindRefusal ──┼─► RunStatus.INVALID ─► exit 2 / HTTP 400 / Lambda 400 / MCP isError
   bind(...) → kwargs | BindRefusal              DI fills INJECTED only               │   (outcome tables in _types: one new row each)
 _primitives/job_schema                       _engine/resolution.build_resolution_plan│
   job_input_schema(contracts, group_opts)      kind from contract.verdict (F-21)     │
   (contract.json_schema; group options       PRE_EXECUTE hooks (in-process, may modify) ─► job(**kwargs)
    merged here, once — F-13)
 _types/enums.RunStatus + INVALID; _types/exit_codes, http_status, outcome: + INVALID row
```

**Boundary check against the seven import-linter contracts** (baseline
`uv run --frozen lint-imports`: "Contracts: 7 kept, 0 broken", run in this worktree):

| contract | does the AFTER keep it? |
| --- | --- |
| Types import nothing internal | yes — `_types/parameter_contract` is stdlib dataclasses and enums only |
| Primitives import nothing internal | yes — `_primitives/parameter_contract` and `argument_binding` import `_types` and pydantic; `pydantic` is already imported from `_primitives` (`config_class_detection.py`, `fingerprint.py`) |
| Peer layers are independent | yes — `_discovery`, `_engine` and `_config` reach the contract through `_primitives` only |
| Events depends on foundation only | untouched |
| Internal never imports public | yes — nothing internal imports `functualize.app`. The renderer is public (`app/adapters`) and reads internal `_types` |
| `_cli` uses public API only | yes — `_cli` (completion, SmartBar, TUI, dispatch, info) reaches the renderer and contracts through `functualize.app.adapters` / `functualize.app.utils` / `functualize.types`, as it reaches `build_click_params_from_fields` today |
| Delivery adapters go through the request, not the engine | yes — MCP, HTTP and Lambda build `RunRequest`s; binding happens inside the engine |

Every wave's tasks re-run `uv run lint-imports` (the AC-13 gate).

## Technical approach, by consumer (D6 order)

1. **Wave 0 — the record.** Contract types, the descriptor field and codec, `CACHE_VERSION` 26, the
   new outcome row (`RunStatus.INVALID`; exit 2; HTTP 400; Lambda 400), and the declaration table.
2. **Wave 1 — the builder.** `build_contract` implements spec B-1 to B-8 and the refusal reasons, plus
   unit tests over the declaration table, compiled both ways for PEP 563.
3. **Wave 2 — discovery and the binder.**
   - Discovery writes contracts for signature, config and group fields. A `REJECTED_DISCOVERY`
     contract becomes a `DiscoveryFailure` (`error_type="UnsupportedParameter"`, next to ADR-018's
     `UnsatisfiableParameter` at `_app/boot.py`), and the job stays registered.
   - `bind` is written and unit-tested in isolation.
4. **Wave 3 — CLI, completion, SmartBar, TUI.**
   - One click renderer from contracts: F-04, F-05, F-07 and F-16 close here.
   - Completion and the SmartBar read its params.
   - The TUI parses bar text with that command. The bar emitter repeats list flags and reads
     arity from the contract.
   - Dispatch's pre-boot group walk reads arity and repeatability from the contract (F-10).
5. **Wave 4 — the test suite on the new renderer.** The builder tests that pin today's two builders
   are rewritten against the one renderer.
6. **Wave 5 — the engine door.**
   - `bind` replaces `unexpected_keyword_error` and `ArgValidator` at `executor.py:1393-1486`.
   - DI fills only `INJECTED` parameters, and `build_resolution_plan` reads contracts, not the
     registry.
   - A missing provider refuses before the call on both boot paths (F-33).
   - `BindRefusal` becomes `RunStatus.INVALID`, with a `prelude_refusal` arm (`pitfalls.md` §25).
7. **Wave 6 — schema and MCP.**
   - `job_input_schema` reads contracts and merges group options once.
   - MCP registers `Tool(parameters=…)` with one handler, and reports failure reasons (F-31).
   - The schema exports and `ToolScope` read the one schema.
8. **Wave 7 — boot and adapters.** The builtin path applies the same import libs as project paths
   (F-30). The Lambda docstrings say `arguments` (F-28).
9. **Wave 8 — D7 deletions,** each gated by an `rg` that must return 0.
10. **Wave 9 — stop depending on `type_annotation` (SS-3 = B).**
    - The descriptor's `type` alias and the codec's `type_annotation` and legacy `"type"` keys go,
      and no legacy key survives. Wave 0's `CACHE_VERSION` 26 bump means an older cache is rebuilt,
      not decoded.
    - The field becomes transitional, with default `""`.
    - The TUI's own `FieldDef.type_annotation` is renamed `type_label`.
    - The last 9 production readers move to the contract.
11. **Wave 10 — delete the field,** with the 45 remaining test and fixture files migrated in three
    disjoint tasks. The gate is `rg '\.type_annotation' src plugins` → 0; today it gives 22
    occurrences in 10 production files (`ss3b-counts.txt`).
12. **Wave 11 — docs, ADR amendments, changelog,** the codemap correction, and the parity test.
13. **Wave 12 — checkpoint.** The whole kit, cold and warm, both PEP 563 modes, coverage and the
    dead-code delta (AC-1 to AC-13).
14. **Wave 13 — artifact clearing** (the two-push sequence).

### The refusal outcome (page §5.7, left to Plan)

The outcome tables have no "bad argument" status:

- `RunStatus` (`_types/enums.py:31-50`) has `REFUSED`, which means "a declared precondition … was
  not met", exits 3 and maps to HTTP 412;
- `ExitCode.USAGE = 2` exists with no `RunStatus` mapped to it (`_types/exit_codes.py:41`).

**This plan adds one status, `RunStatus.INVALID`** (name provisional), meaning: "the call could not
be bound to the job's declaration — nothing ran". It covers a missing, unknown or injected argument, a
value that does not convert, and a call to a job whose parameter discovery refused (DC-1 = B). It is
mapped once in each family:

| family | mapping |
| --- | --- |
| process | `ExitCode.USAGE` (2) |
| HTTP | **400** |
| Lambda | `statusCode` 400 |
| MCP | `isError: true` with the reason |

`REFUSED` keeps its meaning. 400 rather than 422: the request is wrong as a request, which is the
meaning the page's §5.6 examples already used.

## Risks

- **R-1 · Visible behaviour changes for existing users,** listed in `spec.md` § *Evidence and
  constraints*. No shims (constitution), and each is recorded in `CHANGELOG.md` (task 11.1).
- **R-2 · Breadth, now including the field's removal (SS-3 = B).** Measured on `6ff7182a`
  (`ss3b-counts.txt`):
  - `.type_annotation` attribute reads: **22 occurrences in 10 production files**.
  - The `type_annotation` token anywhere in production code: **72 occurrences in 27 files**.
  - Test and fixture files: **53**.
  - `FieldDescriptor` outside `_types/`: **19 production files**. 3 are constructors
    (`providers.py`, `schema_extractor.py`, `app/commands.py`), 1 is the public re-export
    (`types/__init__.py`), and 15 are readers.
  - The `type` alias property has **no production reader**; serena finds one test reference.
  - **Public API:** `functualize.types` re-exports `FieldDescriptor`, so removing the field is a
    public break. The member accepted it with SS-3 = B, and it is recorded in `CHANGELOG.md`
    (task 11.1).
  - **Guard:** the gate, not an audit. After task 10.1, `rg '\.type_annotation' src plugins` → 0
    and `rg -l -w type_annotation tests plugins` → 0.
- **R-3 · The TUI emitter.** `sync.build_command_line` must keep `emit(resolve(text)) == text`
  (`data-flow.md` §7) once lists repeat. `tests/tui_group_options/test_write_back_contract.py` pins
  it (task 3.4).
- **R-4 · Binder warm-up.** It is negligible today, because boot builds pydantic schemas first
  (H3). A future fast path that skips pydantic at boot would move ~0.5 s of schema warm-up onto the
  first bound call. Task 5.2 records the in-process number in its evidence so a regression is
  visible.
- **R-5 · Library mode** is not driven by the kit (F-29). Task 2.1 builds contracts on both
  registration paths (`JobRegistry._extract_descriptors_from_module` and the directory scan), so the
  refusal does not depend on which one runs.
- **R-6 · Existing tests change meaning.** 13 test modules pin today's builders (`blast-radius.txt`,
  `click_builders`). The three cross-builder parity tests, `tests/adapters/test_cold_warm_parity.py`,
  `tests/config/test_click_builder_agreement.py` and `tests/cli/test_schema_surface_parity.py`,
  assert agreement between things this change makes one. They are folded into the new parity test in
  task 11.2, not deleted silently.

## Verification

AC-1 to AC-13 of `spec.md`, run by the checkpoint (task 12.1). Every end-to-end gate runs twice, cold
and warm (`pitfalls.md` §23), and in both PEP 563 modes (§4). Reachability, per the constitution: each
task names the production call path to its code and proves it by removing the call and watching its
test fail.

## Skills consulted

- **`python-design-patterns`**, the repository's own skill (`.agents/skills/python-design-patterns/SKILL.md`).
  This runtime cannot invoke it as a skill, so it was read directly. It contributed "delete before
  abstracting" and "duplication that diverges in dangerous ways should be abstracted sooner … extract
  immediately".
- **`design-patterns-refactoring`**, user-level (Refactoring.Guru catalogue), loaded as a skill. It
  supplied every smell name above and its routing: Shotgun Surgery → Move Method/Field; Duplicate Code
  → Extract Class; Primitive Obsession → Replace Data Value with Object; Dead Code → Delete; Feature
  Envy → Move Method.

## Surviving smells

| id | smell | where | why it survives | maintainer review? |
| --- | --- | --- | --- | --- |
| SS-1 | **Data Class** | `_types/parameter_contract.ParameterContract` | It is the cache record: the warm path must answer without importing a job module (`modules.md:23`), so the contract has to be inert data read by renderers. Behaviour lives in the builder, renderer and binder functions. | no — it is the shape the page approved (§6 AFTER) |
| SS-2 | **Shotgun Surgery (residual, 2 sites)** | a new scalar type touches the `Scalar` enum and builder (`_primitives/parameter_contract.py`) and the click type mapping (`app/adapters/click_params.py`) | Click is forbidden in the kernel layers (constitution, *Forbidden Patterns*), so the click mapping cannot live beside the builder. Down from nine sites, and the parity test fails if the two disagree. | no |
| SS-3 | ~~Duplicate Code (display string kept beside the contract)~~ — **no longer survives** | `FieldDescriptor.type_annotation` | **Answered B** (comment `01a201b6`, 2026-11-22T05:24:10Z): the field, its `type` alias and the codec's `type_annotation` / legacy `"type"` keys are removed (tasks 9.1, 10.1), and every reader takes its label from `contract.display`. The public break is accepted and recorded in the changelog. | answered |
| SS-4 | **Pre-existing God Object (not grown)** | `_engine/executor.JobExecutionEngine`, already past the constitution's ~500-LOC cap (2,747 lines) | **Answered A** (comment `01a201b6`): "not grown" is accepted, and the decomposition remains ADR-020's debt. This plan replaces code inside it and must leave it no larger (task 5.1's gate: line count ≤ 2,747). | answered |

Nothing on the *Forbidden Patterns* list is introduced. SS-4 is a forbidden pattern **already
present**: it is listed so it is seen, and the plan's gate prevents it growing.
