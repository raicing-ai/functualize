# checked-invocation — Tasks

Original planning base `master` `b3e624bd`; execution base `11ed0e82`, branch
`sdd/checked-invocation`. Spec AC1–AC16,
contracts C1–C5, plan §2–§7.

> **Executable.** The maintainer confirmed D1–D5 and accepted S1 in comment
> `01a177e2-43ac-7db8-83d1-21948b9b0a3e` at 2026-10-26T11:04:39Z.
> S4's deletion is routed to a separate follow-up. This parseable task graph
> satisfies the `src/functualize/**` write gate; Execute follows its wave order.
>
> **Amended 2026-10-26** — task 1.2's `[F]` set drops `_types/stdout.py`:
> `EmissionRecord` lives in `_types/run_request.py`. The record is in `spec.md`
> → `## Authority and status`.

Authoring-time measurements (2026-10-24, `b3e624bd`):

- `uv run lint-imports` → 7 kept, 0 broken.
- Baseline over the six touched test files (plan §5) → 105 passed, 5 skipped.
- `rg -n "InvokeResult\(" src plugins examples` → 0.
- `rg -n 'invoke\([^)]*capture=|inv\([^)]*capture=' src tests examples plugins docs` → 0.
- `rg -n "INVOKE_FAILURE" src -l` → 4 files (registration only, plus `invoke.py`).
- serena `find_referencing_symbols(nested_request)` → 4 production sites.

If `master` has moved when wave 0 starts, rebase first and re-run these.

Execution remeasurement (2026-10-26, rebased on `11ed0e82`): the two
constructor/capture queries still have zero hits; `INVOKE_FAILURE` still occurs
in four production files; serena finds four production `nested_request` sites;
the six-file baseline is 105 passed, 5 skipped; `lint-imports` is 7 kept,
0 broken. The `functualize.types` surface set moved to
`tests/test_public_api_surface.py:253-299`; the cited engine anchors did not move.

**Every task's gate also includes:** `uv run ruff check` and `ruff format --check`
on the touched files; `uv run mypy src/`; `uv run lint-imports` (7 kept);
the step tier
(`uv run pytest -n auto -q --no-header $(.agents/skills/test-tiers/scripts/tests-for-diff)`,
mapper exit 0). And, for every new production path, **reachability by
sabotage**: commit first, break the named call, watch the named test fail,
`git checkout --`, amend nothing.

## Wave 0 — pin today

- [x] **0.1 Pin the unchanged surfaces** (AC7 shape half, AC9 default half) —
  **[F]** `tests/types/test_job_result_raise_for_status.py` (new),
  `tests/engine/test_invoke_capture.py` (new)
  - `TestFrozenShape`: `dataclasses.fields(JobResult)` names, order and
    `compare`/`hash` flags equal the literal at `11ed0e82`. Two equal results
    compare equal and hash equal. `exception` is excluded from both.
  - `TestDefaultPathUnchanged`: through a real app, a parent invokes a child
    that emits `{"step": "a"}`, then emits its own document. Stdout is exactly
    `{"step":"a"}\n{"step":"parent"}\n` under `--emit-format json`, and the
    child's returned metadata has neither `"emitted"` nor `"writes"`.
  - Gate: both classes are **green at `11ed0e82`** before any `src/` change.
    This is a pin, not a red test.

## Wave 1 — vocabulary (`_types`)

- [x] **1.1 `JobFailedError` + `JobResult.raise_for_status()`** (C1, C2; A1–A3,
  AC3) — **[F]** `src/functualize/_types/errors.py`,
  `src/functualize/_types/descriptors.py`,
  `tests/types/test_job_result_raise_for_status.py`
  - Error per C2: attributes, message, `TYPE_CHECKING`-only import of
    `JobResult`. Method per C1: returns `self`; otherwise
    `raise JobFailedError(self) from self.exception`.
  - Fix the `descriptors.py:1-6` docstring to read *intra-`_types` imports
    only* (plan §3).
  - Gate: `TestStatusTable` is parametrised over **every** `RunStatus` × {an
    exception, `None`}. The 3 non-failures return `self` (`is`). The other 6
    raise, with `.result is r`, `.job_name`, `.status` and `.exception` equal,
    `__cause__ is r.exception`, and `str(err)` containing the job name, the
    status value and, when present, `ExcClass: message`. `TestFrozenShape`
    (0.1) still green.

