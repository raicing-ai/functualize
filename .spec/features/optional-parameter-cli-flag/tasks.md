# Tasks: optional job parameters on the CLI

The confirmed `spec.md` and `contracts.md` are immutable in this wave. `[F]`
is the allowed edit scope for each task; other paths named below are read-only
checks. Each task requires a commit or reviewable diff and the named evidence.

## Wave 0: shared optional classification

### [x] 1.1 Re-export the existing optional helper

- **Input:** `plan.md` AFTER diagram; `_config/job_config.py::_unwrap_optional`.
- **[F]:** `src/functualize/app/utils.py`.
- **Work:** expose the renderer's existing optional unwrapping rule to `_cli`
  through this public bridge. Do not copy the rule or change `_config` behavior.
- **Invariant:** `_cli` imports no internal package; no Click dependency enters
  the public import path. Existing config coercion and validation still call
  the same helper.
- **Gate/evidence:** `uv run lint-imports` (7 contracts, 0 broken baseline),
  `uv run python -c 'from functualize.app.utils import unwrap_optional_type;
  from typing import Optional; assert unwrap_optional_type(Optional[str]) ==
  (str, True)'` adapted to the chosen public name; a direct import smoke test.
- **Depends on:** none.

## Wave 1: eligibility and safety

### [x] 2.1 Classify optional annotations without changing base_type

- **Input:** task 1.1's public bridge; `parse_annotation` references in the
  builder and CLI unit tests.
- **[F]:** `src/functualize/_cli/annotation_utils.py`,
  `tests/cli/test_cli_compatible_type.py`,
  `tests/cli/test_annotation_utils_properties.py`.
- **Work:** ask the shared helper for the inner type before implicit DI/config/
  CLI checks. Keep the original `AnnotationInfo.base_type` and preserve
  explicit Provide/Option precedence. Add cases for both optional spellings,
  supported standard-library values/enums, unsupported unmarked lists and
  general unions, and optional injected capabilities.
- **Invariant:** only `X` already CLI-eligible gains implicit eligibility;
  `RunContext | None` and `TTY | None` remain non-CLI; `is_di_param` and
  `is_cli_compatible` never both become true.
- **Gate/evidence:** `uv run pytest tests/cli/test_cli_compatible_type.py
  tests/cli/test_annotation_utils_properties.py`; record classification table
  for `str | None`, `Optional[str]`, `bool | None`, `RunContext | None`,
  `TTY | None`, and `list[str] | None`.
- **Depends on:** 1.1.

## Wave 2: Click rendering

### [x] 3.1 Render optional boolean tri-state and collision

- **Input:** task 2.1; existing `negative_flag_for` rule at
  `_types/flag_grammar.py:195`.
- **[F]:** `src/functualize/app/adapters/click_params.py`,
  `tests/adapters/test_boolean_negation.py`.
- **Work:** in the plain signature bool branch, explicitly mark an eligible
  optional boolean as a Click flag, retaining the declared `None` default.
  Reuse `negative_flag_for`; when `no_loud` owns the negative spelling, keep
  `--loud` a bare positive flag with absent `None`.
- **Invariant:** existing non-optional bool and marked Option spellings do not
  move. No duplicate `--no-loud` registration; the sibling receives it.
- **Gate/evidence:** `uv run pytest tests/adapters/test_boolean_negation.py
  tests/types/test_flag_grammar_roundtrip.py`; capture option `opts`,
  `secondary_opts`, `is_flag`, default, and Click values for both normal and
  collision forms. The direct baseline probe showed a lone `--loud` with
  `default=None` needs `is_flag=True` to accept no value.
- **Depends on:** 2.1.

## Wave 3: public behavior

### [x] 3.2 Prove the public command contract

- **Input:** tasks 2.1 and 3.1; `spec.md` E1-E7 and `contracts.md` command
  table.
- **[F]:** `tests/cli/test_optional_parameter_cli.py` (new).
- **Work:** exercise the public `func` command for `greet` and both optional
  spellings, then absent/positive/negative optional bool values. Test a
  `no_loud` sibling and the existing Annotated Option spelling. Check
  documented optional `RunContext` / `TTY` examples do not gain flags.
- **Invariant:** signature parameters remain invocation inputs; config and
  environment sources do not appear. Existing flag values remain unchanged.
- **Gate/evidence:** E1 `--help` lists the three options; E2
  `func greet --greeting hi ada` prints `GREET hi ada`, exit 0; E3/E7 record
  delivered values; E4 run `rg -n 'RunContext \| None|TTY \| None|Optional\[RunContext\]|Optional\[TTY\]' README.md docs`
  (baseline 2 hits, `README.md:57` and
  `docs/guides/interactivity.md:133`) and check every matching example; E6
  demonstrate the new regression fails on `e00d870` and passes on this branch.
