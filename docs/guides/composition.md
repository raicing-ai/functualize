# Composing Capabilities

Every other guide covers one feature. This one covers the **seams between**
them, because that is where the real questions are:

- Does `Fingerprint` still fire if my job takes a `Log`?
- Does `FromJob` deliver anything if the upstream was skipped as fresh?
- Does a failing `Precondition` look like a crash to my CI?
- If I declare `Guards(status=...)` *and* `Fingerprint`, which one wins?
- Where does the config for `def report(config: ReportConfig)` come from — and
  does changing it invalidate the cache?

Each answer below is **executed**, not asserted in prose:
[`examples/standalone/composition_lab/`](https://github.com/raicing-ai/functualize/tree/master/examples/standalone/composition_lab/)
is a runnable project with one job per combination, and
`examples/docs/scenarios/n-composition.toml` runs them and checks their output.
If this page and the framework disagree, that scenario goes red.

```bash
cd examples/standalone/composition_lab
func lab parse          # or any job below
```

---

## 1. Use cases → what to reach for

Start here. Find the sentence that matches what you are trying to do.

| I want to… | Reach for | Verified by |
|---|---|---|
| Run a step only when its inputs changed | `@job(cache=Fingerprint(sources=[...], generates=[...]))` | `lab parse` |
| Read the files I declared, without repeating the glob | `sources: Sources` | `lab parse` |
| Hand a typed value to the next step | a pydantic return type + `Annotated[T, FromJob("group.job")]` | `lab report` |
| Order two steps | `Deps("group.job")` — or just `FromJob`, which *is* an edge | `lab publish` |
| Skip work that something else already did | `Guards(status=["test -f stamp"])` | `lab publish` |
| Refuse to start unless the environment is right | `Guards(preconditions=[Precondition("cmd", msg="…")])` | `lab gated` |
| Fail loudly when the thing I'm meant to verify isn't there | declare it in `Fingerprint(sources=...)` — an empty resolution refuses | `lab verify` |
| Give a caller machine-readable output | `out: Stdout` + `func --output json …` | `lab emit` |
| Run an external command | `sh: Shell` | `lab probe` |
| Retry a flaky *job* | `Exec(retry=Retry(attempts=N))` | `lab probe` |
| Run the same work over N inputs | a driver job + `inv.parallel([...])` | `lab fanout` |
| Keep a value for this invocation | `state: State` | `lab worker` |
| Keep a value **across** runs | a file you own, or the runtime `StateStore` — **not** `State` | `lab counter` |
| Ask a human mid-run | `Gate(...)` in a `@workflow` — see [Workflows](workflows.md) | — |
| Pause and resume a long pipeline | `@workflow` + `--scope-id` | — |
| Expose all of it to an AI agent | the [MCP adapter](mcp.md) — no per-job work | — |

### What *not* to reach for

| Instead of… | Because |
|---|---|
| re-globbing your own `Fingerprint(sources=...)` in the body | two statements of one intent drift; use `Sources` |
| `subprocess.run` | `Shell` gives you secret redaction, streaming, retry and a `FakeShell` for tests |
| a module-level global | `State` for one invocation; a file for across runs |
| `print()` for machine output | `out.emit()` honours `--output`; `print` does not |
| `sys.exit(1)` in a guard | `Precondition` refuses with exit **3**, which a caller can tell from a crash |
| a sentinel file you check by hand | `Guards(status=...)`, which ANDs with staleness (§3, R10a) |
| `time.sleep` retry loops | `Exec(retry=...)` for the job, `sh(..., retry=...)` for one command |

---

## 2. The combination matrix

Read a row as "if my job declares this", a column as "and also this". The cell
is **the rule at that intersection** — the thing you would otherwise have to
discover.

|  | `Fingerprint` | `Deps` / `FromJob` | `Guards(status)` | `Guards(precondition)` | config class | a capability (`Log`, `Shell`, …) |
|---|---|---|---|---|---|---|
| **`Fingerprint`** | — | deps run **first**, then this job's freshness is judged | **ANDed**: status cannot mask changed sources (R10a) | precondition runs **first**; a refusal means freshness is never consulted | config **is in the key** — changing it re-runs | capabilities are **excluded** from the key |
| **`Deps` / `FromJob`** | ↑ | `FromJob` is *also* an edge — don't declare both | status is judged per-job, not per-graph | a refused dep fails the dependent | each job resolves its own config | — |
| **`Guards(status)`** | ↑ | ↑ | — | precondition is evaluated **before** status | callables receive the resolved config | — |
| **`Guards(precondition)`** | ↑ | ↑ | ↑ | — | callables receive the resolved config | — |
| **config class** | ↑ | ↑ | ↑ | ↑ | — | told apart by **position**: config annotates a *parameter*; a pydantic *return* is not config |
| **capability** | ↑ | ↑ | ↑ | ↑ | ↑ | — |

### The five rules worth memorising

**1. The guard order is fixed: platforms → preconditions → status → fingerprint.**
A refusal short-circuits everything after it.

**2. Status ANDs with staleness (R10a).** A `status` guard saying "already done"
does **not** override changed sources. `lab publish` pins this:

```
$ func builtin why lab.publish              # after touching build/report.md
lab.publish → WOULD RUN
  status  test -f build/publish.stamp ✓
  fingerprint  1 changed (build/report.md) since last run
  status satisfied, but sources changed → running (R10a)
```

Without this rule a stale stamp would freeze a pipeline permanently.

**3. Resolved config is in the fingerprint key; injected capabilities are not.**
Changing `--title` re-runs the job. Taking a `Log` does not make it re-run
forever — a live object's `repr` is not stable between processes, so it has no
business in a cache key.

```bash
func lab report --title "A"    # runs
func lab report --title "A"    # skipped — fresh
func lab report --title "B"    # runs again — different key
func lab report --title "A"    # skipped — that key was already recorded
```

**4. A pydantic *return* type is not a config class.** The framework tells them
apart by position, and `lab report` has all three in one signature:

```python
def report(
    log: Log,                                       # capability
    config: ReportConfig,                           # config class — a parameter
    parsed: Annotated[Parsed, FromJob("lab.parse")],# an upstream value
) -> Parsed:                                        # a return type, NOT config
```

**5. `FromJob` works across processes.** The upstream's value is read from its
fingerprint record when it was skipped as fresh, so a consumer does not force
its producer to re-run just to hand over a value.

---

## 3. The idiomatic matrix

Where the framework has an opinion, and what happens when you go around it.

| Concern | Idiomatic | Hand-rolled equivalent | What you lose by hand-rolling |
|---|---|---|---|
| Ordering | `Deps` / `FromJob` | calling a function | the graph — `why`, dedup, parallel scheduling |
| Passing a value downstream | `FromJob` | writing and re-reading a file | typing, and the cross-process record |
| Up-to-date checking | `Fingerprint` | mtime comparisons | `generates` checking, `why`, the state record |
| Reading declared inputs | `Sources` | `Path().rglob(...)` | the guarantee that both see the same files |
| "Already done" | `Guards(status=...)` | `if stamp.exists(): return` | the R10a AND — your check silently masks changed sources |
| "Not runnable here" | `Guards(preconditions=...)` | `sys.exit(1)` | exit **3** vs exit 1; the caller cannot tell refusal from crash |
| External commands | `Shell` | `subprocess.run` | redaction, streaming, `FakeShell` |
| Retry | `Exec(retry=...)` | a `for` loop | backoff policy, exit-code filtering, and it shows up in `why` |
| Concurrency | `inv.parallel([...])` | `ThreadPoolExecutor` | per-child `RunResult`, depth limits, scope propagation |
| Machine output | `out.emit(...)` | `print(json.dumps(...))` | `--output` honouring; `print` ignores it |
| Config | a pydantic parameter | `os.environ[...]` | the ladder (file → env → CLI), `--help` flags, `builtin env` |
| Per-invocation scratch | `State` | a module global | isolation between concurrent invocations |
| Across-run persistence | a file you own | `State` | **`State` does not persist** — see §5 |

---

## 4. Worked pipeline

The whole lab as one flow. Each arrow is a declaration, not a call.

```
inputs/*.yaml
     │  Fingerprint(sources)          read via Sources — no second glob
     ▼
  lab.parse ──────────────► Parsed        (a pydantic return type)
     │  FromJob("lab.parse")
     ▼
  lab.report ─────────────► build/report.md
     │  Deps("lab.report") + Guards(status) + Fingerprint
     ▼
  lab.publish ────────────► build/publish.stamp
```

```bash
$ func lab publish            # runs parse, then report, then publish
PARSED n=2 total=8 keys=['inputs/alpha.yaml', 'inputs/beta.yaml']
REPORT title='Composition Lab' items=2
PUBLISHED

$ func lab publish            # everything fresh; nothing re-runs
$ func builtin why lab.publish
lab.publish → SKIP (already done)
  status  test -f build/publish.stamp ✓
  fingerprint  1 sources unchanged
  deps  lab.report ✓ fresh
```

`func builtin why <job>` is the tool for every "why did/didn't this run"
question, and it reports the verdict the executor would actually reach. It
exits with that verdict too — `0` for a skip, `4` (`ExitCode.STALE`) for a job
that would run — so a script can branch on it without parsing the text.

### 4.1 The release half: a glob, a group flag, a second group, and a gate

```
  lab.publish ────────────► build/publish.stamp
     │  Deps + Fingerprint(generates=["dist/*.tar.gz"])   a pattern, not a path
     ▼
  lab.bundle ─────────────► dist/lab-0.1.0.tar.gz        + GroupOptions(--strict)
     │  Gate(awaits=Approval)                            the walk pauses here
     ▼
  check.signoff                                          a *second* group
```

```bash
$ func lab bundle             # runs: dist/*.tar.gz matches nothing yet
BUNDLED lab-0.1.0.tar.gz strict=False
$ func lab bundle             # fresh: the glob matches now
$ func --force lab --strict bundle
BUNDLED lab-0.1.0.tar.gz strict=True
```

`--force` runs a job freshness would skip. `--strict` is declared **once** on
the group and typed *mid-path* — `lab --strict bundle`, not
`lab bundle --strict`.

```bash
$ func lab release            # blocks at the gate
Blocked: gate 'approval-gate' in scope 'f81eb2d5' awaits input.
  func builtin workflow resume f81eb2d5 approval-gate --input '{…}'
  func lab release --scope-id f81eb2d5
$ echo $?
5
```

Deposit the input and re-run with that scope id and the walk finishes. Omit the
scope id and you open a **new** walk that blocks again — resuming is opt-in.

### 4.2 Two surfaces over one declaration set

The lab ships `main.py` as well, and every claim on this page is verified
against both:

```bash
func lab publish             # pre-boot dispatch, commands built from the live signature
python main.py lab publish   # a FunctualizeApp: click's tree, built from cached descriptors
```

They are two different builders, and they have disagreed — on a config field's
default, and on whether `--scope-id` existed at all, which left a gated walk on
an app entry point blocked, able to accept a deposit, and impossible to resume.
Anything that passes on one surface and fails on the other is a finding, which
is why `tests/test_composition_lab_e2e.py` is parameterised over both.

---

## 5. Traps at the intersections

Each of these is a real defect the framework shipped, or a distinction that
costs an afternoon. See
[`contributor/reference/pitfalls.md`](https://github.com/raicing-ai/functualize/blob/master/contributor/reference/pitfalls.md)
for the full list.

### 5.1 Three things are called "state"; one persists

| Name | Import | Scope | Persists? |
|---|---|---|---|
| `State` (capability) | `functualize.job` | one invocation | **no** |
| `StateStore` (scope) | internal | one `WorkflowScope` | no |
| `StateStore` (runtime) | `functualize.app.utils` | the project | **yes** — `.functualize/state.json` |

`lab fanout` pins it: two children each set `state["slot"]`, and the parent
reads `None`.

```
$ func lab fanout
WORKER slot=a state=a
WORKER slot=b state=b
FANOUT n=2 statuses=['Success', 'Success'] parent_state=None
```

### 5.2 A refusal is not a failure, and not a skip

| Outcome | Status | Exit | Meaning |
|---|---|---|---|
| ran, returned | `SUCCESS` | 0 | |
| guard said nothing to do | `SKIPPED` | 0 | a skip is success at the boundary |
| declined to start | `REFUSED` | **3** | a `Precondition` failed, or declared sources resolved to nothing |
| body raised | `FAILURE` | 1 | |
| paused at a `Gate` | `BLOCKED` | 5 | ran successfully, resumable |

`func lab gated` and `func lab verify` both exit 3 for the two different
reasons. **Do not treat exit 3 as a crash**: nothing ran.

### 5.3 Declaring nothing ≠ declaring something that matches nothing

```python
@job(cache=Fingerprint(sources=["absent/*.json"]))   # refuses — exit 3
@job()                                               # fine — nothing declared
```

`sources.declared` is how a body tells them apart. A stage that certifies
success having verified nothing is the failure this distinction prevents.

### 5.4 A missing declared output forces a run

`generates` is part of the freshness question. Delete `build/report.md` and
`lab report` runs again, even though its inputs are unchanged — it promised to
produce that file.

### 5.5 `--output` is a *global* flag

```bash
func --output json lab emit      # correct
func lab emit --output json      # Error: No such option '--output'
```

A job's **return value is programmatic** — it feeds `FromJob` and `rc.invoke()`
and never reaches stdout on its own. `out.emit()` is the explicit path, and it
is the one that honours `--output`.

### 5.6 `generates` entries are globs, not literal paths

`generates=["dist/*.whl"]` — the form the `@job` docstring itself advertises —
was tested with `(root / entry).exists()`, which is always false for a pattern.
The job reported `output missing: dist/*.whl` forever and rebuilt on every
invocation. It degrades to "always rebuild", never to an error, so the only
symptom is a cache that quietly stops working. Both `sources` and `generates`
are expanded the same way now, and a pattern matching **nothing** is a missing
output that forces a run.

### 5.7 A dependency is not a precondition

```python
@job(group="check", deps=Deps("lab.bundle"))          # correct
def signoff(...): ...
```

Adding `Guards(preconditions=[Precondition(_archive_exists)])` on top reads
like a safety net and is not one: `Deps` has already produced the archive by
the time guards are evaluated, so the guard can never fire. Guard the *world*
— things outside the graph that may not be fit to run in. Let `Deps` guard the
graph.

### 5.8 A mid-path flag does not cross into a walk

`--strict` reaches `lab bundle` when you run it, and does not when the walk
runs it:

```bash
$ func --force lab --strict bundle    # bundle is what you launched
BUNDLED lab-0.1.0.tar.gz strict=True
$ func lab --strict release           # bundle is a *step* of the walk
BUNDLED lab-0.1.0.tar.gz strict=False
```

The flag layer belongs to the command line that typed it, and is not inherited
by jobs the run reaches afterwards — `@workflow` steps, `Deps` upstreams and
`rc.invoke` children alike. This is deliberate: a value typed at `lab` silently
steering a job under another group is the failure it prevents.

Every **other** layer does reach them, because each job resolves them for
itself. To steer a whole walk, set one of those instead:

```bash
$ LAB__STRICT=true func lab release   # every step sees strict=True
BUNDLED lab-0.1.0.tar.gz strict=True
```

Note the **double** underscore: a group option is `GROUP__FIELD`, prefixed by
the group it is declared on, while a job's own config field is `JOB_FIELD`.
[Group Options](group-options.md) covers the rule and the same move from
Python.

---

## See Also

- [Task Runner](task-runner.md) — `@job`, `Deps`, `Fingerprint`, `Guards`, `Exec` in depth
- [Shell Capability](shell.md) — `Shell`, redaction, `FakeShell`
- [Workflows](workflows.md) — `@workflow`, `Gate`, branching, `--scope-id`
- [JobConfig with Pydantic](job-config.md) — the config ladder and `JOB_FIELD`
- [Group Options](group-options.md) — flags shared by every job under a group
- [AI Capability](ai.md) and [MCP Adapter](mcp.md) — exposing this to agents
- [RunContext Lifecycle](run-context.md) — the capability facade
