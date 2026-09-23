# FUN-17 — Contracts

**Status:** refined 2026-09-23 against `1f3b760`. Supersedes the scaffold.

What changes at a boundary. An interface that changes without appearing here is the
defect this file exists to prevent.

## 1. New internal vocabulary — `src/functualize/_types/persistence.py`

One new module. It imports **only** the standard library, as `_types` requires, and it is
public from nowhere in this wave (see §4).

**Why one file and not three.** `_types/commands.py` is already taken — it is the shell's
runtime command tree (`_types/commands.py:1-20`). Putting `ClaimWorkflow` beside
`CommandNode` would collide two unrelated meanings of "command" in one module name. The
whole persistence contract therefore lives in `persistence.py` and is read as a unit.

### 1.1 `StoreProfile` — capability as data

Frozen dataclass. Twelve attributes: two labels plus the **ten measured fields**, in the
order `contributor/reference/substrate-capability-matrix.md` uses.

```python
@dataclass(frozen=True)
class StoreProfile:
    name: str
    cross_aggregate_atomicity: bool
    fencing: Literal["none", "process-local", "cross-process"]
    multi_process: bool
    multi_machine: bool
    durable_outbox: bool
    versioned_migrations: bool
    interactive_transaction: bool
    remote: bool
    max_document_bytes: int | None
    offline_capable: bool
    description: str = ""
```

`fencing` is the one non-boolean. Its three values are the matrix's own
(`tests/substrate_probe/harness.py:67` carries the same tuple) — keep them identical, so
a future probe reading and a shipped declaration are comparable without translation.

`max_document_bytes` is `None` for "nothing refused what was attempted", which is what the
matrix's `unbounded¹` footnote means. It is **not** "there is no limit".

### 1.2 Commands — eight

`ClaimWorkflow`, `CompleteStep`, `SuspendAtGate`, `ResumeWorkflow`, `CancelWorkflow`,
`StateBatch`, `StartAttempt`, `FinishAttempt`. All frozen dataclasses, all values. Every
command that mutates a scope carries the **held generation**, so fencing is enforced in
the store's predicate rather than remembered by a caller.

### 1.3 Outcomes — six

`Claimed`, `Conflict`, `Resumed`, `CancelResult`, `Attempt`, `InputRequest`.

`Conflict` names the holder and the held generation. It is a value, not an error:

```python
def claim(self, cmd: ClaimWorkflow) -> Claimed | Conflict: ...
```

**This is the one place a writer may return something read back**, and it is why `claim`
is specified as a *single-command transaction that commits on the spot*. Compound
transitions return `None` and raise on refusal, because at the moment a buffered writer is
called nothing has been written yet and there is nothing to read back.

### 1.4 Views and queries — six

`RunView`, `WorkflowView`, `EventView`, `RunTree`, `RunQuery`, `WorkflowQuery`.

### 1.5 Protocols — ten

All `@runtime_checkable Protocol`. No ABC — `.spec/CONSTITUTION.md` → *Forbidden
Patterns*, and ADR-022.

| Protocol | Surface |
|---|---|
| `RuntimeStore` | `profile`, `runs`, `workflows`, `inputs`, `transaction()`, `close()` |
| `RuntimeTransaction` | `runs`, `workflows`, `inputs`, `events`, `effects` |
| `RunWriter` | `start_attempt`, `finish_attempt` |
| `WorkflowWriter` | `claim`, `complete_step`, `suspend`, `resume`, `cancel`, `write_state` |
| `InputWriter` / `EventWriter` / `EffectWriter` | append-shaped |
| `RunReader` | `run`, `recent`, `tree` |
| `WorkflowReader` | `workflow`, `resumable`, `events_after` |
| `InputReader` | question-shaped reads |

Readers are named for **questions**, not `get`/`list`/`find`. A backend may answer
`resumable()` from an index; a caller must never discover that by `hasattr`.

`close()` is new and matters: `SQLiteSubstrate` caches one connection per thread in
`threading.local()` and nothing closes them. The port today has no lifecycle at all.

