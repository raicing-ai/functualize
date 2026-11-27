# Plan — inherited group options in AI tools

## Alignment

The grandfathered Confluence [Shape Intent SD/30343171 v5](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/30343171) has `Authority: Approved`; the designer review is issue comment `01a21b0d-ca08-789a-8561-9197537911b4`. The member confirmed this feature's `spec.md` and `contracts.md` at `dafebbcf3f1a72e343d074c54caa8462fca08965` in comment `01a21d11-52fc-7d44-bbf8-cef05ee7dd22`. The Confluence authority cutover rule applies, so there is no shape-file commit SHA for this issue.

In scope, in the shape's terms: **app-wired AI `ToolDef.parameters_schema`**, the inherited `AI.run(prompt, tools=scope)` call, `PydanticAI._resolve_tool_defs`, and optional context for direct `to_tool_defs(registry)`. Out of scope: **`workflow_view.tool_summaries`**, a separate caller-facing projection.

## Architecture gate

The prose pass found ADR-010's one-renderer decision and the wiring guide's group-option stub failure. Serena inspected the live `ToolScope`, `AI`, and plugin symbols and their references. Graphify showed `PydanticAI -> AI`, `AI.run -> ToolScope`, and publisher calls to `job_input_schema`; its graph is 61 commits behind the base and was used for dependency direction only. The current source and the codemaps supplied paths and layer labels. `uv run lint-imports` reports seven kept contracts and zero broken before this change. The existing root test selection passed before product edits: 180 passed, 7 skipped in 537.91 seconds with a 570-second bound; the execution gate uses xdist to retain headroom for added cases. The combined plugin selection failed during collection with `ImportPathMismatchError` because the two plugin packages expose distinct `tests/conftest.py` under the same import name. `--import-mode=importlib` still failed with a plugin registration collision, so the plugin package selections must run separately; no further flag variation was attempted.

BEFORE (arrows mean calls/imports; brackets give audience and layer):

```text
src/functualize/_cli/info.py [internal _cli delivery]
  -> src/functualize/app/utils.py [public app facade]
  -> src/functualize/_primitives/job_schema.py [internal _primitives foundation]
     job_input_schema(descriptor, class names, cached group options)

plugins/adapters/functualize-mcp/src/functualize_mcp/_translator.py [plugin delivery]
  -> src/functualize/app/utils.py [public app facade: fingerprinted cache + renderer]
  -> src/functualize/_primitives/job_schema.py [internal foundation]

plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py [plugin composition]
  -- app job registry only --> plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_pydantic_ai.py [plugin implementation]
  -> plugins/domains/functualize-ai/src/functualize_ai/_ai.py [plugin domain SDK: AI.run selects caller registry or []]
  -> plugins/domains/functualize-ai/src/functualize_ai/_tool_scope.py [plugin domain SDK: descriptor-only schema]
  -> src/functualize/app/utils.py [public app facade: job_input_schema]
  -> src/functualize/_primitives/job_schema.py [internal foundation]

src/functualize/app/_workflow_view.py [public app implementation]
  -> separate tool_summaries projection; no ToolDef edge (excluded)
```

The existing **Shotgun Surgery** is registry selection in `AI.run` and `PydanticAI._resolve_tool_defs`: the two entry points must be changed together, and today choose different registries. The schema renderer itself is shared, but AI omits the context that its two peer publishers pass.

AFTER (the same boundaries, with context passed as data):

```text
src/functualize/_cli/info.py [internal _cli delivery]
  -> src/functualize/app/utils.py [public app facade]
  -> src/functualize/_primitives/job_schema.py [internal foundation]
plugins/adapters/functualize-mcp/src/functualize_mcp/_translator.py [plugin delivery]
  -> src/functualize/app/utils.py [public app facade]
  -> src/functualize/_primitives/job_schema.py [internal foundation]

app APP_READY -> plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py [plugin composition]
  -> src/functualize/app/utils.py [public app facade: resolve_cache_path,
       discovery_hash_for(app), read_group_options_from_cache]
  -- registry + fingerprinted group map --> plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_pydantic_ai.py [plugin implementation]
  -> plugins/domains/functualize-ai/src/functualize_ai/_ai.py [plugin domain SDK: one registry resolution helper]
  -> plugins/domains/functualize-ai/src/functualize_ai/_tool_scope.py [plugin domain SDK: optional context]
  -> src/functualize/app/utils.py [public app facade: job_input_schema]
  -> src/functualize/_primitives/job_schema.py [internal foundation: merge and exclusion unchanged]

src/functualize/app/_workflow_view.py [public app implementation]
  -> separate tool_summaries projection; unchanged
```

