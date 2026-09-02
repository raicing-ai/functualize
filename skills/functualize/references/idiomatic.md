# Idiomatic functualize — intent → mechanism

Feature lists are alphabetical. This is indexed by **what you are trying to
do**, and it names the **combinations**, because almost every real job is two
or three declarations composed and the composition is where the mistakes live.

Find your intent in §1. Read the combination in §2. Check §3 for the trap.
Branch on §4. If a row here disagrees with the installed framework, **the
framework is right** — verify with §5.

---

## 1. Intent → mechanism

| I want to… | Reach for | Not |
| --- | --- | --- |
| Run a function from the CLI | a plain function in a discovered module | `@job` — the decorator declares, it does not register |
| Group commands (`func infra deploy`) | `JOB_GROUP = "infra"` module variable | nested packages, a registry call |
| Take typed, layered settings | a `pydantic.BaseModel` parameter | `os.environ`, `argparse` |
| Take one CLI flag | `Annotated[str, Option("--flag")]` or `Arg()` | a config model with one field |
| Accept piped stdin | `Annotated[str, Stdin(flag="--data")]` | reading `sys.stdin` yourself |
| Share flags across a group | a `GroupOptions` subclass | repeating the field in every config model |
| Print for humans **and** machines | `Stdout` → `out.emit()` | `print()`, or returning a value |
| Log progress | `Log` | `print()`, `logging.getLogger` |
| Run a subprocess | `Shell` | `subprocess.run` |
| Call another job | `Invoke` | importing and calling the function |
| **Use another job's return value** | `Annotated[T, FromJob("group.job")]` | `Invoke` then reading `.value` |
| Order two jobs without passing a value | `Deps("group.job")` | an `Invoke` at the top of the body |
| Skip work when inputs are unchanged | `Fingerprint(sources=…, generates=…)` | hand-rolled mtime checks |
| Refuse to run when the world is wrong | `Guards(preconditions=[Precondition(...)])` | an `if` + `sys.exit(1)` |
| Skip when the work is already done | `Guards(status=[...])` | a sentinel file you check yourself |
| Retry a flaky step | `Exec(retry=Retry(attempts=N))` | a `for` loop with `sleep` |
| Restrict a job to some platforms | `Exec(platforms=[...])` | `if sys.platform` |
| Run several *different* jobs concurrently | `Invoke.parallel([...])` | `threading`, `asyncio` |
| Fan out the same work over N inputs | a driver job + `Invoke.parallel` — see **C3** | `@job(matrix=…)` — see §3.5 |
| Pause for a human or an AI | `Gate(name=…, awaits=Model, strategy=…)` | `input()`, "check this file" |
| Branch on a runtime value | `ConditionalEdge` | an `if` that calls different jobs |
| Compose a multi-step walk | `@workflow(steps=[...], edges=[...])` | a "runner" job invoking in sequence |
| Keep a value for this invocation | `State` | a module global |
| Keep a value **across runs** | a file you own — **not `State`** | `State`, which is in-memory |
| Require a real terminal | `TTY` | checking `sys.stdin.isatty()` |
| Render a live region | `Live` | `rich` directly |
| Ask for a missing value | `Prompt` | `input()` |
| Test a job | `functualize.testing` fakes | constructing capabilities by hand |

Declarations come from `functualize.job`; graph pieces (`Step`, `Edge`, `Gate`,
`ConditionalEdge`, `Tool`, `FromStep`, `END`, `workflow`) from
`functualize.workflow`.

---

## 2. The combinations that carry real work

### C1. Declared inputs + typed handoff — the spine of a pipeline

```python
from typing import Annotated
from functualize.job import job, Log, Fingerprint, FromJob

JOB_GROUP = "audit"

@job(cache=Fingerprint(sources=["src/**/*.yaml"], generates=["out/parsed.json"]))
def parse(log: Log) -> Parsed: ...

@job(cache=Fingerprint(sources=["out/parsed.json"], generates=["out/checked.json"]))
def check(log: Log, parsed: Annotated[Parsed, FromJob("audit.parse")]) -> Findings: ...
```

