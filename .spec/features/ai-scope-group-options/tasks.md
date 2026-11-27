# Tasks — inherited group options in AI tools

Only an unchecked task in the lowest incomplete wave may start. Each task is checked only after its own gate and a production-path sabotage pass. Commit finished code before sabotage, restore the deliberate break, then tick the box in the task's completion commit. The graph below keeps dependent changes serial.

## Wave 0 — app-injected registry fallback

- [x] **1.1 — Offer app jobs through inherited `AI.run` without a caller registry.**
  - Scope: `plugins/domains/functualize-ai/src/functualize_ai/_ai.py`; `plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_pydantic_ai.py`; `tests/group_options/test_surface_parity.py`.
  - Behavior: store the registry once on base `AI`; Pydantic forwards it and delegates registry resolution. Explicit `job_registry=[]` wins. Directly constructed AI and contextless calls keep their current result. This is transitional: app-injected `AI.run` now offers descriptor-only jobs, but their inherited group fields remain absent until 2.1. Mark that site `# TRANSITIONAL(2.1): ...` in code and remove the marker when 2.1 lands; do not claim group parity at this checkpoint.
  - Gate: in the real app fixture, the injected capability's `AI.run(prompt, tools=scope)` sends the scoped job to a provider recorder without `job_registry=`; explicit `[]` sends no job tool; the standalone case stays descriptor-only. Run `timeout 570 uv run pytest --run-slow -n auto -q --no-header tests/group_options/test_surface_parity.py` and, in a separate process, `timeout 570 uv run pytest -q --no-header plugins/domains/functualize-ai-pydantic/tests/test_pydantic_provider.py` (both paths exist). Production path: app APP_READY -> plugin constructs PydanticAI with registry -> inherited AI.run -> ToolScope -> provider. Commit first, break the base registry fallback, see this test fail, restore, then tick.

## Wave 1 — inherited group-option schema parity

- [ ] **2.1 — Pass app-fingerprinted group declarations through AI tool schema publication.**
  - Scope: `plugins/domains/functualize-ai/src/functualize_ai/_tool_scope.py`; `plugins/domains/functualize-ai/src/functualize_ai/_ai.py`; `plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_pydantic_ai.py`; `plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py`; `tests/group_options/test_surface_parity.py`; `tests/plugins/test_tool_scope.py`.
  - Behavior: optional `group_context` on scope resolution, optional stored context on AI, one core-renderer call with class names and map; plugin obtains the map through public core cache functions at APP_READY. No `functualize_mcp` import. Contextless callers are unchanged. This larger vertical task is one unit because its new context path is only production-reachable after the plugin, AI, and scope are connected.
  - Gate: extend the existing MCP parity cell with app-wired AI `ToolDef.parameters_schema == info inputSchema == MCP inputSchema`; check inherited nested options, own-field collision, injected parameter exclusion, and inherited fields outside `required`. The provider recorder observes the same job tool through `AI.run`, and the Pydantic resolver agrees. Add focused contextless and `[]` tests. Capture pre-fix and post-fix fixture outputs. Run `timeout 570 uv run pytest --run-slow -n auto -q --no-header tests/group_options/test_surface_parity.py tests/plugins/test_tool_scope.py` and, separately, `timeout 570 uv run pytest -q --no-header plugins/domains/functualize-ai/tests/test_ai_capability.py` (all paths exist). Production path: APP_READY -> fingerprinted cache -> PydanticAI -> AI.run / Pydantic resolver -> ToolScope -> core `job_input_schema` -> provider. Commit first, break the plugin's context handoff, see the parity test fail, restore, then tick.

## Wave 2 — public explanation

- [ ] **3.1 — Document the restored app-injected call shape.**
  - Scope: `CHANGELOG.md`; `docs/guides/ai.md`.
  - Behavior: state that app-injected `ai.run(prompt, tools=scope)` now offers the scope's jobs without `job_registry=`, and that directly constructed AI and contextless scope resolution remain descriptor-only. Use the guide's existing `ai.run` example as the anchor.
  - Gate: `rg -n 'ai.run\(|ToolScope.only' docs/guides/ai.md` identifies the guide's call site; `git diff --check` and `uv run ruff format --check src/ tests/ plugins/ examples/` stay green. Documentation needs no code sabotage.

## Wave 3 — checkpoint

- [ ] **4.1 — Verify the final branch and prepare the review handoff.**
  - Scope: task-state artifacts only; no product change expected.
  - Gate: `uv run ruff check src/ tests/ plugins/ examples/`, `uv run ruff format --check src/ tests/ plugins/ examples/`, `uv run mypy src/`, `uv run lint-imports`, and one bounded root selection: `timeout 570 uv run pytest --run-slow -n auto -q --no-header tests/group_options/test_surface_parity.py tests/surfaces/test_parameter_surface_parity.py tests/plugins/test_tool_scope.py tests/plugins/test_tool_scope_properties.py tests/plugins/test_tool_scope_translation_properties.py`. The pre-change serial root selection passed 180 tests with 7 skips in 537.91 seconds; xdist supplies headroom for new cases. The plugin package suites are separately gated in tasks 1.1 and 2.1 because combined collection failed in both default and importlib modes. Inspect the changed source with Serena references for orphaned branches and record before/after output, sabotage evidence, and dead-code delta. Push the feature artifacts with the code and open one PR against `master`; CI runs the full suite. Do not clear `.spec/features/` before review and independent verification.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1"]},
    {"id": 2, "tasks": ["3.1"]},
    {"id": 3, "tasks": ["4.1"]}
  ]
}
```
