# Plan

## Approach

Three surfaces, one existing data source. Nothing new is collected: the report
already exists and already survives a warm boot.

1. **Rich renderer** (`_cli/info.py`): the failures panel, above the jobs
   table, mirroring `render_report_text`'s content and order.
2. **`self doctor`**: the `job-discovery` check reads the same report and
   downgrades its status when it is non-empty.
3. **Unknown command**: on the error path, if failures exist, AST-parse each
   failed file looking for a top-level `def` matching the typed name (after
   canonicalization). Name it when found; a generic note otherwise.
4. **The warning line**: replace the two `logger.warning` calls in the
   providers with one formatted message.

## Files

| File | Change |
|---|---|
| `src/functualize/_cli/info.py` | the rich failures panel |
| `src/functualize/_cli/self_doctor.py` | the `job-discovery` check |
| `src/functualize/_cli/dispatch.py` (or where unknown-command is emitted) | the hint |
| `src/functualize/_discovery/cached_provider.py`, `providers.py` | the warning line |
| `tests/cli/test_discovery_failure_surfaces.py` | new |

## Risks

**Attribution must not import.** A8 exists because importing the module is the
thing that failed; doing it again to produce a hint would run half a module's
side effects on an error path. `ast.parse` on the source only.

**The AST read is on the error path only.** One file parse when a command is
already failing. It must never run on a successful dispatch.

**Three kinds share the surface now.** A4 covers all three, because a renderer
written against import failures alone would print an empty `path` for a
collision or an unsatisfiable job.

**Doctor's status is a contract.** A6 changes `worst` for a project with a
broken module. The existing doctor tests assert `ok` on healthy projects, which
is unaffected.
