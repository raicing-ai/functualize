# 06 — Safety, Idempotency & Observability

> **Status: carried forward — current.** Isolation levels, host guards,
> idempotency and the JSONL audit log are realized as specified in
> [`../08-safety-audit.md`](../08-safety-audit.md), including the TTY host-guard
> and the twice-run prover. No divergence.

Three disciplines make the framework trustworthy for unattended use — by CI
pipelines and by AI agents that must not be able to wreck a machine by
mistake.

## Idempotency — the foundational rule

**Every mutating operation checks current state before acting.** The desired
end state, not the action, is the contract.

Why it is non-negotiable:

- **Safe to re-run** — no side effects on repetition;
- **CI/CD-safe** — pipelines can retry without corruption;
- **Agent-safe** — an agent can invoke operations without tracking state;
- **Self-healing** — running an install on an already-correct system is a
  no-op.

Canonical patterns (pseudocode):

```
install():
    if already_present():
        report("already installed"); return
    perform_install()

start():
    if is_running():
        report("already running"); return
    perform_start()

stop():
    if not is_running():
        report("not running"); return
    perform_stop()

restart():
    stop()                       # composed from idempotent parts
    start()                      # → restart is idempotent for free
```

Composition preserves idempotency: built from idempotent parts, the whole
stays idempotent. This is why the framework prefers composing operations over
writing new shell logic.

## Isolation levels

Where an installation *lives* determines its risk. Every program declares its
isolation as a **required tag** — the schema rejects a program without one.

| Level | Scope | Risk | Confirmation required? |
|---|---|---|---|
| `host` | machine-wide — all users, all projects | high; hard to revert | **yes** — warning + confirm |
| `project` | scoped to one project (version-manager pin, venv, project-local dir) | low | no |
| `process` | container / VM / cgroup | none to host | no |

Isolation is a **declared property** (in the declaration block) and a
**detected property** (reported in the diagnosis record). Both exist so that
an agent can learn a tool's risk profile **by reading, without executing
anything**.

Typical mapping of strategy → isolation:

| Strategy | Typical isolation |
|---|---|
| brew, pip (system), cargo, distro-native | `host` |
| version-manager pin, nix profile, venv | `project` |
| container, VM | `process` |

## Safety guards for host-level operations

When a host-isolated operation is about to mutate the machine, two guards run
first.

### Guard 1 — the warning banner

Before any host-level install/uninstall, print a formatted warning stating:
the program name, the isolation level, the scope ("affects all users and
projects"), and that it may not be easily reverted — then require explicit
confirmation.

- **Interactive terminal** → wait for a yes/no answer; anything but yes
  aborts the operation (non-zero exit).
- **CI / non-interactive** → auto-continue *with a log record* (CI is
  presumed deliberate), never hang.

### Guard 2 — the overwrite check

Before installing, detect whether the program **already exists from a
different origin** (e.g. a pip-installed binary is on the path, and the user
is about to brew-install it). If so, warn explicitly: current path and origin
vs. planned install, and require confirmation; no/abort on refusal.

- These guards run **only** for host isolation. Project- and process-scoped
  operations are safe by design — no prompts, no friction.
- Observability is **never** reduced by isolation: everything logs regardless.

### Non-interactive semantics

The rule: **never hang, never silently skip.** Non-interactive contexts
auto-continue with a log entry. Automation must be able to run unattended;
audit must still capture what happened.

## Audit logging — observability

Every lifecycle operation on a program — install, uninstall, invoke — appends
one JSON-lines record to a **shared project audit log**.

```
LogRecord := {
  timestamp: ISO-8601 UTC
  program:   name
  isolation: host | project | process
  operation: "install" | "uninstall" | "invoke" | "event"
  variant:   which strategy was used
  platform:  "<os>/<arch>"
}
```

Design intent:

- **Append-only, one line per event** — grep is the query language; no
  indexing, no rotation in the first version (log volume for CLI tool
  operations is negligible).
- **Shared across all programs in the project** — cross-program questions
  ("every host-level install this week") are one filter.
- **Transparent** — logging writes nothing to the console; users don't see it.
- **Parameterized** — the logging helper is one shared routine receiving
  (program, isolation, operation, variant); no per-tool log code.
- The log directory is created on demand; the location is overridable per
  project.

Combined with the diagnosis record, the two observability surfaces answer
every audit question: **what is true now** (diagnose) and **what was done,
when, by which strategy** (log).

## The self-checking lifecycle: `test`

Every program, library, and service module must expose a `test` operation that
proves the resource's lifecycle works **and is idempotent**:

```
test():
    record = diagnose()                 # must be schema-valid
    install(); install()                # second run must be a silent no-op
    invoke_probe()                      # run the thing, check output
    uninstall(); uninstall()            # second run must be a silent no-op
```

Isolation discipline for the test itself:

- **In a container or CI** → run the full destructive suite.
- **On a developer's machine** → run only the non-destructive checks
  (diagnose validity, structure) and **skip** install/uninstall, with a
  warning. Tests must never mutate a real machine by surprise.

Two test tiers express this:

| Tier | Contents | Where it runs |
|---|---|---|
| Fast / structural | diagnosis output validity, schema conformance, no mutations | anywhere, always safe |
| Full / lifecycle | real install → verify → real uninstall, idempotency checks | only inside an isolated container or CI |

The framework's own test harness follows the same tiering: fast checks on the
host, destructive install/uninstall cycles inside a disposable container.

## Test harness shape

The canonical test suite must prove both directions of the validation
pipeline:

1. **Acceptance cases** — every kind, every isolation level, every interface
   combination, the project templates, the registry: each must produce a
   record that passes its schema, and a structure that passes step 1.
2. **Rejection cases** — each of these must be rejected, loudly:
   - unknown kind (no schema exists → reject);
   - unknown interface, or interface not legal for the kind;
   - dot-notation / strategy names in the interface list;
   - missing status field, missing kind;
   - unknown extra fields in the record;
   - invalid or missing isolation tag on a program;
   - structure violations: missing required capability, missing required
     configuration, missing declaration.

The rejection suite is *why the schema exists*: it pins "wrong is
unrepresentable" as an observable property. If a rejection case starts
passing, the schema regressed.

## Safety summary — the invariants

1. Every mutating operation is idempotent.
2. Every program declares isolation; host-level mutations require
   confirmation; non-interactive runs log and proceed.
3. Every lifecycle event is appended to a shared audit log.
4. Full lifecycle tests run only in isolation.
5. Nothing ever hangs waiting for input in automation contexts.