The only new boundary crossing is a plugin's call to the existing public `functualize.app.utils` cache and schema functions; it does not import an internal core layer or the MCP plugin. The context is stored on the AI base alongside the registry. The Pydantic subclass forwards both and delegates tool resolution to the base helper. This removes the duplicated registry choice without adding a second schema converter. The approved shape still permits an explicit caller registry with stored app context; a foreign registry sharing a group path could inherit this app's options, a narrow compatibility risk to document and test if the fixture makes it observable.

Consulted skills: repository `python-design-patterns` (single responsibility, simple injected data) and user `design-patterns-refactoring` (Shotgun Surgery, Duplicate Code). Candidate review rejected an AI-local group converter because it would recreate the schema duplication ADR-010 removed. It also rejected importing the MCP translator into the AI plugin because that reverses the plugin boundary. The settled AFTER adds no forbidden peer-layer import, singleton, or new renderer.

## Technical approach

1. Restore the documented app-injected `AI.run` behavior first: the base AI owns the optional registry, chooses an explicit caller registry over it (including `[]`), and shares that choice with the Pydantic resolver. Prove a tool reaches a recording provider through the app-injected instance.
2. Read the app-fingerprinted group map at the Pydantic plugin's APP_READY hook with the same three public core functions MCP uses. Pass that optional map through the Pydantic constructor and AI base to `ToolScope`. Derive class names from each declaration's `class_name`; call the existing `job_input_schema` with both names and map. Preserve the descriptor-only result when the map is absent. Extend the existing group-options surface parity fixture and its MCP comparison, including nested inheritance, collision, injection exclusion, optional requiredness, and a provider recorder. Capture the same fixture's before and after output.
3. Amend the AI guide and changelog to state the restored app-injected call behavior and its contextless boundary.
4. Run the focused root and plugin suites and quality gates; use PR CI for the full suite. After each production wiring step, commit before a deliberate break, observe a failing relevant test, restore safely, then tick the task.

Expected source and test hit set from Serena references and `rg -l` on the resolution symbols: `plugins/domains/functualize-ai/src/functualize_ai/_ai.py`, `_tool_scope.py`; `plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_pydantic_ai.py`, `_plugin.py`; `tests/group_options/test_surface_parity.py`; `tests/plugins/test_tool_scope.py`. The Pydantic provider and AI capability tests are verification neighbors. The MCP translator, core renderer, and workflow view remain unedited.

## Risks and gates

- Cache freshness: pass `discovery_hash_for(app)` explicitly; a stale section must not be offered. The app hook runs after job registration. Exercise cold and warm app paths where the parity fixture supports them.
- Compatibility: `to_tool_defs(registry)` and directly constructed `AI` keep descriptor-only schemas; `[]` overrides a stored registry.
- Collision and requiredness: compare full AI, info, and MCP schema objects, rather than only property names.
- Test boundaries: root pytest does not collect plugin package tests. Run each plugin package's tests in its own pytest process; the two combined collection modes failed as above. Pair one plugin selection with each implementation task's root selection so each verification has at most two invocations. Use `--run-slow` and `-n auto` only on root selections; the serial pre-change root selection took 537.91 seconds. Bound each local invocation with `timeout 570` and use CI for the full suite.

## Surviving smells

- **Duplicate Code** — the short cache-acquisition sequence in the Pydantic plugin and MCP translator both calls `resolve_cache_path`, `discovery_hash_for`, and `read_group_options_from_cache`. This remains because the approved shape requires independent plugin packages to use the core public seam, and a shared wrapper would add an abstraction for two small call sites. The schema conversion itself remains single-source. Maintainer review: no; the approved shape already decides this boundary.