- [x] **1.2 `EmissionRecord` + `RunRequest.capture` + reset** (C5; B7) —
  **[F]** `src/functualize/_types/run_request.py`,
  `tests/engine/test_nested_delivery_inputs.py`
  - `EmissionRecord`: a `@dataclass` with `emitted: list[Any]` and
    `writes: list[str | bytes]`, both `field(default_factory=list)`. Not in any
    public `__all__`.
  - `RunRequest.capture: EmissionRecord | None = field(default=None, compare=False)`.
    Not added to `__hash__`. `nested_request` resets it to `None` beside
    `parent_run_id`.
  - Gate: `TestEverythingElseResets` gains
    `test_capture_resets` (a parent request carrying a record → the child's
    `capture is None`) and `test_a_site_that_states_capture_keeps_it`. Two
    requests differing only in `capture` compare equal and hash equal.

## Wave 2 — public export; the recording `Stdout`

- [x] **2.1 Export and pin** (C4; AC7) — **[F]**
  `src/functualize/types/__init__.py`, `tests/test_public_api_surface.py`
  - Gate: the C4 diff exactly. `uv run pytest tests/test_public_api_surface.py`
    green. `git diff --stat` on the test file → 1 file, +3 lines. No other
    `EXPECTED_EXPORTS` set changes.

- [x] **2.2 `WiredStdout` records when given a record** (B2–B4; AC12, AC13 at
  unit level) — **[F]** `src/functualize/_engine/capabilities/stdout.py`,
  `tests/engine/test_stdout_record.py` (new)
  - `WiredStdout(..., record=None)`. `emit`/`write` append and return
    **before** the `"none"`/`None` early returns. `_make_stdout` passes
    `request.capture` (`None` without a request).
  - Gate: with a record and a `StringIO` stream, under `json`, `none`, `raw`
    and `auto`: nothing reaches the stream, and the record holds the values
    `is`-identical, `None` included. A non-JSON object under `json` raises
    nothing. Without a record, output is byte-identical to the same call at
    base. Sabotage: drop `record=` in `_make_stdout` → task 4.1's
    `TestCapture` fails (run in 4.1).

## Wave 3 — one predicate (`invoke.py`, part 1)

- [x] **3.1 `_child_failed` behind the hook and `parallel`** (A6, D3; AC4, AC5)
  — **[F]** `src/functualize/_engine/capabilities/invoke.py`,
  `tests/context/test_invoke_failure_hook.py`,
  `tests/hooks/test_invoke_failure_properties.py`,
  `tests/test_invoke_expanded.py`
  - `_child_failed(status) -> bool` returns
    `is_failure(status, family=Family.TOOL)`. It is used at the hook (`:520`)
    and in `parallel` (`:587`). The stub and wired docstrings name
    `raise_for_status()` (`:126-140`, `:574-581`).
  - Tests: `test_invoke_failure_not_fired_on_timeout` →
    `test_invoke_failure_fired_on_timeout`. The property file's
    failure/non-failure partition becomes the shared set, and its module
    docstring loses "Req 21.6". In `test_invoke_expanded.py`, a new
    `TestCheckedLane` runs a failing child and a `timeout=` child through
    `WiredInvoke`, then calls `.raise_for_status()` and asserts the error's
    identity (AC4). It also gets `test_one_predicate` (AC5): for every
    `RunStatus`, hook fired ⇔ `raise_for_status()` raises ⇔ `parallel` counts
    it as failed.
  - Gate: those four files green. Sabotage: restore the literal
    `in (FAILURE, REFUSED)` at the hook → `test_one_predicate` and the timeout
    test fail.

## Wave 4 — capture (`invoke.py`, part 2)

- [x] **4.1 `capture=` keyword and the one rebuild helper** (C3; B1–B10;
  AC8–AC14 at engine level) — **[F]**
  `src/functualize/_engine/capabilities/invoke.py`,
  `tests/engine/test_invoke_capture.py`
  - Stub and `WiredInvoke.__call__` gain `capture: bool = False`, with a
    docstring per C3 (divert, any format, not transitive, timeout, memory,
    unredacted). The wired path builds an `EmissionRecord` and passes
    `nested_request(..., capture=record)`. `_with_metadata(result, extra)`
    replaces the field-by-field rebuild at `:499-515` and adds
    `{"emitted": tuple(record.emitted), "writes": tuple(record.writes)}`.
  - `TestCapture` covers: emit + write order (AC10); neither, and no `Stdout`
    → two empty tuples; a failing child keeps what it emitted before raising,
    then `raise_for_status()` carries it (AC11); `--emit-format none` (AC12); a
    custom object `is` returned (AC13); an uncaptured grandchild reaches stdout,
    and a captured grandchild is in the child's result only (AC14);
    `awaits_input=` + `capture=True` → both key sets present; a `timeout=`
    child under capture → `TIMEOUT` and a tuple.
  - Gate: `TestDefaultPathUnchanged` (0.1) **still green unmodified**, and
    `TestCapture` green. Sabotage: (a) skip the merge → `TestCapture` fails;
    (b) remove the `nested_request` reset → the AC14 grandchild test fails;
    (c) drop `capture=record` from the request → `TestCapture` fails.

