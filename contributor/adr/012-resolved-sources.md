# ADR-012: A job reads its resolved inputs through a `Sources` capability

**Status**: accepted
**Date**: 2026-08-30
**Deciders**: Hakim (decision D1 during Specify), agent

> Filed as 012, not 010 as `.spec/features/pipeline-readiness/plan.md` says:
> 010 was already taken twice (`010-discovery-cache-filter-awareness`,
> `010-spec-workflow-enforcement-point`) and 011 once.

## Context

A job declares the files it depends on:

```python
@job(cache=Fingerprint(sources=["src/**/*.yaml"], generates=["findings/parsed.json"]))
def parse(log: Log) -> Parsed: ...
```

The pre-flight expands that glob and builds a source map —
`{project-relative path: {mtime, size, sha256}}` — on **every run**, uses it to
decide freshness, and then discards it. The job body, which is about to read
exactly those files, has no way to reach it. So every job re-implements the
glob its own `Fingerprint` just ran:

```python
files = {p.as_posix(): p.read_text() for p in sorted(Path("src").rglob("*.yaml"))}
```

Two statements of one intent, in one declaration, that can drift silently: the
freshness check certifies one set of files and the body reads another. Neither
`expand_sources` nor `build_source_map` is re-exported from any public folder,
so there was not even an unsupported way to ask.

The per-input record is also most of the per-artifact provenance the artifacts
proposal (R4) says the framework does not have — it is computed and thrown
away.

## Decision

Expose it as a **DI-injected capability**, `Sources`, alongside `Log`,
`Invoke`, `Prompt`, `Perf` and `State`:

```python
@job(cache=Fingerprint(sources=["src/**/*.yaml"], generates=["findings/parsed.json"]))
def parse(log: Log, sources: Sources) -> Parsed:
    files = {path: Path(path).read_text() for path in sources.keys()}
```

`Sources` answers three questions that are genuinely different:

| Declaration | `declared` | `items()` |
|---|---|---|
| `Fingerprint(sources=["src/*.yaml"])`, files present | `True` | populated |
| `Fingerprint(sources=["absent/*.yaml"])`, nothing matches | `True` | **empty** |
| no `Fingerprint`, or one with no `sources` | `False` | empty |

The middle row is not a curiosity — it is the same distinction the R3 refusal
needs, and it is why `declared` exists rather than letting an empty mapping
stand for both. **One mechanism, not two**: the pre-flight computes the
distinction once, and both the refusal and this capability read it.

`generates` is exposed on the same object, since the declaration is one thing.

## Consequences

### Positive

- The glob is stated once. The freshness check and the body cannot disagree
  about which files the job is about.
- The per-input `{mtime, size, sha256}` record becomes reachable — provenance
  the framework already computes.
- Pure plumbing: the pre-flight already builds this on every run. Nothing new
  is computed and no run gets slower.

### Negative

- New public API, and public API is forever.
- **An ordering hazard.** DI resolves *before* the pre-flight runs, so the data
  does not exist at injection time. The capability is injected as an empty
  object and populated from the `PreflightDecision` before the body is called.
  That is exactly the shape `contributor/guides/wiring-discipline.md` was
  written for — a capability that resolves and does nothing — so the wiring
  carries a sabotage check on **both** the cold and warm paths, and the
  acceptance gate asserts the behavior rather than the attribute's existence.

### Neutral

- `Sources` is a capability parameter, so the fingerprint-key rule that
  excludes injected parameters excludes it automatically. A job's own resolved
  inputs must never enter its own fingerprint key, and they do not.

## Alternatives Considered

| Alternative | Pros | Cons | Why rejected |
|---|---|---|---|
| **`Sources` capability** (chosen) | Consistent with every other injected capability; opt-in per job, so a job that does not ask pays nothing; a plain parameter is trivially faked in a test | New public type | — |
| `RunContext.sources` property | No new type; `RunContext` is already injected | `RunContext` is the general-purpose bag; adding fingerprint internals to it makes every job carry the concept. A property is also harder to substitute in a test than a parameter | Rejected |
| Re-export `expand_sources` / `build_source_map` as public helpers | Smallest diff | Hands the author the *glob machinery* and asks them to re-run it — which is the duplication being removed. The point is that the job reads what the framework **already resolved**, not that it can resolve the same thing again | Rejected |

### A note on the acceptance gate

Criterion A5 originally asserted
`any(hasattr(RunContext, a) for a in ("sources", "source_map", "fingerprint"))`.

That is worth recording, because the gate was quietly deciding this ADR:

- A `RunContext` property returning `{}` **passes** it, while giving an author
  nothing.
- The `Sources` capability — presented by the defect report as an equally valid
  shape — **fails** it.

So the criterion would have rejected the design chosen here for a reason that
has nothing to do with whether a job can read its inputs. It was rewritten to
assert the behavior in the table above. The fixture pipeline
(`pipeline-readiness/acceptance/code_audit/`) was not touched.
