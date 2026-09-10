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
