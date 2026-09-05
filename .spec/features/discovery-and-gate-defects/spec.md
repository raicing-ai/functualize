# Spec — Discovery and gate defects

Five defects found while auditing 0.2.3 as a substrate for an external host
package (`risekit`). Each is a case where the framework accepts a declaration
and then does not honour it, or fails harder than its own fallback design
intends. None adds public API — that is the sibling feature
`third-party-host-seams`.

Every claim below was reproduced against `a2f453d` (0.2.3) before this spec
was written; the reproductions are in `plan.md` §1.

## Problem statement

A framework that silently discards a caller's declaration is worse than one
that rejects it. Four of these five defects are silent: the caller writes
something reasonable, the framework does nothing with it, and the only symptom
is an empty job list or a missing parameter far downstream. The fifth is the
opposite failure — a missing optional dependency crashes a workflow walk that
was designed to block instead.

## User stories

- **As a host-package author**, when I pass `JobSources(job_providers=[...])`
  I get either my providers or an error — never silence.
- **As a job author**, a job I register at runtime takes the same arguments as
  the same function discovered from a file.
- **As a workflow author**, naming a gate strategy whose plugin I forgot to
  install stops at the gate with a resumable block, the same as every other
  unresolvable gate — not with a traceback.
- **As anyone debugging discovery**, I can ask the tool why a job is missing
  and be told "this module failed to import, here is the error", rather than
  reading scrollback for a warning that has already gone by.

## Behavior

### B1 — `job_providers` is honoured

`JobSources.job_providers` is declared, documented in the dataclass docstring,
and read by nothing.

**Decided 2026-09-05: wire it.** `plan.md` §3 recommended deletion; the
maintainer chose wiring. The field's providers reach the resolution pipeline on
**both** boot paths, including the `(provider, [transforms])` tuple form the
docstring promises, and the declared type stops being `list[Any]`.

`app.add_job_provider()` remains the imperative path; this makes the
declarative one real rather than removing it.

### B2 — `functions` is honoured on both boot paths, or refused

`JobSources.functions` reaches `StaticProvider` only inside `boot_static`.
`boot_static` runs only when `is_fully_explicit()` is true, which additionally
requires no directories, no children, an explicit `config_resolution_chain`,
and explicit plugins with `entry_point_group == ""`.

So `FunctualizeApp("a", job_sources=JobSources(functions=[alpha]))` discovers
**zero jobs** and says nothing.

After this change, `functions` is either honoured on `boot_standard` too, or
construction raises with a message naming the other conditions
`is_fully_explicit()` requires. Silence is not an outcome.

### B3 — `register_dynamic_job` extracts parameters

A function registered dynamically gets `parameters=[]`. The same function
discovered from a directory gets its real parameter list. The dynamic path
already carries `declaration`, `metadata`, and the capability markers — only
the signature extraction is missing.

After this change, both paths produce equal `parameters` for the same
function.

### B4 — an unresolvable gate blocks, including an unregistered strategy

The walker's contract is that any gate it cannot resolve blocks and stays
resumable. That holds for `strategy=None`, for `"ai_outbound"`, and for a
registered resolver that raises. It does not hold when the *strategy name
itself* is unregistered: `GateRegistry.resolve_gate` raises a plain
`ValueError` from outside its per-strategy `try`, and the walker catches only
`GateResolutionError`.

The practical asymmetry: a broken API key degrades gracefully; a forgotten
`pip install functualize-ai` raises out of the walk.

After this change, `Gate(strategy="ai_inbound")` without `functualize-ai`
installed produces a `BLOCKED` walk carrying a reason that names the missing
strategy and, where known, the plugin that registers it.

### B5 — discovery failures are diagnosable, not just logged

A job module that fails to load logs one line to stderr and contributes no
jobs. Nothing records the failure, so `builtin info` shows a short list with
no explanation and the operator has to reproduce the boot to see why.

After this change, the failure is retained and reported by a builtin surface:
module path, exception type, and message.

**Scope widened 2026-09-05 to cover parse failures, not only import failures.**
As first written this covered the import path alone, which does not reach a
`SyntaxError`: a module with a plain typo is rejected earlier, in the
AST/pre-filter stage, at nine sites that swallow it —
`_primitives/pre_filter.py:115,143,188,266,329,387,431` and
`_discovery/ast_extractor.py:37`.

That gap matters because it is the *more likely* failure and it is STATUS
follow-up #12, listed there as a good first issue. Import-only would have
shipped `discovery_failures: []` for a syntactically broken tree — a report
that actively says "nothing is wrong", which is worse than the current silence.

Both stages now record, under one key. The nine sites keep swallowing: a broken
module must stay non-fatal, it just stops being invisible.

### B6 — the gate-strategy documentation states its own constraints

`docs/guides/ai.md` lists `ai_inbound` and the presets `"ai_inbound"` / `"ai"`
under "Gate Strategies" without saying that a `Gate` accepts only the four
bare strategy names — `Gate(strategy="ai")` raises — and that presets are
reachable only through `rc.invoke(..., gate_strategy=...)` and
`app.resolve_gate`.

## Acceptance criteria

Each is executable. Hit counts are from running the command against `a2f453d`
at authoring time.

| # | Criterion | Authoring-time state |
|---|---|---|
| A1 | `grep -rn "job_providers" src/` returns ≥1 hit **outside** `app/config.py`, with a test per boot path and one for the tuple form | 2 hits, both in `app/config.py` |
| A2 | A test asserts `JobSources(functions=[f])` without full explicitness either yields `f` or raises; it never yields `[]` | yields `[]` silently |
| A3 | A test asserts `register_dynamic_job` and directory discovery produce equal `parameters` for one function | `[]` vs `['x']` |
| A4 | A test asserts `Gate(strategy="ai_inbound")` with no resolver registered returns `RunStatus.BLOCKED` | raises `ValueError` |
| A5 | A builtin surface reports a module that failed to import, naming the module and the exception | not reported |
| A5b | The same surface reports a module that failed to **parse** (`error_type == "SyntaxError"`), closing STATUS #12 | not reported; swallowed at 9 sites |
| A6 | `grep -n "preset" docs/guides/ai.md` reaches text stating presets are not valid `Gate` strategies | absent |
| A7 | `uv run pytest`, `uv run ruff check src/ tests/`, `uv run mypy src/`, `uv run lint-imports` all green | — |

## Out of scope

- Any new public API (see `third-party-host-seams`).
- Changing what `is_fully_explicit()` requires — B2 is about the *silence*,
  not about relaxing the condition.
- Redesigning gate strategy naming. The `ai_inbound` / `ai_outbound` axis
  collision with `docs/guides/ai.md`'s job-level inbound/outbound is real and
  documented in `contracts.md` §4, but renaming is a separate decision.
