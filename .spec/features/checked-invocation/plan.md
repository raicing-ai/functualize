# checked-invocation — Plan

Drafted 2026-10-24 against `spec.md`; confirmed by the maintainer on
2026-10-26 in comment `01a177e2-43ac-7db8-83d1-21948b9b0a3e`.
Base `master` `b3e624bd`, branch `sdd/checked-invocation`.
Execute is authorised for the confirmed task graph.

## Alignment

**Shape intent:** *Shape Intent — Checked Invocation and Captured Child
Emissions (inv / JobResult)*, Confluence space `SD`, page `15138825`,
**version 4**: `Status | Approved`, `Authority | Approved`,
`Last reviewed | 2026-10-13`. Read live on 2026-10-24.

The page still carries two sentences written before the v4 field flip. The
preamble says *"The page is not approved: `Authority` stays `Proposed` until
the maintainer moves it."* The `Outcome` section says *"this page's shape is
**not yet approved** — `Authority` is `Proposed`"*. The page's own closing
section defines `Authority` as *"the approval field … Only the maintainer
moves it"*. That field reads `Approved`, so the field governs and the two
sentences are stale prose. Correcting them is the maintainer's edit, not this
branch's.

**Model chosen:** candidate model 1, in the page's words: *"A method on the
frozen result, plus a metadata key — `JobResult.raise_for_status()`,
exception drawn from existing vocabulary; `inv(capture=True)` returns the
child's emissions under a `metadata` key following `_awaits_input`. One result
type, one keyword added to a keyword-shaped signature, no unfreezing."*
Rejected, as the page rejects them: model 2 (*"A second result type per
lane"*), model 3 (*"An await/aggregate object"*), model 4 (*"Capture returns
the emissions directly"*), and model 5 (*"Do nothing"*).

**In scope, in the page's words** (*Boundaries and non-goals*):

- *"`JobResult` **stays frozen and gains no field**; its comparison and hash
  behaviour is unchanged. The checked lane is a *method*; captured emissions
  are *metadata*."* → `spec.md` A7, AC7; C1.
- *"**The unchecked lane is untouched.** `inv("child")` behaves byte-for-byte
  as today"* → A7, B5, AC2, AC9.
- *"**No second guide.** Composition is documented by linking the existing
  `invoke` reference"* → §C, C4.
- *"**No new channel for child output.** Capture rides on `metadata`"* → B2.
  The page's continuation, *"the child's output still goes where the run's
  output goes"*, is the one clause this plan does not follow literally. It is
  **decision D4**, and it is put to the maintainer rather than resolved here:
  FOSS-107 AC1 requires the opposite under `capture=True`, and the page's
  Risk 2 binds the **default**, which stays unchanged.
- *"**Naming is chosen in the spec from existing vocabulary** … whatever new
  public name appears … is added to the pinned surface in
  `tests/test_public_api_surface.py` in the same change"* → D2, D5, C4.

**Out of scope, in the page's words:** *"**Not this shape:** MCH-175
(FOSS-93, `effecting=True` exactly-once semantics)"*. From the carrying issues:
retry, timeouts, and any change to `invoke.parallel`'s result semantics
(FOSS-57). Nothing here changes `parallel`.

**Risks the page names, and where each is answered:** Risk 1 (memory) → B9 and
C1 docs. Risk 2 (silent suppression) → B3, B5 and D4. Risk 3 (public
vocabulary) → C4. Risk 4 (nesting) → A5, B7, AC6 and AC14. Hypotheses H1 and H2
are falsified by AC7 and by AC9 + AC10 respectively.

## 1. Skills consulted

- `python-design-patterns` (in-repo, `.agents/skills/python-design-patterns`):
  KISS and single responsibility. These shaped the choice of one method plus one
  keyword over a new type (models 2 and 3).
- `design-patterns-refactoring` (user-level, Refactoring.Guru catalogue): the
  smell names below come from it — ch32 *Primitive Obsession*, ch35 *Duplicate
  Code* / *Speculative Generality* / *Lazy Class*, ch36 *Middle Man*. So does
  the look at `ShellError` as the Parameter-Object-shaped precedent for C2.

## 2. Architecture pass — today (`b3e624bd`)

Retrieval run: `zg` index built for this worktree (915 files, 14 482 entities,
1 m 31 s). The prose queries hit `CHANGELOG.md:299-313`, ADR-032 §3 and
*Neutral*, `docs/api/context.md:131-163` and `docs/guides/hooks.md:293-307`.
serena `find_referencing_symbols(nested_request)` returned 4 production call
sites: `dependency_runner.py:149`, `workflow_orchestrator.py:94`, and
`invoke.py:472` and `:874`. graphify `get_neighbors(WiredStdout)` returned one
constructor (`_make_stdout`) and one `isinstance` reader
(`executor.py:1997-2003`). `graphify-out` was built at `2269b8d3`; it is used
for direction only, never for lines.

```
BEFORE                                                  layer
─────────────────────────────────────────────────────────────────────────
 job body ── inv("child") ──▶ WiredInvoke.__call__          _engine (peer)
                               │  invoke.py:352-545
                               │  builds nested_request(...) ─────────▶ _types/run_request.py
                               │  engine.run(request) ──▶ JobExecutionEngine
                               │                            │ DI: _make_stdout(ctx)
                               │                            │   reads ctx.context.request
                               │                            ▼    .output_format
                               │                         WiredStdout ──▶ sys.stdout   (always)
                               │                            stdout.py:31-134
                               │  ◀── JobResult ───────── (_types/descriptors.py:476-493)
                               │  awaits_input? rebuild JobResult with _awaits_input keys
                               │  status in (FAILURE, REFUSED)? fire INVOKE_FAILURE  ← predicate #1
                               ▼
                             returns JobResult (unchecked)

 WiredInvoke.parallel ── is_failure(status, Family.TOOL) → RuntimeError … from cause ← predicate #2
                          invoke.py:583-600              (_types/outcome.py:78-89)

 Invoke.__call__ (stub, invoke.py:100-162) ── same signature, raises NotImplementedError
 InvokeResult (invoke.py:71-83) ── no constructor in src/plugins/examples (rg: 0)
 functualize.types ── exports JobResult, is_failure, Family, MissingValueError
 functualize.job   ── exports Invoke, ShellError; job.capabilities re-exports InvokeResult
```

Boundary crossings: public `types/`, `job/` → `_types`, `_engine` (allowed,
public → internal). `_engine` → `_types` (allowed). Nothing crosses a
peer-layer line.

**Smells the BEFORE already carries:**

- **Duplicate Code — two failure predicates in one module.** `invoke.py:520`
  (`in (FAILURE, REFUSED)`) and `invoke.py:587` (`is_failure(..., TOOL)`) answer
  "did this child fail?" differently for `TIMEOUT`, `CANCELLED` and `UNKNOWN`.
  This is the same divergence `_types/outcome.py:1-28` was written to end
  (*"Two of them disagreed"*).
- **Speculative Generality / Lazy Class — `InvokeResult`.** Its docstring says
  it is *"used as the return type when the full JobResult … is not
  available"* and that *"The actual Invoke implementation returns
  functualize._engine.result.JobResult"*. Measured: `rg -n "InvokeResult\("
  src plugins examples` → **0** constructors. `_engine/result.py` is a re-export
  of `_types.descriptors.JobResult` (`result.py:9`). Every `inv()` child, on the
  wired path and on every error path in `WiredInvoke`/`_ParallelBatch`, arrives
  as `_types.descriptors.JobResult` (`invoke.py:373` imports it as
  `_JobResult`; `executor.py:763` `run() -> JobResult`). The only references are
  its re-exports and `tests/test_invoke_stub_expanded.py:159-186`. **This is
  why the checked lane does not add a third type** (dispatch question):
  `InvokeResult` is not on any path an `inv()` result travels, so a method
  there would never run, and a new type would be the page's rejected model 2.
- **Duplicate Code (latent) — JobResult rebuild.** `invoke.py:499-515` rebuilds a
  `JobResult` field by field to add metadata. Capture needs the same thing, and a
  second copy would be the second instance.

## 3. Candidate AFTERs

**AFTER-1 (rejected): capture by redirecting the stream.** `WiredInvoke` hands
the child a `StringIO` `stream=` (`stdout.py:45-55`) and parses the text back.
It **introduces** a parse contract per `--emit-format`, and it loses objects
under `json` (fails B4 and AC13). It cannot record under `none`, which
suppresses before the stream (`stdout.py:90`). It would be a
serialize/deserialize round trip, which FOSS-107 names as the thing to avoid.

**AFTER-2 (rejected): the child's `Stdout` writes the capture into its own
result metadata** (via `ctx.context.metadata`, which `executor.py` merges into
`result_metadata`). There is no request field. But it **introduces** a change to
the child's own recorded result, which MCH-179 rules out (*"any capture that
changes the child's own recording"*). It also makes `capture` transitive by
accident, because the grandchild merges into the same mapping.

**AFTER-3 (chosen): a recorder carried on the request, merged by the caller.**

```
AFTER                                                   layer
─────────────────────────────────────────────────────────────────────────
 job body ── inv("child", capture=True).raise_for_status()
                │
                ▼
 WiredInvoke.__call__                                      _engine (peer)
   record = EmissionRecord() if capture else None ──────▶ _types/stdout.py  (NEW, dataclass)
   nested_request(..., capture=record) ─────────────────▶ _types/run_request.py
   engine.run(request)                                        (field `capture`; reset in
        │ DI: _make_stdout(ctx)                                nested_request ⇒ not transitive)
        │   reads request.output_format, request.capture
        ▼
     WiredStdout(record=…)  ── record is None ──▶ sys.stdout          (unchanged path)
                            └─ record set   ──▶ record.emitted / .writes  (no write)
   ◀── JobResult
   result = _with_metadata(result, {...})   ◀── ONE rebuild helper, used by
            awaits_input keys  +  "emitted"/"writes" tuples        awaits_input AND capture
   if _child_failed(result.status): fire INVOKE_FAILURE      ─┐
 WiredInvoke.parallel: _child_failed(...) → RuntimeError       ├─ one predicate:
 JobResult.raise_for_status(): is_failure(…, TOOL)             ─┘  is_failure(status, Family.TOOL)
        │                                                          (_types/outcome.py)
        └─ raise JobFailedError(self) from self.exception ───▶ _types/errors.py  (NEW class)

 functualize.types ── + JobFailedError                         public
```

`_child_failed` is a one-line module function in `invoke.py`
(`return is_failure(status, family=Family.TOOL)`). It names the question once
for the two engine sites, and `raise_for_status()` calls `is_failure` with the
same family directly, because `_types` cannot import `_engine`. AC5 is the
executable proof that the three agree.

**Smells AFTER-3 introduces, checked:** a live object on a frozen value object
(see `## Surviving smells` S1); *Primitive Obsession* on the two metadata key
strings (S2). AFTER-3 **removes** the duplicate predicate (one definition
behind three sites) and the latent duplicate rebuild (`_with_metadata`). It
adds no peer-layer import, no module-level state (the recorder is per call),
no ABC, and no god-object growth: `invoke.py` is a module of three classes plus
functions, and `WiredInvoke.__call__` grows by about 10 lines. Nothing on
*Forbidden Patterns* survives.

`lint-imports` legality: `_types/descriptors.py` → `_types/outcome.py`,
`_types/errors.py` (intra-`_types`). `_types/errors.py` imports `JobResult`
under `TYPE_CHECKING` only, so there is no runtime cycle:
`grep '^from functualize' _types/errors.py` → none at module level today.
`_engine` → `_types`; `types/` → `_types`. Baseline `uv run lint-imports` →
7 kept, 0 broken (2026-10-24).

`descriptors.py:1-6` says *"Zero imports from any _-prefixed internal package.
Only stdlib imports."* That is already false: the file imports
`_types.enums` and `_types.naming` (`:17-18`). The method adds a third
intra-`_types` import. Task 1.1 updates the docstring to say *intra-`_types`
only* rather than leave a third contradiction.

## 4. Technical approach

**Checked lane.** `JobFailedError` goes in `_types/errors.py`, following that
file's conventions (attributes set in `__init__`, message built there, an
`Attributes:` docstring). `JobResult.raise_for_status()` goes in
`_types/descriptors.py`, importing `is_failure`/`Family` at module level and
`JobFailedError` from the sibling module. `invoke.py` gains `_child_failed`,
which both the hook (`:520`) and `parallel` (`:587`) use. The stub
`Invoke.__call__` and `parallel` docstrings name the method. Export through
`types/__init__.py`.

**Capture.** `EmissionRecord` goes in `_types/stdout.py`. `RunRequest.capture`
goes in `_types/run_request.py`: `compare=False`, left out of the hand-written
`__hash__`, and reset to `None` in `nested_request`'s field dict beside
`parent_run_id` (`:373`). `WiredStdout.__init__(…, record=None)`: when set,
`emit` appends `value` and returns, and `write` appends `data` and returns.
Both check the record **before** the `"none"`/`None` early returns
(`stdout.py:90`, `:113`), so B4 holds. `_make_stdout` passes
`request.capture`. `Invoke.__call__` (stub and wired) gains `capture: bool =
False`. `WiredInvoke` builds the record, passes it, and merges the tuples
through `_with_metadata`. The `awaits_input` block (`:499-515`) moves onto the
same helper.

**Docs, example, ADR.** As `spec.md` §C. The quickstart
`examples/quickstart/step3_invoke/weather.py` gains the checked call and one
captured child, with its test (`adding-public-api.md` §8). AGENTS.md makes an
ADR mandatory for a new public API surface: `contributor/adr/036-…` records
D1–D5. It is also the durable half the `.spec/features/` clearing migrates to,
along with a `.spec/STATUS.md` line.

## 5. Blast radius and sequencing

Files, from the retrieval hit sets (`rg` and serena, 2026-10-24):

| File | Why (hit) |
|---|---|
| `src/functualize/_types/errors.py` | new `JobFailedError` |
| `src/functualize/_types/descriptors.py` | `JobResult` `:476-493` |
| `src/functualize/types/__init__.py` | export, `:16-23`, `__all__` `:58-95` |
| `src/functualize/_types/stdout.py` | new `EmissionRecord` |
| `src/functualize/_types/run_request.py` | field `:191-221`, `__hash__` `:232-257`, reset `:364-374` |
| `src/functualize/_engine/capabilities/stdout.py` | `WiredStdout` `:31-134`, `_make_stdout` `:145-170` |
| `src/functualize/_engine/capabilities/invoke.py` | stub `:100-162`; wired `:352-545`; hook `:520`; parallel `:587` |
| `tests/test_public_api_surface.py` | `:243-289` (C4) |
| `tests/context/test_invoke_failure_hook.py` | `:108` flips (D3) |
| `tests/hooks/test_invoke_failure_properties.py` | `:7`, `:114`, `:146-175` partition (D3) |
| `tests/engine/test_nested_delivery_inputs.py` | reset assertion (serena hit) |
| `tests/test_invoke_expanded.py` | invoke-path test (FOSS-106 AC4 names it); `:483` class |
| new tests | `tests/types/test_job_result_raise_for_status.py`, `tests/engine/test_invoke_capture.py`, `tests/integration/test_checked_invocation_cli.py` (CliRunner over `app.cli_command`, the `tests/context/test_invoke_failure_hook.py` pattern) |
| docs | `docs/api/context.md:101-110,158-160`; `docs/guides/composition.md:8,72,316-318`; `docs/api/types.md:179`; `docs/guides/run-context.md:439-457` |
| example | `examples/quickstart/step3_invoke/weather.py`, `test_step3.py` |
| record | `CHANGELOG.md` `[Unreleased]` `:8`; `contributor/adr/036-checked-invocation-and-capture.md`; `.spec/STATUS.md` |

Not touched, though they reference the same symbols:
`_engine/dependency_runner.py:149` and `_engine/workflow_orchestrator.py:94`
call `nested_request`. The reset keeps them uncaptured with no edit, and AC14
asserts it. `executor.py:1997-2003` (`_arm_output_redaction`) reads
`WiredStdout` by `isinstance` and is unaffected. `testing/doubles.py`
(`MockInvoke`) already absorbs keywords (B10).

Baseline at `b3e624bd`, measured 2026-10-24:
`uv run pytest -n auto -q tests/test_public_api_surface.py tests/test_invoke_expanded.py tests/test_invoke_stub_expanded.py tests/context/test_invoke_failure_hook.py tests/hooks/test_invoke_failure_properties.py tests/engine/test_nested_delivery_inputs.py`
→ **105 passed, 5 skipped** (9.5 s).

## 6. Decisions

D1–D5 were confirmed on 2026-10-26: D1 raises one `JobFailedError(result)`
chained from `result.exception`; D2 places the error in `_types/errors.py` and
exports it from `functualize.types` only; D3 widens `INVOKE_FAILURE` to the
shared failure predicate; D4 diverts captured output into the record; D5 names
the metadata key `writes`. These are the options recorded in `spec.md` §4.

## Surviving smells

- **S1 — a live mutable collaborator on a frozen value object**
  (`RunRequest.capture`, `_types/run_request.py`). The catalogue has no exact
  name for it. The nearest is a coupling smell: the request starts to carry an
  output sink, not only inputs. *Accepted because* the request is the only
  per-run input that reaches the child's `Stdout` factory
  (`_make_stdout` reads `ctx.context.request`, `stdout.py:162-163`). It has a
  precedent: `parent_scope: Any | None` is already a live object on the request
  (`:202`). And `nested_request`'s reset gives non-transitivity for free (B7),
  where AFTER-2 got it wrong. It is kept out of equality and the hash, and no
  door can set it from an envelope. **Accepted by the maintainer 2026-10-26:**
  “S1 accept”; `RunRequest.capture` stays outside equality and the hash, and
  nested-request reset makes capture non-transitive.
  `RunRequest` is public (`functualize.types`), so this is a field on a public
  type, even though only `WiredInvoke` sets it.
- **S2 — Primitive Obsession: two string metadata keys** (`"emitted"`,
  `"writes"`). *Accepted because* the shape fixes the carrier as metadata (H2,
  the `_awaits_input` precedent). ADR-032 §2 accepted the same smell for
  `raised_by_job` by keeping one definition. The two literals are written once,
  in `invoke.py`, and the behaviour test pins them. **Needs maintainer review:
  no.** It is the approved shape's own choice.
- **S3 — `Family.TOOL` borrowed for the invoke boundary.** `outcome.py:55-56`
  describes TOOL as *"A status string in a tool response"*. An `inv()` child is
  not a tool response. *Accepted because* `Invoke.parallel` already decides
  with TOOL (`invoke.py:587`) and the documented set matches
  (`docs/api/context.md:149-151`). A fifth family member would be a new public
  enum value for an identical set (*Speculative Generality*). **Needs
  maintainer review: no.**
- **S4 — `InvokeResult` stays for this feature** (*Speculative Generality / Lazy Class*,
  `invoke.py:71-83`, re-exported from `functualize.job.capabilities`). Nothing
  constructs it. Deleting it is a public-surface removal that neither ticket
  asked for, and doing it here would be the silent scope growth the dispatch
  forbids. The maintainer confirmed deletion if dead; a production constructor
  scan found none. Removal is routed to a separate follow-up after this feature
  merges, because it changes a public export and deserves its own reviewable diff.

## 7. Risks

- **R1 — hook consumers see more events** (D3). An `INVOKE_FAILURE` subscriber
  now receives `TIMEOUT`, `CANCELLED` and `UNKNOWN` children. In-repo
  subscribers: `rg -n "INVOKE_FAILURE" src` → `_events/hooks.py`,
  `_app/hooks_facade.py`, `_app/impl.py` and `invoke.py` (registration plumbing
  only, no consumer logic). Out-of-repo plugins could notice. Pre-release
  stance applies, and the CHANGELOG states it.
- **R2 — a job parameter named `capture`** becomes unreachable through `inv()`
  keywords. Measured: `rg -n 'invoke\([^)]*capture=|inv\([^)]*capture='`
  over `src tests examples plugins docs` → **0**. Stated in the docstring.
- **R3 — timeout under capture** discards post-timeout emissions (B8).
  Documented. It is not silent from the caller's view, because the status is
  `TIMEOUT`.
- **R4 — secrets.** Captured values are the unredacted objects, as the job
  passed them. They stay in-process, like `return_value`, and are redacted only
  if the parent emits them again (its own `WiredStdout` masks its own job's
  secrets, not the child's). The reference documentation says so. If the
  maintainer wants child secrets masked on capture, that is a change to B2.
- **R5 — the dead-code delta** will report `EmissionRecord`, `_with_metadata`
  and `_child_failed` as reachable. It must not report `JobFailedError` as
  TESTS_ONLY: the example (task 4.2) is its non-test caller.
