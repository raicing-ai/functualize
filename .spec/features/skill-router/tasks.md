# skill-router — Tasks

Authored 2026-10-13 against `36eaeabf` (`origin/master`); revised the same day
after the package review of `d34b70d3` (native response shape, native cost, the
freeze's reach, the Plan retrieval). There are sixteen tasks in twelve waves.
Every `now:` below was produced by running its command on this branch at
authoring time.

**Execute is authorised.** The maintainer answered P-1 (downstream task list),
P-2 (verdict constants) and S-1 (Duplicate Code instead of editing Phase 3) on
2026-10-31T02:47:43Z; the three answers are recorded under *Decisions recorded*
below. All three match the package's recommendations, so `spec.md` and
`plan.md` stand as reviewed; a changed answer would have sent them back for
revision first.

**The implementation lands on this branch, in this pull request.** The spec is
created, executed and completed within the same PR, and removed before merging
(T16). Never open a second PR, and never merge.

**The Execute phase reads only this file from the feature directory.** Each
task restates the behaviour, files, commands and observable result that close
it. `B-n`/`AC-n` ids are `spec.md`'s and `C-n` ids are `contracts.md`'s; you
do not need to open them.

## How to read a gate

A gate is a fenced `bash` block holding one **count**, followed on the next
line by `now:` (measured at authoring) and `after:` (what the task must
produce). `tests/spec/test_task_gates_still_hold.py` re-runs every gate of
every `[x]` task against `HEAD`, so each gate counts something later tasks
never remove. `invariant` marks a count that must not change. **Only gates use
the `bash` tag.** Commands to run are in untagged fences, because the parser
reads every `bash` fence as a gate. Comments and docstrings in a counted file
count too. Run every command from the repository root.

## Standing rules for every task

- Worktree `/home/ubuntu/orca/workspaces/functualize/sdd-skill-router`, branch
  `sdd/skill-router`. If `.venv` is missing or stale, run
  `uv sync --frozen --all-extras --all-packages`.
- Checks, redirected to logs: `uv run ruff check --fix src/ tests/ plugins/ examples/`,
  `uv run ruff format src/ tests/ plugins/ examples/`, `uv run mypy src/` and
  `uv run lint-imports`, each `> /tmp/functualize-<cmd>.log 2>&1`, then the
  task's own pytest command. Use at most two pytest invocations per
  verification, and never pipe pytest through `head`/`tail`. `evals/` is not
  in ruff's default paths: also run `uv run ruff check evals/providers` and
  `uv run ruff format --check evals/providers` in T2.
- One commit per task that changes files. Use a conventional subject with
  scope `test`, `docs` or `build` (for `evals/`), at most 72 chars, lowercase
  and imperative. **No tracker key, issue URL, agent, model or run identity in
  any commit message.**
- **No file under `skills/`, `src/`, `plugins/`, `examples/`, `docs/` or
  `tests/hermetic_eval/` changes** (B-29). If a task seems to need one, stop
  and report: the scope is wrong.
- `tests/skill_router_eval/` imports public `functualize` modules only
  (`functualize.app`, `functualize.app.utils`, `functualize.plugin`,
  `functualize.types`, `functualize.workflow`), plus `tests.hermetic_eval`'s
  generic parts listed in T5/T6.
- No offline test makes a network request, spawns a process or sleeps. No
  module in `tests/skill_router_eval/` imports `subprocess`: the only process
  spawns are Phase 3's `FrontierRouter` and the `evals/` harness, both reached
  through imports.
- Reachability: every function a task adds is called by a command (`replay`,
  `select`, `report`) or by the `evals/` provider by the end of its wave. The
  commits of T7 and T8 name that call path.
- Wave ordering is binding: never start wave N+1 while wave N has an unchecked
  task.

## Decisions recorded

- Shape SD/16515075 v3: Approved. D0–D3 = a (owner). D4–D6 as recommended
  (owner, 2026-10-13T06:42:18Z). Corpus-label review waived by the owner (same
  comment).
- P-1 (downstream tasks d1–d5): accepted by the maintainer 2026-10-31T02:47:43Z
  — the five cases exactly as `spec.md:293-306` fixes them; suite size
  5 × 3 arms × 3 repeats = 45 runs.
- P-2 (`min_lead = 0.05`, `max_unsafe_none = 0`): accepted by the maintainer
  2026-10-31T02:47:43Z — frozen in the lock before the first cell
  (`spec.md:345`).
- S-1 (Duplicate Code with Phase 3, no edit to `tests/hermetic_eval/`):
  accepted by the maintainer 2026-10-31T02:47:43Z — the rule-of-three
  extraction is recorded in the reference page and `plan.md:297`.

## Wave 0

### [x] T1 — the catalog declaration

*Files (new):* `tests/skill_router_eval/__init__.py`,
`tests/skill_router_eval/catalog.py`, `tests/skill_router_eval/test_catalog.py`

1. `__init__.py`: a docstring only, stating the instrument's rules. It measures
   pre-context skill selection over a frozen corpus and catalog. Nothing in the
   product imports it. It imports public `functualize` modules only. Offline
   tests never touch the network, spawn a process or sleep. Live runs are
   commands writing outside the repository. Measured numbers are never
   committed.
2. `catalog.py`, exactly C-1: `SKILLS`, `NONE`, `OPTIONS`, `NONE_MEANING`,
   `CatalogError`, `Entry`, `derive_catalog(skills_root)`, `catalog_json`,
   `catalog_sha256` (via `tests.hermetic_eval.comparators.identity_sha256`)
   and `option_meanings`. `derive_catalog` lists the directories under
   `skills_root` that hold a `SKILL.md`. It raises `CatalogError` unless that
   set equals `SKILLS`, naming the extra or missing directories. It reads the
   frontmatter with `yaml.safe_load` and collapses whitespace in `description`.
   The default root is `<repo>/skills`.
3. `test_catalog.py` (AC-1):
   - the real catalog has 5 options in order;
   - each description is non-empty;
   - two derivations give equal digests;
   - a `tmp_path` copy of `skills/` with an extra `functualize-extra/SKILL.md`
     raises, and one with `functualize-cli` removed raises;
   - one changed byte in a copied reference file changes that skill's
     `sha256` and the catalog digest.

Gate:

```bash
ls tests/skill_router_eval/catalog.py 2>/dev/null | wc -l
```
now: `0` · after: `1`

Closes when `uv run pytest tests/skill_router_eval/test_catalog.py -q > /tmp/functualize-t1.log 2>&1`
passes. Commit: `test(skill-router): derive the bounded skill catalog`.

### [x] T2 — the `evals/` harness arms and the downstream suite

*Files:* `evals/providers/_harness.py` (modify), `evals/providers/claude_agent.py`
(modify), `evals/providers/claude_router.py` (modify: one output key),
`evals/suites/skill-router.yaml` (new),
`tests/evals/test_skill_router_arms.py` (new), `evals/README.md` (modify: one
section, *The skill-router suite*)

0. **Measure first (F-10).** Run one cheap headless call on the eval
   credential and save its stream (outside the repo):
   ```
   claude -p "Say OK." --output-format stream-json --verbose --max-turns 1 --model claude-sonnet-5 > /tmp/functualize-claude-stream.jsonl
   ```
   Record whether `assistant` events carry `message.usage` with
   `input_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens`,
   and the `model` string of the `system`/`init` event.
   Save one redacted `assistant` line and the redacted `init` line as the test
   fixture `tests/evals/fixtures/assistant_usage.jsonl`. If there is no usage
   block, implement the field as always `null` and note it in the commit body
   (spec B-22). Then measure the **turn-budget stop** with one more cheap call
   that needs a tool:
   ```
   claude -p "List the files here with Glob, then read one." --output-format stream-json --verbose --max-turns 1 --allowed-tools Glob Read --model claude-sonnet-5 > /tmp/functualize-claude-maxturns.jsonl
   ```
   Record the `result` event's `is_error` and `subtype` in the commit body. T5
   copies that subtype string into `MAX_TURNS_SUBTYPE` (spec F-8; plan R-8).
1. `_harness.py`, exactly C-10:
   - `build_workspace(..., *, skills=None)`: a `skills` list copies exactly
     those `SKILLS_DIR/<name>` directories, and an unknown name raises
     `FileNotFoundError`;
   - `run_claude(..., append_system_prompt=None)`;
   - `AgentRun.first_turn_input_tokens`, set by `_absorb` from the **first**
     `assistant` event's usage only;
   - `AgentRun.duration_s`;
   - `AgentRun.model`, set by `_absorb` from the `system`/`init` event's
     `model` (today that event is only logged, `_harness.py:814-818`);
   - `skill_bodies(names)`.
   With no new keyword passed, the argv and the workspace are byte-for-byte
   today's.
2. `claude_agent.py`: config `arm` ∈ `load-everything | native | router`.
   - `load-everything`: all skills, plus `append_system_prompt =
     skill_bodies(SKILLS)`.
   - `native`: today's `with_skills: true`.
   - `router`: read `FZ_SKILL_ROUTER_SELECTIONS` (JSON, C-7) and take
     `cases[vars.case].outcome`. A skill means `skills=[skill]` plus its body.
     `none` means `skills=[]`. `escalated` means native. A missing env var,
     file or case returns `{"error": ...}`.
   - With `arm` set, `FZ_EVAL_MODEL` or `FZ_EVAL_SANDBOX` set to a value other
     than the config's returns `{"error": "override refused: …"}` before any
     workspace is built (spec B-5; today the env wins, `claude_agent.py:103`).
   - The output `arm` is the config arm when set. The output adds
     `first_turn_input_tokens`, `duration_s`, `model` and `router_outcome`.
   - With no `arm`, the output is unchanged.
2a. `claude_router.py`: the `output` dict gains `"model": run.model`. Nothing
   else changes: no default, no precedence, no key removed. Its one consumer's
   grader reads only `selected`, `skills_loaded` and `any_fired`.
3. `skill-router.yaml`, exactly C-11. Copy the five cases of spec B-19 verbatim
   from `functualize.yaml`, `functualize-app.yaml` and `functualize-skill.yaml`
   by their `description`, adding `vars.case` (`d1`…`d5`) and `vars.expect`.
   Set `options.disableVarExpansion` as the source suites do.
4. `test_skill_router_arms.py` (AC-11). Use a fake `Sandbox.popen` that records
   argv and yields fixture lines, and spawn no process.
   - `skills=["functualize-app"]` mounts exactly that directory;
   - `skills=[]` mounts nothing;
   - `append_system_prompt` reaches the argv;
   - no keyword gives today's argv;
   - `first_turn_input_tokens` is the first usage's sum, ignoring a second
     `assistant` event;
   - the router arm with a missing case errors;
   - with `arm` set and `FZ_EVAL_MODEL=claude-other`, the provider returns an
     `error` and the fake `popen` was never called;
   - `AgentRun.model` comes from the `init` fixture line;
   - each `skill-router.yaml` case equals its source case on `vars` and
     `assert`, ignoring `case` and `expect`.
5. `evals/README.md`: the run command of C-11, the env var, and that the suite
   is on demand, never in CI.

Gates:

```bash
rg -c 'append_system_prompt' evals/providers/_harness.py
```
now: `0` · after: `≥ 2` (record the exact count at commit)

```bash
rg -c 'FZ_SKILL_ROUTER_SELECTIONS' evals/providers/claude_agent.py
```
now: `0` · after: `1`

```bash
ls evals/suites/skill-router.yaml 2>/dev/null | wc -l
```
now: `0` · after: `1`

```bash
rg -c '"model": run\.model' evals/providers/claude_router.py
```
now: `0` · after: `1`

Closes when `uv run pytest tests/evals -q > /tmp/functualize-t2.log 2>&1`
passes (AC-11; the existing contracts now also cover the new suite).
Also run `uv run ruff check evals/providers` and `uv run ruff format --check evals/providers`.
Commit: `build(evals): mount a chosen skill subset and report first-turn tokens`.

## Wave 1

### [x] T3 — the corpus loader, the lock and the labelling rubric

*Files (new):* `tests/skill_router_eval/corpus.py`,
`tests/skill_router_eval/corpus/v1/LABELING.md`,
`tests/skill_router_eval/test_corpus.py`

1. `corpus.py`, C-2/C-3:
   - constants `SEED = 20261013`, `REPEATS = 5`, `TIME_BOX_HOURS = 72`;
   - `DECLARED = {"accept_at": 0.70, "min_margin": 0.10}` and
     `VERDICT = {"min_lead": 0.05, "max_unsafe_none": 0}`, both as
     `MappingProxyType`;
   - `CorpusError`, `Scenario` (the six C-2 keys) and `Lock` (the C-3 fields);
   - `load_corpus(path)`: exact keys in order, `expected ∈ OPTIONS`, and
     errors starting `line <n>:`;
   - `check_v1_shape`: 40 scenarios, ids `k01`…`k40`, 8 per option, and 5/3
     per stratum;
   - `check_seeded_labels(scenarios, triggering_yaml)`: every
     `triggering:<n>` origin's `expected` equals case `n`'s `vars.expect`,
     with exactly 21 such origins;
   - `check_disjoint_from_tasks(scenarios, suite_yaml)`;
   - `INSTRUMENT_FILES`: the ten repository-relative paths of C-3
     `instrument.files`, sorted;
   - `write_lock(version_dir, catalog, identities, *, selection, rule_digest,
     instrument_sha256, frozen_at)`, which refuses when a lock exists.
     `selection` is the C-3 `selection` block without `rule_digest`;
   - `check_lock(version_dir, catalog, identities, *, rule_digest,
     instrument_sha256)`, which raises `CorpusError` on a missing lock, a
     scenario-digest mismatch, a count mismatch, a catalog digest mismatch, a
     selection `rule_digest` mismatch, an instrument digest mismatch or an
     identity mismatch, naming which (spec B-5).
   - `corpus_sha256` and `ordered_cells` are **imported** from
     `tests.hermetic_eval.corpus`.
2. `LABELING.md`, with exactly seven `##` sections:
   - `§1 functualize` … `§4 functualize-skill` and `§5 none`, each quoting
     the catalog meaning;
   - `§6 tie-breaks`, as spec B-3 lists them;
   - `§7 two-skill requests`: such a request is **not labelled**. It is
     listed in `corpus/v1/TWO_SKILL.md` for the finding (spec §6).
3. `test_corpus.py`, using fixtures in `tmp_path`: every `CorpusError`
   branch (one test per mismatch kind above), the lock's round trip, and the
   refusal on an existing lock.

Gate:

```bash
ls tests/skill_router_eval/corpus/v1/LABELING.md 2>/dev/null | wc -l
```
now: `0` · after: `1`

Closes when `uv run pytest tests/skill_router_eval/test_corpus.py -q > /tmp/functualize-t3.log 2>&1`
passes. Commit: `test(skill-router): add the corpus loader, lock and rubric`.

### [x] T4 — the selection workflow

*Files (new):* `tests/skill_router_eval/selection.py`,
`tests/skill_router_eval/test_selection.py`

1. `selection.py`, exactly C-4:
   - `SELECT_INSTRUCTIONS`, `ESCALATED`, `SkillChoice`, `select_decision`,
     `build_selection`, `Selection` and `select(...)`;
   - `fallback=None`, `accept_at=0.70`, `min_margin=0.10`, and options from
     `option_meanings(derive_catalog(...))`;
   - `select` boots a fresh `FunctualizeApp` with the cwd set to `project` and
     restored afterwards, registers `DecisionGateResolver(provider)` as
     `decision`, executes, and reads `decision_record(ScopeStore(app.substrate),
     scope, "select")`.
2. `test_selection.py` (AC-4), with a fake provider:
   - 0.90 `functualize-cli` → `decided_by == "decision"`, outcome
     `functualize-cli`;
   - 0.55 → `RunStatus.BLOCKED`, `decided_by is None`, `escalated`;
   - `none` at 0.90 → `none`;
   - `DecisionUnavailableError` → `escalated`;
   - the `ChoiceRequest` options equal the five meanings in order.

Gate:

```bash
rg -c 'fallback=None' tests/skill_router_eval/selection.py
```
now: `0` (file absent) · after: `1`

Closes when `uv run pytest tests/skill_router_eval/test_selection.py -q > /tmp/functualize-t4.log 2>&1`
passes. Commit: `test(skill-router): add the gated skill selection workflow`.

### [ ] T5 — the comparators

*Files (new):* `tests/skill_router_eval/comparators.py`,
`tests/skill_router_eval/test_comparators.py`

0. **Measure first (F-14, plan R-1).** With `OPENCODE_API_KEY` exported (same
   recipe as Phase 3: the `opencode-go` key from
   `~/.local/share/opencode/auth.json`, never printed), make **one** live
   `hermetic().choose(...)` call. Use the real five-option request built from
   `option_meanings(derive_catalog(...))` and the state `"func: command not
   found"`. Record the outcome in the commit body. If Jev refuses or
   truncates, cut each meaning to its first sentence **inside `catalog.py`**
   (`option_meanings(..., short=True)`, declared in C-1 and digested in the
   lock). Report the deviation. Never edit `skills/`.
1. `comparators.py`, exactly C-5:
   - `KEYWORDS`, written **from the five meanings only, before any corpus
     scenario exists**;
   - `KeywordTable`;
   - `NATIVE_CONFIG = {"model": "claude-sonnet-5", "max_turns": 3,
     "timeout_s": 180, "sandbox": "host"}` (a `MappingProxyType`; the values
     `triggering.yaml:23-35` uses) and `MAX_TURNS_SUBTYPE` (the string T2 step
     0 recorded);
   - `NativeOverrideError`, `NativeCell` (C-5 fields);
   - `NativeRouter`, which loads `evals/providers/claude_router.py` by path
     under the module name `skill_router_native_reference` and caches it in
     `sys.modules`, the same mechanism as `tests/hermetic_eval/_router.py`;
     `call_api` and `environ` are injectable. The constructor raises
     `NativeOverrideError` when `FZ_EVAL_MODEL` or `FZ_EVAL_SANDBOX` is set to
     a value other than `NATIVE_CONFIG`'s. `select` calls `call_api(state,
     {"config": dict(NATIVE_CONFIG)}, {})` and reads the response by the C-5
     table, **in its order**: a missing `output` is a setup failure with cost
     `None`; otherwise unwrap `output` and take `cost`; then `output.error`
     (a non-`MAX_TURNS_SUBTYPE` error fails the cell); then `selected`. A
     top-level `selected` is never read. `identity()` embeds
     `dict(NATIVE_CONFIG)`;
   - re-exports of `hermetic`, `hermetic_identity`, `FrontierRouter` and
     `identity_sha256` from `tests.hermetic_eval.comparators`;
   - `identities() -> dict[str, str]` for the four comparators.
2. `tests/skill_router_eval/fixtures/native_responses.json`: the eight AC-6
   responses, each **in the provider's real shape** (`claude_router.py:60-61`
   for the setup error, `:75-84` for the envelope, with every `output` key the
   provider emits), plus the legacy top-level-`selected` shape.
3. `test_comparators.py` (AC-6): the keyword table's determinism, one-hot and
   uniform-0.20 cases; every `NativeRouter` row of the fixture, including the
   config the fake received (`max_turns == 3`), the kept cost on a failed run,
   `None` cost on a setup failure and the legacy shape failing; the
   `NativeOverrideError` on `FZ_EVAL_MODEL=claude-other` and on
   `FZ_EVAL_SANDBOX=docker` with the fake never called; and that constructing
   `NativeRouter` and `FrontierRouter` spawns nothing.

Gate:

```bash
rg -c '^KEYWORDS' tests/skill_router_eval/comparators.py
```
now: `0` (file absent) · after: `1`

```bash
rg -c '"max_turns": 3' tests/skill_router_eval/comparators.py
```
now: `0` (file absent) · after: `1`

Closes when `uv run pytest tests/skill_router_eval/test_comparators.py -q > /tmp/functualize-t5.log 2>&1`
passes. Commit: `test(skill-router): add the keyword and native comparators`.

### [ ] T6 — the metrics

*Files (new):* `tests/skill_router_eval/metrics.py`,
`tests/skill_router_eval/test_metrics.py`

1. `metrics.py`, pure functions over C-8 rows:
   - `routed_confusion` (5 × 6, with an `escalated` column) and
     `proposed_confusion` (with a `failed` column);
   - `accuracy_summary` (accuracy, per-option precision and recall,
     macro-F1);
   - `errors_at(rows, accept_at, min_margin)`, returning the four spec B-13
     errors;
   - `coverage`;
   - `calibration`, with a five-option Brier score;
   - `outcome_at` (the offline rule via the imported `accepts`; a failed cell
     is `escalated`), `sweep` and `conformance`;
   - `context_bytes(row, catalog)` per arm and `context_summary` (spec B-18);
   - `wilson(successes, n)`;
   - `downstream_summary(promptfoo_results)`, which also returns the set of
     observed `model` values;
   - `native_cost(rows)` (C-9): sums `row["native"]["cost_usd"]`, counts
     `None` as unpriced;
   - `verdict(...)` (spec B-24).
   **Import, do not copy**, `accepts`, `agreement`, `variance`, `latency` and
   `cost` from `tests.hermetic_eval.metrics`. `cost` is for token columns only;
   **never** use its `usd_total` for native (it is `0.0` for every
   non-frontier ledger, `tests/hermetic_eval/metrics.py:231-252`).
2. `test_metrics.py` (AC-8, AC-10, AC-12 Wilson): hand-computed fixtures for
   every function. Include a zero-flip deterministic ledger, a five-option
   Brier case, each verdict branch including the unsafe-`none` override, and
   the native-cost case of AC-8: rows priced 0.0421, 0.0187 and `None` give
   `usd_total == 0.0608` and `unpriced_cells == 1`, while the imported `cost`
   gives `usd_total == 0.0` on the same rows.

Gate:

```bash
rg -c '^from tests\.hermetic_eval\.metrics import' tests/skill_router_eval/metrics.py
```
now: `0` (file absent) · after: `1`

```bash
rg -c '^def native_cost' tests/skill_router_eval/metrics.py
```
now: `0` (file absent) · after: `1`

Closes when `uv run pytest tests/skill_router_eval/test_metrics.py -q > /tmp/functualize-t6.log 2>&1`
passes. Commit: `test(skill-router): add selection and context metrics`.

## Wave 2

### [ ] T7 — the replay, freeze and select commands

*Files (new):* `tests/skill_router_eval/replay.py`,
`tests/skill_router_eval/select.py`, `tests/skill_router_eval/test_replay.py`

1. `replay.py`, exactly C-6/C-8. Follow Phase 3's loop semantics (header,
   budget, rate-limit pause without sleeping, `invalid_model` exit 3, time box
   → `not_attempted`, resume). Gated comparators go through
   `selection.select`. `native` goes through `NativeRouter.select`, with
   `route` = selected-or-`none` and `decided_by = "native"`.
   - `PROBE_STATE`, `probe_rule_digest(entries, project)` (one
     `selection.select` with `KeywordTable()` in a scratch project under
     `tmp`; returns `Selection.rule_digest`) and `instrument_sha256(repo_root)`
     over `corpus.INSTRUMENT_FILES` (C-3, C-6).
   - `--freeze` derives the catalog, computes both, and writes the lock with
     the four identities and the `selection` block.
   - Every start or resume calls `check_lock` with the **re-derived** catalog,
     probe `rule_digest` and instrument digest; `run.json` carries them, and a
     resume with a different header exits 2.
   - Each gated row carries `rule_digest` (C-8). A row whose `rule_digest`
     differs from the lock's is **not appended**; exit 2.
   - `--comparator native` constructs `NativeRouter` before any write; a
     `NativeOverrideError` exits 2. The row's `native` block is the
     `NativeCell` fields, its `failure` is `NativeCell.failed`, its `route` is
     `NativeCell.route`.
   - The default run dir is
     `$XDG_STATE_HOME|~/.local/state/functualize-skill-router-eval/<run-id>`.
2. `select.py`, exactly C-7. It runs the same `check_lock` as `replay`, writes
   `rule_digest` and `instrument_sha256` into `selections.json`, and refuses
   an `--out` path inside the repository.
3. `test_replay.py` (AC-3, AC-5, AC-7, plus the AC-9 fixture ledger). Use
   fakes only, with a 3-scenario corpus under `tmp_path` and `--corpus-root`
   / `--skills-root` seams. AC-3 now includes: a monkeypatched
   `SELECT_INSTRUCTIONS`; a changed byte in a scratch copy of a pinned file
   (pass the repo-root seam); `FZ_EVAL_MODEL=claude-other` and
   `FZ_EVAL_SANDBOX=docker` for `native`; a cell whose recorded `rule_digest`
   differs (no row appended, exit 2); and `select` on a mismatched lock.

Gate:

```bash
ls tests/skill_router_eval/replay.py tests/skill_router_eval/select.py 2>/dev/null | wc -l
```
now: `0` · after: `2`

```bash
rg -c '^def probe_rule_digest' tests/skill_router_eval/replay.py
```
now: `0` (file absent) · after: `1`

Closes when `uv run pytest tests/skill_router_eval/test_replay.py -q > /tmp/functualize-t7.log 2>&1`
passes. Commit: `test(skill-router): add the replay, freeze and select commands`,
with a body naming the call path `replay.main → selection.select →
app.execute → decision_record`.

## Wave 3

### [ ] T8 — the report command

*Files (new):* `tests/skill_router_eval/report.py`,
`tests/skill_router_eval/test_report.py`

1. `report.py`, exactly C-9 and spec B-25/B-26. Its tables cover routing per
   comparator (native as an accuracy-only row), the four errors, the sweep
   table at `min_margin = 0.10`, context per arm (bytes, ratio to native first,
   load-everything beside it), downstream per arm (success, Wilson interval,
   tokens, cost, turns, duration, `skills_loaded`, observed model), and
   provenance (including the selection `rule_digest` and the instrument
   digest). The native routing row's USD is `metrics.native_cost`, never
   Phase 3's `cost`. Exit 2 (C-9) when the inputs disagree on the corpus,
   catalog, `rule_digest` or instrument digest, when a gated ledger holds a
   `rule_digest` other than the lock's, or when the native ledger or the
   downstream results carry more than one observed model.
   `finding.md` states the verdict, the failed conditions, the gaps
   (`functualize-cli`/`none` have no downstream task; the single-skill label
   set and `TWO_SKILL.md` entries) and the deviations.
2. `test_report.py` (AC-9 doctored ledger → exit 4, AC-12, AC-13): the
   native fixture ledger's nonzero `usd_total` appears in `metrics.json` and
   `benchmark.md`; a gated ledger with a second `rule_digest` exits 2; a
   native ledger or downstream file with two observed models exits 2.

Gate:

```bash
ls tests/skill_router_eval/report.py 2>/dev/null | wc -l
```
now: `0` · after: `1`

Closes when `uv run pytest tests/skill_router_eval -q > /tmp/functualize-t8.log 2>&1`
passes. Commit: `test(skill-router): add the report and verdict`, with a body
naming `report.main → metrics.verdict`.

## Wave 4

### [ ] T9 — corpus v1, drafted

*Files (new):* `tests/skill_router_eval/corpus/v1/scenarios.jsonl`,
`tests/skill_router_eval/corpus/v1/TWO_SKILL.md`

Precondition: T5's `KEYWORDS` is committed (provenance: the table predates
the corpus).

1. Seed the 21 `triggering.yaml` cases in file order with `origin:
   triggering:<n>` and their own label. Draft 19 new scenarios against
   `LABELING.md` to reach 8 per option and 5 `clear` + 3 `borderline` per
   option. Write a rubric-citing `rationale` for every one. Run no
   comparator. Copy no downstream task prompt.
2. Requests that need two skills go in `TWO_SKILL.md` (prompt plus the two
   skills), never into `scenarios.jsonl`.
3. Extend `test_corpus.py`: `check_v1_shape`, `check_seeded_labels` and
   `check_disjoint_from_tasks` over the real file (AC-2).

Gate:

```bash
wc -l < tests/skill_router_eval/corpus/v1/scenarios.jsonl 2>/dev/null || echo 0
```
now: `0` · after: `40`

Closes when `uv run pytest tests/skill_router_eval/test_corpus.py -q > /tmp/functualize-t9.log 2>&1`
passes. Commit: `test(skill-router): draft the version 1 selection corpus`.

## Wave 5

### [ ] T10 — reviewer label check, then freeze

*Files:* `tests/skill_router_eval/corpus/v1/corpus.lock.json` (new, written by
the command), `tests/skill_router_eval/test_corpus.py` (extend)

Precondition: the owner waived label review (2026-10-13). Instead, a
**reviewer other than the drafter** reads every `rationale` against
`LABELING.md` and records "labels checked: N/40 consistent" in the PR
conversation. Any inconsistency is fixed in T9's file **before** the freeze.
No live cell has run.

1. Freeze:
   ```
   uv run python -m tests.skill_router_eval.replay --freeze --corpus v1
   ```
2. `test_v1_lock_matches_corpus_catalog_and_comparators`: `check_lock` with
   the re-derived catalog and `comparators.identities()` returns a lock with
   `count == 40`, `repeats == 5` and `seed == 20261013`, with the re-computed
   probe `rule_digest` and instrument digest. From here on, an edit to
   `scenarios.jsonl`, **any of the ten `INSTRUMENT_FILES`** (the selection
   instructions, option meanings and thresholds included, through the
   `rule_digest`) or **any file in `skills/`** fails this test. The remedy is
   `v2/`, never an edited lock.

Gate:

```bash
rg -c '"catalog_sha256"' tests/skill_router_eval/corpus/v1/corpus.lock.json 2>/dev/null || echo 0
```
now: `0` · after: `1`

Closes when the test passes and the branch is pushed, so the lock is on the
remote before any measurement. Commit: `test(skill-router): freeze the version 1 selection corpus`.

## Wave 6

### [ ] T11 — the live routing measurement and the selections (no commit)

*Files:* none in the repository. The outputs are four run directories and
`selections.json` under `~/.local/state/functualize-skill-router-eval/`.

Preconditions:
- the maintainer's Codex login is live (`codex login status`);
- `OPENCODE_API_KEY` is exported in the same shell call (never printed);
- the eval credential for `claude` is present (`cd evals && npm run doctor`);
- `FZ_EVAL_MODEL` and `FZ_EVAL_SANDBOX` are unset (the native replay and the
  `arm` runs refuse them otherwise).

1. In foreground calls, one invocation per tool call, re-invoke each with the
   same `--run-dir` until it prints `run complete`:
   ```
   uv run python -m tests.skill_router_eval.replay --corpus v1 --comparator deterministic --run-dir "$HOME/.local/state/functualize-skill-router-eval/v1-deterministic"
   uv run python -m tests.skill_router_eval.replay --corpus v1 --comparator native --run-dir "$HOME/.local/state/functualize-skill-router-eval/v1-native"
   uv run python -m tests.skill_router_eval.replay --corpus v1 --comparator frontier --run-dir "$HOME/.local/state/functualize-skill-router-eval/v1-frontier"
   uv run python -m tests.skill_router_eval.replay --corpus v1 --comparator hermetic --run-dir "$HOME/.local/state/functualize-skill-router-eval/v1-hermetic"
   uv run python -m tests.skill_router_eval.select --tasks evals/suites/skill-router.yaml --out "$HOME/.local/state/functualize-skill-router-eval/v1-selections.json"
   ```
2. On `resume after <UTC>`, stop that comparator, report the time on the
   tracker, and resume in a later run. Never sleep or poll inside a run. Exit
   3 voids the run. Never re-run a completed comparator to improve numbers.

Closes when each `cells.jsonl` has 200 lines and `selections.json` has 5 cases
(AC-14, routing half). No commit.

## Wave 7

### [ ] T12 — the live downstream runs (no commit)

*Files:* none in the repository. The output is
`~/.local/state/functualize-skill-router-eval/v1-downstream.json`.

Preconditions: T11's `selections.json` exists, the eval credential is present,
and the container image is built (`evals/README.md`). These 45 agent runs are
the spend the owner approved under D3. Print the cumulative cost from the
results and report it.

```
cd evals && FZ_SKILL_ROUTER_SELECTIONS="$HOME/.local/state/functualize-skill-router-eval/v1-selections.json" npx promptfoo eval -c suites/skill-router.yaml --no-cache --repeat 3 -o "$HOME/.local/state/functualize-skill-router-eval/v1-downstream.json"
```

The suite is long-running (about 45 × a few minutes). Run it as one
foreground call per arm with `--filter-providers <label>` if one call would
exceed the tool timeout, writing one results file per arm. The report then
takes three `--downstream` files; T8 accepts a repeated flag. A run cut
short is reported, never silently re-run.

Closes when the results hold 45 rows across the three arms (AC-14, downstream
half). No commit.

## Wave 8

### [ ] T13 — the report, published and delivered (no commit)

*Files:* none in the repository.

1. Generate and check:
   ```
   uv run python -m tests.skill_router_eval.report --run-dir …/v1-hermetic --run-dir …/v1-frontier --run-dir …/v1-deterministic --run-dir …/v1-native --selections …/v1-selections.json --downstream …/v1-downstream.json --out …/v1-report
   uv run python -m tests.skill_router_eval.report … --check …/v1-report
   ```
   Both exit 0. Exit 4 means stop and report.
2. Publish with the Atlassian tools (shape evidence row; spec B-27). Create
   one page in `SD`, parent `5144577`, titled `Skill Router — Corpus v1
   Results`. Its body is the status line ("Computed verdict: <verdict> — a
   recommendation; the disposition is the maintainer's"), the corpus and
   catalog digests and the commit, then `finding.md`, then `benchmark.md`.
   Attach the report files, the four ledgers, `selections.json` and the
   downstream results. **Read it back live** (AC-18). A failed Atlassian
   call follows the fail-closed rule: retry at least 3 times, then stop.
3. Deliver the same files on the tracker with the verdict and the page link.

Closes when both commands exit 0, the page reads back with both digests, and
the delivery comment exists. No commit.

## Wave 9

### [ ] T14 — the durable half: the method, not the numbers

*Files:* `contributor/reference/skill-router-evaluation.md` (new),
`.spec/STATUS.md` (modify)

1. The reference page has exactly these sections: `## What it measures`,
   `## The catalog and the corpus freeze`, `## The selection gate`,
   `## The comparators and the arms`, `## Running it`, `## The measurements`,
   `## The verdict rule`, `## What it does not measure` and
   `## Extending to a third question`. The last section is S-1's
   rule-of-three note: where a shared `Question` abstraction would be
   extracted. It carries **no measured number**.