`FromJob` does three things at once, which is why it beats `Invoke` here: it
**declares the dependency edge**, **injects the upstream's return value** typed,
and — with `FromJob("…", run=False)` — lets you consume a recorded value without
re-running the producer.

**Reach for `Invoke` instead** when you need the result *envelope* (status,
exception, metadata) rather than the value, or when the job name is computed at
runtime.

### C2. `Fingerprint` + `Guards` — skip vs refuse

They answer different questions, and the engine evaluates them in a fixed order
(`platforms → preconditions → status → fingerprint`):

| | Question | Outcome |
| --- | --- | --- |
| `Exec(platforms=…)` | "does this apply on this OS?" | skip, neutral — invisible |
| `Guards(preconditions=…)` | "is the world fit to run in?" | **fail the run** — a human must act |
| `Guards(status=…)` | "has this already been done?" | skip, satisfied — exit 0 |
| `Fingerprint` | "have the inputs changed?" | skip, fresh — exit 0 |

A truthy `status` guard **ANDs with** file staleness rather than overriding it: a
status check saying "already done" must not mask sources that changed. (With
`method="none"` or no declared sources there is nothing to be stale about, so a
satisfied status guard skips on its own.)

**The heuristic that matters.** If the guard failing means *you should not trust
a clean result*, it is a `precondition`. If it means *there is genuinely nothing
to do*, it is `status`. Getting this backwards produces a check stage that exits
0 having verified nothing:

```python
# ✗ Exits 0, silently, having checked nothing.
@job(guards=Guards(status=[lambda: Path("AUDIT.md").exists()]))
def signoff() -> Verdicts: ...

# ✓ "The thing I verify must exist" is a precondition.
@job(guards=Guards(preconditions=[
    Precondition("test -f out/AUDIT.md", msg="run `audit report` first"),
]))
def signoff() -> Verdicts: ...
```

### C3. Fan out over N inputs

There is no matrix expansion in the engine (§3.5), so write a driver job that
invokes a worker per slice:

```python
@job
def check_all(log: Log, invoke: Invoke) -> None:
    kinds = ("hardcode", "diff", "dirdiff")
    results = invoke.parallel([("audit.check", {"kind": k}) for k in kinds])
    for kind, r in zip(kinds, results):
        if r.status is not RunStatus.SUCCESS:
            log.error(f"{kind} failed")

@job
def check(log: Log, kind: str) -> None: ...
```

`Invoke.parallel` takes `(job, kwargs)` pairs, accepts 1–32 of them, and returns
`JobResult`s **in input order**, so the `zip` is safe. Drop `.parallel` for a
plain loop when the slices must run in sequence.

What you do **not** get is per-slice *inputs*: `Fingerprint.sources` and
`generates` are literal glob strings on the declaration with no interpolation, so
every slice evaluates the same source set and they go stale together.
Independent staleness per slice needs N separately-declared jobs.

### C4. `@workflow` + `Gate` — a walk that pauses and resumes

```python
from functualize.workflow import workflow, Step, Edge, Gate, END

@workflow(
    steps=[Step(parse), Step(check),
           Gate(name="commentary", awaits=Commentary, strategy="ai_outbound"),
           Step(report)],
    edges=[Edge("parse", "check"), Edge("check", "commentary"),
           Edge("commentary", "report"), Edge("report", END)],
)
def audit_run(log: Log) -> str: ...
```

A gate that cannot resolve exits **5 (blocked)**, not 1 — a pause is resumable
and a failure never finished. The blocked run prints the resume commands; see
[workflows.md](workflows.md).

**Use `@workflow` when** the shape is a graph with pauses or branches. **Use
`Deps` + `FromJob` when** it is a straight dependency chain — a workflow adds a
scope and a topology you then have to maintain.

### C5. `Gate(tools=[Tool(...)])` + `FromStep` — bounded AI handoff

`Tool(job, **bound)` narrows what a gate may call and fixes some of its
arguments; `FromStep("step")` binds a tool argument to an earlier step's
recorded result. Together they let an agent act at a pause without handing it
the whole job registry.