## Wave 5 — through the user's door

- [ ] **5.1 CLI integration** (AC1, AC2, AC6, AC8, AC9) — **[F]**
  `tests/integration/test_checked_invocation_cli.py` (new)
  - CliRunner over `app.cli_command` (the
    `tests/context/test_invoke_failure_hook.py` pattern). An isolated `HOME`
    and `XDG_*` if any subprocess is spawned (AGENTS.md *Writing tests*).
    Cases: `chain` unchecked → exit 0; checked → exit 1 and stderr has
    `JobFailedError`, `'boom'`, `RuntimeError: boom failed`; `DEBUG` traceback
    has `in boom`; a refused child raises; grandparent → `chain` → `boom` gives
    exit 1 with both runs `FAILURE`; the FOSS-8 parent with `capture=True` →
    one stdout document holding the children's values, and without it → one
    per child plus the parent's.
  - Gate: green. The PR body carries the before/after transcripts of AC1 and
    AC8, produced by `func` on the branch (`spec.md` §1 commands).

- [ ] **5.2 Docs** (§C; AC15 docs half) — **[F]** `docs/api/context.md`,
  `docs/guides/composition.md`, `docs/api/types.md`,
  `docs/guides/run-context.md`
  - At the anchors in plan §5, with no second guide.
  - Gate: `uv run pytest tests/test_contributor_docs.py -q` green (it is the
    docs-link suite). `rg -n "raise_for_status|capture=True" docs` hits all 4
    files, and `rg -n "raise_for_status" docs/api/context.md` → ≥2 (the
    `rc.invoke` reference and the `invoke.parallel` pointer at `:158-160`).

- [ ] **5.3 Example caller** (AC15 example half; `adding-public-api.md` §8) —
  **[F]** `examples/quickstart/step3_invoke/weather.py`,
  `examples/quickstart/step3_invoke/test_step3.py`
  - `morning_report` checks `forecast` with `.raise_for_status()`, takes one
    captured child, and catches `JobFailedError` in one illustrated branch.
    The test runs it through the engine.
  - Gate: `uv run pytest examples/quickstart/step3_invoke -q` green.
    `rg -n "JobFailedError|raise_for_status|capture=True" examples` → ≥3 hits.

## Wave 6 — the record

- [ ] **6.1 ADR, changelog, status** — **[F]**
  `contributor/adr/036-checked-invocation-and-capture.md` (new),
  `CHANGELOG.md`, `.spec/STATUS.md`
  - The ADR records D1–D5 as answered, S1 and S4, and the retirement of
    "Req 21.6". `[Unreleased]` gets *Added* (the method, the error, `capture=`)
    and *Changed* (`INVOKE_FAILURE` now fires on `TIMEOUT`/`CANCELLED`/`UNKNOWN`).
    `STATUS.md` gets one line pointing at the ADR: this is the durable half the
    `.spec/features/` clearing migrates.
  - Gate: `uv run pytest tests/test_contributor_docs.py -q` green. The commit
    messages and the ADR carry no tracker key, tracker URL or internal id
    (`message-hygiene`).

## Wave 7 — checkpoint

- [ ] **7.1 Verify the whole change** — **[F]** none (read-only)
  - All five checks. Wave tier:
    `timeout 570 uv run pytest -n auto -q tests/types tests/engine tests/context tests/hooks tests/integration tests/test_invoke_expanded.py tests/test_public_api_surface.py`.
    `uv run python .github/scripts/dead_code_delta.py origin/master HEAD`,
    with every finding classified KNOWN or UNMARKED (expect 0 TESTS_ONLY for
    `JobFailedError`: its caller is 5.3). Re-run every sabotage named in 2.2,
    3.1 and 4.1 once more on the final head. Dispatch the tip tier on CI;
    never wait on it.
  - Then the two-push sequence (`.claude/rules/spec-workflow.md`
    *Version control lifecycle*): open the PR, wait for validation, and only
    then make the deletion-only `git rm -r .spec/features/checked-invocation`
    commit last.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["0.1"] },
    { "id": 1, "tasks": ["1.1", "1.2"] },
    { "id": 2, "tasks": ["2.1", "2.2"] },
    { "id": 3, "tasks": ["3.1"] },
    { "id": 4, "tasks": ["4.1"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1"] }
  ]
}
```