2. `.spec/STATUS.md`: after `### Hermetic evaluation — delivered`, add
   `### Skill router evaluation — delivered` (at most 15 lines) covering the
   instrument path, the reference page, the corpus and catalog digests, the
   results page, and the open items (disposition; Phase 5; the two-skill
   gap).

Gates:

```bash
ls contributor/reference/skill-router-evaluation.md 2>/dev/null | wc -l
```
now: `0` · after: `1`

```bash
rg -c '^### Skill router evaluation' .spec/STATUS.md
```
now: `0` · after: `1`

Commit: `docs(reference): describe the skill router evaluation`.

## Wave 10

### [ ] T15 — checkpoint

*Files:* none expected.

1. Run the standing checks, then
   `uv run pytest tests/skill_router_eval tests/evals tests/hermetic_eval -q > /tmp/functualize-t15.log 2>&1`
   (AC-17). Dispatch the full tier on the PR's CI; do not run it locally.
2. `uv run python .github/scripts/dead_code_delta.py origin/master HEAD > /tmp/functualize-deadcode.log 2>&1`:
   classify each finding KNOWN or UNMARKED (advisory).
3. Invariant gates over the whole range:

```bash
git diff --name-only origin/master...HEAD -- skills src plugins examples docs tests/hermetic_eval | wc -l
```
now: `0` · after: `0` · invariant

