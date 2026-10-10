# plan.md — one stdin classification behind both doors

## BEFORE

```
resolve_stdin_params                        StdinCollector.is_available
├─ Rule 1: explicit CLI wins                = sys.stdin.isatty()
├─ Rule 2: one marker max                     and sys.stdout.isatty()
├─ Rule 3: is_stdin_available()               (its own copy of the TTY idiom
│   = not sys.stdin.isatty()                   the collector comment calls
│   ├─ streaming → lazy NDJSON                 "mirroring the _cli/stdin_reader
│   └─ read_stdin()  ← BLOCKS forever            idiom")
│       on `sleep 30 | func s`;               → prompts at a TTY, else
│       an empty stream arrives as            unavailable (default /
│       undocumented "" over the default      InputNotAvailable)
└─ Rule 4: TTY → {}
```

## AFTER

```
resolve_stdin_params                        StdinCollector.is_available
├─ Rule 1: explicit CLI wins                = stdin_state() is TTY
├─ Rule 2: one marker max                     and sys.stdout.isatty()
├─ Rule 3: streaming (non-TTY) → lazy NDJSON
│   (the documented opt-in to waiting)
├─ Rule 4: is_stdin_available() → read_stdin()
│   = stdin_state() is READY —
│   "a read returns promptly": input or EOF
│   ("" deposited for an empty-but-present
│   stream; documented)
└─ Rule 5: TTY or never-written pipe → {}
    (the signature default wins)

                        stdin_state()
              one classifier, two projections
              TTY | NO_INPUT | READY
```

## Design skills consulted

- `python-design-patterns` (in-repo, `.claude/skills/python-design-patterns`):
  KISS, SRP, Separation of Concerns, and its **Rule of Three** — "wait until you
  have three instances before abstracting".
- `design-patterns-refactoring` (user-level; Dive Into Design Patterns +
  Refactoring.Guru catalogue): smell vocabulary and technique mapping.

Smell names from those catalogues, not invented: BEFORE is **Duplicate Code** —
two modules answer the same TTY question, and the collector's own comment
("Mirrors the `_cli/stdin_reader` TTY idiom") is the duplication admitting
itself. The technique is **Extract Function**: one `stdin_state()`, each door a
documented projection of it.

Rule of Three, weighed honestly: two doors are fewer than three instances, and
the in-repo skill warns against premature abstraction. The deciding constraint
is not cosmetic duplication but the acceptance criterion that the two doors
"agree rather than contradicting" — a correctness coupling the tests must
enforce in one place. If a third consumer appears it joins the same function.

## Technical approach

1. `stdin_state(stream=None) -> StdinState` in `stdin_reader.py`, non-blocking
   probe: `isatty()` → `TTY`; else `select.poll()` on `fileno()` with a zero
   timeout (mirroring `capabilities/shell.py`'s documented "poll(), not
   select()" reason — FD_SETSIZE under xdist): events → `READY` (read returns
   input or EOF promptly), none → `NO_INPUT`. POLLHUP/POLLERR wake even a
   POLLIN-only registration, so end-of-stream reads as `READY`, not `NO_INPUT`.
2. A stream with no pollable fd (`fileno()` raises; `select.poll` absent, i.e.
   Windows; probe raises `OSError`/`ValueError`/`AttributeError`) is
   unprobeable: today's rule exactly — the gate reads eagerly and `read_stdin`
   returns what it read. No fd-less or Windows behaviour changes.
3. `is_stdin_available()` becomes `stdin_state(...) is READY`; `read_stdin`
   keeps its contract. The resolution rules restructure per contracts.md, with
   the streaming hoist (rule 3 above the readiness gate, TTY still excluded) so
   `sleep 5 | func transform` with a slow producer keeps flowing.
4. `StdinCollector.is_available` reads `stdin_state() is TTY` and keeps its
   stdout half (peer-layer import inside `functualize._engine`, invisible to
   the independence contract).
5. Tests drive real `os.pipe()`s — no mocks for the states themselves: a
   held-open write end (never written, wall-clock bound), a closed write end
   (empty but present), written data (multi-line + multibyte), `/dev/null`.
   One parity test pins both doors' projections per state. The three existing
   test files move their patch seam from `sys.stdin.isatty`/`.read` attributes
   to the `is_stdin_available`/`read_stdin` function seams with assertions
   unchanged.

## Files

1. `src/functualize/_engine/stdin_reader.py`
2. `src/functualize/_engine/capabilities/stdin_collector.py`
3. `tests/engine/test_stdin_states.py` (new)
4. `tests/cli/test_stdin_integration_unit.py`
5. `tests/cli/test_stdin_resolution_properties.py`
6. `tests/engine/test_run_request_stdin.py`
7. `contributor/adr/032-optional-stdin-empty-stream.md` (new)
8. `contributor/architecture/interactivity-model.md`
9. `CHANGELOG.md`
10. `.spec/features/optional-stdin-pipe/{spec,contracts,plan,tasks}.md` (this
    tree; cleared before merge)

## Risks

- **Windows**: no `select.poll`, sockets-only `select()`. The fallback keeps
  today's eager rule — no regression by construction; the never-written-pipe
  hang remains there, documented in the spec's platform note and the ADR.
  `PeekNamedPipe` is the named follow-up shape, not silently approximated here.
- **Data-then-stall producer**: a writer that emits bytes and never closes can
  still block inside `read_stdin()`. Unchanged eager contract; fixing it needs
  a stall timeout or a knob — user-visible surface, out of scope. The
  iterator-typed parameter remains the documented opt-in for slow producers.
- **FD_SETSIZE**: `select.select` would raise "filedescriptor out of range" in
  wide xdist sessions; `select.poll` has no ceiling (the `shell.py` lesson).

## Surviving smells

1. `read_stdin()` is still eager to end-of-stream — the data-then-stall class
   above, deliberately kept (fixing it is a user-visible knob).
2. Unprobeable streams fall back to the eager rule (fd-less doubles, Windows):
   unknown readiness is answered by reading, as today. Production hands the
   engine a real fd; nothing else can observe the difference.
3. Codemap gap: `contributor/architecture/codemaps/modules.md`'s `_engine`
   section still omits `stdin_reader` / `stdin_collector` (pre-existing; out of
   this change's scope).
4. The prompt door (non-TTY → default / `InputNotAvailable`) and the parameter
   door (empty stream → `""`) answer different questions — a prompt has no
   caller-piped "empty answer", a parameter does. Kept split, documented side
   by side in `contributor/architecture/interactivity-model.md` so the model
   reads as one design, not a contradiction.
