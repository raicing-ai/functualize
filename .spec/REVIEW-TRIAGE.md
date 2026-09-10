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
