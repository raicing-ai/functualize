# Tasks: one parameter contract behind every surface

The confirmed `spec.md`, `contracts.md`, `schema.md` and `plan.md` are the inputs.

- **`[F]` is each task's allowed edit scope.** It is the hit set of the retrieval query named in the
  task (`matrix/evidence/blast-radius.txt`, `gates-authoring.txt`).
- **Counts in `Gate` were measured at authoring time on `da912d76`.**
- **Reachability** (constitution, *Quality Gates*): each task names the production call path to its
  code and proves it by removing that call and watching a named test fail. Commit first, sabotage
  second, restore third.
- **Transitional states are labelled in code** with `# TRANSITIONAL(<task>): …` and removed by the
  named task.
- **SS-3 = B (member, comment `01a201b6-3d91-7eb2-8587-df5f212bf69f`, 2026-11-22T05:24:10Z).**
  `FieldDescriptor.type_annotation` is removed in this change, not kept as a display label.
  - No task adds a new read of `type_annotation`.
  - A task that edits a file which reads it replaces that read with the contract:
    `contract.display` where a human needs a type label, and the contract's fields
    (`verdict`, `shape`, `cli`) where behaviour depends on it.
  - Waves 9 and 10 remove what is left, and 10.1 deletes the field.
- **Every task's gate also includes** `uv run lint-imports` (baseline "7 kept, 0 broken"), plus
  `uv run ruff check`, `ruff format --check` and `mypy src/` on the files it touches.

## Wave 0 — the record, the outcome row, the table, two independent fixes

### [x] 0.1 Contract types, the descriptor field, the cache codec

- **Input:** `schema.md` (types, invariants 3 and 5, cache encoding).
- **[F]:**
  - `src/functualize/_types/parameter_contract.py` (new);
  - `src/functualize/_types/descriptors.py`;
  - `src/functualize/_primitives/cache_format.py`;
  - `tests/types/test_parameter_contract_codec.py` (new).
- **Work:**
  - Add the frozen dataclasses and enums.
  - Add `FieldDescriptor.contract` (optional, default `None`). Do **not** touch
    `type_annotation`, its `type` alias or the codec's `"type"` key here: their removal is placed in
    waves 9 and 10 (SS-3 = B).
  - Encode and decode it in `_field_to_dict` / `_field_from_dict` (`descriptors.py:631`, `:685`),
    with `default_json` as JSON-native.
  - Bump `CACHE_VERSION` from 25 to 26 (`cache_format.py:178`).
- **Invariant:** `_types/parameter_contract.py` imports stdlib only. A descriptor with a contract
  round-trips through the codec equal to itself.
- **Gate/evidence:**
  - `uv run pytest tests/types/test_parameter_contract_codec.py tests/test_descriptor.py tests/discovery/test_cache_manager.py tests/config/test_descriptor_cache_fidelity.py`;
  - `rg -n "^CACHE_VERSION = 26" src/functualize/_primitives/cache_format.py` → 1 hit (today
    `CACHE_VERSION = 25`, 1 hit);
  - `lint-imports` "Types import nothing internal" KEPT.
- **Depends on:** none.

### [ ] 0.2 One new outcome: `RunStatus.INVALID`

- **Input:** `plan.md` § *The refusal outcome*; `_types/enums.py:31-50`; `_types/exit_codes.py:41`;
  `_types/http_status.py:54-74`.
- **[F]:**
  - `src/functualize/_types/enums.py`;
  - `src/functualize/_types/exit_codes.py`;
  - `src/functualize/_types/http_status.py`;
  - `src/functualize/_types/outcome.py`;
  - `tests/types/test_outcome_invalid.py` (new).
- **Work:** add `INVALID` ("the call could not be bound to the job's declaration — nothing ran").
  Map it once per family: exit `USAGE` (2), HTTP 400, Lambda 400. Make it terminal and not
  resumable.
- **Invariant:** `REFUSED` keeps exit 3 / HTTP 412. Every family's table maps `INVALID`.
- **Gate/evidence:** `uv run pytest tests/types/`, which includes the existing
  `test_every_surface_declares_its_family.py`.
- **Execute finding (2026-11-22):** the gate is red at
  `tests/types/test_descriptor_owner_class.py::test_cache_reader_refuses_version_22`, which asserts
  `CACHE_VERSION == 25`. Task 0.1 correctly bumped it to 26. This existing test is outside both
  tasks' `[F]` scopes; the outcome implementation is committed, but 0.2 remains unchecked pending
  a task-scope revision for the version assertion. Raw gate output:
  `/tmp/functualize-wave0-02-pytest.log` in the executing worktree.
- **Depends on:** none.

### [ ] 0.3 The declaration table

