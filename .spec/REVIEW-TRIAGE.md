# Review triage — five adversarial reviews of the completed features

Five read-only reviewers audited the five features whose gates had passed, on
four axes each: scrutiny (falsify the ACs), architecture, design patterns and
refactoring, code smells. **46 findings**: 8 Blocking, 21 Serious, 13 Minor,
4 Nit.

This file is the ledger. Every finding gets a verdict, and the two questions the
maintainer asked of each one:

- **Why the implementer missed it** — not as blame; as the shape of the gap, so
  the next task can be written to close it.
- **What test would have caught it** — because a finding without a test is a
  finding that comes back.

Anything **not fixed** appears here with its reason: needs a decision, or
deferred and why. Nothing is dropped silently.

## Status key

`FIXED` · `CONFIRMED` (reproduced, not yet fixed) · `TRIAGING` · `NEEDS DECISION`
· `DEFERRED` · `REJECTED` (checked, does not hold)

---

## Findings that are the same defect wearing different clothes

Several findings are one class. Fixing the class settles them together, and the
aggregate test is worth more than five separate ones.

**Class A — a gate or test that cannot fail.** The signature defect of this
branch: six were already found during execution, and the reviewers found four
more.
`rre F2` · `rre F13` · `roa B2` · `roa S4` · `asp B-1` · `adj B2`

