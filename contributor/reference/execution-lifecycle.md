# Execution lifecycle — the order, and why it is this order

Every job runs through `JobExecutionEngine._execute_lifecycle`
(`src/functualize/_engine/executor.py`). It is a twenty-step linear procedure,
and **almost every step's position is a constraint rather than a preference**.

Those constraints used to exist only as comments inside a 323-line method, so
"does `Deps` run before the pre-flight?" was a question you answered by reading
the method. This page is the answer. NestJS publishes the same thing as
`faq/request-lifecycle.md`, for the same reason.

`tests/engine/test_lifecycle_order.py` asserts the observable half of this
sequence. If you reorder the method, that test fails — which is the difference
between a document and a contract.

---

## The sequence

| # | Step | Why here |
|---|---|---|
| 1 | Materialize a lazy function | **Before any signature introspection**, so the resolution-plan and validator caches key on the real function and the `ExecutionContext` carries it |
| 2 | `@workflow` prelude — walk the declared graph | A blocked or failed walk returns **before DI and before any hook fires**: the body is the job, and the job has not been reached yet |
| 3 | Build the `ExecutionContext` | — |
| 4 | **DI resolution** → writes `context.injected` | Must precede the pre-flight: the pre-flight's args hash reads `context.injected` |
| 5 | Ensure a `RunContext` exists in `context.capabilities` | Middleware needs one whether or not the job asked for it |
| 6 | Resolve the config model → writes `context.injected` | **Before PRE_EXECUTE hooks**, and in the same `try` as steps 7–8: all three raise `ValidationError`, and the handler is what turns a config failure into a `FAILURE` `JobResult` the CLI can render instead of a raw traceback |
| 7 | Resolve `GroupOptions` → writes `context.injected` | **After** the job's own config. A `GroupOptions` parameter is never the job's config class, so the two never contend for the same parameter |
| 8 | Validate arguments; snapshot `resolved_inputs` | Same handler as 6–7. The snapshot is what the job was *actually* given, post-coercion, with secrets masked — it lands in `state.json` and is handed to external agents over MCP |
| 9 | **Dependencies (`Deps`)** | **Before the pre-flight, not after**: a dep may regenerate a file this job fingerprints, so checking staleness first would compare against sources the dep is about to change. Same ordering `make` uses — build prerequisites, then compare timestamps |
| 10 | **`FromJob` injection** → writes `context.injected` | After the upstreams have run (9), before the pre-flight decision (12) — a guard may be a callable that reads one |
| 11 | `Exec.run` session skip | Intra-run de-duplication ("already ran this session"), decided before the freshness question is asked at all |
| 12 | **Pre-flight check** — guards + file staleness | After config resolution (6), because a guard may be a callable taking the resolved config. Before PRE_EXECUTE (16), because a skipped job must not fire hooks that assume it ran. Reads `context.injected` for the args hash |
| 13 | **Complete pre-flight-bound capabilities** (`Sources`) | After 12, because the resolved map does not exist before it. **Before 14**, because that step discards the decision — binding after it would hand a job an empty source map on exactly the runs a `FromJob` dependent triggers |
| 14 | `force` / `force_fresh` override | See "The two forces" below |
| 15 | Pre-flight result — skip / refuse / block | Returns without running the body |
| 16 | `job.execute.start` event, perf mark, PRE_EXECUTE hooks | The first point at which the job is committed to running |
| 17 | Exec policy (retry) wraps `_execute_with_lifecycle` — **the body runs** | — |
| 18 | Deferred shells, in a `finally` | Covers success, failure and Ctrl+C (`KeyboardInterrupt` propagates) — the cases a user-level `try/finally` in job code cannot be trusted to cover |
| 19 | Workflow `record_body` | Body-once-per-scope (§A.7): replaying a finished scope answers with the recorded value instead of running the body again |
| 20 | Write the fingerprint record | **Only for a run that actually succeeded.** Recording after a failure would mark the job current and skip the retry the user is about to make |

---

## The four writers of `context.injected`

Steps **4, 6, 7 and 10** each add parameter names to `context.injected`.

`context.injected` is an exact subtraction: it is how the engine tells "the
caller passed this" from "the framework supplied this", and the args hash
depends on the answer. **A fifth injection site that forgets to record itself
silently changes every fingerprint key** — which is defect D1, verbatim.

If you add one, add it to this list too.

---

## The two forces

Step 14 has two independent overrides, and they are not the same claim.

| | Produced by | Overrides |
|---|---|---|
| `force_fresh` | the workflow walker, for a `FromJob` dependent whose upstream value cannot be reused | `SKIP_FRESH` only |
| `force` | a caller — `--force` on either CLI | `SKIP_FRESH` and `SKIP_SATISFIED` |

`force_fresh` is narrow on purpose, and its reason is worth keeping: *wanting a
value is not a reason to run somewhere the job does not belong.* Freshness
answers "are the outputs on disk current?", which says nothing about a return
value that was never storable — so a dependent that needs the value overrides
that and nothing else.

`force` is a person saying "run anyway", so it also overrides a satisfied
`status` guard. Neither overrides a failing `Precondition` (still exit 3), a
gate awaiting input (still exit 5), or step 11.

---

## What this does not cover

* `_execute_with_lifecycle` (step 17) — the hook/middleware sequence *inside*
  the body's execution. See `contributor/architecture/execution-flow.md`.
* The boot sequence. See `contributor/architecture/boot-sequence.md`.
* The exit-code mapping at the process boundary. See
  `src/functualize/_types/exit_codes.py`, which is the single table, and
  `deliver_job_result`, which routes every status through it.

## Related

- `contributor/adr/012-resolved-sources.md` — why step 13 exists
- `contributor/adr/014-capability-registry.md` — why step 13 is a loop over
  declarations rather than one hard-coded call
- `contributor/guides/wiring-discipline.md` — how to prove a step is reached