- **Input:** `matrix/rows.py` (166 rows); `matrix/report.py::proposed` (each row's expected verdict).
- **[F]:** `tests/_support/parameter_matrix.py` (new).
- **Work:** each row is data: id, declaration source, expected verdict, and per-surface expectations
  (spelling, requiredness, delivered type). Proposed verdicts are as on page v5. H166 and the other
  missing-provider rows are `REJECTED_DISCOVERY`, *reported*, per DC-1 = B. Generated module sources
  compile both with and without `from __future__ import annotations`.
- **Invariant:** the table is the single source that 1.1's unit tests, 11.2's parity test and 11.1's
  docs table read (page §5.8).
- **Gate/evidence:** `uv run python -c "from tests._support.parameter_matrix import ROWS; assert len(ROWS) == 166"`.
- **Depends on:** none.

### [ ] 0.4 Lambda docstrings name the shared envelope (F-28)

- **Input:** `gates-authoring.txt` `lambda-kwargs-doc`: 4 hits, at `__init__.py:8`, `:154`, `:178`
  and `:220`.
- **[F]:** `plugins/adapters/functualize-lambda/src/functualize_lambda/__init__.py`.
- **Work:** the docstrings describe `{"job": …, "arguments": {…}}`. No code change: the envelope
  already reads `arguments` (`run_request.py:343`).
- **Gate/evidence:** `rg -n '"kwargs"' plugins/adapters/functualize-lambda/src` → 0 hits (today 4).
- **Depends on:** none.

### [ ] 0.5 One import environment for every command (F-30)

- **Input:** `matrix/evidence/plugin-lib-order.txt`. The candidate mechanism: `cli_app` applies
  `cli_config.import_libs` (`_cli/main.py:300`), while project boots apply
  `effective[IMPORT_LIBS.key]` (`:1250`, `:1405`).
- **[F]:**
  - `src/functualize/_cli/main.py`;
  - `tests/cli/test_plugin_import_environment.py` (new).
- **Work:** confirm the mechanism with the repro, then make the builtin path add the same convention
  directories before plugins load.
- **Gate/evidence:** the new test runs the `plugin-lib-order.txt` repro in a subprocess for
  `func h1`, `--help`, `mcp schema`, `builtin info schema` and `builtin shell-init bash`. All 5 must
  show the provider registered. Today 2 of 5 print `registration failed`.
- **Depends on:** none.

## Wave 1 — the classifier

### [ ] 1.1 `build_contract`

- **Input:** `spec.md` B-1 to B-8 and B-14; `contracts.md` §1; `schema.md`; task 0.1 types;
  task 0.3 table.
- **[F]:**
  - `src/functualize/_primitives/parameter_contract.py` (new);
  - `tests/primitives/test_build_contract.py` (new).
- **Work:**
  - Classify from `resolved_hints()` and the markers. The capability names come from
    `_primitives/capability_names.py:49`; also `Provide`, `FromJob` and `Secret`.
  - **Never** consult a DI registry (F-21).
  - Produce `json_schema` from `TypeAdapter(...).json_schema()` of the declared shape (D4).
  - Produce `reject_reason` text in the §5.7 shape.
  - Admit `timedelta` as an ISO 8601 duration.
- **Invariant:** one verdict per parameter. PEP 563 makes no difference (E142, F-32). Under the
  ~500-LOC cap.
- **Gate/evidence:**
  - `uv run pytest tests/primitives/test_build_contract.py` passes for every row of the table in
    both annotation modes;
  - `wc -l src/functualize/_primitives/parameter_contract.py` ≤ 500;
  - `lint-imports` "Primitives import nothing internal" KEPT.
- **Depends on:** 0.1, 0.3.

## Wave 2 — discovery writes contracts; the binder exists

### [ ] 2.1 Signature parameters get contracts; refusals are reported, not fatal

- **Input:** 1.1. ADR-018's `UnsatisfiableParameter` is at `_app/boot.py` (`gates-authoring.txt`
  `unsatisfiable`: 1 hit).
- **[F]:**
  - `src/functualize/_discovery/providers.py`;
  - `src/functualize/_discovery/registry.py`;
  - `src/functualize/_app/boot.py`;
  - `tests/discovery/test_contract_discovery.py` (new).
- **Work:**
  - `extract_parameters_from_signature` sets `contract` on every parameter it emits, and
    `type_annotation` keeps today's value until wave 9, and new readers read `contract.display`
    (SS-3 = B).
  - `JobRegistry._extract_descriptors_from_module` (`registry.py:359-551`) does the same, so library
    mode agrees (plan R-5).
  - A `REJECTED_DISCOVERY` parameter records `DiscoveryFailure(error_type="UnsupportedParameter")`
    and a boot warning. The job stays registered (DC-1 = B).
- **Invariant:** cold and warm descriptors compare equal.
- **Gate/evidence:** `uv run pytest tests/discovery/test_contract_discovery.py tests/discovery/test_discovery_failures.py tests/integration/test_warm_cold_boot.py`. The new test boots each table row cold and warm in a subprocess.
- **Reachability:** `func <job>` → `DirectoryScanProvider` → `extract_parameters_from_signature`.
- **Depends on:** 1.1.

### [ ] 2.2 Config and group fields get contracts; the config-type refusal runs (F-29)

- **Input:** 1.1. `validate_job_config_types` executed 0 of 42 statements under `func`
  (`cov_census.txt`).
- **[F]:**
  - `src/functualize/_discovery/schema_extractor.py`;
  - `src/functualize/_discovery/group_options_extractor.py`;
  - `tests/discovery/test_config_field_contracts.py` (new).
- **Work:**
  - `extract_field_descriptors` and `extract_group_options_fields` attach contracts.
  - An unsupported config field type (`dict`, nested model) becomes a `REJECTED_DISCOVERY` contract
    on every boot path.
- **Gate/evidence:** `uv run pytest tests/discovery/test_config_field_contracts.py tests/group_options/test_group_options_discovery.py`. Rows F150 and F151 are reported, not run.
- **Depends on:** 1.1.

### [ ] 2.3 `bind`

- **Input:** `schema.md` § *Binding*; `spec.md` B-23 to B-26; 1.1.
- **[F]:**
  - `src/functualize/_primitives/argument_binding.py` (new);
  - `tests/primitives/test_argument_binding.py` (new).
