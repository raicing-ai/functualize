# Plan — workflow-continuation

---

## 1. The approach in one line

**Every verb gets one implementation in `app/`, and the three surfaces become thin
callers of it.** Everything else in this feature is a consequence of that.

The repository already has the pattern and names it: `deposit_gate_input` was lifted out
of the MCP plugin into `app/_workflow_resume.py` so *"CLI and MCP share one notion of
accepting gate input"*. Three more things need the same lift — the scope projection, the
gate-tool call, and the job-executing funnel — and once they are lifted, `resume`
advancing, the `--wf-*` family and the parity test are all small.

## 2. Four new modules in `app/`, one per concern

| Module | Holds | Why not one file |
|---|---|---|
| `app/_workflow_view.py` | `describe_scope`, `list_scopes`, `derived_state`, topology resolution | Read-only. No app boot except topology fallback. |
| `app/_workflow_answer.py` | `answer_gate`, `gate_draft`, `resolve_gate` | Needs the live Pydantic model; writes only the gate record. |
| `app/_workflow_control.py` | the execute funnel, `call_gate_tool`, `resume_scope`, `cancel_scope`, `purge_scopes` | **Runs jobs.** The one module here that can have side effects. |
| `app/adapters/workflow_flags.py` | the `--wf-*` option list and its resolution | Adapter-layer: it is Click, not domain. |

`app/_workflow_resume.py` keeps `deposit_gate_input` and `pending_gates` — those names are
imported by three files and mean exactly what they say.

All are re-exported through `functualize.app.utils`, which is the only route `_cli` may
legally import (verified: `pyproject.toml` contract *"_cli uses public API only"*, line
319).

## 3. The execute funnel is the load-bearing part (research R2)

MCP's gate-tool policy is enforced at `_execute_job` (`_server.py:239-242`), described in
its own comment as *"the one place a job-executing call cannot get past, so there is no
version of the check a caller can forget to make"*.

`builtin workflow resume` advancing a walk means the **CLI becomes a second job-executing
door**. If it called `app.execute` directly, the gate policy would be theatre — the exact
failure `_gate_refusal` was written to prevent.

So `app/_workflow_control.py` owns the funnel:

```
resume_scope ─┐
call_gate_tool─┼─→ _guarded_execute(app, store, job, scope_id, **kwargs)
MCP _execute_job ┘        └─ GateToolPolicy check → app.execute
```

`GateToolPolicy` moves from the MCP plugin to `app/` with it. The plugin keeps a thin
re-export so `_server.py` is unchanged in shape.

## 4. Files to change

### New
```
src/functualize/app/_workflow_view.py
src/functualize/app/_workflow_answer.py
src/functualize/app/_workflow_control.py
src/functualize/app/adapters/workflow_flags.py
tests/workflow/test_workflow_surface_parity.py
tests/workflow/test_wf_flags_dispatch_matrix.py
tests/workflow/test_gate_drafts.py
tests/workflow/test_cancel_is_terminal.py
tests/plugins/test_mcp_job_tools_mode.py
```

### Modified
```
src/functualize/app/utils.py                       re-exports
src/functualize/app/_workflow_resume.py            model_dump fix; hint text
src/functualize/app/adapters/click_params.py       --wf-* in, --scope-id out
src/functualize/app/adapters/lazy_command.py       --wf-* in, --scope-id out
src/functualize/app/adapters/cli.py                --scope-id out
src/functualize/app/core.py                        _workflow_scope_id documented API-only
src/functualize/_cli/builtins.py                   list/show/answer/resume/gate-tool/purge
src/functualize/_cli/dispatch.py                   --scope-id out of the global set
src/functualize/_cli/main.py                       handler signatures; single-file peer fix
src/functualize/_engine/workflow_runner.py         cancelled is terminal
src/functualize/_primitives/scope_store.py         draft slot
src/functualize/_primitives/state_store.py         draft accessors forwarded
src/functualize/_types/errors.py                   ScopeCancelledError
plugins/functualize-mcp/.../_workflow_tools.py     thin callers
plugins/functualize-mcp/.../_tools.py              metadata + status string
plugins/functualize-mcp/.../_server.py             metadata + job_tools mode
plugins/functualize-mcp/.../_config.py             job_tools
plugins/functualize-mcp/.../_translator.py         stop repeating examples
docs/cli/workflow.md, docs/guides/mcp.md, docs/guides/workflows.md
docs/guides/composition.md                         --scope-id examples
README.md, CHANGELOG.md
contributor/reference/workflow-walker.md
contributor/architecture/surface-boundary.md       worked example rebuilt on --wf-*
```

## 5. Risks

**R-a · The projection lift changes the MCP wire shape.**
`get_workflow_state` gains `state`, `epilogue` and per-gate `draft`. Additive only — no
key is removed or retyped. `tests/plugins/test_mcp_workflow_tools.py` asserts on specific
keys, not on the whole dict; verified by reading its assertions before the lift.

**R-b · `resume` advancing changes an exit code that is scripted against.**
`builtin workflow resume` returns 0 today after a deposit. After this it returns whatever
the walk returns — including 5 for a still-blocked run. That is the point, and it is a
breaking change on a pre-release version. CHANGELOG names it.

**R-c · The `--wf-*` family has two injection points and they have diverged before.**
`pitfalls.md` §23 is exactly this pair (`create_job_click_command` / `make_lazy_command`).
Mitigation is structural: **one** `workflow_flags.py` builds the option list *and*
resolves it, and both constructors call it. AC-20 runs every assertion cold and warm.

**R-d · Deleting `--scope-id` while `--wf-resume` is not yet wired would strand every
blocked run.** Sequencing, not luck: T18 (removal) is two waves after T17 (the flags), and
T17's own gate asserts `--wf-resume` advances before the removal task may start.

**R-e · `answer` auto-committing could write a payload the walker then rejects.**
The invariant is the mitigation: `payload` is written only by
`model(**draft.values).model_dump()`. If it validates, the walker's own strategy path
would have produced the same object — that is what T5 makes true, and T5 is in wave 2.

**R-f · `job_tools="none"` could hide jobs an existing agent depends on.**
Default stays `"all"`. The mode is opt-in, and the metadata fix (T1) lands two waves
earlier so the generic door is already lossless when the mode becomes usable.

**R-g · `purge` deletes scope records.** It moves nothing aside — unlike
`state clear --scopes`, which moves the whole file. Mitigated by refusing to purge a scope
that is `running`, `blocked`, `waiting` or `ready`; only terminal states are purgeable,
and `--state` cannot name a live one.

**R-h · The parity test can pass vacuously** if it enumerates a hardcoded list. R3: it
must derive both sets from the live command tree and the live tool registry. Its own
sabotage check is adding a parameter to one side and watching it fail.

## 6. The one thing this feature does not do

**It does not fence concurrent walkers.** Two `--wf-resume` invocations against the same
scope will both walk it. The scope-file flock serializes the *writes*, so the file never
corrupts, but neither walker knows the other exists and the second overwrites the first's
step records with its own.

This is strictly worse than today only in the sense that today the operation is
inconvenient enough to be rare. Making `resume` easy makes the race easy.

Shipping anyway, deliberately: the fix is a lease with a fencing token, which is roadmap
item 8's runner work, and building half a lease here would be the speculation the
constitution forbids. The CHANGELOG says so plainly rather than leaving it to be
discovered.
