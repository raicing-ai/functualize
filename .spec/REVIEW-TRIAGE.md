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


## Batch 8 — `run-outcome-authority` A1–A3, the architecture findings

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `roa A2` — a second place answers "is this phase terminal?", and the two disagree about REFUSED | **FIXED** | Two literal sets, one module apart, in sibling files under `_engine/capabilities/`. `workflow.py`'s carried a comment explaining exactly what omitting REFUSED costs — *"a refused step simply never gets `end_time` or `duration`, so it reads as still running in every consumer of this record"* — and `runcontext.py` had precisely that defect. Nobody read the two side by side, because nothing made them adjacent. Worse, `tests/context/test_runcontext_status.py` **wrote out its own terminal list to state the contract independently**, mirrored the copy *without* REFUSED, and then asserted agreement with it — so the guard certified the defect and the two could never converge by failing. | They asked "what else answers a question something else already answers?" — the brief's own question — and looked one module over from the file the feature edited. | One definition: `RunStatus.terminal`, beside `resumable` and `ran`. `runcontext.py` derives its re-exported `_TERMINAL_STATES` from it; `workflow.py` asks the status directly. The test's independent list gains REFUSED and now compares against the **property**, not against one module's copy. Plus `test_only_one_module_defines_which_states_are_terminal`, an AST scan over `_engine/` that flags a written-out set while allowing a comprehension. Dropping REFUSED fails 19; reintroducing a literal fails the scan. |
| `roa A1` — `Family` has one live dimension, and nothing ties a family to its table | **FIXED (the mechanical half)** · redesign **not taken**, reason below | `_NOT_A_FAILURE` has four entries and **three are the same frozenset** — only PROCESS differs, and only about BLOCKED. And `is_failure(status, family=WIRE)` followed by `exit_code_for_status(status)` type-checks, runs, and answers 5 for BLOCKED while claiming the wire family. The pairing lived in the author's head. | They compared the four table entries and noticed three were identical, then asked what stops a caller pairing a family with the wrong number. | `TestEachFamilyAgreesWithTheTableItNames` — for every terminal status, each *numbered* family's answer must equal what its own table renders. PANEL and TOOL are named as knowingly unnumbered rather than assumed, and a fifth family that names no table fails. Editing `_NOT_A_FAILURE[WIRE]` without the HTTP table now fails 3. **The two members that were unreachable were fixed in batch 7** (`OUTCOME_FAMILY`). |
| `roa A3` — `_types` is documented as behaviour-free; `flag_grammar.py` is 210 lines of behaviour | **FIXED (the doc was wrong)** | The line said *"only dataclasses, enums, protocols"* and had been false for a long time — well before this feature. | They read a doc line against the code it describes. | The reviewer offered a dichotomy — the doc is stale, or the module is in the wrong layer — and the evidence settles it decisively: `flag_grammar.py` defines **4** functions, while `workflow.py` defines 36, `job_declaration.py` 27, `naming.py` 25, `redaction.py` 18. `flag_grammar` is among the *least* behavioural modules in the package. `contributor/architecture/overview.md` now says what `_types` actually holds and what still does not belong there (anything reaching a subsystem — enforced by contract). |

### A judgement I did not make

`roa A1` offered two refactorings, preferring *"make the family own the number"*
— `Family.PROCESS` carrying the exit code, `Family.WIRE` the HTTP status. That
is a real improvement and it **contradicts a recorded design decision**:
`contributor/architecture/run-model/06-outcome-authority.md` §D chose a function
over the object deliberately. Prior art outranks a fresh argument, and
contradicting it silently is the one thing the retrieval rules forbid.

No surface commits the mismatch today — every `is_failure` call site pairs
PROCESS with the exit table and PANEL with the panel — so the hazard is latent,
and it is now mechanically checked. Redesigning the authority is a maintainer's
call, not a triage fix, and it is not blocking anything.


## Batch 9 — `run-request-entry` F6 and F8: surface policy stops being convention