- **Work:**
  - Refuse unknown keys, injected keys, missing required arguments and non-converting values with
    `BindRefusal(argument, reason)`.
  - Apply defaults from `default_json`.
  - Convert with a `TypeAdapter` built from the live annotation and cached on the binder instance
    (not module state), honouring `Field()` constraints (subsumes `ArgValidator`).
- **Gate/evidence:** `uv run pytest tests/primitives/test_argument_binding.py`. Record the in-process
  timing as `matrix/binder_cost.py` measures it; at authoring time it was ~18 µs per call for 15
  arguments.
- **Depends on:** 1.1.

## Wave 3 — the one click renderer

### [ ] 3.1 `render_click_params(contracts)` for every click command

- **Input:**
  - 2.1 and 2.2;
  - `serena find_referencing_symbols`: `build_click_params` (3 production callers: `click_params.py:1416`, `:1530`, `:1571`);
  - `build_click_params_from_fields` (production callers: `_cli/main.py:898`, `_cli/completions/data.py:73,87`, `_cli/tui/smart_bar_autocomplete.py:320`, `app/adapters/cli.py:442`, `click_params.py:287`).
- **[F]:**
  - `src/functualize/app/adapters/click_params.py`;
  - `src/functualize/app/adapters/lazy_command.py`;
  - `src/functualize/app/adapters/cli.py`;
  - `tests/adapters/test_render_click_params.py` (new).
- **Work:**
  - One renderer from contracts for the live job command, the warm lazy command, plugin command
    callbacks (contracts built on the fly) and group options.
  - Never pass `default=None` with `required=True` (F-07; click 8.4.1, `f07-click.txt`).
  - Parse `timedelta` as ISO 8601 (F-05), and leave already-typed defaults alone (F-04).
  - Repeatable options for `list[T]` and `tuple[T, ...]`.
  - Refuse two CLI markers at discovery, not here (F-16 via 1.1).
  - Keep `build_click_params`, `build_click_params_from_fields` and
    `build_click_params_from_descriptor` as delegating wrappers marked `# TRANSITIONAL(7.3)`, so
    their existing callers and tests keep working until wave 7.
- **Invariant:** the cold and the warm command for one job are built by the same function from equal
  contracts.
- **Gate/evidence:** `uv run pytest tests/adapters/ tests/cli/test_option_marker_unit.py tests/cli/test_arg_marker_unit.py`. Plus the kit:
  - `probes.sh`: no `Traceback` for timedelta;
  - `func d094`: exit 2, `Missing option '--p'`;
  - `func b053 --p a --p b`: `p=['a', 'b']` once 5.1 binds; `('a', 'b')` before 5.1 is acceptable
    and noted.
- **Reachability:** `func <job>` → `_cli/main._handle_job` → `create_job_click_command` → the
  renderer.
- **Depends on:** 2.1, 2.2.

## Wave 4 — completion, SmartBar, the TUI door, the pre-boot walk

### [ ] 4.1 Completion and SmartBar offer exactly the rendered spellings (F-06, F-27)

- **Input:**
  - 3.1;
  - `gates-authoring.txt` `name-skip` (2 hits, both in `smart_bar_autocomplete.py`);
  - `injection-by-type-name` (`smart_bar_autocomplete.py:554`);
  - `job-param-string-reads` (`smart_bar_autocomplete.py:559`).
- **[F]:**
  - `src/functualize/_cli/completions/data.py`;
  - `src/functualize/_cli/tui/smart_bar_autocomplete.py`;
  - `src/functualize/_cli/completions/flag_filtering.py`.
- **Work:**
  - Both read the rendered params' `opts` and `secondary_opts`, excluding hidden params.
  - Delete `_candidates_flag`'s own field loop, the name skip, `_extract_short_names` and the
    `"list["` test.
  - `FlagDescriptor.is_list_type` comes from the contract.
  - Drop the `annotation_utils.unwrap_annotated` import at `smart_bar_autocomplete.py:842`, which
    8.1 deletes.
- **Gate/evidence:**
  - `rg -n '"rc", "run_context", "log"' src` → 0 (today 2);
  - `rg -n annotation_utils src/functualize/_cli/tui/smart_bar_autocomplete.py` → 0 (today 1);
  - `uv run pytest tests/_cli/test_completion_flag_pairs.py tests/_cli/test_flag_filtering.py`;
  - kit `surf_check.py` W-bar → 0 rows (today 65).
- **Depends on:** 3.1.

### [ ] 4.2 The TUI bar parses with the CLI grammar (D8, F-26)

- **Input:** 3.1; `gates-authoring.txt` `tui-parser`: `parse_cli_args_to_kwargs`, 12 hits in 5
  files.
- **[F]:**
  - `src/functualize/_cli/tui/cli_arg_parser.py`;
  - `src/functualize/_cli/tui/app.py`;
  - `src/functualize/_cli/inline_tui.py`;
  - `src/functualize/_cli/tui/chain_resolution.py`;
  - `src/functualize/_cli/tui/sync.py`.
- **Work:**
  - Replace `parse_cli_args_to_kwargs` with a parse through the job's rendered click command.
  - The emitter `sync.build_command_line` repeats list flags and reads arity from the contract, and
    keeps `emit(resolve(text)) == text` (`data-flow.md` §7).
  - The injection filter (`app.py:2274`) reads the verdict.
