# Spec: A job can take a Path, a UUID, or a date

Found while landing the Subjects guide, whose example carried the note "a bare
`Path` parameter fails at boot — take `str` and convert". Measured against
`78d9ff4`, that undersells it by a lot.

## Problem

```python
from pathlib import Path

def backup(to: Path) -> None:
    """Back up to a directory."""
```

A job that takes a directory — close to the most ordinary thing a task runner
is asked to do.

```
$ func backup --to /tmp/x
Error: Job 'backup' could not be loaded: DI validation failed with 1 error(s):
  1. No provider for Path (job: '<unknown>', available: [])
```

**Everything except builtins is assumed to be a dependency to inject.**
`validate_di_bindings` (`_engine/executor.py`) skips builtins, the framework's
injected capabilities, Pydantic models, `Optional[...]` and `FromJob`, and
demands a registered provider for everything else. `pathlib.Path` is not a
builtin, so it is "everything else". Same for `UUID`, `date`, `Decimal`, and
any `Enum` subclass.

**The explicit escape hatch does not work either.** Writing the marker that
says *this is a command-line option* changes nothing:

```python
def with_marker(p: Annotated[Path, Option(help="a path")]) -> None: ...
->  No provider for Path
```

**One such job takes down the whole CLI on a cold boot** — not just that job,
and as an unhandled traceback rather than an error message:

```
each row is a fresh cold boot:
func fine (an unrelated healthy job)  -> FAILED   DIValidationError traceback
func builtin info                     -> FAILED   <- the diagnostic command
func strpath --to /tmp/x  (a str job) -> FAILED
func --help                           -> ok
```

It is masked on a warm boot — cached jobs register as lazy proxies and the
validation skips proxies — so it presents as intermittent: it appears after a
cache clear, on a fresh clone, in CI.

**The rest of the stack is already correct**, which is what makes this narrow:

| Stage | State |
|---|---|
| parameter extraction | already publishes `Path`/`UUID`/`date`/`Decimal`/`Enum` as CLI parameters **[probed]** |
| runtime resolution (`build_resolution_plan`) | already classifies them `"skip"`, never injected **[probed]** |
| click type resolution (`_resolve_type`) | knows `Path`; `UUID`/`date`/`Decimal` fall back to `str` |
| **boot-time DI validation** | **demands a provider — the defect** |

So a `Path` parameter is simultaneously a published CLI parameter and a
required dependency, and only the boot gate objects.

Nothing in the docs advertises these parameter types, and nothing warns against
them. No example in the repo takes one.

## Behavior

### A fixed set of standard-library value types are parameters, not dependencies

`Path`, `UUID`, `date`, `datetime`, `time`, `timedelta`, `Decimal`, and any
`Enum` subclass, alongside the builtins already excluded. One list, in
`_primitives/`, beside the existing one-list-for-injected-capability-names —
the same reason applies: every layer that classifies a signature must agree,
and the copies drift.

### An explicit marker wins over the type

A parameter carrying `Arg(...)`, `Option(...)` or `Stdin(...)` is a CLI
parameter whatever its annotation. The author has stated the intent; the
framework should not overrule it. This is what makes the list a convenience
rather than a ceiling.

### A genuine dependency still fails, and still fails early

`def deploy(db: Database)` with no provider registered is unchanged: it is an
error, reported at boot rather than at first use.

### An unsatisfiable job fails alone

**This is a deliberate departure from `CONSTITUTION.md` "Boot & Config", which
says DI failures are loud at boot. Approved explicitly by the maintainer.** The
loudness is kept; the blast radius is not:

- the job is not registered, and is reported the way a module that failed to
  import is reported — in `discovery_failures`;
- every other job still works;
- `builtin info` and `builtin self doctor` still work, which is the point:
  under the old behaviour the two commands an operator would use to find out
  what was wrong were the two the fault took down;
- invoking the affected job by name gives a clean error naming the job, the
  parameter and the fix — not a traceback.

### Conversion

A published parameter is converted to its annotated type before the job sees
it: `--to /tmp/x` arrives as `Path("/tmp/x")`, not `"/tmp/x"`. `Path` already
converts; `UUID`, `date`, `datetime` and `Decimal` are added. An unparseable
value is a usage error naming the parameter, not a traceback.

## Acceptance criteria

| # | Criterion | Authoring-time state |
|---|---|---|
| A1 | `def backup(to: Path)` runs, and receives a `Path` | boot fails for the whole CLI |
| A2 | Same for `UUID`, `date`, `datetime`, `Decimal`, and an `Enum` subclass | all fail identically |
| A2b | **Corrected during execution.** An `Enum` parameter runs and is validated against its members, but arrives as the member's `str` **value**, not the member. Pre-existing — `_click_type_for` renders `click.Choice` of values and nothing converts back — and out of scope to change here, because a job comparing against strings today would break. Recorded in STATUS rather than claimed | — |
| A3 | `Annotated[SomeClass, Option(...)]` is a CLI parameter whatever the type | fails |
| A4 | A job with a genuinely unregistered dependency is still an error | holds; must keep holding |
| A5 | That error no longer takes down unrelated jobs | takes down every command |
| A6 | `builtin info` and `builtin self doctor` work with such a job present | both fail |
| A7 | The affected job is reported in `discovery_failures` | nothing reported |
| A8 | Invoking the affected job gives a message naming the job and parameter, not a traceback | unhandled traceback |
| A9 | The message names the parameter, not just the type — `'<unknown>'` is gone | `job: '<unknown>'` |
| A10 | A malformed value (`--when notadate`) is a usage error, not a traceback | n/a |
| A11 | Warm and cold boot agree **on what a caller observes**: invoking an unsatisfiable job explains itself on both. The boot-time *report* appears only on a cold boot, because a warm boot registers lazy proxies and validating them would mean importing every module — the cost lazy boot exists to avoid. Narrowed during execution from "agree", which was not achievable without either always importing or never reporting | cold raised for the whole app, warm passed silently |
| A12 | `func --help` still works (it already did) | holds |
| A13 | Full gates green | — |

## Out of scope

- **Arbitrary user types as CLI parameters.** A type not on the list and not
  explicitly marked stays a dependency. Inverting that default would turn a
  forgotten provider into a silent CLI flag.
- **Container types** (`list[Path]`, `dict[...]`). `list[str]` and friends
  already work; widening the element type is a separate question.
- **Making DI failures non-fatal in library mode.** A host constructing
  `FunctualizeApp` directly still gets the error at construction; what changes
  is that it names one job and does not abort the others' registration.
