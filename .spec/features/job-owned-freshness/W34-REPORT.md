# W34 — report (job-owned-freshness, waves 3–4 · T4, T5)

Agent scope: **T4** (worked example + guide, spec AC-8) and **T5** (feature gate). Worktree
`/home/viltohmyst/.herdr/worktrees/functualize/agent-f9-freshness-w34`, branch
`agent/f9-freshness-w34`. **No git command was run** (RULES §1); every sabotage was restored by
`cp -f` from `/tmp/f9-backup/` and each restore is proven byte-identical with `cmp`, below.
Nothing in `src/` changed: this wave is example + docs only.

---

## 0 · Retrieval — verified before starting (RULES, first section)

```
$ ls graphify-out/graph.json .serena/project.yml && du -sh .zvec-grep
.serena/project.yml
graphify-out/graph.json
74M	.zvec-grep
```

All three present and warm. No re-bootstrap was needed.

**The venv, however, did not arrive complete.** `uv run pytest examples/ --collect-only`
exited with three `ModuleNotFoundError`s (`functualize_ai`, plus the inline/state plugins), so
no example could run at all. `uv sync --all-packages` fixed those but *pruned* the `tui`
extra, which turned `uv run mypy src/` red on a file I never touched:

```
src/functualize/_cli/tui/functualize_autocomplete.py:18: error: Cannot find implementation or
library stub for module named "textual_autocomplete"  [import-not-found]
… 6 errors in 1 file (checked 335 source files)
```

`mtime` on that file is `11:01:36`, the worktree's checkout stamp — it is not mine. The fix is
the one `contributor/guides/docs-example-parity.md` prescribes, all three flags at once:

```
$ uv sync --all-packages --all-extras --group docs
$ uv run mypy src/
Success: no issues found in 335 source files
```

Every command in §3 below was run **after** that sync.

---

## 1 · Scope note — where the example actually lives, and why

`tasks.md:130` and `plan.md:28` both name
`examples/quickstart/…/self_caching_job.py`. **`examples/quickstart/` is defined as the
README's Quick Start, one directory per step** (`examples/quickstart/README.md`: *"Working
examples for each step in the README Quick Start"*, and the table maps every directory to a
"README Step"). The Quick Start has exactly eight steps and the ninth would have to be written
into the user-facing root `README.md` — a file that is not in this task's list, and a much
larger editorial change than a worked example warrants.

A job-owned freshness lab is not a quickstart topic: it is the last thing a reader needs, not
the first. So the example went to `examples/standalone/` — the repo's *"Feature reference, no
project setup needed"* tree, whose one-directory-per-feature shape `secrets_lab/` and
`config_lab/` already establish — under the brief's own file name, so the AC-8 gate selects:

```
examples/standalone/freshness_lab/
├── README.md                       162 lines — the walkthrough (a checklist, secrets_lab-shaped)
├── pyproject.toml                    2 lines — [tool.functualize] jobs_directories = ["jobs"]
├── inputs/alpha.md, inputs/beta.md  11 lines — the declared sources
├── jobs/self_caching_job.py         93 lines — `report` (decides=True) + `baseline` (control)
└── tests/test_self_caching_job.py  185 lines — seven tests, real `func` processes
```

**Deviation from the brief's path: one directory segment.** The file name
(`self_caching_job.py`) and the gate selector (`-k self_caching`) are exactly as specified.
If the intended answer really was a ninth quickstart step, the correct fix is to correct
`tasks.md`/`plan.md` — the same path appears in both, and the root README would have to grow a
step.

### Files touched outside the brief's three entries — and why

The brief lists `examples/quickstart/…/self_caching_job.py`, `docs/guides/`, and
`11-boundaries.md`. Three more files were edited, each because a new example directory that no
index names is the repo's own documented drift class (*"Index drift — a new example invisible
to readers"*, `contributor/guides/docs-example-parity.md`):

| File | Change |
|---|---|
| `examples/README.md` | standalone bullet list: added `freshness_lab/`, and restored `composition_lab/` — the list said "six directories" over a seven-row table and omitted `composition_lab` entirely. Both counts now read **eight**, matching the tree |
| `examples/standalone/README.md` | "Seven directories" → "Eight"; one table row; one checklist entry |
| `docs/examples/index.md` | one clause in the "Also in the repo (source-only)" paragraph |

`examples/quickstart/README.md`, `examples/docs/scenarios/*` and `mkdocs.yml` were **not**
touched.

---

## 2 · T4 · The worked example and the guide