**Class B — a `tasks.md` record that no longer holds against HEAD.** A gate is
authored by running it, but nothing re-runs it after later tasks change the code,
so a `[x]` can rest on a value that has since moved.
`rre F3` · `adj M5` · `asp S-4` · `jof` (T1's gate unsatisfiable at its named path)

> **Class A and Class B share one fix**: a test that reads every `tasks.md`, runs
> every gate it declares, and asserts the recorded `after:` value still holds. It
> converts "the gate was true once" into "the gate is true now", and it fails
> loudly for a gate that cannot fail at all (its `now:` and `after:` are equal).

**Class C — an acceptance criterion kept by nothing.**
`rre F4` · `roa B1` (fixed) · `roa B2`

**Class D — prose that outlived the code it described.**
`rre F11` · `rre F12` · `roa S2` · `roa S3` · `adj M1` · `adj N1` · `jof` (the
`Freshness` docstring demonstrating an unreachable path)

**Class E — real behaviour defects.** These are the ones a user would hit.
`rre F1` (fixed) · `adj S3` (fixed) · `adj S1` · `adj S2` · `adj S4` · `adj S5` ·
`adj B2` · `asp S-1` · `asp S-2` · `asp S-3`

**Class F — architecture and design judgements.** Several of these are genuine
trade-offs rather than errors, and some want the maintainer's call.
`rre F6` · `rre F7` · `rre F8` · `rre F9` · `rre F10` · `roa A1` · `roa A2` ·
`roa A3`

---

## Batch 1 — triaged and fixed

| Finding | Verdict | Why the implementer missed it | What catches it now |
|---|---|---|---|
| `rre F1` — delivery inputs stop at the first nesting hop | **FIXED** | They used to be a process-global on the app, so nesting inherited them *by accident of storage*. Making them per-request made the inheritance something the code has to say, and no site said it. `RunRequest.replace`'s own docstring promised the behaviour and had no caller. | `tests/engine/test_nested_delivery_inputs.py` — 8 tests, including that stating one field does not drop the other two |
| `rre F2` — T5's R-b test cannot fail | **FIXED** | The test called `build_request` twice with identical arguments and said so: "equal by construction". Writing it felt like testing the contract; it was testing `==`. | `tests/adapters/test_request_builder.py` drives both real constructors; sabotaged to prove it fails |
| `roa B1` — AC-6's process half thrown away | **FIXED** | The test asserted the value `execute_job_sync` **computed**, which was correct. Nobody asked what the caller did with it: `run_worker` ignores its callable's return and nothing assigned `app.return_code`. | `tests/_cli/test_tui_process_exit_code.py` — asserts the wiring, not the calculation |
| `adj S3` — config-declared cwd dropped | **FIXED** | The filter compared **paths**, and the change-site comment stated the correct rule (*declared or implicit*) that the code did not implement. A comment is not a test. | `test_single_file_cwd_isolation.py::TestAConfigDeclaredCwdSurvives`, beside T14's original defect |
| `rre F3` · `adj M5` · `asp S-4` · `jof` T1 — stale gate records | **FIXED (class)** | A gate is authored by running it, and **nothing re-runs it**. Later tasks move the code; the `[x]` rests on a number that has moved. | `tests/spec/test_task_gates_still_hold.py` re-runs every finished task's gate |
| *(not reported by any reviewer)* — the engine seal undone | **FIXED** | `agent_step.py` came from a branch predating the seal and re-added two reach-throughs. `git` merged cleanly, and ruff, mypy and all six contracts stayed green. **Five reviewers did not find this either** — it did not exist in any single branch. | The same gate re-run test, on its first run |

## Needs a decision from the maintainer

### D-1 · `agent-step-port` S-3 — the spec forbids a default executor; the code ships one

`spec.md` says it four times, in four places: *"A default executor. §3.5"* (out of
scope), *"does not fall back to asking me the question myself"* (US-3), *"It does
**not** fall back to prompting a human — a fallback that changes who answers is a
different program"* (§3.5), and the design doc's *"No default executor."*

The code registers core's `CliPromptExecutor` in **both** boot paths, and
`AgentStepRegistry.resolve` hands it every step that named no executor. A test
asserts that behaviour. So on a bare install, the most natural declaration an
author can write is performed by asking that author to do the work.

Both readings are coherent, and the choice is the maintainer's, not mine.

**Status: NEEDS DECISION.** Nothing changed pending it.

### D-2 · `adjacent-defects` S1 — where should `str` → enum conversion live?

**Status: open. Half of S1 is fixed and half is not, and the unfixed half is a
design question rather than a bug with an obvious answer.**

What still happens, on an app's own entry point, from its second run onward:

```
$ python main.py paint red      # run 1 (cold)
body=Color:<Color.RED: 'red'>   # the enum member — correct

$ python main.py paint red      # run 2 (warm)
body=str:'red'                  # a string
```

The spelling is now the same on both runs (that was the fixed half). The
**type** is not. `US-3` says *"an enum arrives in my job as that enum, on every
surface"*, and on the warm path it does not.

**Why it is not a one-line fix.** The cold path builds click parameters from the
live signature, so it has the `Color` class and hands back `Color.RED`. The warm
path builds them from the cached descriptor, whose whole purpose is to render
the CLI **without importing the job module** — and the cached record is:

```json
{"name": "color", "type_annotation": "Color", "choices": ["red", "green"]}
```

`"Color"` is a bare class name. There is nothing there to import.

Three ways out, and they are not equivalent:

1. **Record the enum's import path** in `FieldDescriptor` and import it lazily
   inside `convert()` — so `--help` and completion stay import-free, and the
   import happens only when a value is actually being converted, which is
   immediately before the job module gets imported anyway. Cost: a new
   descriptor field, another `CACHE_VERSION` bump, and both extractors. Risk:
   a job module loaded dynamically may not have an importable `__module__`.
2. **Coerce at the job-invocation boundary**, where the engine has the real
   function object with real annotations. One place, and it would fix HTTP,
   Lambda and MCP at the same time — they have the same defect for the same
   reason. Cost: the kernel starts doing type coercion, which is a new
   responsibility for it.
3. **Narrow the claim.** Say the enum arrives as its *value* on cache-backed
   surfaces, and make `US-3` say so. Costs nothing and is honest, but it is a
   real reduction in what the framework promises.

**My recommendation: (2).** The other surfaces have this defect too, and (1)
fixes only click. But it puts coercion in the kernel, which is exactly the kind
of thing `engine-sealed-construction` is trying to keep out of there — so it is
your call, not mine.

**Deferred, not dropped**, and not blocking: the spelling fix removed the
user-visible *surprise* (a value accepted on Monday and refused on Tuesday).
What remains is a type mismatch that a job body sees as `str` consistently on
that surface.

## Batch 3 — Class E, the `adjacent-defects` behaviour defects

Every one reproduced first, against a real invocation, before anything was
changed; every fix then sabotaged to watch its new test fail.

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `adj S4` — a cache written before T13 is still honoured | **FIXED** | A test builds its fixture *with the code under test*, so it only ever sees the new shape. The poisoned entry's shape never changed — only its meaning — so `from_dict` reads it happily and `discovery_hash` matches. T13's `**Files:**` line did not include `cache_format.py`, which put the bump outside the task's scope, and the task report never raised it. | They asked what a cache written by the **previous build** does — the one question a fixture-based test cannot ask. | `CACHE_VERSION` 20 → 21, plus `test_discovery_failures.py::TestTheUpgradePathFromAPoisonedCache`: three tests, one of which injects the poison at the *current* version to prove it really does suppress the failure. Reverting the bump fails two of them. |
| `adj B2` — a fifth caller supplies no fingerprint, and the sabotage cannot fail | **FIXED** | T10 fixed the four callers it could see by grepping core. The MCP plugin is in `plugins/`, and `discovery_hash`'s **default** turned "a caller nobody updated" into "skip the check" silently. The named sabotage ("drop the argument at the call site; this test must fail") left the suite green because **no test can observe what a caller passed**. | They ran the sabotage the task specified and watched it not fail, then asked who else reads that cache section — and looked outside `src/`. | The default is **gone**: `discovery_hash` is required and keyword-only, so omission is a `TypeError` and a mypy error rather than a silent skip. Plus `test_omitting_the_fingerprint_is_not_possible` and `test_every_in_tree_reader_passes_one`, which also refuses a reader that writes `discovery_hash=None` to quiet the checker. |
| `adj S2` — the app entry point's suggestions are not fuzzy | **FIXED** | T12's job was to make the app *reach* the shared reporter, and it did. The reporter then reached a **second, private matcher** that had always been there. The test T12 added asserted the explanation text — which the two doors genuinely did share. Nobody asked whether the *suggestions* were the same, because AC-12 says "the same explanation". | They typed a realistic typo instead of the fixture's word, on both doors, and compared. `gret` → `func greet` on one, nothing on the other. | One implementation: `app.utils.suggest_similar_commands`, the union of both (prefix/substring either direction, Levenshtein ≤ 2, case-insensitive). Both private copies deleted; both old test suites now run against it. New `test_a_typo_suggests_the_same_names_on_both_doors` runs on both doors via `cli_run`, with a far-miss falsifier beside it. |
| `adj S1` — #38 survives on the warm path | **PARTLY FIXED** · rest **NEEDS DECISION (D-2)** | Both of T11's tests carry `@surfaces("func")`, and that door is the single-file **eager** renderer. The parameterisation *looked* like two surfaces and was one code path. The second renderer reads `FieldDescriptor.choices`, which `_discovery/providers.py` alone filled with member **names** while the field's own docstring, `schema_extractor.py`, `_cli/introspect.py` and `_EnumChoice` all say **values**. | They ran the same program **twice** — the one thing a single test invocation never does — and watched the accepted spelling change between run 1 and run 2. | `providers.py` now emits `str(member.value)`; folded into the same `CACHE_VERSION` 21 bump, since a v20 entry spells choices the way the CLI will now refuse them. `TestTheWarmPathOffersTheSameSpellings` asserts the two renderers agree, including the int-valued enum that makes "values" a rendering rather than a lookup. **Still open: the body receives `str`, not the member, on the warm path — see D-2.** |
| `adj S5` — a cwd plugin directory still executes at boot | **FIXED** | T14 was written against the *mechanism* they had just read (discovery's directory list); AC-14 was written against the *outcome* ("not hijacked by an unrelated module in the working directory"). The plugin loader reaches `./.functualize/plugins/` by its own convention, execs it during app construction, and is unreachable from `job_sources` — so the reported symptom survived at a doorway the fix never came near. Both halves were right about their own half. | They went at the **outcome** and looked for other ways to reach it, rather than re-checking the mechanism that had just been changed. | `PluginSources.ambient_directory`, `False` in single-file mode, keeping T14's own line: a **declared** `plugins_directories` still loads. `TestTheOtherDoorIntoTheWorkingDirectory` — one end-to-end case and one resolver case proving declared survives. |

### The pattern in this batch

Four of the five are the same shape as batch 1's: **the implementer verified the
half they wrote.** The new one is `adj S4` and `adj S1` together — *a test that
builds its own fixture can only see the current build*. Neither "what does
yesterday's cache do" nor "what does run 2 do" is reachable from a fixture, and
both defects lived exactly there. That is worth a standing habit: for anything
persisted or memoised, **run it twice**, and **inject the previous shape**.


## Batch 4 — Class E, the `agent-step-port` behaviour defects

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `asp S-1` — refusals escape as raw tracebacks, exit 1 | **FIXED** (exit-code half) · history half **DEFERRED**, see below | Every test in `test_agent_step_refusals.py` drives `WorkflowRunner` or `AgentStepRegistry` directly and asserts `pytest.raises(...)`. That is **correct at that level** — and is exactly the behaviour that is wrong one layer up. The refusal *should* be an exception inside the engine and *should not* be one at the process boundary, and no test in the feature crossed that line. `contracts.md` §5 asserted the mapping existed; nothing implemented it. | They ran the **CLI construction path verbatim** rather than the unit under test, and read the exit code. | `scope_store_refusal` → `prelude_refusal`, now catching both agent errors and mapping them to `ExitCode.REFUSED` (3), with the docstring carrying why 3 and not 2. New `tests/workflow/test_agent_step_refusal_exit_code.py`: 4 cases × both doors, including a second invocation for the warm dispatch wrapper. Removing the catch fails 6 of 8. |
| `asp S-2` — the `CORE_*` mechanism is unenforced | **FIXED** | Every `CORE_*` check in the file is a `for name in table.core_names` loop, so an empty set makes all of them vacuous, and the one per-provider check derives its expectation from the hint function itself. `CORE_EXECUTORS` was a **fourth literal spelling** of a name that already exists on the class and as the table key; the strategy table it was copied from *builds* its set from `GateStrategy.*.value`, and the copy lost precisely that property. | They performed the single edit the mechanism exists to catch — emptying the set — and watched all four checks pass while the hint started telling the operator to "install functualize". | `TestTheCoreSetIsTiedToSomething`: the set is non-empty, its names are in the table, and `CORE_EXECUTORS == {CliPromptExecutor.name}` — asserted in the test because `agent_providers` cannot import `agent_step` (the dependency runs the other way). Emptying the set now fails 3. |
| `asp S-3` — the spec forbids a default executor; the code shipped one | **FIXED** in batch 2 as **D-1** | — | — | `tests/workflow/test_agent_step_walk.py` registers `_CliPromptExecutor` explicitly, the way a plugin does. |

### Deferred, with its reason

**`asp S-1`, second half — a refusal writes no history record and fires no
`AFTER_FAILURE` hook.** Reproduced and confirmed:

```
release -> raised AgentExecutorUnavailableError
boom    -> RunStatus.FAILURE
history: [('boom', 'failure')]
```

A job that ran and threw is recorded; a job that was refused before starting is
not. That is a real inconsistency and the fix is *not* at the click boundary:
the refusal would have to become a `JobResult(status=RunStatus.REFUSED)` inside
`_execute_lifecycle`, the way `GuardState.REFUSED` already does
(`_engine/executor.py:2278`), so that history, hooks and the exit code all fall
out of the one path instead of being re-derived at each surface.

**Deferred to `durable-run-layer` (F5, 0/13 tasks), not dropped.** That feature's
entire subject is *one identity for a run and one place to emit its events*; a
refusal that produces no run record is a case it has to answer anyway, and
answering it here would mean writing the same code twice — once at the boundary
now, once through the event path later. The user-visible half (a clean line and
the right exit code) is fixed today, so nothing is left in a broken state while
this waits.


## Batch 5 — `run-outcome-authority`, the two Blocking findings that were real

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `roa B3` — AC-2's gate cannot see the set it audits, and the surviving set is a delivery decision | **FIXED** | The gate greps for the three members **on one line**; `ruff format` had wrapped them across three. Sixth time on this branch, and the first time it hid a real divergence rather than a stale number. The adjudication ("the engine has no delivery surface") was then made *about the module* rather than about the function: `_is_failure` is reached only through an observer, the only observer is the CLI's parallel renderer, and the thing it controls is a `::error::` annotation in a CI log. | They ran the gate, then ran a **multiline** version of the same pattern, and read the surviving function's own docstring — which argues in delivery language ("for the *reader*", "would cry wolf in a CI log"). | The decision moved to `_cli/parallel_output.py`, which asks `is_failure(status, family=Family.PROCESS)`; the engine now reports the *status*, and `ParallelObserver.release` takes it. `tests/types/test_no_second_failure_set.py` replaces the grep with an **AST scan** plus a named allowlist, so formatting is not a variable and every surviving set is an argument someone wrote down. Three tests in `test_builtin_parallel.py` pin that BLOCKED gets one answer. |
| `roa B2` — AC-7's panel≡table parity test does not exist | **FIXED** | `tasks.md` named the file in T7 and then *reassigned* AC-7 to `tests/types/test_outcome_families.py`, which tests the module and never touches the panel. The reassignment reads like coverage and is not: nothing in the repo ran a BLOCKED run through the TUI at all. So T7's declared sabotage — "change the panel's family from `PANEL` to `PROCESS`; the parity test must fail" — had nothing to fail. | They ran `find tests -name '*panel_agrees*'`, got nothing, and then checked whether the *reassigned* file actually covered the criterion. | `tests/tui_audit/test_panel_agrees_with_table.py`: every terminal `RunStatus` × two assertions, through a real `FunctualizeInlineTUI`, a real `RichLog` and the real thread worker, with expectations **derived from `functualize.types`** rather than written down a second time. Plus `test_the_two_families_actually_differ_somewhere`, so the parity assertions cannot pass vacuously. T7's sabotage now fails 2. |

### What the divergence actually cost, for the record

`func builtin parallel` on a batch where one job paused at a gate: exit **5**
(the outcome authority, via T4) and **no `::error::` annotation** for the job
that paused (the engine's private tuple). CI red, nothing marked, and the reader
sent to expand every collapsed group to find out which job it was. Neither half
was wrong on its own; they were two answers to one question inside one command,
which is the exact thing this feature exists to end.

Both had passed every gate the feature wrote.


## Batch 6 — `run-request-entry` F4: four criteria kept by nothing

The feature's own AC→test table opens with *"A criterion with no test is a
criterion nobody is keeping."* Four of its rows named a keeper that does not
keep the criterion. None of the four was a **code** defect — the behaviour works
in all four cases, and I drove each one before writing anything. They are
**verification-record** defects, which is a distinct and quieter failure: the
table reads as coverage, so nobody looks again.

| AC | What the table named | What it actually kept | Now kept by |
|---|---|---|---|
| **AC-4** *"No file outside `_engine/` passes a job function for execution. **Asserted by a test, not by review.**"* | an `rg` command | review, with a shell in front of it — the criterion says in bold that this is what it does not want | `tests/spec/test_one_execution_entry.py` — the entry takes a request and nothing else, no public engine method accepts a job function, and an AST scan finds every out-of-kernel call that *runs* something. Resolution calls (`materialize_job`) are excluded by name, so the test is an invariant rather than a list of exceptions. Two sabotages, two failures. |
| **AC-6** *"cold and warm produce the same result **and the same recorded history entry**"* | `TestWarmBootParity` + `test_lazy_true_engine_materialization` | a **file trace of execution order**, and *import counts* plus one warm result. Neither compares the two runs; nothing anywhere compared history. | `tests/integration/test_cold_warm_history_parity.py` — output, exit code, and the history record's identity fields (`args_hash` included, which is the one artefact that would notice the two wrappers **binding arguments differently** while the printed output stayed identical). Includes `_assert_warm`, so the file cannot quietly compare two cold runs. |
| **AC-10** *"with `--prompt-gates` **prompts**"* | `test_app_surface_prompt_gates.py` | that the flag is accepted, and that a walk blocks without it. Its own docstring concedes the rest: *"Whether an interactive prompt actually renders is not testable without a tty."* True of a *terminal* prompt; the flag only adds `"prompt"` to the strategy list, and the resolver asks whatever `PromptCollector` the surface stack yields. | `tests/cli/test_prompt_gates_actually_prompts.py` — a pushed surface *is* the collector: asked, asked for the gate's field, walk completes; and without the flag, neither. |
| **AC-14** *"a `@workflow` submitted through `interactivity.job.submit` that blocks on a gate reports a scope id, and that scope can be answered and resumed"* | `test_event_submit_scope.py` | four tests over a plain `def greet()` — no graph, no gate, nothing to resume. The two halves were guarded separately (the registry learns an id; the id is well-formed) and **the join was not**: a change that kept the façade call and dropped the id at the engine seam would pass both and leave the audit's defect intact — *the scope existed and was unaddressable*. | A new class in the same file: submit, read the id off the registry, answer *that* scope's gate, resume, require completion — plus an unanswered-scope falsifier. Restoring the direct engine call fails 4. |

### Found while writing AC-10's test, and fixed

`GateRegistry.resolve_gate` kept only the **last** rung's exception, so a broken
earlier strategy left no trace and the operator was shown the *next* strategy's
complaint. A `prompt` resolver raising `TypeError` reported *"Cannot resolve
model Prefs from config chain: unresolved fields: ['budget']"* — a message
naming the config chain, which was working perfectly, and never mentioning
`prompt`. I lost time to it by being that broken resolver.

Every rung's failure is now reported, each labelled with the strategy it came
from. `TestEveryRungReportsItsOwnFailure` pins both that and the single-failure
case, which must still read cleanly.


## Batch 7 — `run-outcome-authority` S1–S6

Two with code substance, four record corrections. All six are now closed.

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `roa S2` — three of six surfaces declare their family only in prose | **FIXED** | T6's gate was `rg -c 'Family.WIRE' <file>` ≥ 1, and the docstring paragraph satisfied it — while *also asserting the property the gate was checking* ("naming it keeps the surface-to-family map greppable"). `AUDIT.md`'s hazard #1 exactly. The consequence: `Family.WIRE` and `Family.TOOL` reached HEAD with **no code consumer anywhere** — two members of a four-member vocabulary were decoration. T13's orphan scan should have caught that and did not. | They grepped for `family=Family.` and noticed the three plugins were absent from the results, then checked whether those files imported `Family` at all. They do not. | `OUTCOME_FAMILY = Family.<X>` as an assignment in each of the three, and `tests/types/test_every_surface_declares_its_family.py` checks each **declaration against what the surface actually renders for BLOCKED** — written as an equality, not `if WIRE then …`, so a wrong declaration fails rather than being skipped. Both tests fail under a swapped family. |
| `roa S4` + `S5` — AC-10 measures mention, not dependency; a consumer still reads the legacy path | **FIXED** | The scan is bounded to `src/`, and the one importer of the `_types/naming.py` re-export lives under `tests/` — invisible to it. The re-export's own comment says it is "kept for older importers"; there were none. | They ran the search over `tests/` as well as `src/`. | `tests/adapters/test_boolean_negation.py` migrated to `functualize.types`; the re-export deleted (pre-release, clean cutover). Two import-level tests added beside the mention scan, and the module docstring now **states plainly what the count does and does not prove** rather than implying it is a dependency list. |
| `roa S1` — the adjudicated inventory is not the code | **FIXED (record)** | Five sites were listed; two of them (`workflow.py:166`, `:199`) are `(FAILURE, REFUSED)` hook-firing conditions that no reading makes a success set. Line drift cannot explain a wrong *set shape* — the row was written from memory rather than from the hit set, which is the thing `.claude/rules/spec-workflow.md` says a task's file list must never be. | They ran the query and compared it with the row. | The AC-2 row restated with the honest inventory, and the gate replaced by the AST scan. |
| `roa S3` — the feature contradicts itself about what changed | **FIXED (record)** | `tasks.md` says W3 is "the only behaviour change in the feature"; `spec.md` §1.5 says the TUI is "the only surface calling a blocked run a success"; §1.1 of the same document lists `func builtin parallel` as a deciding site, and wave 2 changed its answer. The wave-audit table already knew two answers changed. A reviewer bisecting for the parallel exit-code change lands on W3 and finds nothing. | They read the graph's rationale against the audit table in the same file. | Both sentences corrected in place, with the correction quoted rather than the original silently replaced. |
| `roa S6` — "three plugin `test_status_codes.py` suites" | **FIXED (record)** | `spec.md` was corrected to two during execution; `tasks.md` T6 and the feature checklist were not. `find plugins -name 'test_status_codes.py'` returns two. | They ran the `find`. | Both places corrected. |

