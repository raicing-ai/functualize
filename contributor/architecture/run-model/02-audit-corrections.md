# 02 · Audit corrections — what survived three releases, and what moved

The entrypoint audits were verified against `origin/master` @ `c0c921f`. Master is now
`e57f0c9`: three PRs later (#34 scope durability, #35 workflow continuation, #36 CI), and
one minor release (0.3.0). An audit whose citations no longer resolve is a liability, so
every claim was re-run before this set carried it.

The full claim-by-claim table is in [evidence/drift-2026-09-09.md](evidence/drift-2026-09-09.md).
This document holds the four things that *changed the argument*.

---

## A. The headline: the audit held

Of 17 re-verified claims, **15 STILL HOLD, 2 DRIFTED, 0 became FALSE.**

The reason is worth stating because it is not luck. Every core file the audits cite is
**byte-identical** between `c0c921f` and `e57f0c9`:

```
SAME  src/functualize/_engine/executor.py
SAME  src/functualize/app/core.py
SAME  src/functualize/_app/boot.py
SAME  src/functualize/_app/impl.py
SAME  src/functualize/_engine/capabilities/runcontext.py
SAME  src/functualize/_engine/capabilities/stdout.py
SAME  src/functualize/_types/exit_codes.py
SAME  src/functualize/_types/http_status.py
SAME  src/functualize/_config/chain.py
SAME  src/functualize/_cli/tui/job_execution.py
SAME  src/functualize/_discovery/cached_provider.py
```

PR #35 was **+9,418 / −1,294 and almost entirely additive** — six new modules, a large
`_cli/builtins.py` expansion, and a rewritten MCP plugin. It did not touch a single
structure either audit flagged. That is itself the finding: a whole release passed through
this codebase without going anywhere near the entry boundary, because there is no reason
for a feature to go there. Features grow *around* the boundary. Which is why it accretes.

## B. Both drifts grew in the direction the audit predicted

### B.1 RunStatus translation sites: 7 → **9**

The audit counted seven. PR #35 added two more in one release:

| # | Site | Added |
|---|---|---|
| 1–2 | the two tables: `_types/exit_codes.py:50-68`, `_types/http_status.py:53-75` | — |
| 3 | `app/adapters/click_params.py:1271-1276` (in `deliver_job_result`, def at `:1194`) | — |
| 4 | `_cli/tui/job_execution.py:271-285` — its own success set `(SUCCESS, SKIPPED, BLOCKED)` | — |
| 5 | `_cli/builtins.py:589-608` — `func builtin parallel`, own success set at `:598` | — |
| 6 | `_cli/builtins.py:1354-1367` — **`_resume_exit()`** | **PR #35** |
| 7 | `plugins/functualize-mcp/.../_tools.py:35-48` — **`wire_status()`** | **PR #35** |
| 8 | `plugins/functualize-http/.../__init__.py:193` | — |
| 9 | `plugins/functualize-lambda/.../__init__.py:65` | — |

Site 6 is the sharper one. `_resume_exit()` is a **string → RunStatus reverse lookup**,
with a hand-rolled fallback when the reverse lookup misses:

> `return 0 if status in {"answered", "drafted"} else 1`

A tenth vocabulary, invented because the ninth could not be reached.

Site 7 is the one that should end the argument. `wire_status()` did not exist at `c0c921f`
(`git grep "def wire_status" c0c921f` → empty). It was written during the workflow-continuation
work to fix the fact that MCP's execution doors disagreed with each other about how a status
reaches the wire. **Its own docstring says "Three doors disagreed."** The codebase
independently rediscovered the audit's thesis, in writing, three weeks later — and fixed it
locally, at one adapter, producing a ninth site rather than removing the need for one.

*This is not a criticism of PR #35.* Fixing it locally was the correct call for that release.
It is evidence about what happens **in the absence of an authority**: the right local fix and
the wrong global outcome are the same commit.

### B.2 The `app/utils.py` corridor: 2,021 → **2,068** LOC, 75 → **93** re-exports

+47 lines and **+18 public re-exports in a single release**. The audit recorded this
corridor as out of scope and "the next surface-boundary question". It is growing at
18 re-exports per release. It stays out of scope here too — see
[11-boundaries.md](11-boundaries.md) — but the growth rate is now measured rather than
asserted.

## C. New since the audit: a ninth door, and it is the shape of the fix

`src/functualize/app/_workflow_control.py:176`:

```python
return app.execute(_canonical(job_name), scope_id=scope_id, **kwargs)
```

`guarded_execute` is a **new execution door**, added by PR #35 as the single funnel that all
three workflow surfaces (CLI verbs, MCP tools, `--wf-*` flags) execute through. It routes via
`app/core.py:621`, so it adds **no new name→function resolution site** — the count stays at
eight.

That makes it the most useful object in this document set: **it is a proto-`engine.run()`,
built independently, for the workflow half of the problem.** It exists because making the
CLI's `resume` verb actually advance a walk created a second job-executing door, and the
author's response was to build one funnel and route everything through it — with a policy
object (`GateToolPolicy`) deciding what may pass.

The design in [04](04-request-and-entry.md) is that move, applied to all nine doors instead
of three. The pattern is not speculative; it shipped, and it works.

## D. Corrections to carry

Two classes. **Neither is drift** in the first group — these citations were wrong at
`c0c921f` too, and the files never changed:

| Citation as written | Correct | Note |
|---|---|---|
| "`execute()` is a **12**-parameter procedure" | **13** parameters (excluding `self`) | Recount; the argument is unaffected and slightly strengthened |
| `executor.py:656` (`def execute`) | `executor.py:**657**` | |
| `executor.py:1214`, `:1793` (engine resolves by name) | `:**1216**`, `:**1795**` | |
| `_config/sources.py:36` | `:**35**` | |
| `app/core.py:711-822` (`func why`'s second verdict engine) | `:**725-823**` — `explain()` is 701-724 (prose), `explain_verdicts()` is the second engine | |
| **`_app/runcontext.py:698`** | **`_engine/capabilities/runcontext.py:698`** | The cited path **does not exist and never did** |

And genuine post-#35 moves:

| Was | Now |
|---|---|
| `click_params.py:82` (`_force` read), `:1141` | `:**74**`, `:**1148**` |
| `lazy_command.py:141` | `:**153**` |
| `dispatch.py:736` | `:**729**` |
| `builtins.py:604` | `:**608**` |
| `main.py:1643` | `:**1655**` |
| MCP `_server.py:272`, `_tools.py:254`, `:408` | `:**278**`, `:**287**`, `:**450**` |

## E. Where the two audits disagree — and which numbering this set uses

The coverage audit and the depth audit assign **different content to "Cause 4"**:

| | Cause 4 is… |
|---|---|
| Depth audit (`audit-engine-encapsulation.md` §1) | `func`'s pre-boot layer is a permanent second CLI, and the "one rule" fixes are per-rule hand extractions |
| Shape-intent synthesis | The **deposit protocol** is the divergence generator |
| ADR-020 | follows the depth audit |

Both are real; they are not the same claim. The divergence ids hang off different ones:
`D-1`, `D-2`, `D-3`, `D-5` and `D-13` are consequences of the **deposit protocol**, while
roadmap step 5 (`flag_grammar`) is a consequence of the **pre-boot second CLI**.

> **This set uses four causes, renumbered once, and never re-uses the old numbers:**
> **C-I** the unresolved entry contract · **C-II** the unsealed engine ·
> **C-III** the per-surface delivery act · **C-IV** the deposit protocol ·
> **C-V** the pre-boot vocabulary.
>
> That is five, not four. The two audits were each compressing to four and each dropped a
> different one. See [appendix-a-audit-synthesis.md](appendix-a-audit-synthesis.md).

## F. One audit claim this set does not carry

The coverage audit's §B matrix places D-13's `✗` in the **`Invoke`/`rc.invoke` column**.
D-13 is about `interactivity.job.submit`, which is surface #15 and has no column of its own.
Re-verified: `rc.invoke` **does** propagate scope (`_engine/capabilities/invoke.py` passes
`parent_scope`), so the cell is wrong, not merely misplaced. The defect is real and is
carried as [04 §C](04-request-and-entry.md); the matrix cell is corrected in
[07-surface-parity.md](07-surface-parity.md).
