# Plan

## Approach

The defect is one over-broad `else` in a boot-time gate. The rest of the stack
already treats these types correctly, so the fix is a classification list plus
a disposition change — not new plumbing.

1. **`_primitives/parameter_types.py`** — the list and two predicates (C1).
2. **`_engine/executor.py::_di_binding_errors`** — skip a parameter that is a
   CLI value type or carries an explicit marker, before consulting the
   registry. Also attach the *parameter* name to the error, so the message
   stops saying `job: '<unknown>'`.
3. **`validate_di_bindings`** returns per-job errors instead of raising (C2).
4. **`_app/boot.py`** — unregister the affected jobs, record one
   `DiscoveryFailure` each, and continue. A job removed here is absent from
   the CLI, so invoking it produces the existing unknown-command path, which
   `discovery-failure-surfaces` teaches to explain itself.
5. **`app/utils.py::_resolve_type`** — the four conversions (C4).

## Files

| File | Change |
|---|---|
| `src/functualize/_primitives/parameter_types.py` | new — the list and predicates |
| `src/functualize/_engine/executor.py` | classification; per-job return; parameter name in the error |
| `src/functualize/_app/boot.py` | disposition: unregister and report |
| `src/functualize/app/utils.py` | four click conversions |
| `tests/execution/test_di_validation.py` | rewritten to the per-job outcome |
| `tests/cli/test_parameter_types.py` | new — end to end through the CLI |

## Risks

**Widening the list is a one-way door.** A type that becomes a CLI parameter
cannot later become injectable without breaking a job that relies on it. The
list is therefore standard-library value types only — things with an obvious
string form — and the explicit marker is the escape hatch for everything else.

**The constitutional departure.** `CONSTITUTION.md` requires DI failures to be
loud at boot. They stay loud; they stop being fatal to unrelated jobs.
Explicitly approved. Recorded in the spec, in this plan, and in the ADR this
feature adds, because a later reader finding a non-raising boot needs the
reason without archaeology.

**Three test modules pin the old exception.** Rewritten, not deleted: the
old behaviour stays legible in the diff, and the criteria that replace it
(A4, A5) assert both halves — still an error, no longer contagious.

**Enum is a subclass check, not a name match**, unlike every other entry. That
asymmetry is deliberate — the names are user-defined — and is the one place
this list cannot follow `capability_names.py`'s pattern.