These are one finding wearing two hats: **what the engine decides from a
surface** (F6) and **whether a door has to name itself** (F8). Both were held by
convention, and both failed *silently* when the convention was not followed.

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `rre F6` — `CONSOLE_SURFACES` is engine policy living in `_types`, and a second hand-maintained taxonomy | **FIXED** | The set was written when stdin resolution moved into the kernel, and it was *correct*. What it could not be was **total**: adding a console door to the 18-value `Literal` and forgetting the set silently dropped stdin for it (the parameter's default wins, nothing said); adding a non-console door re-introduces the `/dev/null` read the docstring warns about. A third copy of the four names was re-typed in `tests/engine/test_run_request_stdin.py`. The second policy — `request.surface == "app.parallel"` for history — is the same shape, one method away, and nobody saw them as one thing. | They listed every consumer of the set and asked what happens to a door that is in the `Literal` and not in the set. | `SurfacePolicy` + `SURFACE_POLICY`, one entry per door, both decisions as fields. The lookup is a **subscript**, so an unclassified door raises `KeyError` rather than inheriting the majority answer — which is the whole difference from a `frozenset` membership test. `CONSOLE_SURFACES` survives as a *derived* name. `TestEveryDoorIsClassified` (5 tests) makes totality true rather than intended; adding a door to `RunSurface` and not to the policy now fails. |
| `rre F8` — `surface` has a default, so "every door names itself" is honour-system | **FIXED** | `RunRequest.surface` is required, which *is* the right shape and was already done — the field even carries a docstring saying "a door must name itself". Then all four constructors that build one defaulted it to `app.cli`. The feature applied exactly this rule to `prompt_gates`, `output_format` and `force` and **stopped one field short**, so the check was a convention rather than a mechanism. | They followed the seam furthest from anyone's attention — `create_job_command`, the callable form for embedders, reached from `_discovery/registry.py` with no surface argument — and printed the request it produces. | No default at `build_request`, `create_job_click_command`, `build_job_engine_callback`, `make_lazy_command`. `mypy` then named all four call sites, which is the enforcement; `TestEveryDoorNamesItselfOrDoesNotCompile` keeps the defaults from growing back. |

### What the mislabel actually cost

`create_job_command` labelled every embedder run `app.cli` — a door it never
came through. Not cosmetic, and this is exactly why F6 and F8 are one finding:
`app.cli` **owns the process's stdin**, so the mislabel handed those runs stdin
resolution and the ambient click-context read, chosen for a door they had not
used. Its default is now `app.execute` — what an embedder holding a callable
actually is — and `test_the_embedder_seam_is_not_labelled_as_the_app_cli`
asserts the default is outside `CONSOLE_SURFACES` rather than merely that it
changed.

### A correction to my own reading

Mid-triage I said `_dispatch_group` was mislabelled `app.cli`. It is not — it
passes `surface="func.group"`, and my grep window was ten lines short of the
argument. The reviewer's finding was about the *signatures* defaulting, and the
one caller genuinely relying on the default in a way that mattered was the
embedder seam.


## Batch 10 — `run-request-entry` F9 and F10

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `rre F10` — `_click_obj()` reaches into a foreign program's `ctx.obj` | **FIXED** | The accessor's docstring defends the channel on **lifetime** — a click context is per-invocation, unlike the process-lifetime deposit it replaced — and that argument is correct and answers the wrong question. **Ownership** is the property that matters, and the walk-up returns *the nearest* dict. `CliAdapter.__call__` skips registering its own callback when the caller brings their own group, so in an embedded app the nearest dict is **the host's**. A host storing its own globals there — the plain click idiom — silently drove `force`, `prompt_gates` and `output_format`. | They read the defence, noticed it argued lifetime rather than ownership, then wrote a host program that owns its group and printed the request. | `_click_obj(app_ref)` trusts a dict only when `obj["app"] is app_ref`, which is what `adapters/cli.py` already puts there. `TestOnlyThisAppsAmbientDictIsTrusted` — four tests, including that the app's *own* dict is still read (refusing every ambient dict would pass the headline test and break `--force`) and that a **second app's** dict is refused, since "has an `app` key" is not identity. |
| `rre F9` — `guarded_execute` hardcodes `surface="app.execute"` | **FIXED** | The constant was written when `guarded_execute` had one caller. It grew two more — `func builtin workflow resume` and the MCP workflow tools — and neither could say so, because the parameter did not exist. Same shape as F8: the field is required on `RunRequest` and optional everywhere that builds one. | They asked what the `surface` field is *for* and then checked whether the workflow verbs could answer it. | `surface` threads through `resume_scope` / `call_gate_tool` / `guarded_execute`, defaulting to `app.execute` — honest, because a caller with nothing to say about its door genuinely is programmatic. `func.builtin` returns to the vocabulary **on the terms its deletion named**: *"if a later door needs one, it comes back together with the code that produces it."* It does not own stdin — a control verb must not read the user's terminal on a resume. |
| `rre F9` — `ExecutionContext.request` duplicates the fields beside it | **DOCUMENTED + PINNED**; collapse **deferred to F3**, reason below | `request` was added to carry the delivery inputs to capability factories, whose only route to it is `ctx.context`. That justifies carrying the object; nothing said what the *relationship* to the restated scalars is, so the field reads as a second source of truth — which `_types/protocols.py` explicitly forbids, in a sentence written about the other context. | They counted the fields both shapes hold and found the rule missing. | The field now states it: the scalars are **this execution's working copy**, `request` is **what the door asked for**; they start equal and a nested run's context legitimately differs. `tests/engine/test_context_request_agreement.py` asserts they do not drift for a top-level run, off a real run rather than a constructed context. |

### Deferred, with its reason

**Collapsing the duplication** — deleting `invoke_depth`, `cwd`, `job_directory`
and `parent_scope` from `ExecutionContext` and taking a `.request.` hop at the
**15** read sites — is `engine-sealed-construction`'s business. T6–T11 extract
`WorkflowOrchestrator` and `DependencyRunner` from exactly this code and put
`RunContext` on a diet. Doing it now is a churn that feature has to redo, and it
would make its diff harder to read. The hazard the duplication creates is
*divergence*, and divergence is now a failing test rather than a possibility.

### A mistake worth recording

The first version of that drift test patched `_engine.context.ExecutionContext`.
`executor.py` binds the name at import, so **nothing was intercepted** and every
assertion ran over an empty list — passing. `test_the_recorder_actually_saw_something`
is what caught it, and it is the falsifier I nearly did not write. Patch where a
name is *used*, not where it is defined.


## Batch 11 — `run-request-entry` F11, F12, F13 — and a hole in my own gate test

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `rre F12` — one wire contract, four copies, three wrong citations | **FIXED** | HTTP and Lambda's `_envelope` were **byte-identical** but for the `surface` literal, and MCP restated the shape in prose at both its doors. Nothing about layering forced the fork — `_types/run_request.py` is stdlib-only and all four already import `RunRequest` from it — it was simply written where it was needed, twice. The citations drifted because each copy was written at a different moment: two said "risk R-a, spec AC-9", one said "spec AC-4, AC-9"; the criterion is **AC-17a**. | They diffed the two copies and then checked what each docstring cited. | `functualize.types.request_from_envelope` — one parser, `surface` as a parameter, the contract documented once. `TestOneWireContract` covers AC-17a's actual property (a payload key named `scope_id` arrives as an argument; the control input beside it does not) and a structural test refuses a door that parses the envelope itself again. |
| `rre F11` — two comments describe machinery this feature deleted | **FIXED** | T11 and T12 deleted both bridges and their gates read 0 — but the gates match **identifiers**, so prose naming them survived and went on telling a reader the mechanism existed. It does not: `func --output json builtin info jobs` answers `Error: No such option '--output'`. | They read the comment and ran the command it implied. | Both comments corrected to state what is true, including that the delivery flags do not reach BUILTIN mode. Making them reach it is a behaviour change nobody asked for; inventing one while fixing a comment is how scope grows silently, so it is recorded rather than done. |
| `rre F13` — a test that cannot fail | **FIXED** | `test_every_declared_surface_is_constructible` iterated `RUN_SURFACES` and asserted each constructs — but `RUN_SURFACES` **is** `get_args(RunSurface)` and `__post_init__` rejects exactly its complement. It asserted that the set derived from the closed set is inside the closed set. | They checked what each test in the file would fail on, and this one had no answer. | Replaced by the falsifiable property underneath: every declared surface must be **named somewhere that produces one**. A label nothing can produce is decoration — which is why two were deleted and why `func.builtin` came back only when a door needed it. Re-declaring `func.bare` now fails. |

### The one that matters most: my own aggregate test had the branch's signature defect

While correcting F11's comment I wrote the deleted identifier into the replacement
prose — which pushed `run-request-entry`'s bridge gate from **0 to 2**, and
`tests/spec` **stayed green**. Two bugs in the parser I wrote in batch 2:

1. **Wrapped commands were skipped silently.** The skip test was `"\n" in cmd`,
   and a gate typed across two lines with a trailing `\` is one command. Every
   such gate never ran.
2. **Worse: one gate swallowed the next.** `run-request-entry/T11` writes its
   record on two lines (`now at wave 4 entry: … ·` / `after: 0`). The pattern
   required the values on the single line after the closing fence, so the
   non-greedy `cmd` expanded **past its own fence** looking for one that
   matched — consuming the gate in between, then running one gate's command
   against another gate's recorded value.

The parser is now fence-aware and joins continuations. That immediately surfaced
three records nobody had checked:

- `adjacent-defects/T7` — reads 3 against `after: 0`. **Not a regression**: the
  record's own second branch is *"unchanged with each remaining site carrying a
  comment naming why"*, and all three do. Annotated, because a line offering two
  outcomes and naming neither reads as a failure on re-run.
- `run-request-entry/T16` — `now == after == 4`, a gate that cannot fail. The
  author **disclosed it** — *"the count is not the gate here; the test is"* — in
  words the parser does not read. Marked `invariant` so the machinery can see
  what the prose already said.
- The bridge gate itself, once un-swallowed.

`test_every_fenced_gate_is_accounted_for` is the new guard: every fenced gate is
either checked or skipped **for a reason the test can name**. A count could never
have caught a whole *category* going missing — it stayed comfortably above its
floor of 12 the entire time.

**The lesson, stated plainly:** the test written to catch unfalsifiable gates was
itself partly unfalsifiable, and a count of what it found could not reveal that.
When a check filters, assert on **what it filtered out**, not only on what it kept.


## Batch 12 — `run-request-entry` F5 and F7, the feature's last two

| Finding | Verdict | Why the implementer missed it | Why the reviewer found it | What catches it now |
|---|---|---|---|---|
| `rre F7` — `_request_kwargs`' config-model split is a no-op defended by an unasserted claim | **FIXED — and the finding was stronger than the report** | The split came over from the click adapter along with stdin resolution, as one move. In the adapter it had a job: click built config options and job options separately, so the two halves were already distinct there. Moving both to the engine put the halves back into one dict on the way in and merged them on the way out, and nobody re-asked whether the round trip still did anything. The docstring answered the question with a claim — *"a `Stdin` marker never sits on a config model's field"* — that read like a design rule and was in fact a guess. | They noticed the union of the two halves is the input mapping, then went looking for what the split could possibly distinguish, and found only a case the docstring declared impossible. |  The claim is false: a job **can** declare `data: Annotated[str, Stdin()]` beside a config model with a `data` field, and nothing refuses it. Measured on the three cases the split can distinguish, it changed the answer **exactly once, and in the wrong direction** — an explicit `None` on a colliding name reached the config model and failed `str` validation instead of being dropped so the pipe could supply it. So it was inert where it was defended and wrong where it was not, and it is deleted rather than asserted. `TestAMarkerThatSharesAConfigFieldsName` — four tests, the first of which asserts the collision is constructible at all, so the class fails loudly if a future change makes the premise moot. Reinstating the split turns exactly one of them red, which is how the "wrong direction" claim above was measured rather than argued. |
| `rre F5` — AC-20 cannot be assessed under machine load | **CONFIRMED contention, and the residue fixed** | The budget's own comment already anticipated half of it — *"CI is slower and noisier than this machine, and a perf test that flakes gets muted, which is worse than one that is loose"* — and answered it with headroom (1800ms against an 850ms max). Headroom is the wrong instrument: a 3.5×-oversubscribed machine does not add a constant, it multiplies. The conftest already skipped these tests under coverage and xdist for precisely this reason; it just never considered the load the harness cannot see. | They read `/proc/loadavg` before believing the failure — 41.55 on 12 cores — and noticed two budgets this feature never touched blew out by the same factor. | Re-run alone at load 4.0/12 cores: **12 passed in 5.27s**, so the finding's own discriminator holds. The residue is now closed at the source: `_oversubscription()` in `tests/conftest.py` reads the 1-minute load average per core, and above **2.0** every `perf_budget` test skips with a reason naming the measured load — the same rule already applied to coverage and xdist, extended to the third distortion. `tests/perf/test_budget_guard.py` pins both directions, including the reviewer's exact 41.55/12 reading, and pins that an *unmeasurable* machine keeps asserting: failing to skip is a flake you re-run, failing to assert is a regression that ships. |

### Why 2.0, and not tighter

The budgets already carry ~2× headroom over their authored maxima, so anything
below a 2×-oversubscribed machine still fits inside them and keeps asserting. A
serial `pytest` on a 2-core CI box sits near 1×. The reviewer's box sat at 3.5×
and produced 3× the budget. 2.0 is the line between "the number describes the
code" and "the number describes the queue" — and it is a constant with a comment
citing the two real measurements, not a tuned threshold.

`run-request-entry`'s thirteen findings are now closed: F1–F4 and F6–F13 fixed,
F5 confirmed as contention with its residue fixed.


## Builtins and the delivery inputs — a question `rre F11` raised and did not answer

`F11` was filed as prose drift, and fixing it left a vaguer claim than it should
have: *"the delivery flags do not reach BUILTIN mode."* True, and it does not say
which flags, why, or whether it matters. The maintainer asked the two questions
that expose it — **which builtins would need them, and are delivery flags even a
different thing from early-parse flags?** Both are answered here from measurement.

### They are not two vocabularies — one is a subset of the other

All three delivery inputs live in the same pre-boot grammar as every other
global (`_types/flag_grammar.py`): `--output` in `GLOBAL_OPTIONS_OPTIONAL_VALUE`,
`--force` / `--prompt-gates` / `--no-prompt-gates` in `GLOBAL_BOOL_FLAGS`. So
"early-parse flag" is the *grammar*; "delivery input" is the subset that lands on
a `RunRequest`.

**BUILTIN mode drops exactly that subset**, which is a much sharper fact than
"the flags do not reach here":

```
func --log-level ERROR       builtin version  ->  functualize 0.3.0
func --config-directory /tmp builtin version  ->  functualize 0.3.0
func --exclude nothing.py    builtin version  ->  functualize 0.3.0
func --output json           builtin version  ->  Error: No such option '--output'.
func --force                 builtin version  ->  Error: No such option '--force'.
func --prompt-gates          builtin version  ->  Error: No such option '--prompt-gates'.
```

The globals that configure **discovery and the process** get through; the three
that configure **a run** do not, because BUILTIN mode builds no request.

### Which builtins would actually use one

Of the seventeen, only two run a job, and one more reports on whether a job
*would* run:

| Builtin | Would use | Status |
|---|---|---|
| `builtin parallel` | **`--force`** | **A real asymmetry.** `func build --force` works; `func builtin parallel build deploy` cannot force, so a fresh job is skipped with no override. `execute_parallel(job_names, timeout, observer)` has no parameter for it and builds `WiredInvoke` with **no `parent_request`**, so `nested_request(None, …)` gives every item `force=False`. The *carrying* mechanism works — that is `rre F1`, fixed in batch 1 — the **door has no flag**. |
| `builtin why` | `--force` | `why` reports the freshness verdict, and `--force` changes what that verdict would be. Currently unsayable. |
| `builtin workflow resume` | `--prompt-gates` | **Not a gap.** It takes `--input` / `--gate`, an explicit answer, which is a reasoned alternative to prompting for a verb that may be run non-interactively. |
| the other fourteen | — | Inspection only. Nothing to deliver. |

### And a collision found while checking

Three *local* spellings of "how should this be rendered" have grown inside the
builtins, and one **collides with the global flag of the same name**:

| Where | Flag | Values |
|---|---|---|
| global | `--output` | `auto, json, ndjson, raw, none` — `out.emit()` serialization |
| `builtin parallel` | `--output` | `interleaved, grouped, prefixed` — output *routing* |
| `builtin workflow resume` | `--format` | `table, json` |
| `builtin why` | `--json` | (a boolean) |

Same name, **disjoint value sets, different meanings** — plus two more spellings
of the JSON question. This is the divergence class `run-outcome-authority` exists
to end, in a corner the global grammar does not reach.

### Status: the `--output` half is DONE; the rest is still open

**Renamed 2026-09-10, on the maintainer's decision: the global `--output` is now
`--emit-format`.** The reasoning is in `_types/flag_grammar.py` beside the table
and in `tests/cli/test_emit_format_rename.py`; the short version is that two
informed guesses at what the old name meant — `--line-format` and
`--return-value-format` — both described something the flag provably does not
do, and a name that reliably produces the wrong model is worth changing while
the project is pre-release.

The evidence that settled it, from one job that emits one value and returns
another:

```
$ func --emit-format json j.py returns_only   ->  (nothing, exit 0)
$ func --emit-format raw  j.py returns_only   ->  (nothing)
$ func --emit-format json j.py emits          ->  {"from":"emit"}
```

The return value is never rendered at any format, and `print()` is ignored too.

`func builtin parallel --output {interleaved,grouped,prefixed}` is deliberately
**untouched** — a different flag with a disjoint vocabulary, and the collision
is gone now that the global has a different name. Whether it should become
`--layout` for accuracy is a separate, smaller question.

**No migration aid, deliberately.** I first added a `RENAMED_FLAGS` table so the
old spelling would answer *"'--output' was renamed to '--emit-format'"*, on the
grounds that `Unknown command 'output'` is a poor error. The maintainer removed
it: the project is pre-alpha, `.spec/CONSTITUTION.md` says **delete rather than
shim**, and a migration aid is precisely how one thing acquires two names. The
old flag now gets whatever any unknown token gets. What survives is a test that
`--output` appears in **no** grammar table — the property worth guarding is that
there is only one spelling, not that the dead one is polite.

**A real bug the dual-surface test caught.** Click derives a callback's
parameter name from the flag, so renaming only the flag string left the app
adapter reading a variable that no longer existed — `--emit-format none`
silently stopped suppressing on the app surface while `func` kept working. The
`[app]`/`[func]` parameterisation is what made it visible.

### Still open (D-3, narrowed)

Nothing is being changed on the strength of this. Wiring `--force` into
`builtin parallel` and `builtin why` is a small, well-understood addition; the
`--output` collision is not, because renaming either spelling is a **breaking
CLI change** and the two meanings are both legitimate. Three options, in the
order I would take them:

1. **Wire `--force` only.** Closes the asymmetry a user can actually hit, touches
   `execute_parallel`'s signature and two builtins, leaves the naming alone.
2. **Also rename `builtin parallel --output` to `--layout`** (or `--report`), so
   one spelling means one thing. Breaking, and worth it only if the collision is
   thought likely to bite.
3. **Record both as intended and stop.** Defensible: a builtin is a command, not
   a job, and a command owning its own flags is ordinary.

My recommendation is (1) now and (2) folded into whichever feature next touches
the builtin CLI, because a breaking rename wants a release note rather than a
triage commit. **Your call.**