## 2. Changed signature — `_app/boot.py`

```python
# before
def build_engine(host: EngineHost) -> JobExecutionEngine: ...      # boot.py:220
# after
def build_engine(host, *, runtime_store, substrate) -> JobExecutionEngine: ...
```

Both call sites change: `boot.py:403` (`boot_static`) and `boot.py:622`
(`boot_standard`). `rg -c 'build_engine\(app\)$' src/functualize/_app/boot.py` returns `2`
today and must return `0`.

**`substrate` is a second, separate argument and that is deliberate.** Deleting the lazy
property removes the engine's only source for `StoreSubstrate`, which it still needs for
two things that are not runtime truth: `FreshStore` (`executor.py:1544`) and `ScopeStore`
(`executor.py:1565`). D-9 keeps `StoreSubstrate` alive for exactly those. Folding it into
`RuntimeStore` would merge derived-fingerprint storage with runtime truth — the drift this
initiative exists to prevent. Two arguments, two lifetimes, both injected.

`build_engine` is keyword-only for both, so a positional call cannot silently bind the
wrong one.

## 3. New errors — `src/functualize/_types/errors.py`

Two, appended to the existing eighteen:

- `RuntimeStoreCapabilityError` — a required capability is absent. The message names the
  **store**, the **field** and the **config key**, because the reader's question on hitting
  it is always "which setting do I change".
- `CrossAggregateRefusedError` — a transaction spanned two aggregates on a store declaring
  `cross_aggregate_atomicity=False`. Names both aggregates. Raised on commit, before
  anything is applied.

Both subclass `Exception`, matching every other class in that module.

## 4. Public API surface — **unchanged this wave**

`tests/test_public_api_surface.py` enforces the exported surface, and **this wave exports
nothing new**. That is a decision, not an oversight.

D-9 (export `StoreSubstrate` and `Stored` from `functualize.plugin`; deprecate
`ScopeStore` and `RunStore`) is marked *needs a public-API decision* in
`contributor/architecture/research/runtime-persistence-engine-owned/09-decisions.md`. It
is unanswered. Shipping the export as a side effect of a ports ticket would settle a
public-API question by accident, so `functualize.plugin.__all__` is untouched here and
the question is carried to the maintainer in `plan.md` → *Approvals still open*.

The consequence is recorded honestly rather than hidden: `docs/guides/workflows.md:386`
continues to tell plugin authors to import `functualize._types.protocols.StoreSubstrate`,
a private path. That defect survives this wave.

## 5. Backward compatibility

**One thing breaks, for one audience.** `build_engine` is internal (`_app/boot.py`) and
has no public re-export. `rg -c 'build_engine' src/functualize/app/ src/functualize/plugin/`
returns `1`, and the single hit is **a comment**, not a call or an export —
`app/core.py:286` mentions `_app/boot.build_engine` while explaining who calls what.
Checked rather than assumed: an earlier draft of this line claimed `0` and was wrong.
So no user or plugin author can be holding the symbol, and the comment needs updating
with the signature. Pre-release stance applies regardless
(`.spec/CONSTITUTION.md` → *Pre-Release Stance*): no shim, no `DeprecationWarning`.

`app.install_substrate()` and the `substrate_override` slot keep working for the
`FreshStore`/`ScopeStore` path. What changes is that the engine no longer *reads* them —
`_app` does, at step 6.5, and passes the result in. A plugin that installs a substrate at
`APP_READY` is now installing it **after** the engine was wired, which is a behaviour
change a test must pin rather than a doc must mention. T12 owns it.

## 6. Verification

```bash
uv run lint-imports
```
Seven contracts, zero violations — and **not sufficient on its own**.
`exclude_type_checking_imports = true` makes a deferred `_types → _app` import invisible
to it (`contributor/architecture/codemaps/dependencies.md:37`, measured by adding one).
T15 pairs it with an import-line test in the shape of
`tests/types/test_plugin_host_port.py`.