```bash
rg -l functualize_decision_jev src | wc -l
```
now: `0` · after: `0` · invariant

```bash
git ls-files | rg -c "cells\.jsonl|benchmark\.md|selections\.json"
```
now: `0` · after: `0` · invariant

```bash
rg -l "^(from|import) functualize\._" tests/skill_router_eval | wc -l
```
now: `0` · after: `0` · invariant

```bash
rg -l "^import subprocess|^from subprocess" tests/skill_router_eval tests/evals/test_skill_router_arms.py 2>/dev/null | wc -l
```
now: `0` · after: `0` · invariant

Closes when all of the above hold. Commit nothing unless a check needed a
fix; such a fix lands before T16. **A fix to a file in `INSTRUMENT_FILES`
after T10 voids corpus v1** (the lock test fails, by design): stop and report
it instead of committing it; never edit the lock.

## Wave 11

### [ ] T16 — clear the spec artifacts (deletion-only, last)

*Files:* `.spec/features/skill-router/**` (delete)

1. Push the feature commits first and let CI's validation jobs pass,
   including the three `test-full` legs. The artifact checks are expected to
   be red.
2. As the **last** commit, deletion only: `git rm -r .spec/features/skill-router`,
   committed as `chore(spec): clear the skill router artifacts`, then push.

