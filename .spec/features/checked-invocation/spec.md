# checked-invocation — Specification

A parent job can **assert** that a child it invoked did its work, in one call
on the result it already holds, and can **take back** what that child emitted
as data instead of letting it reach stdout. Two opt-in additions to the
composition primitive `inv("child")`; the call a parent already makes does
exactly what it does today.

## Authority and status

- **Shape intent:** Confluence `SD/15138825` **v4**, `Status: Approved`,
  `Authority: Approved`, `Last reviewed: 2026-10-13`. Read live on 2026-10-24
  from the issue's `Shape intent` property. The page's preamble and its
  `Outcome` section still say "not approved"; both sentences predate the v4
  field flip, and the **field** governs (`plan.md` → `## Alignment`).
- **Multica:** `Shape state = approved` on both carrying issues (read
  2026-10-24).
- **Lanes:** FOSS-106 (checked lane, §A) and FOSS-107 (capture, §B), both
  `Accepted` in Jira and read live on 2026-10-24.
- **Status: confirmed 2026-10-26.** The maintainer confirmed D1–D5 as
  recommended and accepted S1 in comment
  `01a177e2-43ac-7db8-83d1-21948b9b0a3e` (2026-10-26T11:04:39Z).
  Execute is authorised against the confirmed contracts and task graph.
- **Amended 2026-10-26.** `EmissionRecord` is placed in
  `_types/run_request.py`, beside the annotation that names it, not in
  `_types/stdout.py`: `get_type_hints(RunRequest)` resolves the annotation in
  that module's globals and the module may import nothing from `functualize`.
  Nothing is re-exported from `_types/stdout.py`. `contracts.md` C5,
  `plan.md` §4 and its file table, and `tasks.md` 1.2's `[F]` set follow the
  placement. Behaviour is unchanged. Maintainer, 2026-10-26: "I choose (a)"
  (comment `01a17859-e237-7681-94c5-543f294fee87`).

Original planning base: `master` `b3e624bd`, measured 2026-10-24. Execution
base: `11ed0e82`, remeasured 2026-10-26; the public-surface set moved ten lines
to `tests/test_public_api_surface.py:253-299`, while cited engine anchors stayed.

## 1. Problem

### 1.1 Failure is not assertable (FOSS-106)

Reproduced at `b3e624bd`, in single-file mode with an isolated `HOME`:

```text
# jobs/demo.py — boom() raises RuntimeError("boom failed");
# chain(inv: Invoke) calls inv("boom"), prints the status, returns
$ func jobs/demo.py boom    -> exit 1, stderr: "Error: RuntimeError: boom failed"
$ func jobs/demo.py chain   -> exit 0, stdout:
    CHAIN CONTINUED: status=RunStatus.FAILURE exception=RuntimeError('boom failed')
```

