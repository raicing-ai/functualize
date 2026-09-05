# Plan — Discovery and gate defects

## 1. Reproductions (run against `a2f453d` before planning)

```python
from functualize.app import FunctualizeApp, JobSources, ConfigSources, PluginSources
from functualize._config import ResolutionChain
from functualize.job import job

@job
def alpha(x: int = 1) -> None:
    """Alpha."""

def explicit(**kw):
    base = dict(
        job_sources=JobSources(directories=[], functions=[alpha], lazy=False),
        config_sources=ConfigSources(config_resolution_chain=ResolutionChain([])),
        plugin_sources=PluginSources(entry_point_group="", explicit_plugins=[]),
    )
    base.update(kw)
    return FunctualizeApp("a", **base)
```

| Case | Result |
|---|---|
| fully explicit → `boot_static` | `['alpha']` |
| `JobSources(functions=[alpha])` alone | `[]` — **silent** (B2) |
| `JobSources(job_providers=[StaticProvider([alpha])])` | `[]` — **silent** (B1) |
| `register_dynamic_job(app, "beta", alpha)` | `parameters: []`, `declaration: True` (B3) |
| the same `alpha` discovered from a directory | `parameters: ['x']` |
| `Gate(strategy="ai_inbound")`, nothing installed | `ValueError: Unregistered gate strategy 'ai_inbound' referenced during resolution of gate 'triage'` (B4) |
| `Gate(strategy="ai_inbound")`, resolver registered but raising | `BLOCKED` — the intended behaviour |
| module raising on import | stderr warning, `[]` jobs, nothing retained (B5) |

## 2. Code sites

| Defect | File:line | What is there now |
|---|---|---|
| B1 | `app/config.py:48`, `:56` | field + docstring line; `grep -rn "job_providers" src/` = **2 hits, both here** |
| B2 | `_app/boot.py:242` | `if app._job_sources.functions:` inside `boot_static` (starts `:112`); `boot_standard` starts `:327` and has no equivalent |
| B3 | `_app/impl.py:732` | `parameters=[]` — 1 hit in the file |
| B4 | `_engine/workflow_walker.py:278` | `except GateResolutionError:` — 1 hit; `_gate/_registry.py` raises bare `ValueError` for an unregistered name, outside the per-strategy `try` |
| B5 | the directory-scan import path in `_discovery/providers.py` | logs and continues |
| B6 | `docs/guides/ai.md` "Gate Strategies" | lists presets without the `Gate` constraint |

## 3. The one decision needed before Wave 1

**B1 — wire `job_providers`, or delete it?**

Deleting is smaller and loses nothing today: `add_job_provider()` already
covers the case from inside a plugin's `__call__(app)`, which is the path an
external host actually uses. Wiring it means honouring the
`(provider, [transforms])` tuple form the docstring promises, on both boot
paths, with tests for each.

Recommendation: **delete**, and note `add_job_provider` in the removal commit.
The field has never worked, so nothing can depend on it, and the pre-release
stance permits the removal.

Task 1.1 is written so either answer is executable; it must not start until
the maintainer has answered.

## 4. Approach per defect

**B2.** Move the `functions` → `StaticProvider` step out of `boot_static` into
a helper both boot paths call. `boot_standard` builds its pipeline later, so
the provider is appended at the same point relative to directory providers,
which keeps `StaticProvider`'s bare-name keying (probe 11's collision finding)
unchanged in ordering terms.

Refusal is the fallback if wiring proves to reorder discovery: raise from
`JobSources.__post_init__`? No — `JobSources` cannot see the other two source
objects. It must be raised at construction of `FunctualizeApp`, where
`is_fully_explicit()` is already called. Prefer wiring; refuse only if wiring
changes an existing test's expected order.

**B3.** `_app/impl.py:732` replaces `parameters=[]` with the same extraction
the providers use. `extract_parameters_from_signature` lives in
`_discovery/providers.py:64` and already skips `self`/`cls`. `_app` may import
`_discovery` (composition root), so no layer violation. Import it beside the
`extract_capability_markers` / `extract_ext_metadata` imports already at
`:720`.

**B4.** Two candidate fixes:

1. Widen the walker's `except GateResolutionError` to include `ValueError`.
   Smallest, but swallows unrelated `ValueError`s from a resolver.
2. Have `GateRegistry.resolve_gate` treat an unregistered name as a *failed
   strategy* — record it and `continue` — when the strategy list has more than
   one entry, keeping the hard raise when a single explicit strategy was named.

Prefer **2**: it keeps a typo in `gate_strategy="ai_inbund"` loud, and makes
the ladder behave like a ladder. `GateResolutionError` then carries the
unregistered names in `last_error`, which is what fills `blocked_reason`.

The strategy→plugin table (`contracts.md` §2) lives in `_gate/_strategy.py`
next to the enum. Core naming a plugin in a message is not an import.

**B5.** Retain failures where they occur rather than re-deriving them: the
scan already catches and logs, so it appends to a list on the provider, which
the app exposes for the builtin surface to read. Lazy/cached discovery must
not report a stale failure — a cached run that imported nothing has no
failures to report, so the list is only populated on a real scan, and the
report says which.

**B6.** Documentation only, no code. `docs/` is ungated by the spec hook.

## 5. Risks

| Risk | Mitigation |
|---|---|
| B2's wiring changes job ordering, breaking a name-collision expectation | probe: `StaticProvider` keys by bare name and a duplicate loses *every* job. Add the ordering assertion to the same test that covers B2 |
| B4 option 2 makes a genuine typo silent when it appears inside a preset | the preset path already raises a *distinct* message naming the preset; keep that branch raising |
| B5's list grows unbounded in a long-lived app | discovery runs once per boot; the list is per-scan, not per-invocation |
| B1 deletion breaks an out-of-tree caller | the field is read by nothing, so a caller passing it gets no behaviour today; removal turns silence into `TypeError`, which is the improvement |

## 6. Files to change

```
src/functualize/app/config.py                 B1
src/functualize/_app/boot.py                  B2
src/functualize/_app/impl.py                  B3
src/functualize/_gate/_registry.py            B4
src/functualize/_gate/_strategy.py            B4 (strategy→plugin table)
src/functualize/_engine/workflow_walker.py    B4 (blocked_reason)
src/functualize/_discovery/providers.py       B5
src/functualize/_cli/info.py                  B5 (report payload)
docs/guides/ai.md                             B6
tests/…                                       one test per defect
```

Note `src/functualize/**` is gated by the spec hook — `tasks.md` must exist
with a parseable dependency graph before any of these are written. It does.