Gate:

```bash
git ls-files .spec/features | wc -l
```
now: `5` (after this package's own commit) · after: `0`

Closes when `spec-artifacts-cleared` is green on the PR. Never merge.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["T1", "T2"] },
    { "id": 1, "tasks": ["T3", "T4", "T5", "T6"] },
    { "id": 2, "tasks": ["T7"] },
    { "id": 3, "tasks": ["T8"] },
    { "id": 4, "tasks": ["T9"] },
    { "id": 5, "tasks": ["T10"] },
    { "id": 6, "tasks": ["T11"] },
    { "id": 7, "tasks": ["T12"] },
    { "id": 8, "tasks": ["T13"] },
    { "id": 9, "tasks": ["T14"] },
    { "id": 10, "tasks": ["T15"] },
    { "id": 11, "tasks": ["T16"] }
  ]
}
```

Wave notes:

- **Wave 0.** T1 (`tests/skill_router_eval/catalog.py`) and T2 (`evals/`,
  `tests/evals/`) touch disjoint files and share nothing.
- **Wave 1.** T3, T4, T5 and T6 each own one new module plus its test, and
  all import `OPTIONS` from T1. T5 imports `option_meanings` and T4 imports
  `derive_catalog`; neither imports the other. T6 is pure over rows.
- **Wave 2.** T7 needs T3 (lock), T4 (selection) and T5 (comparators).
- **Wave 3.** T8 needs T6 and T7's fixture ledger (AC-9).
- **Waves 4–5.** The corpus is drafted after `KEYWORDS` exists, then reviewed
  and frozen. The reviewer check replaces the waived owner approval.
- **Barrier-critical path:** T1 → T5 → T7 → T8 → T9 → T10 → T11 → T12 → T13.
  The live waves (6–8) gate on credentials and on Jev and Codex usage windows,
  and they dominate the calendar time.
- **Waves 9–11.** These are the durable docs, the checkpoint and the
  deletion-only tip, each alone and in that order.
