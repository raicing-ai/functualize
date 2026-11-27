# Refused lazy app command plan

## Alignment

Approved Shape Intent [SD/30310404 v4](https://raicing-ai.atlassian.net/wiki/spaces/SD/pages/30310404), `Authority: Approved`, updated 2026-11-27 04:47:12 UTC. The dispatch comment `01a21b6c-eb06-775d-9482-a5ee24376b2e` records the approval and assigns this implementation. In the shape's words, the changed surface is the **app-script lazy command**; the **func refused command** is the existing parity reference. Independent workflow/info commands, HTTP, Lambda, MCP, and TUI are outside scope.

## Architecture before

```text
app script -> app/adapters/cli.py [public adapter layer]
           -> app/adapters/lazy_command.py [public adapter layer]
           -> app/adapters/click_params.py descriptor params [same layer]
           -> Click parses arguments [external library boundary]
           -> lazy callback -> engine request [_engine layer]
```

The callback refusal is too late for Click parse errors. The `func` eager builder already checks the app's admitted contracts before it creates parameters. Existing smell: **divergent change** between eager and lazy command construction. `lazy_command.py::make_lazy_command` is also a **long method**; this change does not expand its callback.

## Architecture after

```text
app script -> app/adapters/cli.py [public adapter layer]
           -> app/adapters/lazy_command.py [public adapter layer]
              -> app/adapters/click_params.py admission lookup [same layer]
                 -> refused: shared refusing Click command -> stored reason
                 -> admitted: existing descriptor params -> Click -> callback
```

The new branch returns before descriptor parameter and workflow flag construction. It imports two same-layer helpers and reuses the shared refusal renderer. No new cross-layer dependency is introduced. The candidate avoids a second renderer and another refusal rule. The remaining **divergent change** is the two command builders; the existing architecture has both because warm commands use cached descriptors. The **long method** remains, but the early guard adds only a small, local decision.

## Surviving smells

- **Divergent change:** eager and lazy builders still construct normal commands separately. Their shared refusal command makes this particular rule common.
- **Long method:** `make_lazy_command` retains its existing callback; a broader refactor is outside this issue.

Consulted `.agents/skills/python-design-patterns` (KISS and single responsibility) and `design-patterns-refactoring` (divergent change, long method). The existing codemaps place `CliAdapter`, `lazy_command`, and `click_params` in the same adapter region and identify the app and `func` entry paths.

## Files and proof

- `src/functualize/app/adapters/lazy_command.py`: early refusal branch.
- `tests/cli/test_app_refused_call_rendering.py`: real app-script cold/warm subprocesses and argument matrix.
- `tests/cli/test_invalid_call_rendering.py`: unchanged `func` parity test.

Prove reachability with `FunctualizeApp -> CliAdapter.run -> _build_job_command -> make_lazy_command -> _refused_job_command`. After committing the implementation, temporarily remove the new branch and require the warm test to fail, then restore it.
