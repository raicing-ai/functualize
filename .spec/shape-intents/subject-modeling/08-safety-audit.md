# 08 — Safety, Idempotency & Audit

The intent's safety policy, unchanged, on mechanisms that exist.

## 1. Idempotency — status guards

| Operation | Guard | On repeat |
|---|---|---|
| `install` | `Guards(status=[already_installed])` + `Fingerprint(generates=[lockfile])` | `SKIPPED` → exit **0** |
| `uninstall` | `Guards(status=[already_absent])` | `SKIPPED` → 0 |
| `start` / `stop` / `restart` | `Guards(status=[in_desired_state])` | `SKIPPED` → 0 |
| `bootstrap` | per-tool `rc.invoke` of idempotent installs | all skipped → 0 |

**[probed]** — a second `install` returned `RunStatus.SKIPPED`, and `why`
reported `SKIP (already done) / status guards satisfied`.

Preconditions are for refusals only. Using one for idempotency exits **3** and
aborts `bootstrap` on the first already-installed tool.

## 2. Isolation

`Isolation` (`host` / `project` / `process`) is a required class attribute on
substrates that can mutate a machine, checked at binding, carried in the
record, and published in `info schema` / MCP — so an agent reads a tool's risk
profile without executing (criterion 66), and via the AST reader without even
importing (`02` §5).

## 3. The host guard

The intent's rule is asymmetric, and no single `prompt_confirm` expresses it:
interactive default is **no**; non-interactive **auto-continues with a log
record, never hangs**.

The interactivity signal is an optional TTY parameter — `tty: TTY | None` is
injected only when an exclusive terminal is grantable, otherwise `None`
(`_discovery/providers.py:285`). `rc.is_interactive` does not exist.

```python
@job(guards=Guards(status=[jsonschema_present]))
def install(self, rc: RunContext, sh: Shell, tty: TTY | None = None) -> None:
    plan = resolve_variant("jsonschema", None)
    if plan.isolation is Isolation.HOST:
        if tty is None:                                  # CI / piped / MCP
            self.audit(AuditEvent(op="install", mode="auto-continue", plan=plan))
        else:
            if not rc.prompt_confirm(host_warning(plan), destructive=True, default=False):
                raise HostInstallRefused(plan)           # nothing ran
            self.audit(AuditEvent(op="install", mode="confirmed", plan=plan))
    plan.perform(sh)
```

Measured off-terminal semantics **[probed]**:

| Call | With no collector |
|---|---|
| `prompt_confirm(q, default=False)` | `False` |
| `prompt_confirm(q, default=True)` | `True` |
| `prompt_confirm(q)` — no default | raises `InputNotAvailable` |

So `default=False` is right for the interactive arm and would be *wrong* as the
whole mechanism — it would silently abort every CI install. The `tty is None`
branch is what makes both criteria true at once.

Project- and process-isolated operations never reach the prompt (criterion 40):
the `isolation is HOST` test guards the whole block, and a test asserts no
prompt request is emitted for a `project` variant.

**Overwrite check:** before install, compare the record's `installed` block
(path + origin) against the plan. A different origin adds a line to the banner
and routes through the same confirm flow (criterion 39) — one comparison, no
second code path.

**Not a gate.** A workflow `Gate` blocks until input is deposited, which is the
hang the intent forbids. Gates stay reserved for genuinely resumable flows.

## 4. Exit codes

| Code | Meaning | Reached by |
|---|---|---|
| 0 | success, **or skipped** | completion; status/fingerprint skips |
| 1 | the body raised | `HostInstallRefused`, a failed verdict |
| 2 | usage / config | click, config resolution |
| 3 | refused — a declared precondition unmet | no variant; destructive tier outside isolation |
| 4 | stale-check failure | fingerprint |
| 5 | blocked at a gate | release flows only |

Callers can distinguish "declined" (1, with a message) from "refused before
trying" (3) from "already fine" (0).

## 5. The audit log

An inherited appender, written once:

```python
class Resource:
    def audit(self, event: AuditEvent) -> None:
        path = self._audit_path()                        # config `audit.path`
        path.parent.mkdir(parents=True, exist_ok=True)   # on demand (criterion 43)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(event.model_dump_json() + "\n")
```

`AuditEvent` carries the intent's fields — timestamp, program, isolation,
operation, variant, platform — plus `mode`
(`confirmed`/`auto-continue`/`declined`), which is what makes criterion 38's
log record auditable rather than merely present. It writes nothing to the
console (criterion 42): the appender takes no `Log` and emits no event.

**Not the EventBus.** A boot-registered `AFTER_SUCCESS` subscriber would catch
every job for free, and that is the problem — the intent's log is the
*lifecycle* audit. functualize already keeps the other artifact
(`builtin history`), and the two coexist without either pretending to be the
other.

## 6. The twice-run prover

The intent (criterion 45): `diagnose → install → install → probe → uninstall →
uninstall`. **This cannot be a workflow**: a node's graph key is the referenced
job's name (`_types/workflow.py:131`), duplicates are a decoration-time
`ValueError`, and `Step` has no name-plus-job form.

It is a job body, which is better — the proof is an *assertion* about the
second run's status, which no edge could express:

```python
@job(guards=Guards(preconditions=[in_isolated_runner]))     # → exit 3 on a dev box
def test(self, rc: RunContext) -> LifecycleReport:
    g = self.group
    rc.invoke(f"{g}.diagnose")
    first, second = rc.invoke(f"{g}.install"), rc.invoke(f"{g}.install")
    assert_status(first,  RunStatus.SUCCESS, "first install must act")
    assert_status(second, RunStatus.SKIPPED, "second install must be a no-op")
    rc.invoke(f"{g}.run", args=["--version"])
    rc.invoke(f"{g}.uninstall")
    assert_status(rc.invoke(f"{g}.uninstall"), RunStatus.SKIPPED, "…")
```

`rc.invoke(job_name, **kwargs)` takes the name and keyword arguments only —
there is no `namespace=` parameter; passing one forwards it to the job
(`_engine/capabilities/runcontext.py:365`).

**The group is resolved, not literal.** In the guest delivery `self.group`
already carries the namespace (`04` §3), so the prover works unchanged in both
deliveries — which `12`'s parameterized suite checks.

### Tiers

| Tier | Where | Steps | Mechanism |
|---|---|---|---|
| fast, non-destructive | developer machine | `diagnose` + safe probes | the default body |
| full, destructive | container / CI | the cycle above | `Guards(preconditions=[in_isolated_runner])` |

The destructive tier **refuses** (exit 3) outside an isolated runner rather
than being discouraged — criterion 46 enforced, and visible in
`rise builtin why <group>.test` before you run it. A callable guard that raises
counts as not satisfied (`_engine/guards.py:276`), so a detection error refuses
rather than proceeding.

## 7. Invariants

1. Every mutating operation is idempotent, and `why` prints the verdict.
2. Programs declare isolation; host mutations confirm interactively;
   non-interactive auto-continues **with `mode` in the record**.
3. Every lifecycle event appends one JSONL line; nothing reaches the console.
4. Destructive tests refuse outside isolation.
5. Nothing hangs: the `tty is None` branch answers before any prompt is issued,
   and no rise prompt is ever called without a default.
