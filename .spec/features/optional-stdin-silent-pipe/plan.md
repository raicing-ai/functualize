# Plan — optional-stdin-silent-pipe

## Alignment

Implements `spec.md` R1–R7: an eager `Stdin` parameter takes a pipe's content
only when content is actually there; a silent pipe (R3) and an empty stream (R4)
both resolve nothing so the signature default survives; streaming stays the
documented opt-in to waiting (R6); Rule 4 on a TTY is untouched (R2).

## BEFORE / AFTER

BEFORE — Rule 3 read "pipe present" as "data available":

```text
resolve_stdin_params
        │
        ├─ explicit value? ── yes ──▶ {param: value}              (Rule 1)
        │
        ├─ several Stdin params? ──▶ ValueError                   (Rule 2)
        │
        ├─ is_stdin_available() = not isatty()     ← "pipe present"
        │        │
        │        ├─ streaming? ──▶ {param: iter_stdin_ndjson()}
        │        │
        │        └─ read_stdin() ──▶ {param: content}   ← blocks until every
        │                              writer closes; "" overwrites the default
        │
        └─ TTY ──▶ {}                                (Rule 4: default wins —
                                                      reachable only here)
```

AFTER — Rule 3 takes only what is already there:

```text
resolve_stdin_params
        │
        ├─ explicit value? ── yes ──▶ {param: value}              (Rule 1)
        │
        ├─ several Stdin params? ──▶ ValueError                   (Rule 2)
        │
        ├─ stdin is a terminal? ── no ──┐
        │        │                      │
        │        │              ├─ streaming param? ──▶ {param: iter_stdin_ndjson()}
        │        │              │        (R6: the documented opt-in to waiting)
        │        │              │
        │        │              └─ _stdin_data_ready()?
        │        │                        ├─ no ──▶ {}   (R3: silent pipe,
        │        │                        │              default wins, no wait)
        │        │                        └─ yes ─▶ read_stdin() to EOF
        │        │                                       ├─ content ──▶ {param: content}
        │        │                                       │             (R5: intact)
        │        │                                       └─ "" ──▶ {}  (R4: empty
        │        │                                                      stream, default
        │        │                                                      survives)
        └─ TTY ──▶ {}                                (Rule 4: default wins — unchanged)
```

## Design skills consulted

- `design-patterns-refactoring` — *Encapsulate What Varies*: the readiness check
  is the one varying decision in Rule 3, so it becomes a single seam
  (`_stdin_data_ready`) instead of scattering polls. No pattern restructure
  applies: this is a policy fix inside one function, and the Rule 3 branch
  (streaming vs eager) is deliberate policy, not a switch smell.
- Repo-local `test-tiers` / `.agents/skills/test-tiers/SKILL.md` — step tier via
  `tests-for-diff`, no single pytest call past 600 s, nothing backgrounded.
- `.spec/TESTING.md` + `contributor/reference/testing-strategy.md` — tier
  commands, fixture conventions (`cli_run`, `xdg_dirs`, `project_tree`).
- `contributor/guides/wiring-discipline.md` — the new rule is observed through
  the public entry points (`func`/`app` via `cli_run`, `engine.run`), not only by
  calling `resolve_stdin_params` directly.

## Technical approach

1. `_stdin_data_ready(timeout=0.0)` in `stdin_reader.py`: consult a test
   double's `data_ready()` when present; otherwise `select.select([sys.stdin.fileno()], [], [], timeout)`;
   on any failure to poll (`AttributeError`, `OSError`, `TypeError`, `ValueError`)
   return `True` — the historical read-to-EOF contract for unprobeable streams
   (including Windows pipes).
2. `is_stdin_available()` becomes `not isatty() and _stdin_data_ready()` — the
   meaning its docstring always claimed ("data available"). Historical exception
   behavior (return `False`) preserved.
3. Rule 3 restructure in `resolve_stdin_params`: branch on streaming first
   (unchanged lazy hand-over on any pipe), then gate the eager `read_stdin()` on
   `_stdin_data_ready()`; skip a falsy read so an empty stream resolves nothing.
4. Docstring alignment: `StdinCollector.is_available()` states the shared rule
   with the reader; the public `Stdin` docstring says "piped content", not
   "piped".
5. Tests swap the whole `sys.stdin` object for a fake stream (`isatty`, `read`,
   `data_ready`) instead of patching methods on the real one — a method patch
   leaves the real `fileno()` behind and the probe would poll the runner's own
   stdin. Wall-clock tests use a real `os.pipe()` with the write end held open,
   run in a daemon thread with `join(timeout)` so a regression fails instead of
   hanging the suite.

## Files to change

| file | change |
|---|---|
| `src/functualize/_engine/stdin_reader.py` | readiness seam, Rule 3 rewrite, docstrings |
| `src/functualize/_engine/capabilities/stdin_collector.py` | shared-rule docstring (behavior unchanged) |
| `src/functualize/_types/cli_markers.py` | `Stdin` docstring accuracy (behavior unchanged) |
| `tests/_support/stdin_fakes.py` | new: one fake stdin seam shared by both suites |
| `tests/cli/test_stdin_integration_unit.py` | wall-clock silent-pipe, empty-stream pin, real-data intact; seam updates |
| `tests/engine/test_run_request_stdin.py` | engine-level parity pins; seam updates |
| `CHANGELOG.md` | `[Unreleased]` → `### Fixed` entry |
| `.spec/features/optional-stdin-silent-pipe/*` | this record (branch-only, cleared pre-merge) |
| `.spec/STATUS.md` | durable-half migration at clear time |

## Risks

- **Partial write, pipe held open** (`printf 'x'; sleep 30 |`): data is "ready",
  so `read()` still waits for EOF. That is the normal pipe contract — writers
  close — and quiet-period truncation would risk losing data. Documented, not
  fixed.
- **Windows**: `select` cannot poll pipes; the fallback keeps today's blocking
  behavior there. No regression; CI tests on Linux only.
- **Late-starting producers**: `slow_producer | func eager_job` with an eager
  parameter now resolves the default instead of waiting. That is the requested
  behavior (R3); a stage that must wait is a streaming parameter (R6).
- **Flaky wall clock**: bounds are generous (5 s join against a call that should
  take milliseconds) and the probe is a zero-width poll, so only a real
  regression can exhaust them.

## Surviving smells

- `is_stdin_available()`'s name still says "available" where the concept is
  "content is ready"; kept because the symbol is referenced across tests and the
  internal API, and the docstring now defines it precisely.
- `read_stdin(encoding=...)`'s parameter remains documentation only
  (`sys.stdin.read()` takes no encoding) — pre-existing, untouched here.
- Rule 3 keeps an explicit streaming/eager branch. Deliberate policy (R6), but
  the split lives inside `resolve_stdin_params`; a future split into two
  resolvers would read cleaner and was not worth the churn for one rule change.
- `_stdin_data_ready()` answering `True` on unprobeable streams is
  platform-uneven by design (Windows keeps the old behavior). A portable probe
  (e.g. `msvcrt`/threads) would remove the asymmetry at real complexity cost.
- The executor's "drop a `None` argument" loop stays as the mechanism through
  which `{}` means "let the signature default win". Its docstring still cites
  the `/dev/null` empty-string behavior as motivation; the motivation is now
  historical but the loop itself is load-bearing.
