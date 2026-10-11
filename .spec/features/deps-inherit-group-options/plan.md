# plan.md — deps-inherit-group-options

## Design skills consulted

- `.claude/skills/python-design-patterns` (the repo's own; read at
  `.agents/skills/python-design-patterns/SKILL.md`) — KISS, separation of
  concerns, single responsibility. This change is a one-line pass-on plus
  tests; the principles selected *against* any larger reshaping (see BELOW
  pass).
- `coding__design-patterns-refactoring` (user-level, present in this
  session's listing; its Refactoring.Guru catalogue verified to carry the
  smell names used below — chapters 32/34/36) — consulted for the smell
  vocabulary in the BEFORE/AFTER passes.

## BEFORE — the shape now

```
_cli/main.py                       _types/run_request.py
  walk.options ─► group_option_values
        │                            nested_request(parent, **changes)
        │                              resets: kwargs, group_option_values=None,
        │                                      parent_scope, scope ids, …
        │                              keeps:  prompt_gates, output_format, force
        ▼
  RunRequest(group_option_values=map)          [layer: built at the door]
        │
        ▼
  _engine/executor.py  engine.run(request)     [peer layer _engine]
        │  _execute_lifecycle(..., group_option_values=map)
        │        │
        │        ├─► _resolve_group_options(fn, ctx, map)   ← invoked job: OK
        │        │
        │        └─► DependencyRunner.run_for(job, fn, ctx) [peer layer _engine]
        │                 │ run_node(node) for every node of the graph,
        │                 │  all built from the TOP job's context.request
        │                 ▼
        │             nested_request(ctx.request, surface="engine.dependency")
        │                 group_option_values ── RESET to None ──╮
        │                                                        ▼
        └──────────────────────────────────────────── engine.run(dep request)
                                            _resolve_group_options(fn, ctx, None)
                                            dep resolves default < file < env
                                            ≠ the value the invoked job saw (BUG)
```

Modules involved, by layer: `_cli/main.py` (delivery, unchanged by this
feature), `_types/run_request.py` (shared vocabulary, unchanged),
`_engine/executor.py` and `_engine/dependency_runner.py` (peer layer; the
runner is the only production file that changes), `docs/guides/group-options.md`
(docs, gains the carve-out). No boundary crossing is added: the runner already
imports `nested_request` from `_types`, which is legal for a peer layer.

### Smells the BEFORE already carries (named, with where)

- **Middle man** — `DependencyRunner.run_node` forwards seven fields to
  `nested_request` one by one (`_engine/dependency_runner.py:146-165`). Not
  introduced by us; the move is deliberate (engine-sealed-construction/T7
  extracted it), and this feature adds an eighth pass-on rather than a new
  indirection.
- **Primitive obsession** — the group-CLI layer is a flat `dict[str, Any]`
  keyed by field name, not by group path, so two groups sharing a field name
  cannot be told apart inside the map (`_engine/executor.py:2376-2380` filters
  it; `_cli/main.py:1004` builds it). Pre-existing by design (§5 / C-D3 chose
  the flat merge); inheritance makes no new exposure because the filter runs
  per declared class at the dependency.

## AFTER — the shape this feature leaves

```
  DependencyRunner.run_for(context)              [peer layer _engine]
        │ run_node(node):
        │   parent_request = context.request      ← the dependent's request
        │   nested_request(
        │       parent_request,
        │       surface="engine.dependency",
        │       … unchanged …
        │       group_option_values=              ← STATED, on purpose — the
        │           parent_request.group_option_values    one line this adds
        │   )
        ▼
  engine.run(dep request) ─► _resolve_group_options(fn, ctx, map)
        dep resolves the same CLI value the invoked job saw,
        scoped to the fields its own GroupOptions class declares
```

`nested_request`'s reset stays (workflow steps and `rc.invoke` children keep
the documented boundary, and the tests pinning it stay green untouched); the
dependency seam states the field exactly the way `invoke.py` already states
it. One production line, one import-free change, in the file the evidence
named.

### Smell check on the AFTER (introduced-smells pass)

- Does it add **shotgun surgery** (a rule spread over more files)? No — it
  narrows one: "which nested surfaces carry the CLI layer" now reads from the
  three seam sites plus one doc section, and each site states its own policy
  explicitly.
- Does it widen any **middle man**? By one keyword argument on an existing
  delegation — accepted, see BEFORE pass.
- Does it introduce **primitive obsession**? No new primitives; the existing
  flat map travels by reference and every consumer filters it per class.

## Surviving smells

None new. The two pre-existing smells above (**middle man** in
`DependencyRunner.run_node`, **primitive obsession** in the flat group-CLI
map) survive unchanged and need no maintainer review: both are recorded
deliberate decisions (T7's extraction memo; §5/C-D3's flat-merge decision),
and this feature does not grow either one beyond the single pass-on line.

## Files to change

| File | Change |
|---|---|
| `src/functualize/_engine/dependency_runner.py` | `run_node` states `group_option_values` from the dependent's request (the one production line + its comment) |
| `tests/group_options/test_group_options_deps.py` | new: AC-1..AC-4 — engine repro, depth, precedence-at-the-hop, `_handle_group` repro |
| `docs/guides/group-options.md` | the `Deps` carve-out in "Steering a whole run from code" (AC-5's boundaries restated for deps) |

Untouched on purpose: `_types/run_request.py` (the default reset is the
boundary the other surfaces rely on), `_engine/workflow_orchestrator.py` and
`_engine/capabilities/invoke.py` (other lanes' files; their pinned boundaries
hold because the default reset stays), `_cli/**`, `_app/**`.

## Risks

- **A dependency under a different group could pick up a like-named field.**
  Mitigated by construction: `_resolve_group_options` filters the map to the
  fields each declared class has, so only a *shared field name* crosses, and
  it resolves identically on both sides of the hop — the semantics the
  invoked job already has with two ancestor classes. Asserted in AC-3's
  ladder test.
- **Freshness/caching could mask the dependency's resolved value.** The
  dependency runs (or is skipped as fresh) before the dependent's pre-flight;
  a skipped-as-fresh dependency does not resolve options at all. The tests
  declare no fingerprints, so every node runs; `--force` interplay is out of
  scope per the dispatch.
- **A warm-boot deferred-import stand-in for the dependent's request.**
  `context.request` is the request the dependent actually runs under
  (`executor.py:1264-1274` sets it inside `_execute_lifecycle`), so there is
  no second source to drift from.
