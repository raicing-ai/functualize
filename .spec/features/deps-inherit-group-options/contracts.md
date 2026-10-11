# contracts.md — deps-inherit-group-options

## External interfaces touched

None change shape. Every signature, field and surface literal in the shipped
package is byte-identical after this feature; the change is in what one
internal seam passes.

## The contract being kept, and the carve-out added

`docs/guides/group-options.md` ("Steering a whole run from code") records the
boundary this feature carves into:

> The flag layer is the one that is **not** inherited. … A step that should
> receive one is given it, explicitly, by the job that drives it.

The guide's rule — *nothing is inherited; anything passed is passed on
purpose* — is kept, not loosened. The carve-out is one more deliberate
pass-on, beside `rc.invoke(..., group_option_values=...)`:

| Nested surface | Who builds the request | Group-CLI layer |
|---|---|---|
| `engine.step` (workflow step) | `_engine/workflow_orchestrator.py` | not passed (unchanged, pinned by `test_a_workflow_step_does_not_inherit_the_group_cli_layer`) |
| `invoke` / `invoke.parallel` (`rc.invoke`) | `_engine/capabilities/invoke.py` | stated by the caller; `None` when the caller says nothing (unchanged, pinned by `test_the_group_cli_layer_does_not_cross_an_invoke_boundary`) |
| **`engine.dependency` (`Deps` upstream)** | `_engine/dependency_runner.py` | **now stated from the dependent's request — every dependency inherits the run's CLI layer** (this feature) |

`nested_request`'s reset of `group_option_values` (the default boundary) is
deliberately untouched: stating the field at the dependency seam is what keeps
the first two rows of the table true without editing their files.

## Scoping guarantee (why inheritance is safe for unrelated groups)

`_resolve_group_options` (`_engine/executor.py`) hands each declared
`GroupOptions` class only the keys *that class declares*
(`scoped_values = {k: v for k, v in cli_values.items() if k in field_names}`).
A dependency under a different group therefore picks up nothing from a flag
map keyed for another group — the flat map is filtered, not splatted. A field
name two groups share resolves identically on both sides of the hop, which is
the flat-merge semantics the top-level job already has (§5 / C-D3,
`test_two_declared_ancestors_see_one_value_for_a_shared_field`).

## `RunRequest` semantics after this feature

- `RunRequest.group_option_values` — meaning unchanged: the flat group-CLI
  layer the door that built the request parsed. Now also present on requests
  the dependency runner builds for `surface="engine.dependency"`.
- `nested_request(parent, **changes)` — unchanged default: resets
  `group_option_values` unless a caller states it. The dependency runner
  states it; `invoke.py` already did.
- Run records / history: nothing new is recorded. `group_option_values` was
  and remains absent from the run record; only resolution behavior changes.

## Docs surface

`docs/guides/group-options.md` § "Steering a whole run from code" gains the
`Deps` carve-out: a dependency is part of fulfilling the request that carried
the flag, so it inherits the CLI layer; steps and `rc.invoke` children keep
the documented boundary. `docs/` is not a gated path; the edit rides this
branch's diff.
