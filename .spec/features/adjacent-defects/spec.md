# Feature — adjacent-defects

Implements **F8** of `contributor/architecture/run-model/13-roadmap.md`: ten small, verified,
mutually independent defects that the entrypoint audit found beside its subject and did not
own, plus the declared-and-never-used names this document set turned up while surveying.

**Depends on:** nothing. **Blocks:** nothing. Executable at any point in the branch.

Every item below was re-verified at `e57f0c9` with the command recorded in `tasks.md`.

---

## 1. The problem

These are not one problem. They are ten, and the only thing they share is that each is
**small, verified, and currently owned by nobody** — the class of defect that survives
indefinitely because it is never anyone's feature.

Three of them are *live user-facing bugs*. Four are **declarations with no producer or
consumer**. Two are **comments that are false**. One is a measurement the audit asked for and
never got.

### 1.1 A group-options conflict crashes with a traceback

`_discovery/cached_provider.py:916` raises `GroupOptionsConflictError` during
`boot_standard`. Verified: `rg -c 'except GroupOptionsConflictError' src/` returns **0** —
nothing in shipped code catches it. The user sees a Python traceback and exit 1.

ADR-018 established that a discovery failure is *reported, not fatal* — but its surface covers
module **reads**, not group-option conflicts, so this path never joined it.

### 1.2 Single-file mode boots a second app that executes CWD code

`_cli/main.py:1652-1668` runs `auto_discover(cwd)` and constructs a second `FunctualizeApp`.
Any module in the working directory has its top-level code executed. The coverage audit
reproduced a stray CWD script hijacking routing and reporting
`Error: No such command '<target>.py'` (exit 2) — the target file never reached.

PR #35 patched a *symptom* (`main.py:1544-1560` skips peers already registered, with a
regression test) without removing the second boot. The structure is live and shipping bugs.

### 1.3 The group-options cache section has no fingerprint

`read_group_options_from_cache` (`app/utils.py:1636`) takes `cache_path` and nothing else:

```python
def read_group_options_from_cache(
    cache_path: Path,
) -> dict[str, GroupOptionsSpec] | None:
```

There is no fingerprint parameter, so **no caller can supply one**. Every other cache section
is guarded by `discovery_hash`, computed on every boot (`_app/boot.py:518`) precisely so a
changed filter invalidates. This section is the one hole in that scheme, and it is the
suspected mechanism behind a conflict that survived `func builtin cache clear` and mtime
bumps in one observed fixture transition.

*(The audit cited `utils.py:1589`. It is `:1636` at `e57f0c9` — `app/utils.py` grew 47 lines
in 0.3.0.)*

### 1.4 The layer contract is blind to 125 imports — and the audit's premise was wrong

`pyproject.toml:234` sets `exclude_type_checking_imports = true`, hiding **125**
`TYPE_CHECKING` imports of internal packages from all six import-linter contracts.

The audit proposed measuring the flip and, *"if `_config → _events` is the only violation"*,
either legalizing it or moving it behind a protocol.

**Measured, with a temporary config outside the tree:** flipping the flag breaks **all six
contracts** with **47 violations** — `_cli/tui/` (18), `_engine/` (8), `_types/` (7),
`_app/` (6), and the rest. `_config → _events` is not the only violation; it is one of many,
and most of the rest are legitimate annotation-only references.

So the audit's conditional never fires, and its recommendation does not apply. This feature
records the measurement and **declines to flip the flag** — see §3.4.

### 1.5 Four names are declared and used by nothing

| Name | Where | State |
|---|---|---|
| `get_missing_required_args` | STATUS #13 | 3 references in `src/`, none a production caller — the live answer comes from `SmartBar.evaluate` |
| `omit_defaults` | STATUS #14 | 3 references; no production caller passes `True` |
| `job.execute.error`, `cli.parse.start`, `tui.session.start/end` | `_events/_catalog_entries.py` | declared in the catalog, **emitted nowhere** |
| `JobContext.deadline` | `_engine/capabilities/job_context.py:27,38` | *"Optional deadline after which the job should abort"* — no construction site sets it |
| `_deposit` | `plugins/functualize-mcp/.../_workflow_tools.py:423` | orphaned by 0.3.0's `answer_gate` |