### 2.1 What changed

**The example** (`jobs/self_caching_job.py`, 93 lines) is two declarations and a decision:

```python
@job(
    group=JOB_GROUP,
    cache=Fingerprint(
        sources=["inputs/*.md"],
        generates=["build/report.json"],
        decides=True,                      # when I am fresh, run me anyway
    ),
)
def report(fresh: Freshness, sources: Sources, log: Log) -> None:
    verdict = fresh.verdict()
    if verdict is not None and verdict.is_fresh:
        cached = json.loads(ARTIFACT.read_text())
        log(f"up to date under {verdict.key} — returning the artifact")
        print(f"CACHED built={cached['built']} state={verdict.state.value}")
        return
    built = uuid.uuid4().hex[:8]           # a real build: new identity each time
    …write build/report.json…
```

The artifact is `build/report.json` — the job's own path, format and contents, declared under
`generates` and never opened by the framework. `baseline` beside it is the same work with the
same declaration and **no** `decides`: the control that shows the default still skips. The
`built` token is what makes "did it rebuild?" observable rather than inferred.

**The tests** (185 lines, 7 tests) drive the real `func` CLI in a copy of the lab with its own
`XDG_CACHE_HOME`, as `composition_lab`'s e2e suite does and for the reason recorded there —
freshness is a fact about a *previous process*, so an in-process test cannot observe it:

| Test | Pins |
|---|---|
| `test_a_cold_run_builds_and_writes_its_own_artifact` | cold: body entered with `state=run`, artifact matches the published token |
| `test_a_fresh_run_enters_the_body_and_returns_the_artifact` | **the feature**: second run enters the body, reads `state=skip_fresh`, returns the *same* token, publishes no `BUILT` |
| `test_removing_the_declared_artifact_forces_a_rebuild` | a missing declared output is not fresh |
| `test_a_changed_input_forces_a_rebuild` | a changed source is not fresh |
| `test_the_framework_never_reads_the_artifact` | hand-edit `build/report.json`; the job is **still fresh** and returns the hand-edited bytes — the N1 boundary, made falsifiable |
| `test_a_job_without_the_opt_in_never_enters_its_body` | the control: exit 0, empty stdout |
| `test_they_describe_the_same_run` | the job's `verdict().state` and `func builtin why` render the same run (`run`/`WOULD RUN` before, `skip_fresh`/`SKIP (up to date)` after) |

**The guide** — `docs/guides/task-runner.md`, a new `### Deciding your own freshness` section
of 93 lines between *"Reading the inputs you declared"* and *"With guards"*: the default, the
declaration, the two-run transcript, the verdict's fields, the `why` agreement, and what it is
**not** (not a cache; not an obligation to skip; not a way to report a skip; `SKIP_FRESH` only;
and — the W012 note's item — the body runs on every invocation while the inputs are unchanged,
because a decided run does not rewrite its record). Plus `decides` in the `Fingerprint` value
object and a See Also link to the lab. Every transcript in it was executed verbatim from a
clean copy of the lab before it was written down.

