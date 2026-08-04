# Discovery Strategy

How to determine IF E2E validation is needed, WHAT tier to use, and WHERE to find validation scenarios.

---

## Phase 0 — Impact Surface Detection

Before deciding what to validate, determine whether the change has TUI/CLI blast radius.

### Inputs (pick whichever is available)

1. **Plan/spec scope section** — the "In scope" file list from a plan or spec
2. **Git diff** — `git diff --name-only $(git merge-base origin/main HEAD)..HEAD` or against the plan's commit SHA
3. **Tasks.md inference** — read completed task descriptions and infer which files were touched

### Dependency Trace

Read `contributor/architecture/dependency-graph.md` to understand the module dependency DAG. The key insight: `_cli/` imports ONLY from public API modules (`app/`, `job/`, `plugin/`, `types/`, `testing/`, `workflow/`), but `_app/` (composition root) wires ALL internal layers together. So:

- A change to a **peer layer** (`_engine/`, `_config/`, `_discovery/`, `_gate/`, `_plugins/`) flows through `_app/` → public API → `_cli/`
- A change to **foundation** (`_primitives/`, `_events/`, `_types/`) could affect anything
- A change to **public API** directly affects `_cli/` if `_cli/` imports that module

### Module → TUI Surface Mapping

| Changed module | What TUI surface it feeds | Targeted probe focus |
|---|---|---|
| `_cli/tui/` | Direct TUI code | Whatever was changed |
| `_cli/` (non-tui) | Inline TUI, main routing, introspect | Boot, command routing |
| `_engine/` | Job execution → result rendering in TUI | Run a job, check output display |
| `_config/` | Config resolution → Config Table panel, pre-flight, detail drill-down | Open config panel, check values |
| `_discovery/` | Job finding → Job browser, SmartBar completions | Boot TUI, check job list populates |
| `_app/boot.py` | Boot sequence → everything | Smoke: does TUI boot at all? |
| `_app/` (other) | FunctualizeApp wiring → everything | Smoke + targeted based on what wiring changed |
| `_events/` | EventBus → cross-panel sync, refresh | Edit a value in panel, confirm sync |
| `_primitives/` | DIRegistry, middleware → boot and capability resolution | Smoke: does TUI boot? |
| `_gate/` | Gate resolution → workflow step pausing | Workflow with gates (if example exists) |
| `_plugins/` | Plugin loading → what TUI sees at boot | Boot with plugins active |
| `_types/` | Shared dataclasses/protocols → everything | Smoke (cascading risk) |
| `app/` (public) | FunctualizeApp public API → _cli/ uses it | Check `_cli/` imports; if hit, smoke |
| `job/` (public) | RunContext, capabilities → job execution in TUI | Run a job |
| `types/` (public) | JobResult, JobDescriptor → display rendering | Run a job, check result display |
| `workflow/` (public) | Workflow composition → workflow TUI | Workflow execution if example exists |
| `plugin/` (public) | Plugin authoring API → plugin loading at boot | Boot with plugins |
| `testing/` (public) | Test utilities only | SKIP — no runtime TUI impact |

### Tier Assignment

```
FULL:
  - Any file in _cli/ was changed
  - Explicit [verify-e2e:full] annotation

TARGETED:
  - A peer layer or public API module was changed AND you can identify
    the specific TUI surface it feeds (use the table above)
  - Explicit [verify-e2e:targeted] annotation

SMOKE:
  - Foundation layers changed (_primitives, _events, _types)
  - _app/boot.py changed
  - You can't pinpoint which surface is affected but there IS a path to _cli/
  - Explicit [verify-e2e:smoke] annotation

SKIP:
  - Only tests/, docs/, contributor/, .github/, .spec/ changed
  - Only testing/ (public) changed
  - No import path from changed code to _cli/ (confirm with grep)
  - Explicit [verify-e2e:skip] annotation (rare — used to override)
```

---

## Phase 1 — Scenario Discovery

Once you know validation is needed and at what tier, find the right scenarios.

### Discovery Sources (check in order)

1. **`docs/testing/*.md`** — Manual test guides. These are the highest-fidelity source: a human wrote exact keystrokes and expectations. Parse:
   - "Setup" sections → which example directory to use
   - "Steps" sections → interaction sequences (translatable to probe steps)
   - "Expect" lines → what text should appear on screen

2. **`examples/README.md`** — Maps example directories to features they demonstrate. Use to match a claimed behavior to the example that exercises it.

3. **`examples/*/README.md`** — Per-example docs list what they demonstrate and how to run them.

4. **The spec/plan's acceptance criteria** — ACs phrased as "user sees X" or "pressing Y does Z" translate directly to probe steps.

5. **`contributor/guides/steering_textual_tui.md`** — Canonical behavioral expectations for TUI components, key bindings, mode transitions.

### Example Directory Mapping

| Claim domain | Primary example | Fallback |
|---|---|---|
| Inline TUI (SmartBar, panels, completions) | `examples/standalone/showcase` | `examples/quickstart/step4_tui` |
| CLI command routing, group commands | `examples/standalone/showcase` | `examples/quickstart/step1_basic` |
| Config resolution, layered config | `examples/standalone/config_lab` | `examples/standalone/showcase` |
| Job discovery, filtering | `examples/standalone/discovery_lab` | `examples/standalone/showcase` |
| Project-level FunctualizeApp | `examples/project/weather_app` | — |
| Workflow composition | `examples/quickstart/step7_workflow` | — |
| Plugin loading | `examples/plugins/file_based_plugin` | — |
| MCP adapter | `plugins/functualize-mcp/examples/` | — |
| Scaffolding | `examples/quickstart/step8_scaffold` | — |
| AI/invoke patterns | `examples/quickstart/step5_ai` | — |

### When No Scenario Exists

If a behavioral claim maps to no existing example:
1. Flag it in the report as `NO SCENARIO — cannot validate E2E`
2. Suggest which example could be extended (or a new one created) to cover it
3. Do NOT create examples yourself — that's implementation work, not verification
4. Still count it in the report totals so the coverage gap is visible
