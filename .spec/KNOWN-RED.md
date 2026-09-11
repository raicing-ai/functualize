# Known-red — failures that are not your change

The orchestrator maintains this file. **Read it before triaging a red suite**, and
before writing "this failure is not mine" in a report.

Two agents on this branch independently triaged the *same eight* failures, in
runs that between them took over half an hour. That work only needed doing once.
If you diagnose something new, tell the orchestrator and it lands here.

Every entry states the **reproduction** and the **discriminator** — the command
that distinguishes this known cause from a real defect that happens to look like
it. An entry with no discriminator is an excuse, not a diagnosis.

---

## 1 · A failure that passes when re-run alone

**Cause.** `-n auto` distributes tests across workers, and this repository is
often worked on by several agents at once. A test can fail because of another
worker's global state, or because a file changed underneath the run.

**Discriminator.**

```bash
uv run pytest <the exact node id> -q -p no:randomly --run-slow
```

Passes alone → artifact. Fails alone → **yours, or a real defect.** Say which in
your report; "it's probably concurrency" without running this is not triage.

---

## 2 · Tests that no longer exist

**Cause.** Another agent renamed or replaced a test class while your suite was
running. Your run compiled their new source against your stale copy of the tests.

**Discriminator.**

```bash
grep -n "^class <TheClassName>" <the file>
```

No output → the class is gone; the failure is a ghost of a file that has since
changed. This is not hypothetical: a run reported four failures in
`TestTtyRequiredNoDefault` and `TestTtyWithDefault`, and neither class exists any
more.

---

## 3 · `tests/_cli/test_snapshot_baseline.py` — **FIXED, 2026-09-10**

Was: four failures whenever `NO_COLOR=1` or `TERM=dumb` was set, which every
agent shell exports and an interactive shell does not. The TUI entered its
`nocolor` pseudo-class and every colour in the render changed.

The fixture now pins the colour mode, so these pass in any shell. **If you see
them fail now, that is real** — do not wave it through as the old environment
issue.

---

## 4 · `tests/_cli/test_self_doctor.py::…::test_a_recognised_installation_reports_ok`

**Cause.** Environmental. It reverse-maps `argv[0]` through installed console
scripts and picks up a *sibling worktree's* stale venv from `PATH`
(`…/.worktrees/mcp-server-fixes/.venv/bin/func=warning (0.2.3 unknown [stale])`).

**Discriminator.** The failure text names a path outside this worktree. If it
names only paths inside this worktree, it is real.

---

## 5 · Timing-sensitive assertions on a loaded machine

**Cause.** The framework warns on stderr when a plugin takes over 50 ms to
import. On a busy machine it does, and any test asserting `stderr == ""` fails
with a message about plugin load time rather than about its own subject.

`tests/pipeline/test_exit_codes.py` was fixed by running its subprocess with
`--log-level ERROR` (2026-09-10). **If you write a test that asserts on empty
stderr, do the same** — otherwise you have written an unmarked performance
budget. Real budget assertions live in `tests/perf/` and carry the `perf_budget`
marker, which skips them under parallel runs.

**Discriminator.** The failure message mentions `took NNNms to load (budget:`.

---

## 6 · Hypothesis `FlakyFailure`

**Cause.** Seen as `TypeError("'NoneType' object is not subscriptable") [single
exception in FlakyFailure]` in property tests under `-n auto`. Hypothesis
replays a failing example and gets a different result, which means the failure
depended on shared state rather than on the example.

**Discriminator.** Rule 1. If it passes alone, it is this. If it reproduces
alone, you have found a genuine state leak and it is worth reporting loudly —
nobody has chased these down yet.

---

## 7 · A global registration changing what other tests count

**Cause.** Registering a new capability, event, or public name changes what
every test that *enumerates* those things sees — and those tests belong to no
task's file list.

**Discriminator.** Does the failing assertion count or list something? If so and
your change adds to that set, it **is** yours, however unrelated the file looks.
Update the test; that is in scope.

## 8 · `test_thread_worker_keeps_event_loop_responsive` — flaky under `-n auto`

**Seen:** 2026-09-10, one failure in a `--run-slow -n auto` run
(11,415 passed, 1 failed). Not seen in the four preceding full runs the same day.

**Discriminator.** Run it alone:

```
uv run pytest tests/tui_audit/test_blocking_worker.py -q -p no:randomly
```

Three consecutive isolated runs passed (3 passed, ~3.1s each). The test asserts
the Textual event loop stays responsive **within a time budget** while a thread
worker runs, so it measures wall-clock latency — which is exactly what `-n auto`
on a loaded machine takes away. A real regression here would fail in isolation
too, and repeatably.

**Not a defect on this branch**, and nothing in this session touched the worker
path except `_cli/tui/job_execution.py`'s verdict branch (which does not run in
this test). If it starts failing *in isolation*, that is a different bug and
this entry no longer applies.

## 9 · `tests/test_packaging.py::TestBuildArtifacts` — flaky under `-n auto`

**Seen:** 2026-09-10, two failures in a `--run-slow -n auto` run
(11,451 passed, 2 failed): `test_build_produces_sdist_and_wheel` and
`test_wheel_contains_entry_points`.

**Discriminator.** Run the file alone:

```
uv run pytest tests/test_packaging.py -q -p no:randomly --run-slow
```

Passed 14/14 on two consecutive isolated runs. These shell out to a real build
and write into the repository's `dist/`, which is **one directory shared by
every xdist worker** — so two workers building at once see each other's
half-written artifacts. It is the same category as the 25 artifact failures
this branch measured under four-way worktree concurrency, and the reason
worktree isolation was adopted.

**Not a defect on this branch.** If it fails *in isolation*, that is a real
packaging break and this entry does not apply.

---

## 10 · `tests/discovery/test_parse_failure_persists.py::test_a_warm_run_reports_exactly_what_the_cold_one_did` — flaky under `-n auto`

**Both parametrizations.** Either `[app]` or `[func]` can be the one that
fails; the cause is the shared cache path, not the door, so pinning the entry
to one of them would make the other read as a new defect.

**Seen:** 2026-09-11, one failure in a `-n auto` run (10,137 passed, 1 failed),
during `engine-sealed-construction`/T8. The commit under test renamed
`rc.<member>` call sites and touched nothing in `_discovery/`.

**Seen again:** 2026-09-11, `[func]` this time, in the `-n auto` run that
verified the capability-duality fixes (11,699 passed, 1 failed). Serial re-run
of the file: 9 passed, 1 skipped.

**Discriminator.** Run the file alone, then the directory, then a wider slice:

```
uv run pytest tests/discovery/test_parse_failure_persists.py -q      # 9 passed, 1 skipped
uv run pytest tests/discovery -q -n auto                             # 667 passed
uv run pytest tests/discovery tests/cli tests/group_options -q -n auto  # 2502 passed
```

All green. The test asserts a **cold run and a warm run produce the identical
failure list, in order** — it runs the same tree twice and compares. Both runs
resolve a cache path, and under xdist several workers resolve into the same
`XDG_CACHE_HOME` unless a test owns one; a neighbour writing between the two
runs changes what the second one reads.

**Not a defect on this branch.** If it fails *in isolation*, the cold/warm
agreement has genuinely broken and this entry does not apply — that pair is a
real defect this file's §2 was written about, not a flake.