- **Gate/evidence:**
  - `rg -n -w parse_cli_args_to_kwargs src` → 0 (today 12);
  - `uv run pytest tests/tui_group_options/test_write_back_contract.py tests/tui/test_command_path_surface.py tests/cli/tui/test_descriptor_fields.py tests/cli/test_pending_execution_integration.py`;
  - kit `tui_extra.py` → 0 rows (today 91), W-collapse → 0 (today 34).
- **Reachability:** TUI run → `job_execution.run_job` → `app.job_kwargs_for` → the click parse.
- **Depends on:** 3.1.

### [ ] 4.3 Bar readiness and the pre-boot group walk read the contract (F-10)

- **Input:** 3.1; `job-param-string-reads` hits at `bar.py:294` and `dispatch.py:715`.
- **[F]:**
  - `src/functualize/_cli/tui/bar.py`;
  - `src/functualize/_cli/dispatch.py`;
  - `src/functualize/app/commands.py`.
- **Work:**
  - Arity comes from `contract.shape`, not `== "bool"`.
  - `walk_group_path` accumulates repeated group flags into a list for repeatable group fields.
  - `JobNode.params()` keeps returning cached descriptors, now carrying contracts.
- **Gate/evidence:**
  - `rg -n -F 'type_annotation == "bool"' src/functualize/_cli/dispatch.py` → 0 (today 1);
  - the kit's `func g160g --p a --p b run` gives `['a', 'b']` (today `['b']`);
  - `uv run pytest tests/cli/tui/test_bar_properties.py tests/cli/test_pre_boot_resolution.py`.
- **Depends on:** 3.1.

## Wave 5 — the engine door

### [ ] 5.1 Bind at the door; DI fills only `INJECTED`; kind from the contract

- **Input:**
  - 2.1 to 2.3, and 0.2;
  - `gates-authoring.txt` `engine-old-binding`: 7 hits (`executor.py` 3, `validation.py` 4);
  - `registry-kind`: 2 hits in `resolution.py`.
- **[F]:**
  - `src/functualize/_engine/executor.py`;
  - `src/functualize/_engine/resolution.py`;
  - `src/functualize/_engine/validation.py` (deleted);
  - `tests/engine/test_binding_door.py` (new).
- **Work:**
  - At `executor.py:1393-1486`, replace `unexpected_keyword_error` (workflows only) and
    `ArgValidator` with `bind`, before DI resolution and before `PRE_EXECUTE`.
  - DI fills `INJECTED` names only. A caller key for one never arrives, because `bind` refuses it.
  - `build_resolution_plan` reads `contract.verdict`, so `base_type in registered_types` and
    "Optional[T] is always classified as di" go.
  - A missing provider refuses before the call, on cold and warm alike (F-33).
  - `BindRefusal` becomes `JobResult(status=INVALID)`.
- **Invariant:** `JobExecutionEngine` does not grow: `ast` line count ≤ 2,747 (`executor.py:213-2959`
  at `da912d76`).
- **Gate/evidence:**
  - `rg -n -w -e ArgValidator -e unexpected_keyword_error src` → 0 (today 7);
  - `rg -n 'base_type in registered_types' src/functualize/_engine/resolution.py` → 0 (today 1);
  - `uv run pytest tests/engine/ tests/execution/test_resolution_plan.py tests/test_resolution_plan_properties.py`;
  - kit `str-provider.txt` repro: every `str` job runs;
  - kit `unknown-keys.txt` repro: all five surfaces refuse `zzz`;
  - kit `surf_check.py` W-inject → 0 (today 35), W-crash → 0 (today 50), W-type → 0 (today 49),
    W-default → 0 (today 14);
  - `cold_compare.py` → 0 real differences (today F-33 rows C085, C087, E138, H166).
- **Reachability:** `FunctualizeApp.execute(RunRequest)` → `engine.run` → `_execute_lifecycle` →
  `bind`.
- **Depends on:** 2.1, 2.2, 2.3, 0.2.

### [ ] 5.2 The CLI renders `INVALID` as a one-line usage error (pitfalls §25)

- **Input:** 0.2; `click_params.prelude_refusal`.
- **[F]:**
  - `src/functualize/app/adapters/click_params.py`;
  - `tests/cli/test_invalid_call_rendering.py` (new).
- **Work:** add an `INVALID` arm to `prelude_refusal` and the result delivery: exit 2, one line, no
  frames.
- **Gate/evidence:** the new test runs `func` in a subprocess for a missing, an unknown, an injected
  and a non-converting argument. It asserts `stderr` contains no `File "` and the exit code is 2.
- **Depends on:** 0.2. 3.1 has already changed this file (an earlier wave).

## Wave 6 — the one schema

### [ ] 6.1 `job_input_schema` reads contracts and merges group options once (D4, F-02, F-13, F-34)

- **Input:**
  - 2.1 and 2.2;
  - `type-maps` gate: `job_schema.py` 3 hits;
  - `injection-by-type-name`: `job_schema.py:185`.
- **[F]:**
  - `src/functualize/_primitives/job_schema.py`;
  - `src/functualize/_cli/info.py`;
  - `src/functualize/app/utils.py`.
- **Work:**
  - The properties are `contract.json_schema`. `required` is the contracts' requiredness.
  - Group options are merged inside `job_input_schema`, so `info` and MCP are identical by
    construction.
  - `TYPE_MAP` goes.
- **Gate/evidence:**
  - `rg -n -w TYPE_MAP src/functualize/_primitives/job_schema.py` → 0 (today 3);
  - kit `check.py` predicates `array`, `type`, `identity` and `required` → 0 rows (today 17, 8, 2
    and 19);
  - `uv run pytest tests/cli/test_schema_surface_parity.py tests/app/test_dynamic_registration.py`.
