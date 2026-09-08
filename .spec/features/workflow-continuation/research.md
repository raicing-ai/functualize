# Research — workflow-continuation

Findings from the Specify and Plan retrieval passes that **changed the shape of the
feature**. Findings that were simply true went straight into `spec.md`.

---

## R1 · `--wf-resume` cannot be a plain Click option — it must short-circuit the run

Measured, not assumed. The job command's callback (`build_job_engine_callback`,
`click_params.py:1067`) is the *only* place a job runs, and it ends in
`app_ref.execution_engine.execute(...)`. `--wf-status` and `--wf-show` must **exit 0
without running the job** (AC-25), so they cannot be ordinary kwargs consumed inside that
callback after the engine is reached — they have to be handled at the top of `wrapper`,
before `requires_tty`, before DI, before the engine call.

That places three of the nine flags on a different control path from the other six:

| Flag | Path |
|---|---|
| `--wf-status`, `--wf-show` | short-circuit at the top of `wrapper`, echo, `SystemExit(0)` |
| `--wf-resume`, `--wf-input`, `--wf-gate`, `--wf-retry-epilogue`, `--wf-run-id` | resolve to a `scope_id` (+ a pre-deposit) and fall through to `execute()` |

Consequence for the plan: the flag family is **one helper called from two injection
points**, not two independent option lists. `pitfalls.md` §23 is the precedent — the same
two constructors already diverged once on result handling, and every assertion here runs
warm and cold.

## R2 · `resume` advancing means tier 1 executes jobs — a real boundary change

`builtin workflow`'s four verbs read the store directly and never boot the app, except
`resume`, which boots only to materialize a Pydantic model. Making `resume` *advance*
means the builtin group now **runs a graph**.

Verified constraint: MCP's gate-tool policy is enforced at `_execute_job`
(`_server.py:239-242`), described in its own comment as *"the one place a job-executing
call cannot get past"*. A `builtin workflow resume` that called `app.execute` directly
would be a **second** door into the same room with no lock on it — precisely the failure
`_gate_refusal` exists to prevent (`_tools.py:79-95`).

So `resume_scope` in `app/` must route through the same funnel, and the funnel must move
out of the MCP plugin into `app/` with it. This is a larger lift than "move `_describe`"
and it is why T-lift is sequenced before T-resume.

## R3 · The parity test must enumerate, not sample

`pitfalls.md` §19's rule: *"a docstring claiming parity is a claim; a parity test is the
parity."* The precedent test (`tests/config/test_env_name_rule_parity.py`) derives the
value from **each producer** and asserts equality, rather than checking one against a
literal.

Applied here: the parity test must build the verb/parameter set from the **live Click
command tree** and from the **live registered MCP tool list**, then assert set equality.
A hardcoded list of verbs would be a sixth copy (`pitfalls.md` §6). This is why AC-29 is
phrased as "fails when either surface gains a verb the other lacks" — a new verb on
either side must break it without anyone editing the test.

## R4 · `--scope-id` removal is 5 files, and one of them is a *retained* seam

`grep -rc 'scope-id' --include='*.py' src/` returns, verified:

```
src/functualize/_cli/dispatch.py:3
src/functualize/_cli/main.py:1
src/functualize/app/_workflow_resume.py:2
src/functualize/app/adapters/cli.py:1
src/functualize/app/adapters/click_params.py:7
```

The two in `_workflow_resume.py` are **emitted hint text**, not plumbing — the resume
hint a blocked run prints. They change meaning entirely: with `--scope-id` gone the hint
must name `--wf-resume`, and spec §5 of `05-target-surface.md` calls the blocked output
"load-bearing" precisely because "re-run the command you remember" no longer works.

`app._workflow_scope_id` is **kept**. It is the embedded-host seam (`app/commands.py`
never threaded the CLI flag, which is the bug `_scope_id_option` was written to fix), and
removing it would re-open that hole for programmatic hosts. Documented as API-only.

## R5 · The SINGLE_FILE crash is a *double registration*, not a name collision

Reproduced at `24c5cc0` in a scratch directory — full traceback, `_cli/main.py:1548` →
`_app/impl.py:708`.

The mechanism matters for the fix. Directory discovery registers `forecast` from
`weather.py`; `_register_single_file_peers` then registers **the same function from the
same module** again. It is not two different jobs contending for one name — it is one job
registered twice. So the fix is for peer registration to skip a name the registry already
holds, not to rename or to make `register_dynamic_job` permissive. Making the *registry*
permissive would mask genuine collisions, which is the check's actual job.

## R6 · `state` cannot be `running` honestly, and the roadmap already said so

`FrontierWalk.start` sets `RUNNING` only on first entry, so a **resumed** walk reports
`blocked` for its whole duration. Shipping a derived `running` that reads from
`status == "running"` therefore under-reports rather than lying — a resumed walk shows
`waiting`/`ready`, which is what the store actually knows.

Accepted as-is: `waiting`/`ready`/`stalled` are pure derivations with zero risk and pay
for themselves immediately (`ready` is exactly what `resume` can advance and what a
scheduler polls). Accurate live-vs-parked reporting needs the tier-2 lease. Not faked in
the meantime.

## R7 · `answer` must fix the payload shape *first*, in the same change

`workflow_walker.py:275` stores `model.model_dump()`; `_workflow_resume.py:88` stores the
raw dict. A partial-deposit feature that accumulated raw fragments and then committed
them raw would make the divergence **permanent** and much harder to unpick, because the
draft would then be the canonical accumulation format.

So the two-line fix (`store.deposit_gate_payload(scope_id, gate, model(**payload).model_dump())`)
is the *first* task of the item-4 wave, not a cleanup after it. AC-10 pins it.

## R8 · Removing `resume_gate` and `list_active_workflows` breaks documented examples

`docs/guides/mcp.md:55,200` and `docs/guides/workflows.md:247` all name
`resume_workflow` and describe it as advancing — so those three lines become **true** for
the first time. But `resume_gate` and `list_active_workflows` appear in prose that must
be rewritten, not just renamed, because `answer_gate` has different addressing (joint,
each optional) rather than being `resume_gate` under a new name.

Docs are part of the feature, not a follow-up: `doc-verify` is a required check.