`JobContext.deadline` is the worst of these: it promises a capability the engine has
**explicitly decided not to build** (`_engine/exec_policy.py:7-22` — a thread-based timeout
reports TIMEOUT while the work continues; SIGALRM silently does nothing in the TUI). A field
that documents an abort that cannot happen is worse than no field.

### 1.6 Two comments are false

- **`tests/perf/test_startup_budget.py:56`** — *"a single boot calls
  `importlib.metadata.entry_points()` seven times (measured)"* and recommends caching it.
  Caching **shipped** on 2026-08-27 (`84ed555`, PR #4); the comment was written 2026-08-20
  (`b5495c6`, PR #3) — the previous PR — and was never deleted. It has misled at least one
  architecture audit, which repeated the recommendation as current fact.
- **`app/_workflow_control.py:17-18`** — states that `--wf-resume` *"passes through
  `guarded_execute`"*. It does not: `apply_workflow_flags` returns a scope id
  (`workflow_flags.py:376-402`) and the click wrappers call the engine directly. Repo-wide,
  `guarded_execute(` has exactly **two** callers.

### 1.7 Three callers bypass the entry-point cache

`_primitives/entry_points.py` exists so the path is scanned once per process. Three callers
still call `importlib.metadata.entry_points()` directly:
`plugins/functualize-ai/.../_provider_discovery.py:53`, `_cli/skills.py:156`,
`_cli/tui/display_provider_discovery.py:77`.

**Not a boot win** — two are lazy imports inside functions and one is a plugin. It is a
consistency gap: three callers of a superseded API, with no test pinning the count.

### 1.8 Three shipped behaviours the audit re-confirmed open

| id | Behaviour |
|---|---|
| **#37** | An unknown command on a project's own `main.py` gets click's `No such command` (exit 2); `func` gets an explanation with fuzzy suggestions (exit 1). Both call `explain_missing_job`; click's `UsageError` fires first in standalone mode |
| **#38** | An enum parameter arrives in the job as `str`. `_click_type_for` renders a `click.Choice` of member values and nothing converts back. The programmatic path passes the member through unchanged, so the two surfaces disagree about the type of the same parameter |
| **#27** | A `SyntaxError` in a discovered module is reported on run one and **vanishes on run two** against a warm cache, while a `ModuleNotFoundError` in the same tree repeats every run |

---

## 2. User stories

- **US-1** As a user with two files declaring the same group option, I get a rendered error
  telling me which two files, not a traceback.
- **US-2** As a user running `func weather.py` in a directory containing other scripts, my
  script runs — a neighbouring file cannot hijack the command.
- **US-3** As a user, a job parameter typed as an enum arrives in my job as that enum, on
  every surface.
- **US-4** As a user, a broken module reports its breakage on every run, not only the first.
- **US-5** As a maintainer, a comment in this repo describing the code is true, or it is gone.
- **US-6** As a maintainer, a name that nothing calls is deleted or wired — not left as a
  promise.

---

## 3. Behaviour

### 3.1 Failures are rendered, not raised

`GroupOptionsConflictError` joins ADR-018's reported-not-fatal surface: the conflict is
rendered, names both files, and exits with the discovery-failure code — not a traceback.

### 3.2 One boot per invocation

Single-file mode reuses the app it already built. If that proves to change routing behaviour,
the fallback is narrower: the second boot keeps its discovery but stops importing from CWD,
and the misleading error is replaced by one that names the real cause.

> **This is the only item here with architectural blast radius.** It is executed last, and if
> it cannot be done without behaviour change it is **withdrawn and recorded**, not forced.

### 3.3 The cache section gets a fingerprint

`read_group_options_from_cache` takes the fingerprint its siblings take, and its callers
supply it, so a changed discovery filter invalidates group options as it invalidates
everything else.

### 3.4 The `TYPE_CHECKING` flag stays on, and the reason is written down

The measurement (§1.4) is recorded in `contributor/` beside the layer contract, with the 47
violations broken down by package. The flag is **not** flipped: most of the hidden imports are
legitimate annotation-only references, and flipping it would either force runtime imports that
cost boot time or bury six contracts in exemptions.

What changes is that the hole is **documented and bounded** rather than a footnote in a
serena memory: the contract's blind spot has a measured size, and a future reader can tell
whether it grew.

### 3.5 Dead names are deleted, or wired, and it is one or the other

For each name in §1.5, the task either deletes it or names its production call path. "Leave
it, it might be useful" is not an outcome — `CONSTITUTION.md` → *Reachability*.

`JobContext.deadline` is **deleted**. Reinstating a deadline is F5's lease
(`08-durable-runs.md` §D), which is a different mechanism with a different name.

### 3.6 What must not change

- The six import-linter contracts stay green at their current setting.
- ADR-018's existing reported-not-fatal behaviour for module reads.
- 0.3.0's single-file peer-registration fix (`main.py:1544-1560`) and its regression test
  stay, whatever happens to §3.2.

---

## 4. Acceptance criteria

- **AC-1** A group-options conflict during boot renders an error naming both declaring files
  and exits with the discovery-failure code. `rg -c 'except GroupOptionsConflictError' src/`
  returns ≥ 1.
- **AC-2** `read_group_options_from_cache` accepts a fingerprint and every caller supplies
  one; a changed discovery filter invalidates the group-options section.
- **AC-3** The `TYPE_CHECKING` measurement is recorded in `contributor/` with the per-package
  violation counts, and `exclude_type_checking_imports` is unchanged and annotated with why.
- **AC-4** `get_missing_required_args` and `omit_defaults` are each deleted, or have a named
  production call path proven by breaking it and watching a test fail.
- **AC-5** `job.execute.error`, `cli.parse.start` and `tui.session.*` are each emitted, or
  removed from the catalog. No catalog entry lacks a producer.
- **AC-6** `JobContext.deadline` is gone.
- **AC-7** `_deposit` (`_workflow_tools.py:423`) is gone.
- **AC-8** `tests/perf/test_startup_budget.py` no longer claims seven uncached
  `entry_points()` calls per boot.
- **AC-9** `app/_workflow_control.py`'s module docstring no longer claims `--wf-resume` passes
  through `guarded_execute`.
- **AC-10** The three direct `importlib.metadata.entry_points()` callers use the cached
  helper, **or** are documented as deliberate exceptions; a test pins the count either way.
- **AC-11** An enum job parameter arrives in the job body as the enum member on the CLI, and
  the CLI and programmatic paths agree on its type (#38).
- **AC-12** An unknown command on a project's own entry point produces the same explanation
  `func` produces (#37).
- **AC-13** A module with a `SyntaxError` reports it on run one **and** run two against a warm
  cache (#27).
- **AC-14** Single-file mode is not hijacked by an unrelated module in the working directory —
  **or** the item is withdrawn with the reason recorded in `.spec/STATUS.md` (§3.2).

---

## 5. Out of scope

- STATUS **#4** (shell-completion model unification) and **#22** (`tui.default_surface` inert
  until shell import) — real, confirmed open, and both a separate subsystem
  (`13-roadmap.md` §E).
- The `app/utils.py` corridor itself. This feature fixes the one bounded wound inside it
  (§1.3); the 2,068-LOC corridor is `11-boundaries.md` **N3**.
- Anything that requires `RunRequest`. This feature is deliberately independent of F1.

## 6. Prior art

- **ADR-018** — discovery failure is reported, not fatal. §3.1 extends its surface rather than
  inventing a second reporting path.
- **ADR-011** — cache fingerprinting; §3.3 is the section that ADR-011 did not reach.
- **`pitfalls.md` §6** — one registry, and a test that checks it. §3.5 and AC-10 are that
  shape.
- **`CONSTITUTION.md` → Reachability** — "no task closes without naming the production call
  path". §3.5 is that rule applied retroactively to five names.