- **Depends on:** 2.1, 2.2.

## Wave 7 — MCP, the AI tool scope, and the wrappers retired

### [ ] 7.1 MCP registers from the schema, without `exec`, and reports failures (F-12, F-24, F-31)

- **Input:** 6.1; `gates-authoring.txt` `mcp-exec` (1 hit) and `type-maps` (`_server.py` 2,
  `_schema_export.py` 3); fastmcp 4.0.3 `Tool.parameters`, `Tool.run(arguments)`,
  `FastMCP.add_tool(tool)`.
- **[F]:**
  - `plugins/adapters/functualize-mcp/src/functualize_mcp/_server.py`;
  - `plugins/adapters/functualize-mcp/src/functualize_mcp/_translator.py`;
  - `plugins/adapters/functualize-mcp/src/functualize_mcp/_schema_export.py`.
- **Work:**
  - One `Tool` subclass per job carries `parameters=job_input_schema(...)`; its `run` builds a
    `RunRequest`.
  - The translator stops merging group options, because 6.1 merges them.
  - A failed run returns `isError: true` with the reason.
  - The schema exports read the one schema. The JSON → TypeScript name map stays: it maps JSON types,
    not Python ones.
- **Gate/evidence:**
  - `rg -n 'exec\(fn_source' plugins/adapters/functualize-mcp/src` → 0 (today 1);
  - kit: `func mcp serve` starts with G156 present, and every `tools/call` row agrees with HTTP;
  - `uv run pytest plugins/adapters/functualize-mcp/tests/ tests/plugins/test_mcp_translator.py tests/plugins/test_mcp_translation_properties.py tests/plugins/test_mcp_tools.py`.
- **Depends on:** 6.1.

### [ ] 7.2 The AI `ToolScope` reads the one schema (spec revision S-1)

- **Input:** 6.1; `type-maps` gate: `_tool_scope.py` 4 hits.
- **[F]:** `plugins/domains/functualize-ai/src/functualize_ai/_tool_scope.py`.
- **Work:** `_fields_to_schema`, `_python_type_to_json_type` and `_annotation_to_json_type` are
  replaced by `job_input_schema`.
- **Gate/evidence:**
  - `rg -n -e _python_type_to_json_type -e _annotation_to_json_type plugins/domains/functualize-ai/src` → 0 (today 4);
  - `uv run pytest plugins/domains/functualize-ai/tests/`.
- **Depends on:** 6.1.

### [ ] 7.3 Retire the transitional click wrappers

- **Input:** 3.1's `# TRANSITIONAL(7.3)` markers; the 13 test modules in `blast-radius.txt`
  `click_builders`.
- **[F]:**
  - `src/functualize/app/adapters/click_params.py`;
  - `src/functualize/_cli/main.py`;
  - `tests/adapters/test_click_params_parity.py`, `tests/adapters/test_boolean_negation.py`;
  - `tests/cli/test_arg_marker_unit.py`, `tests/cli/test_positional_arg_properties.py`;
  - `tests/group_options/test_group_options_surfaces.py`;
  - `tests/test_lazy_wrapper.py`, `tests/test_lazy_wrapper_properties.py`;
  - `tests/types/test_flag_grammar_roundtrip.py`;
  - `tests/config/test_surface_boot_config_parity.py`.
- **Work:**
  - Delete the wrappers, `_click_type_for`, `_field_click_type`, `_resolve_type_string`,
    `_option_from_marker` and `_get_list_inner_type`.
  - Callers, including `_cli/main.py:898` `_render_group_option_rows`, call the renderer.
  - Rewrite those tests against `render_click_params`.
- **Gate/evidence:**
  - `rg -n -e TRANSITIONAL\(7.3\) -e _resolve_type_string -e _click_type_for -e _get_list_inner_type src` → 0;
  - `uv run pytest tests/adapters/ tests/cli/ tests/types/ tests/group_options/`.
- **Depends on:** 3.1, 4.1, 4.2, 4.3, 5.2. This file was last changed in wave 5.

## Wave 8 — D7 deletions

### [ ] 8.1 Dead code in `_cli`

- **Input:** `gates-authoring.txt` `dead-symbols`: 17 hits.
- **[F]:**
  - `src/functualize/_cli/annotation_utils.py` (deleted; `parse_annotation` has no remaining caller
    after 7.3);
  - `src/functualize/_cli/completions/engine.py`, `src/functualize/_cli/completions/__init__.py`;
  - `src/functualize/_cli/tui/type_hint_formatter.py` (deleted), `src/functualize/_cli/tui/__init__.py`;
  - `src/functualize/_engine/stdin_reader.py` (a docstring that names the deleted module);
  - `tests/cli/test_annotation_utils_properties.py`, `tests/cli/test_cli_compatible_type.py`;
  - `tests/_cli/test_type_hint_formatter.py`, `tests/cli/tui/test_completer_properties.py`.
- **Work:**
  - Delete `SwappableCompleter`, `format_type_hint` and its `_TYPE_MAP`, and
    `parse_annotation`/`AnnotationInfo` (including the write-only `field_metadata`).
  - Their tests go with them. Any assertion still meaningful moves to 1.1's tests first.