**The cross-reference** — `contributor/architecture/run-model/11-boundaries.md` §B: the
subsection *"What it costs today: the job never sees the verdict"* becomes *"What it cost, and
what F9 did about it"* (+11 lines). The refusal and its reasoning are untouched; the paragraph
that said F9 *"applies that precedent"* now states that it landed, what moved (the conditional
early return, `force_fresh`'s scope) and what did not (the framework still owns no artifact),
and points at the example, the guide section and `wiring-discipline.md`.

### 2.2 Gate — AC-8

```bash
uv run pytest examples/ -q -k self_caching
```

**Before** — the selector named nothing (the branch's own note, re-confirmed):

```
$ uv run pytest examples/ -q -k self_caching
194 deselected in 0.70s
```

**After:**

```
$ uv run pytest examples/ -q -k self_caching
.......                                                                  [100%]
7 passed, 194 deselected in 17.36s
```

Two different spellings of the same question, neither of them the task's own gate:

```
$ uv run pytest examples/ --collect-only -q | grep -c self_caching
7
$ uv run pytest examples/standalone/freshness_lab -q --no-header
.......                                                                  [100%]
7 passed in 64.13s (0:01:04)      # under CPU contention with the slow suite; 16s alone
```

**Gate 2 — the vocabulary agrees with `why` (risk R-c):**

```bash
rg -c 'GuardState' src/functualize/_engine/capabilities/freshness.py src/functualize/_engine/explain.py
```

Before: `freshness.py: 3`, `explain.py: 15`. After: **unchanged** — W012 already satisfied this
(`freshness.py` was `n/a` at authoring time). T4 changes no production file. Verified
behaviourally rather than by `rg`, which is the stronger spelling of the same claim:

```
$ uv run python -c "…FreshnessVerdict(state=SKIP_FRESH…); print(v.is_fresh, HEADLINES[v.state])"
is_fresh -> True
why headline -> SKIP (up to date)
why headline for RUN -> WOULD RUN
```

### 2.3 Sabotage — the example really depends on the feature

`decides=True` deleted from the lab's `report` job (one line; nothing else):

```
$ uv run pytest examples/standalone/freshness_lab -q --no-header
FAILED …::TestTheJobThatDecides::test_a_fresh_run_enters_the_body_and_returns_the_artifact
    - AssertionError: assert 'CACHED' in ''
      +  where '' = CompletedProcess(args=[…'func', 'lab', 'report'], returncode=0, stdout='', stderr='').stdout
FAILED …::TestTheBoundaryThisExistsToMakeUsable::test_the_framework_never_reads_the_artifact
    - AssertionError: assert 'state=skip_fresh' in ''
FAILED …::TestTheVerdictAndWhyAgree::test_they_describe_the_same_run
    - AssertionError: assert 'state=skip_fresh' in ''
3 failed, 4 passed in 15.94s
```

Each failure is on that test's **own** assertion: the second run published *nothing*, which is
the engine skipping the body — the exact behaviour `decides=True` removes. Restored by `cp -f`
from the backup, then:

```
$ uv run pytest examples/standalone/freshness_lab -q --no-header
7 passed in 15.95s
```

---

## 3 · T5 · Feature gate

### 3.1 Every command, real output

```
$ uv run ruff check src/ tests/ plugins/
exit=0
All checks passed!

$ uv run ruff format --check src/ tests/
exit=0
1111 files already formatted

$ uv run ruff check examples/standalone/freshness_lab/     # extra: examples/ is not in the
exit=0                                                     # repo's lint target set
All checks passed!

$ uv run mypy src/
exit=0
Success: no issues found in 335 source files

$ uv run lint-imports
exit=0
Analyzed 335 files, 888 dependencies.
Peer layers are independent KEPT
Events depends on foundation only KEPT
Primitives import nothing internal KEPT
Types import nothing internal KEPT
Internal never imports public KEPT
_cli uses public API only KEPT
Contracts: 6 kept, 0 broken.

$ uv run pytest examples/ -q
exit=0
........................................................................ [ 35%]
........................................................................ [ 71%]
.........................................................                [100%]
201 passed in 291.72s (0:04:51)          # 194 before this wave, +7 from freshness_lab

$ HYPOTHESIS_PROFILE=ci uv run pytest --run-slow -n auto -q
exit=0
11209 passed, 139 skipped, 3087 warnings in 668.99s (0:11:08)
```

**The `--run-slow` suite is green with no triage needed.** Every failure class RULES documents
for this shell is absent: `tests/_cli/test_snapshot_baseline.py` passed (4/4) in the parallel
run, no `FlakyFailure` worker crashes, no uv-stderr budget reds. Nothing to re-run alone, so
nothing is reported as an artifact.

### 3.2 AC-1…AC-8, each named to a test

| AC | Test(s) |
|---|---|
| **AC-1** reads state, key, recorded value, declared sources + generates | `tests/execution/test_freshness_capability.py::test_the_verdict_is_populated_on_the_cold_path` (and `…_warm_path`); end-to-end, `freshness_lab::TestTheJobThatDecides::test_a_fresh_run_enters_the_body_and_returns_the_artifact` reads `.key` and `.state` |
| **AC-2** bound after the pre-flight, before the body; cold **and** warm | `…::test_the_verdict_is_populated_on_the_cold_path`, `…::test_the_verdict_is_populated_on_the_warm_path`, plus sabotage (b) failing **both** |
| **AC-3** a job that does not opt in is unchanged | `test_fingerprint_decides.py::test_a_job_that_does_not_opt_in_is_still_skipped`; end-to-end, `freshness_lab::TestTheBoundaryThisExistsToMakeUsable::test_a_job_without_the_opt_in_never_enters_its_body` (exit 0, empty stdout) |
| **AC-4** opted-in body entered on `SKIP_FRESH` and reads it | `…::test_an_opted_in_job_enters_its_body_and_reads_the_fresh_verdict`, `…::test_the_declaration_survives_a_warm_boot`, and the example's `test_a_fresh_run_enters_the_body_and_returns_the_artifact` |
| **AC-5** opt-in bypasses nothing but `SKIP_FRESH` | `…::test_opting_in_does_not_bypass_a_failing_precondition`, `…::test_opting_in_does_not_bypass_a_satisfied_status_guard`, `…::test_opting_in_does_not_bypass_a_blocking_gate` |
| **AC-6** the verdict is the engine's object, not recomputed | `…::test_the_reading_changes_when_the_decision_changes`, `…::test_the_source_map_is_the_decisions_own_object`; gate `rg -c 'compute_args_hash\|glob\|stat\(' freshness.py` → `0` |
| **AC-7** sabotage fails on both paths | §3.4 (b): 4 failed, including both named binding tests |
| **AC-8** declaration documented with a worked example that runs in `pytest examples/` | §2.2; the guide's new section and the lab's README |

### 3.3 Orphan scan — `Freshness`, `FreshnessVerdict`, `decides`

Every production mention of `Freshness` outside its own module is a registration or a
re-export; there is no definition without a reader, and no second implementation:

```
$ rg -n 'Freshness' src/ --glob '!**/capabilities/freshness.py'
src/functualize/_engine/executor.py:1823   (comment)
src/functualize/_primitives/capability_names.py:60    "Freshness",      ← ADR-014 name set
src/functualize/job/__init__.py:29,98      import + __all__               ← public export
src/functualize/job/_freshness.py:6        mirror module
src/functualize/job/capabilities.py:27,45  import + __all__
src/functualize/_types/job_declaration.py:202   (docstring reference)
```

`FreshnessVerdict` is constructed exactly once (`freshness.py:122`, in `_bind`) and consumed by
the example's body and by `test_freshness_capability.py`. `decides` has two production roles —
declared/serialized in `_types/job_declaration.py` (field `:216`, validation `:238`, `to_dict`
`:252`, `from_dict` `:264`) and read in `_engine/executor.py:1132` — and one declarer outside
`src/`: the lab's `report`. No orphan.

Reachability through the public surface is proven the way the example does it, not by
inspection: the lab imports `Freshness` from `functualize.job` and the CLI runs it. And an
example that never ran would fail its own tests — which §2.3 showed by breaking it.

### 3.4 The two sabotages

Both were recorded in W012 for waves 1–2; T5's list names them, so they were **re-run here**
against the current tree, backed up to `/tmp/f9-backup/` first.

**(a) T3 — `decides` always true.** `_decides = bool(getattr(_cache, "decides", False))` →
`_decides = True` in `executor.py`:

```
$ uv run pytest tests/execution/test_fingerprint_decides.py -q --no-header
FAILED …::test_a_job_that_does_not_opt_in_is_still_skipped
    - AssertionError: assert <RunStatus.SUCCESS: 'Success'> is <RunStatus.SKIPPED: 'Skipped'>
1 failed, 6 passed in 4.00s
```

**(b) T2 — the binding is unwired.** `instance._bind(decision)` → `del decision, instance` in
`freshness.py`:

```
$ uv run pytest tests/execution/test_freshness_capability.py -q --no-header
FAILED …::test_the_verdict_is_populated_on_the_cold_path - AssertionError: the verdict never
       arrived — the bind is unwired / assert None is not None
FAILED …::test_the_verdict_is_populated_on_the_warm_path - <same>
FAILED …::test_the_reading_changes_when_the_decision_changes
FAILED …::test_the_source_map_is_the_decisions_own_object
4 failed, 3 passed in 0.76s
```

**Both paths fail**, which is AC-7, and each on its own assertion. Restored by `cp -f`; then,
and this is the proof that nothing was left behind:

```
$ cmp /tmp/f9-backup/executor.py src/functualize/_engine/executor.py        → identical
$ cmp /tmp/f9-backup/freshness.py src/functualize/_engine/capabilities/freshness.py → identical
$ cmp /tmp/f9-backup/self_caching_job.py examples/standalone/freshness_lab/jobs/self_caching_job.py → identical
$ uv run pytest tests/execution/test_freshness_capability.py tests/execution/test_fingerprint_decides.py -q
14 passed in 4.09s
```

---

## 4 · Scope behaviour — T5's "wave 3 changed nothing in production"

T4 added no production code: `src/` is byte-identical to the branch as received (the `cmp`
block above covers every `src/` file a sabotage touched, and no other `src/` file was opened
for writing). The behaviour the wave demonstrates was landed by waves 0–2 and is pinned by
their tests plus the two sabotages above.

---

## 5 · Defects found and **not** fixed (rule 2: not my files)

1. **`func builtin why` and a job name containing `_` disagree with the run.** The CLI
   canonicalises a job name to its dashed command form when it *runs* (`state.json` records
   `lab.plain-report::fa72…::checksum`) but passes the caller's spelling straight to the
   pre-flight when it *explains*. Found while prototyping a control job called
   `plain_report`:

   ```
   $ func lab plain_report              # runs, records under lab.plain-report
   $ func builtin why lab.plain-report
   lab.plain-report → SKIP (up to date)
     fingerprint  2 sources unchanged
   $ func builtin why lab.plain_report
   lab.plain_report → WOULD RUN
     fingerprint  no previous run recorded
   ```

   This is a pre-existing name-normalisation defect, unrelated to F9, and it is why the example
   uses `report`/`baseline` — names that cannot trip it. It is in `_cli`/`app`, not in this
   wave's files. **Worth its own task**: `func builtin why` exits 4 for a job that just
   succeeded, and a script branching on that verdict gets the wrong answer.

2. **`contributor/architecture/run-model/04-request-and-entry.md:270` is stale.** §E says *"The
   engine has already decided, and the body is never entered"* — true when written, false since
   wave 2. The brief listed `11-boundaries.md` for the cross-reference, not this file, so it was
   left alone; it is the same class of drift §B had, and it is a one-paragraph fix.
   `run-model/CHANGELOG.md:50` and `evidence/drift-2026-09-09.md:109` carry the same sentence
   and are **dated records** — correctly left as they are.

3. **`skills/functualize/references/capabilities.md` does not mention the opt-in.** Its
   `Freshness` row is accurate but silent about `Fingerprint(decides=True)`, which is the only
   way a job ever gets to act on a fresh verdict. `skills/` ships to users and is not in this
   task's file list; `uv run pytest tests/skills/ -q` is green either way (68 passed, 4
   skipped), so this is a discoverability gap, not drift. Flagged for whoever owns the skill.

4. **`examples/README.md` said "six self-contained directories" over a seven-row table** and its
   bullet list omitted `composition_lab/` entirely. Fixed as a side effect of adding the eighth
   entry (§1) rather than left at eight rows under a "six" heading.

---

## 6 · What I could not do / did not do

- **No `git` command was run**, as instructed. There are therefore no commits, and the Wave
  Audit's `git show --stat` check is not runnable from here — the file list in §1 is the scope
  evidence instead.
- **`.spec/STATE.md` was not updated**: not in my file list, and rule 2 is absolute.
- **No `examples/docs/scenarios/*.toml` was added** for the guide's new section. The task's gate
  is the `examples/` pytest selector and T4's tests run the claims; a scenario would make the
  *guide's console transcripts* executable too, which is the stronger form. It is a new file
  outside the brief — see the question below.
- **`04-request-and-entry.md` and the skill row were left untouched** (§5), deliberately.

---

## 7 · Questions (not blocking; recorded so they do not resurface)

1. Was `examples/quickstart/…/self_caching_job.py` really meant to be a ninth Quick Start step?
   If yes, `tasks.md`/`plan.md` and the root README need the correction, and the lab should
   move; if no, the path in both files should say so (it is the same wrong path in two files,
   exactly as T1's `di.py` was).
2. Should the lab's `lab report` / `lab baseline` keep the control job? I kept it because the
   declaration "when I am fresh, run me anyway" is only meaningful against the default, and the
   repo's example convention favours a decoy — but it is a second job in a 93-line file.
3. Does the `_`/`-` name defect (§5.1) belong to F8's `adjacent-defects`, or to the
   surface-boundary work? It is one normalisation call, but it changes `why`'s exit code, so it
   silently misleads any script.

---

## Verdict table

| task | done? | gate before | gate after |
|---|---|---|---|
| **T4** | yes | `pytest examples/ -q -k self_caching` → `194 deselected` (0 selected); `GuardState` count `freshness.py: 3` / `explain.py: 15` | `7 passed, 194 deselected`; counts unchanged (already ≥1); example sabotage fails 3 tests, restore `7 passed` |
| **T5** | yes | — (checkpoint) | ruff 0, format 1111 formatted, mypy 335 files clean, lint-imports 6/6, `examples/ 201 passed`, `--run-slow 11209 passed / 139 skipped`; sabotages (a) 1 failed, (b) 4 failed incl. both binding tests; all restores `cmp`-identical |