---

## 3. Traps

### 3.1 Returning a value does not print it
The return value is for `FromJob` consumers, not the terminal. Use
`out.emit(...)`. This is the one every newcomer hits.

### 3.2 A capability is a *parameter*, never a constructor
`def deploy(log: Log)` — the engine injects by type. Never `Log()`.

### 3.3 `State` does not persist
It is per-invocation and in memory. See
[capabilities.md](capabilities.md#state--per-invocation-and-the-name-misleads)
for the three things called "state" and which one survives.

### 3.4 A `generates` entry is a glob pattern
`generates=["dist/*.whl"]` means "a wheel whose version I do not know". Both
`sources` and `generates` are patterns, not literal paths.

### 3.5 `@job(matrix=…)` is accepted and does nothing
The kwarg is still on the decorator and still shape-validated, and **no code
reads it**. A job written with `matrix=` runs exactly once with its slice
parameter unbound — you get neither an error nor the behaviour. Use **C3**.

### 3.6 A failed precondition currently exits 1
The distinction between "refused" and "raised" is real in the engine
(`GuardState.ERROR` vs an exception) but does not reach the process: both map to
`RunStatus.FAILURE` and exit **1**. Do not write CI that greps for exit 3 to
detect a refusal — see §4 for what each code actually means today.

### 3.7 `func` is often not on PATH
Establish the invocation prefix before anything else — the main skill's §0.

---

## 4. Exit codes are the contract

Branch on these, not on prose:

| Code | Means | Produced by |
| --- | --- | --- |
| 0 | success, **or a skip** | a job that ran, or one skipped fresh/satisfied/neutral |
| 1 | the job raised, timed out, was cancelled — **or a precondition failed** | see §3.6 |
| 2 | usage or config error | bad flags, unparseable config |
| 3 | refused pre-flight | today, only a job declaring `tty: TTY` invoked without a terminal |
| 4 | reserved for stale-check | **not produced by any current command** |
| 5 | blocked at a gate — resumable, *not* a failure | a `Gate` whose input is unresolved |

`0` covering skips is deliberate: `func build && func deploy` must not stop
because `build` was already up to date.

**5 is the one worth special-casing.** It means someone needs to supply input
and the run can continue afterwards.

---

## 5. Verify, do not assume

The framework answers these itself. Prefer asking it over trusting any
document, this one included.

| Question | Command |
| --- | --- |
| What commands exist, and what does each take? | `func builtin info schema` — jobs *and* builtins, one call; `--kind job` to narrow |
| What jobs exist? | `func builtin info` |
| Would this job run, and why? | `func builtin why <job>` |
| What ran recently? | `func builtin history` |
| What is the resolved config? | `func builtin config show` |
| Where does runtime state live? | `func builtin state show` |
| What does this job take? | `func <group> <job> --help` |

Two habits worth more than any table here:

**Run a pipeline twice before believing it.** Cold and warm are different
programs — the second builds commands from a discovery cache and may never
import your file. `func builtin cache clear` forces the cold path.

**Do not parse prose.** Use exit codes, and `--output json` where a job emits.

---

## 6. Shape → starting point

For choosing an architecture rather than a feature.

| If the work is… | Start from | Key combination |
| --- | --- | --- |
| One command, some flags | a function + `Option`/`Arg` | — |
| One command, many settings | a function + a config model | config precedence |
| A chain: A produces, B consumes | two jobs | **C1** |
| A chain that should skip when unchanged | two jobs + `Fingerprint` | **C1 + C2** |
| The same work over N inputs | a driver + `Invoke.parallel` | **C3** |
| Independent work, wall-clock bound | `Invoke.parallel` | — |
| A pipeline a human inspects midway | `@workflow` + `Gate` | **C4** |
| A pipeline an agent acts inside | `@workflow` + `Gate(tools=…)` | **C4 + C5** |
| Work that must not run in a bad state | any of the above + `Guards` | **C2** |