- **Gate/evidence:**
  - `rg -n -w -e SwappableCompleter -e format_type_hint -e field_metadata src` → 0 (today 17 with `coerce_kwargs`, which is 8.2's);
  - `rg -n 'annotation_utils' src plugins/*/*/src -g '*.py'` → only the prose mention in
    `_engine/stdin_reader.py:241`, which is updated (today 4 hits);
  - `uv run pytest tests/cli tests/_cli`.
- **Depends on:** 7.3.

### [ ] 8.2 Dead and superseded code in `app/utils`, `_discovery`, `_config`, `_app`

- **Input:**
  - `dead-symbols`: `coerce_kwargs`, `_resolve_type` (`app/utils.py`);
  - `optional-unwrappers`: 5 hits; `list-unwrappers`: 3 hits;
  - `type-maps`: `providers.py` 6 and `schema_extractor.py` 5;
  - `validate-config`: 5 hits.
- **[F]:**
  - `src/functualize/app/utils.py`;
  - `src/functualize/_discovery/providers.py`;
  - `src/functualize/_discovery/schema_extractor.py`;
  - `src/functualize/_config/job_config.py`;
  - `src/functualize/_app/boot.py`;
  - `tests/test_coerce_kwargs.py`, `tests/test_property_type_coercion_roundtrip.py`.
- **Work:**
  - Delete `coerce_kwargs` and `_resolve_type`, `_annotation_to_type_str` (the display label now
    comes from the contract), `_unwrap_optional` ×4 and `_unwrap_list` ×2 where a contract now
    answers, and `schema_extractor`'s type maps.
  - `validate_job_config_types` and its boot wiring go; 2.2's refusal replaces them.
  - Keep any unwrapper still used outside parameter classification, and say which in the task
    record.
- **Gate/evidence:**
  - `rg -n -w -e coerce_kwargs -e _resolve_type -e _annotation_to_type_str -e _JSON_SCHEMA_TYPE_MAP -e validate_job_config_types src` → 0;
  - the behaviour-pattern gate (`job-param-string-reads` plus `injection-by-type-name`) → 0 (today
    7 + 3);
  - `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`, with every finding
    classified;
  - `uv run pytest tests/discovery tests/config`.
- **Depends on:** 7.3, 5.1, 6.1.

## Wave 9 — stop depending on `type_annotation` (SS-3 = B)

Counts measured at authoring time on `6ff7182a` (`matrix/evidence/ss3b-counts.txt`,
`ss3b-remaining.txt`):

- `rg -n '\.type_annotation' src plugins -g '*.py' -g '!**/tests/**'` gives **22 occurrences in
  10 files**.
- `rg -l -w type_annotation src plugins -g '*.py' -g '!**/tests/**'` gives **27 files** (re-run on
  `2058c56b`; the earlier "26" came from a query that left out `plugins/conftest.py`).
  - **17** are already in a wave 0–8 task's `[F]` and are cleared by the rule above.
  - **10** are scoped here:
    - 9.2: `_cli/data/toml_writer.py`, `_cli/tui/panels/config_table.py`,
      `_cli/tui/settings_panel.py`, `_cli/tui/source_chain_detail.py`;
    - 9.3: `plugins/conftest.py`, `_cli/introspect.py`, `_cli/tui/preflight_summary.py`,
      `_cli/tui/source_chain_providers.py`, `_types/flag_grammar.py`, `app/_workflow_view.py`.
  - 9.2 also edits `_cli/tui/chain_resolution.py`, one of the 17 (task 4.2), for the `FieldDef`
    rename.
- Test and fixture files mentioning it: **53**. 8 are in earlier tasks' `[F]`; the other 45 are
  scoped in wave 10.

### [ ] 9.1 The descriptor stops carrying the string: alias and codec keys go, the field becomes transitional

- **Input:**
  - `_types/descriptors.py:87-89` (the `type` property, "Backward-compatible alias for
    type_annotation");
  - `:636` (the codec writes `"type_annotation"`);
  - `:700-701` (the decoder accepts `"type_annotation"` or the legacy `"type"`).
- **[F]:**
  - `src/functualize/_types/descriptors.py`;
  - `tests/test_descriptor.py`, `tests/test_property_field_descriptor_extraction.py`.
- **Work:**
  - Delete the `type` property. Its only reader is `tests/test_descriptor.py:386` (serena
    `find_referencing_symbols`). The one production fallback to a `type` attribute,
    `_tool_scope.py:422`, is rewritten by 7.2.
  - The codec stops writing `type_annotation` and stops reading `type_annotation` **and** the
    legacy `"type"` key. **Decision: no legacy key survives.** Task 0.1 bumped `CACHE_VERSION` from
    25 to 26, so a cache written by an older version is not decoded but rebuilt, once
    (`pitfalls.md` §5).
  - `type_annotation` gets the default `""`, marked `# TRANSITIONAL(10.1): removed once every
    reader and test is off it`.
- **Gate/evidence:**
  - `rg -n -F -e 'def type(' -e 'else "type"' src/functualize/_types/descriptors.py` → 0 (today 2: `:87`
    the alias, `:701` the legacy key);
  - `uv run pytest tests/test_descriptor.py tests/test_property_field_descriptor_extraction.py tests/discovery/test_cache_manager.py`.
- **Depends on:** 8.1, 8.2.

### [ ] 9.2 The TUI row model's field is renamed `type_label`

- **Input:** `FieldDef` (`_cli/tui/panels/config_table.py:73`) is a separate TUI view-model class
  with its own `type_annotation: str = "str"` (`:86`). It is constructed at `chain_resolution.py:156`,
  `:269`, `settings_panel.py:359` and `source_chain_detail.py:429`, and described in
  `_cli/data/toml_writer.py:6`, `:60` and `:86`.
- **[F]:**
  - `src/functualize/_cli/tui/panels/config_table.py`;
  - `src/functualize/_cli/tui/chain_resolution.py`;
  - `src/functualize/_cli/tui/settings_panel.py`;
  - `src/functualize/_cli/tui/source_chain_detail.py`;
  - `src/functualize/_cli/data/toml_writer.py`.
- **Work:**
  - Rename the field to `type_label`. Job rows fill it from `contract.display`; settings rows fill
    it from `Setting.type` as today.
  - **Why rename a field SS-3 did not name:** it is private TUI state, and with the old name the
    removal gate `rg '\.type_annotation'` could never reach 0 honestly.
- **Gate/evidence:**
  - `rg -n -w type_annotation src/functualize/_cli/tui/panels/config_table.py src/functualize/_cli/tui/chain_resolution.py src/functualize/_cli/tui/settings_panel.py src/functualize/_cli/tui/source_chain_detail.py src/functualize/_cli/data/toml_writer.py` → 0;
  - `uv run pytest tests/cli tests/_cli -k "chain or preflight or settings or toml"`.
- **Depends on:** 8.1, 8.2.

### [ ] 9.3 The remaining production readers read the contract

- **Input:** `ss3b-remaining.txt`, production files not in an earlier task's `[F]`, minus 9.2's.
- **[F]:**
  - `src/functualize/_cli/introspect.py`;
  - `src/functualize/_cli/tui/preflight_summary.py`;
  - `src/functualize/_cli/tui/source_chain_providers.py`;
  - `src/functualize/_types/flag_grammar.py`;
  - `src/functualize/app/_workflow_view.py`;
  - `plugins/conftest.py`, `plugins/adapters/functualize-mcp/tests/conftest.py`.
- **Work:**
  - Display reads become `contract.display`.
  - `flag_grammar.py:153`'s `!= "bool"` becomes `contract.shape.scalar is Scalar.BOOL`.
  - The two plugin conftests build descriptors with `contract=`.
- **Gate/evidence:**
  - `rg -n -w type_annotation` over these 7 files → 0;
  - `uv run pytest tests/cli/test_introspector.py tests/types/ plugins/adapters/functualize-mcp/tests/`.
- **Depends on:** 8.1, 8.2.

## Wave 10 — `type_annotation` is deleted (SS-3 = B)

The tasks in this wave are independent. Each migrates only its own test files. 10.1 deletes the
field, and the wave is complete when the whole suite is green with it gone.

### [ ] 10.1 Delete `FieldDescriptor.type_annotation`

- **[F]:** `src/functualize/_types/descriptors.py`.
- **Work:** remove the field and its `TRANSITIONAL(10.1)` marker. Every constructor already passes
  `contract=` (2.1, 2.2, 4.3).
- **Gate/evidence:**
  - `rg -n '\.type_annotation' src plugins -g '*.py'` → 0 (today 22 occurrences in 10 production
    files);
  - `rg -n -w type_annotation src plugins -g '*.py' -g '!**/tests/**'` → 0 (today 72 occurrences in
    27 files);
  - after 10.2–10.4: `rg -l -w type_annotation tests plugins -g '*.py'` → 0 (today 53);
  - `uv run pytest` (the full suite, at the end of the wave).
- **Depends on:** 9.1, 9.2, 9.3.

### [ ] 10.2 Migrate the CLI test modules

- **[F]:**
  - `tests/cli/`:
    - `test_chain_drill_down.py`, `test_chain_kind_aware.py`, `test_cross_panel_sync.py`;
    - `test_diff_view_wiring.py`, `test_enum_parameter_roundtrip.py`;
    - `test_introspect_values.py`, `test_introspect_values_unit.py`, `test_introspector.py`;
    - `test_param_kind.py`, `test_pending_execution_integration.py`;
    - `test_preflight_compact.py`, `test_preflight_enriched.py`, `test_preflight_truncation.py`.
  - `tests/_cli/`:
    - `test_completion_flag_pairs.py`, `test_inline_tui_v2_autocomplete_integration.py`;
    - `test_orchestrator_handoff.py`, `test_secret_masking_surfaces.py`.
- **Work:** construct descriptors with `contract=`, and assert `contract.display` where a test
  checks a type label.
- **Gate/evidence:** `rg -l -w type_annotation` over these 17 files → 0; `uv run pytest tests/cli tests/_cli`.
- **Depends on:** 9.1, 9.2, 9.3.

### [ ] 10.3 Migrate the plugin and discovery test modules

- **[F]:**
  - `tests/plugins/`:
    - `test_mcp_server.py`, `test_mcp_tools.py`, `test_mcp_translation_properties.py`;
    - `test_mcp_translator.py`, `test_mcp_visibility_properties.py`;
    - `test_schema_export.py`, `test_schema_export_properties.py`;
    - `test_three_doors_agree.py`, `test_tool_scope.py`.
  - `tests/discovery/`:
    - `test_di_exclusion_properties.py`, `test_parameter_extraction.py`, `test_schema_extractor.py`;
    - `test_transform_group_filter_property.py`, `test_transform_identity_property.py`;
    - `test_transform_namespace_property.py`, `test_transform_rename_property.py`.
- **Work:** as 10.2.
- **Gate/evidence:** `rg -l -w type_annotation tests/plugins tests/discovery` → 0;
  `uv run pytest tests/plugins tests/discovery`.
- **Depends on:** 9.1, 9.2, 9.3.

### [ ] 10.4 Migrate the remaining test modules

- **[F]:**
  - `tests/test_schema_extractor_properties.py`;
  - `tests/config/test_pep563_annotation_sites.py`;
  - `tests/app/test_dynamic_registration.py`;
  - `tests/group_options/`:
    - `test_combination_matrix.py`, `test_group_options_discovery.py`;
    - `test_group_options_dispatch.py`, `test_tui_group_flags.py`;
  - `tests/tui_group_options/test_write_back_contract.py`.
- **Work:** as 10.2.
- **Gate/evidence:** `rg -l -w type_annotation` over these 8 files → 0; `uv run pytest tests/group_options tests/tui_group_options tests/config tests/app tests/test_schema_extractor_properties.py`.
- **Depends on:** 9.1, 9.2, 9.3.

## Wave 11 — documentation and the parity test

### [ ] 11.1 Docs, changelog, ADR amendments, codemap correction

- **[F]:**
  - `docs/guides/jobs-discovery.md`, `docs/guides/job-config.md`;
  - `CHANGELOG.md`;
  - `contributor/adr/010-job-schema-in-core.md`, `contributor/adr/018-unsatisfiable-jobs-are-reported-not-fatal.md`;
  - `contributor/architecture/codemaps/data-flow.md`.
- **Work:**
  - `jobs-discovery.md` gains *Which parameters are inputs*, rendered from the table.
  - `job-config.md:47-69` now describes the refusal that actually runs.
  - `CHANGELOG.md` lists every visible change (`spec.md` § *Evidence and constraints*), including
    the public API removal of `functualize.types.FieldDescriptor.type_annotation` and its `type`
    alias (SS-3 = B), with the replacement: `FieldDescriptor.contract`.
  - ADR-010 records that its renderer now reads contracts. ADR-018 records the cold-path fix and
    the `UnsupportedParameter` sibling.
  - `data-flow.md` §2's priority line matches the code: the caller never reaches an `INJECTED`
    parameter.
- **Gate/evidence:** `uv run mkdocs build --strict` (`mkdocs.yml` is at the repository root), and
  11.2's docs-table test.
- **Depends on:** 10.1, 10.2, 10.3, 10.4.

### [ ] 11.2 The parity test (AC-10), with the three cross-builder tests folded in

- **[F]:**
  - `tests/surfaces/test_parameter_surface_parity.py` (new), `tests/surfaces/test_parameter_docs_table.py` (new);
  - `tests/adapters/test_cold_warm_parity.py`, `tests/config/test_click_builder_agreement.py` and
    `tests/cli/test_schema_surface_parity.py` (deleted, assertions migrated).
- **Work:**
  - From `tests/_support/parameter_matrix.py`, drive help, bash, zsh, SmartBar, the TUI door, info,
    the MCP schema and call, HTTP and Lambda for every row, cold and warm, in both PEP 563 modes.
    Use subprocesses where `pitfalls.md` §23 and §25 require them.
  - Assert the row's verdict on every surface.
- **Gate/evidence:** green under `uv run pytest tests/surfaces/`, and runnable within the 600 s
  tool-call cap. If not, split it by row group, as the `test-tiers` skill prescribes.
- **Depends on:** 10.1, 10.2, 10.3, 10.4. The docs-table half also depends on 11.1.

## Wave 12 — checkpoint

### [ ] 12.1 Acceptance checkpoint (AC-1 to AC-13)

- **Work:** run every gate in `spec.md` § *Acceptance checks* from `matrix/`, cold and warm, in both
  PEP 563 modes. That includes the coverage census (0 executed statements in deleted symbols:
  vacuous, because they are gone, so the census also confirms their files no longer exist) and the
  repository's five checks.
- **Gate/evidence:** every AC row's "must show after the change" column, pasted as command plus
  output into the task record.
- **Depends on:** all earlier tasks.

## Wave 13 — artifact clearing

### [ ] 13.1 Two-push clearing sequence

- **Work:**
  - Migrate the durable half (the decision to ADRs, already done in 11.1; the status to
    `.spec/STATUS.md`).
  - Push the feature commits and let validation pass.
  - Then make one deletion-only commit, `git rm -r .spec/features/parameter-contract`, and push it.
- **Gate/evidence:** `git ls-files .spec/features/parameter-contract` is empty; `git show --stat HEAD`
  shows deletions only; `spec-artifacts-cleared` passes.
- **Depends on:** 12.1.

## Task Dependency Graph

```json
{
  "waves": [   { "id": 0, "tasks": [   "0.1",   "0.2",   "0.3",   "0.4",   "0.5" ]
    },
    { "id": 1, "tasks": [   "1.1" ]
    },
    { "id": 2, "tasks": [   "2.1",   "2.2",   "2.3" ]
    },
    { "id": 3, "tasks": [   "3.1" ]
    },
    { "id": 4, "tasks": [   "4.1",   "4.2",   "4.3" ]
    },
    { "id": 5, "tasks": [   "5.1",   "5.2" ]
    },
    { "id": 6, "tasks": [   "6.1" ]
    },
    { "id": 7, "tasks": [   "7.1",   "7.2",   "7.3" ]
    },
    { "id": 8, "tasks": [   "8.1",   "8.2" ]
    },
    { "id": 9, "tasks": [   "9.1",   "9.2",   "9.3" ]
    },
    { "id": 10, "tasks": [   "10.1",   "10.2",   "10.3",   "10.4" ]
    },
    { "id": 11, "tasks": [   "11.1",   "11.2" ]
    },
    { "id": 12, "tasks": [   "12.1" ]
    },
    { "id": 13, "tasks": [   "13.1" ]
    }
  ]
}
```
