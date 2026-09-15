# Freshness Lab — a job that caches its own artifact

The framework decides whether your declared inputs changed. It does **not**
decide what to do about it: only your job knows the artifact's format, where it
lives, how long it stays valid, and whether a rebuild is worth avoiding. So the
framework hands over the verdict, and the job decides.

This lab is that shape, in two declarations and about thirty lines of body.

```
freshness_lab/
├── inputs/
│   ├── alpha.md         # declared as `sources` — the inputs are not the point
│   └── beta.md
├── jobs/
│   └── self_caching_job.py
│       ├── report       # Fingerprint(decides=True) — owns its artifact
│       └── baseline     # the same work, no opt-in — the framework skips it
└── pyproject.toml
```

Run everything from this directory. `build/` is written by the jobs and can be
deleted at any time.

## 1. Run it

```console
$ func lab report
rebuilt build/report.json from 2 declared inputs
BUILT built=836e97a7 state=run
```

The body entered with `state=run`: the pre-flight found no record of these
inputs, so the job was not fresh and did real work.
`build/report.json` is the artifact — the job chose the path, the name and the
format:

```json
{
  "built": "836e97a7",
  "inputs": {"inputs/alpha.md": 11, "inputs/beta.md": 16},
  "total": 27
}
```

## 2. Run it again — and watch the body run anyway

```console
$ func lab report
up to date under lab.report::fa723457…::checksum — returning the artifact
CACHED built=836e97a7 state=skip_fresh
```

Two things happened, and the second is the feature:

1. The engine's pre-flight said **`SKIP_FRESH`**. Without an opt-in that is the
   end of the run — the body never executes.
2. `Fingerprint(decides=True)` says *"when I am fresh, enter my body and let me
   decide"*. So the body ran, read `fresh.verdict()`, saw `is_fresh`, and handed
   back the artifact it had already built. Same `built` token as step 1: nothing
   was rebuilt.

The declaration is the whole opt-in:

```python
@job(
    cache=Fingerprint(
        sources=["inputs/*.md"],
        generates=["build/report.json"],
        decides=True,          # ← when I am fresh, run me anyway
    ),
)
def report(fresh: Freshness, sources: Sources, log: Log) -> None:
    verdict = fresh.verdict()
    if verdict is not None and verdict.is_fresh:
        …return the artifact…
```

A job that does not opt in is skipped in silence — that is `lab baseline`
below, and it is what every job does today.

## 3. The verdict is the engine's, not a recomputation

```console
$ func builtin why lab.report
lab.report → SKIP (up to date)
  fingerprint  2 sources unchanged
```

`why` renders the guard pipeline's `GuardState`; the job reads the same state
off `fresh.verdict()`. A person and their job cannot disagree about a run,
because both are reading one decision — the one the pre-flight made.
`tests/test_self_caching_job.py::TestTheVerdictAndWhyAgree` pins that.

## 4. Declared outputs are checked for *presence*, never read

Delete the artifact and the next run rebuilds:

```console
$ rm build/report.json && func lab report
rebuilt build/report.json from 2 declared inputs
BUILT built=f916850a state=run
```

Change its *contents* by hand, though, and the job is still fresh:

```console
$ printf '{"built": "hand-edited", "inputs": {}, "total": 0}' > build/report.json
$ func lab report
up to date under lab.report::fa723457…::checksum — returning the artifact
CACHED built=hand-edited state=skip_fresh
```

That is the boundary in one command. The framework knows the path only because
the job declared it under `generates`, and all it asks is "is it there?" — the
bytes are the job's business. A framework-owned artifact store could not be
tested this way, because it would have to read the artifact to decide whether it
was valid.

## 5. The control: no opt-in, no body

`lab baseline` is the same work, same declaration, without `decides`:

```console
$ func lab baseline
rebuilt build/baseline.json from 2 declared inputs
BUILT-BASELINE built=39511a8a

$ func lab baseline
$ echo $?
0
```

The second run printed nothing at all: `SKIP_FRESH` ended the run before the
body. Exit code 0 either way — a skip is a success, and `decides=True` is not a
way to ask for one, only a way for the job to decide.

## What this is not

- **Not a cache.** The framework stores no artifact, addresses nothing by
  content, and evicts nothing. The verdict is the contract; the storage is yours
  (`contributor/architecture/run-model/11-boundaries.md` §B, **N1**).
- **Not an obligation to skip.** Reading a fresh verdict does not require you to
  return early. A job that is fresh and cheap can do the work anyway.
- **Not a way to report `SKIP`.** The distinction between *"the framework
  skipped me"* and *"I ran and decided nothing needed doing"* stays honest in
  the run history.
- **Not a change to anything else.** `decides=True` affects `SKIP_FRESH` only,
  exactly as `force_fresh` does. A failing `Precondition` still refuses (exit
  3), a blocking gate still blocks (exit 5) — being fresh your own way is not a
  reason to run somewhere the job does not belong.

## Tests

```bash
uv run pytest examples/standalone/freshness_lab/ -v
```

Seven tests drive the real `func` CLI in an isolated copy of this directory:
the cold build, the fresh run that returns the artifact, the deleted-input and
changed-input rebuilds, the hand-edited artifact that stays fresh, the control
job whose body never runs, and the `why`/verdict agreement.