- **Depends on:** 2.1, 3.1.

## Wave 4: validation and release record

### [x] 4.1 Run complete verification and record the fix

- **Input:** tasks 3.1 and 3.2; `CHANGELOG.md` Unreleased → Fixed.
- **[F]:** `CHANGELOG.md`, `tests/adapters/test_click_params_parity.py`
  (maintainer-approved scope correction, 2026-11-12: only to add the new
  optional `path` option to `job_plain`'s snapshot, with a stable rendering
  for click's address-bearing `FuncParamType` repr).
- **Work:** add a concise user-visible changelog entry, then run focused and
  full quality gates. Check E5 against existing parity/flag snapshots. After
  committing the implementation, temporarily remove its production call path
  to prove the new end-to-end test fails, restore it, and report the result.
- **Invariant:** no spec or contract edit; no config source change; no release
  tag. Recheck the 0.5.0 tag has not been cut before merge preparation.
- **Gate/evidence:** `uv run ruff check src/ tests/`,
  `uv run ruff format --check src/ tests/`, `uv run mypy src/`,
  `uv run lint-imports`, `uv run pytest`, plus
  `uv run pytest tests/adapters/test_click_params_parity.py
  tests/cli/test_arg_marker_unit.py
  tests/types/test_flag_grammar_roundtrip.py`. Record all exits and the E1-E7
  matrix; no broad test repair outside `[F]` without revisiting this plan.
- **Depends on:** 3.1, 3.2.

## Wave 5: implementation review handoff

### [x] 5.1 Present implementation evidence for review

- **Input:** task 4.1's green local gates and E1-E7 evidence.
- **[F]:** none (checkpoint).
- **Work:** push the implementation branch, open the implementation PR, and
  present the remaining Long Method and Duplicate Code smells by name to the
  maintainer. Do not infer approval from green tests or CI.
- **Invariant:** the feature directory remains tracked for review; no merge
  before required checks and maintainer acceptance.
- **Gate/evidence:** PR diff and test evidence, CI state, and explicit reviewer
  disposition. No tracker key, task id, agent/model name, or agent trailer in
  commit, branch, PR title, or PR body.
- **Depends on:** 4.1.
- **Disposition:** reviewer APPROVE with zero blockers at `968e2f6b` (review
  comment `01a1cf27-0cee-7bc1-b62b-005c6b8c5ad1`, 2026-11-12T09:46:45Z);
  maintainer accepted both surviving smells as follow-up work (comment
  `01a1d812-b689-7a05-8cf2-09cccb7528a7`, 2026-11-14T03:21:07Z), recorded as
  `.spec/STATUS.md` *Potential Follow-ups* 35.

## Wave 6: merge preparation

### [ ] 6.1 Preserve durable decisions, then clear branch-only artifacts

- **Input:** task 5.1 review and green required checks; `.spec/README.md`
  feature-artifact lifecycle.
- **[F]:** `.spec/STATUS.md`,
  `.spec/features/optional-parameter-cli-flag/spec.md`,
  `.spec/features/optional-parameter-cli-flag/contracts.md`,
  `.spec/features/optional-parameter-cli-flag/plan.md`,
  `.spec/features/optional-parameter-cli-flag/tasks.md`.
- **Work:** first commit and push a concise durable outcome/decision in
  `.spec/STATUS.md` (or a contributor ADR if the decision warrants it). In a
  **separate final deletion-only commit**, run
  `git rm -r .spec/features/optional-parameter-cli-flag`, then push again.
- **Invariant:** no feature artifact survives on the merge head; the final
  commit contains only deletions. The earlier committed `tasks.md` keeps the
  `contract-diff-carries-task-graph` check auditable across the PR range.
- **Gate/evidence:** `git ls-files .spec/features/optional-parameter-cli-flag`
  is empty after the deletion commit, `git show --stat --oneline HEAD` shows
  deletions only, and `spec-artifacts-cleared` passes. Merge only after all
  required checks and before 0.5.0 is tagged.
- **Depends on:** 5.1.

## Task Dependency Graph

```json
{
  "waves": [
    {"id": 0, "tasks": ["1.1"]},
    {"id": 1, "tasks": ["2.1"]},
    {"id": 2, "tasks": ["3.1"]},
    {"id": 3, "tasks": ["3.2"]},
    {"id": 4, "tasks": ["4.1"]},
    {"id": 5, "tasks": ["5.1"]},
    {"id": 6, "tasks": ["6.1"]}
  ]
}
```