A failed child is a **value**, not an error. That is deliberate and
documented: `docs/api/context.md:110` (*"Returns: `JobResult` with status,
duration, return_value, and exception"*), and
`docs/api/context.md:158-160` (*"`Invoke.__call__` invokes one child and returns
its `JobResult`"*). What is missing is a **checked lane**: nothing in the call a
parent makes asks it to look, so a parent continues past a failed child.

`Invoke.parallel` already gained a checked default
(`_engine/capabilities/invoke.py:583-600`, `CHANGELOG.md:299-313`):
it raises `RuntimeError` naming each failed child and chains the first cause.
Its predicate is `is_failure(status, family=Family.TOOL)`
(`invoke.py:587`). A single `inv()` has no equivalent.

### 1.2 A child's emissions are not addressable (FOSS-107)

```text
# parent(inv, out) invokes child_a, which emits {"step": "a"}, then emits its own
$ func --emit-format json jobs/demo.py parent   -> exit 0, stdout = TWO documents:
    {"step":"a"}
    {"step":"parent"}
```

Deliberate: `_engine/capabilities/stdout.py:12-14` — explicit emission is
*"never surface-suppressed … The job author asked for it."* The child's
`out.emit()` reaches the caller's stdout unattributed, and only its
`return_value` is reachable as data.

## 2. User stories

- **US-1.** As a job author composing children, I write
  `inv("build").raise_for_status()` and my parent stops — with a non-zero exit
  and the child's name and error on stderr — when `build` did not do its work.
- **US-2.** As a job author who handles failure myself, I keep writing
  `r = inv("build")` and branching on `r.status`. Nothing changes for me.
- **US-3.** As a job author composing on a child's output, I write
  `r = inv("report", capture=True)` and read what `report` emitted from
  `r.metadata["emitted"]`, and none of it reaches stdout.
- **US-4.** As a job author who uses both, I write
  `inv("report", capture=True).raise_for_status()`. A failed `report` raises,
  and the error still carries what `report` emitted before it failed.

## 3. Behaviour

### §A — the checked lane (FOSS-106)

**A1. One method on `JobResult`.** `JobResult.raise_for_status()` raises
`JobFailedError` when the result's status means *the job did not do its
work*. Otherwise it returns the same result object. *(D2: the name. Returning
the result is decided in `contracts.md` C1.)*

**A2. "Did not do its work" has one definition.** It is
`is_failure(status, family=Family.TOOL)` (`_types/outcome.py:78-89`), the
predicate `Invoke.parallel` already raises on. Measured over `RunStatus`:

| Status | Raises | Why |
|---|---|---|
| `SUCCESS` | no | |
| `SKIPPED` | no | a skip is not a failure in every family (`outcome.py:62-75`) and exits 0 |
| `BLOCKED` | no | a declared, resumable pause (`enums.py:34-44`, `RunStatus.resumable`) |
| `FAILURE` | yes | |
| `REFUSED` | yes | a declared precondition was not met. The `INVOKE_FAILURE` hook was widened to it for this reason (`invoke.py:517-520`) |
| `TIMEOUT` | yes | reachable from one `inv()`: `_execute_with_timeout`, `invoke.py:683-708` |
| `CANCELLED` | yes | |
| `UNKNOWN` | yes | |
| `RUNNING` | yes | transient; `is_failure` answers `True` by its docstring (`outcome.py:85-87`) |

This matches the documented `invoke.parallel` set (`docs/api/context.md:149-151`:
*"`SUCCESS`, `SKIPPED`, and `BLOCKED` do not trigger the default raise. Other
terminal statuses, including `FAILURE` and `TIMEOUT`, do."*).

**A3. The raised error carries the child's identity.** `JobFailedError` holds
the whole `result` and exposes `job_name`, `status` and `exception` from it.
`metadata` is reachable as `err.result.metadata`. When the result has an
`exception`, the new error is raised **from** it (`__cause__`), so the child's
own exception and frames stay attached. *(D1: chain vs re-raise.)*

**A4. The parent's stderr names the child and its error.** At the default log
level the CLI boundary prints one line for a job's own exception
(`app/adapters/click_params.py:1315-1349`, ADR-032 §3). That line therefore
reads, for the repro above:

```text
Error: JobFailedError: job 'boom' did not succeed (Failure): RuntimeError: boom failed
```

At `--log-level DEBUG` the full traceback is printed. It shows the child's
`RuntimeError` frames, then *"The above exception was the direct cause of the
following exception"*, then the parent's frame.

**A5. A nested parent that lets it escape stays honest.** When the parent does
not catch `JobFailedError`, the parent's own result is `FAILURE`, its
exception is the `JobFailedError`, and it is marked raised-by-job because it
escaped the parent's call (ADR-032 *Neutral*). `func chain` exits **1**
(`exit_code_for_status(FAILURE)`), and the run log records both `boom` and
`chain` as `failure`. This holds one level further up: a grandparent that calls
`inv("chain").raise_for_status()` raises a `JobFailedError` whose cause is
`chain`'s `JobFailedError`.

**A6. The `INVOKE_FAILURE` hook uses the same predicate.** It fires when
`is_failure(result.status, family=Family.TOOL)`. Today it fires on
`FAILURE` or `REFUSED` (`invoke.py:520`), so this **adds** `TIMEOUT`,
`CANCELLED`, `UNKNOWN` and `RUNNING`. One test pins today's narrower set:
`tests/context/test_invoke_failure_hook.py:108`
(`test_invoke_failure_not_fired_on_timeout`, "Req 21.6"). A second asserts it:
`tests/hooks/test_invoke_failure_properties.py:7,146-175`. Both flip. *(D3.)*

**A7. The unchecked lane is untouched.** `inv("child")` without the call
behaves as it does today: `func chain` exits 0, and the result still carries
`status` and `exception`. `JobResult` gains no field. Its `__eq__`, its
`__hash__` and its field list are unchanged, and `exception` keeps
`compare=False, hash=False` (`_types/descriptors.py:492`).

**A8. Every `JobResult` has the method, wherever it came from.**
`app.execute(request) -> JobResult` (`app/core.py:568`) and every
`invoke.parallel(..., raise_on_failure=False)` result answer it the same way.
The second is how a caller gets the whole batch and then checks one item. A
caller that is not a job sees the same `JobFailedError`.

### §B — capture (FOSS-107)

**B1. Opt-in keyword.** `inv("child", capture=True)` (and
`rc.invoke("child", capture=True)`, which forwards keywords at
`_engine/capabilities/runcontext.py:509-518`) records what **that child**
passes to its `Stdout`. Default `capture=False`.

**B2. Returned on the result's metadata.** The returned `JobResult` carries
two keys. The frozen type gains no field (the `_awaits_input` precedent,
`invoke.py:499-515`):

- `metadata["emitted"]` — a `tuple` of the values passed to `out.emit()`, in
  call order, **as passed**. Nothing is serialized, re-parsed or redacted, and
  `None` is recorded like any other value.
- `metadata["writes"]` — a `tuple` of the payloads passed to `out.write()`, in
  call order, as passed (`str` or `bytes`). *(D5: `writes` vs the ticket's
  `written`.)*

Both keys are present, and both are empty tuples, when the child emitted
nothing on that channel or never declared a `Stdout` at all.

**B3. Captured output does not reach stdout.** Under `capture=True` the child's
`emit` and `write` are recorded **instead of** written. The parent decides
what, if anything, to emit. *(D4: divert vs tee.)* For the FOSS-8 repro with
`capture=True` on both children, `func --emit-format json parent` prints
**exactly one** document, the parent's, and that document carries the
children's captured values.

**B4. Capture ignores `--emit-format`.** The format governs rendering to the
stream, and capture bypasses the stream. `capture=True` records under
`--emit-format none` exactly as under `json`. A value the format cannot
serialize (a custom object under `json`) is captured as the object itself, and
no error is raised.

**B5. The default path is byte-for-byte unchanged.** Without `capture=True`,
the child's output goes where it goes today, and the returned metadata gains
neither key.

**B6. Failure still reports, with what was emitted.** A child that emits and
then raises returns `status=FAILURE` with `metadata["emitted"]` holding what
it emitted before raising. With §A, the `JobFailedError` from
`raise_for_status()` carries those values on `err.result.metadata`.

**B7. Scoped to the child it was asked of — not transitive.** Capture applies
to the invoked child's own `Stdout` only:

- a grandchild that the captured child invokes **without** `capture=True`
  writes to stdout as it does today;
- a grandchild invoked **with** `capture=True` is captured into the child's
  result, and the child can then emit or return it. That emission is in turn
  captured by the parent: the data survives nesting.
- Dependency runs (`Deps`) and workflow steps that the child triggers are never
  captured.

**B8. Timeout.** A captured child that times out returns `TIMEOUT` with what
it emitted **up to the timeout**. The thread cannot be interrupted, so it may
keep running (`invoke.py:926-934`), and anything it emits after that point is
discarded. It is not written to stdout. The reference documentation says so.

**B9. Memory.** Captured values are held, by reference, in the parent's result
for as long as the parent keeps it. The reference documentation states that,
and there is no cap or default that hides it (shape Risk 1).

**B10. Out of scope, stated.** `Invoke.parallel` does not accept `capture`, and
its behaviour and its `ParallelObserver` seam (`invoke.py:37-57`) are
unchanged. `MockInvoke` (`testing/doubles.py:91-107`) already absorbs every
keyword. A test that passes `capture=True` to it receives the result it
configured, with no capture keys added.

### §C — documentation (both)

**C1.** `docs/api/context.md` `rc.invoke` (`:101-110`) shows the checked call,
says plainly that the result is unchecked by default, and documents
`capture=True`: the default, the two keys, B3, B4, B7, B8, B9. Its `invoke.parallel`
paragraph (`:158-160`) points at `raise_for_status()` for the single call.

**C2.** `docs/guides/composition.md` adds the composition rule for children.
`invoke` composes **values**, so check them. `Deps`/`FromJob` composes
**statuses**: a refused dep fails the dependent (`:72`). The guide's opening
questions (`:8`) gain *"Does a failing child look like a crash to my CI?"*.
`:316-318` gains the rule that a child's emission reaches the caller's stdout
unless captured. It also says that only return values and captured documents
are reachable as data, and what a checked child failure does to the parent's
status and exit code (A5).

**C3.** `docs/api/types.md:179` (*"`--emit-format` governs `out.emit()` and
nothing else"*) gains one sentence: this holds for invoked children too, and
capture records regardless.

**C4.** `docs/guides/run-context.md:439-457` (`rc.invoke`) links the
`docs/api/context.md` reference rather than restating it. There is no second
guide (shape *Boundaries*).

## 4. Decisions (confirmed 2026-10-26)

| # | Decision | Confirmed option | Alternative considered | Why |
|---|---|---|---|---|
| **D1** | Raise shape when the child has an exception | one type, `raise JobFailedError(result) from result.exception` | re-raise the child's own exception, and use a new type only when there is none (FOSS-106 *Deliverable 1*) | The approved shape names one type carrying identity. The boundary prints one line (A4), and a re-raise prints `RuntimeError: boom failed` without saying which child. A re-raise also mutates the child's exception's `__traceback__`, and that object is the one on the child's own result. `invoke.parallel` already chains (`invoke.py:599`). |
| **D2** | Name and home of the error | `JobFailedError` in `_types/errors.py`, exported from `functualize.types` beside `JobResult` | `InvokeError` (mirrors `ShellError` for `Shell`) | The method sits on every `JobResult`, including `app.execute`'s (A8), so an `Invoke`-named error misnames half its callers. `Job…Error` is the file's family (`JobNotFoundError`, `JobDependencyError`, `JobMaterializationError`). `functualize.types` already exports an error a boundary must catch (`MissingValueError`, `types/__init__.py:11-15`). |
| **D3** | `INVOKE_FAILURE` hook predicate | widen to the shared predicate (A6); retire "Req 21.6" | keep the hook at `FAILURE`/`REFUSED`; the method and the hook then disagree on `TIMEOUT` | FOSS-106 AC5 asks for one shared predicate. The hook's own comment says it exists to notice a child that did not do its work (`invoke.py:517-519`), and a timed-out child is that. |
| **D4** | Under capture, does the child's output still reach stdout? | **divert**: recorded, not written (B3) | **tee**: recorded *and* written | FOSS-107 AC1 requires exactly one document. MCH-179 criterion 4 defers to "the ticket". The shape page's *Boundaries* bullet reads *"the child's output still goes where the run's output goes"* and its Risk 2 says *"The default must leave output where it goes today"*. Divert keeps the **default** unchanged (B5) and suppresses only when asked. The suppression is stated in the docstring and the reference, so it is never silent. |
| **D5** | Name of the `write()` key | `writes` | `written` (FOSS-107 text) | The shape says "naming is chosen in the spec from existing vocabulary". `functualize.testing.FakeStdout` already records the same two channels as `emitted` and `writes` (`testing/stdout.py:39-42`). A test that swaps `FakeStdout` for real capture then reads the same names. |

## 5. Acceptance criteria

Each is a gate the execution phase runs. `tasks.md` names the test that holds
each one.

**Checked lane (FOSS-106)**

- **AC1** — The repro with `.raise_for_status()` added to `chain`: `func chain`
  exits **1**, and its stderr carries `JobFailedError`, `'boom'` and
  `RuntimeError: boom failed`. At `--log-level DEBUG` the traceback contains
  `demo.py", line …, in boom`. Both transcripts (before: exit 0; after: exit 1)
  are pasted in the PR.
- **AC2** — Without the call, `func chain` still exits **0**. A child refused
  by a failing `Precondition` **does** raise under `raise_for_status()`.
- **AC3** — A unit table over every `RunStatus` × {exception set, `None`}:
  `SUCCESS`, `SKIPPED` and `BLOCKED` return the same object (`is`). Every other
  status raises `JobFailedError` with `.result is result`, `.job_name`,
  `.status` and `.exception` equal to the result's, and `__cause__ is
  result.exception`.
- **AC4** — An invoke-path test in `tests/test_invoke_expanded.py`. It runs a
  failing child through `WiredInvoke`, calls `.raise_for_status()`, and asserts
  the raised error's identity. It also covers `TIMEOUT` reached through
  `inv(..., timeout=)`.
- **AC5** — One predicate. A test asserts, for every `RunStatus`, that
  `INVOKE_FAILURE` fires **iff** `raise_for_status()` raises **iff**
  `invoke.parallel` counts the child as failed. The two existing tests in A6
  are rewritten to the shared set.
- **AC6** — A nested parent (grandparent → `chain` → `boom`, both checked)
  leaves `chain` as `FAILURE` and the grandparent's run as `FAILURE`, exit 1. The
  `JobFailedError` chain reaches `boom`'s `RuntimeError` through `__cause__`.
- **AC7** — `JobResult`'s `dataclasses.fields()` names and flags are unchanged.
  Two equal results still compare equal and hash equal.
  `tests/test_public_api_surface.py` passes with `"JobFailedError"` added to the
  `"functualize.types"` set and nowhere else.

**Capture (FOSS-107)**

- **AC8** — The FOSS-8 repro with `capture=True`:
  `func --emit-format json parent` prints exactly **one** document, the
  parent's, and it contains the children's captured values.
- **AC9** — The same repro without `capture=True` is unchanged: one document
  per child followed by the parent's (three for FOSS-8's two-child original),
  exit 0, and no `emitted` or `writes` key on the returned metadata.
- **AC10** — A child that calls both `emit()` and `write()` under capture: each
  key holds that channel's payloads in order. A child that calls neither, or
  declares no `Stdout`, yields two empty tuples.
- **AC11** — A failing child under capture: `status=FAILURE`, and
  `metadata["emitted"]` holds what it emitted before raising. Then
  `raise_for_status()` raises with those values on `err.result.metadata`.
- **AC12** — `capture=True` with `--emit-format none` records the values, and
  nothing reaches stdout.
- **AC13** — A custom object emitted under `--emit-format json` with capture is
  returned as the same object (`is`), and no error is raised.
- **AC14** — Not transitive: an uncaptured grandchild's emission reaches
  stdout, and a captured grandchild's is recorded only in the child's result.
  The `nested_request` reset is asserted in
  `tests/engine/test_nested_delivery_inputs.py`.

**Both**

- **AC15** — Docs updated at C1–C4, and `examples/` carries a caller of
  `raise_for_status()`, `JobFailedError` and `capture=True`
  (`contributor/guides/adding-public-api.md` §8).
- **AC16** — `uv run ruff check`, `ruff format --check`, `mypy src/`,
  `lint-imports` (7 kept, 0 broken) and the step tier all pass.
