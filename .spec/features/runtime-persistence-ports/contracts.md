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
two things that are not runtime truth: `FreshStore`
(`_primitives/fresh_store.py:68`) and `ScopeStore` (`_primitives/scope_store.py:109`).
D-9 keeps `StoreSubstrate` alive for exactly those. Folding it into
`RuntimeStore` would merge derived-fingerprint storage with runtime truth — the drift this
initiative exists to prevent. Two arguments, two lifetimes, both injected.

`build_engine` is keyword-only for both, so a positional call cannot silently bind the
wrong one.

### 2.1 New port member — `_types/host.py`

`PluginHost` gains a **twelfth** member, `offer_substrate(offer: SubstrateOffer) -> None`,
and the module gains `SubstrateOffer: TypeAlias = Callable[[PluginHost], StoreSubstrate]`.

It sits in the **storage** section beside `install_substrate`, not in `HooksView`, and the
placement carries the argument. A plugin registers a question boot will ask; it does not
register a callback fired at a lifecycle point, and nothing but `_select_runtime_store`
ever invokes it. `HooksView` therefore stays one member and the census sentence —
*"`on_ready` is the only lifecycle hook a plugin registers"* — stays true rather than being
reworded to survive.

`install_substrate` keeps its place for a plugin whose choice needs no configuration. Both
doors append to one claim list, and §5 states what happens when two plugins use them.

Nothing is added to `functualize.plugin.__all__`; §4 is unchanged.

The engine's `substrate` is now a plain attribute, not a property (T12's last letter): the
property had become a field read with a long docstring, and deleting it outright would
have broken `app.substrate` (`app/core.py`) and three suites that read
`engine.substrate`. The engine's readers and the app's facade read the one field.

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
`_app` does, at step 6.5, and passes the result in. **T12 completed that change and
pinned it:**

- The engine resolves nothing, and it cannot be *constructed* without storage: `runtime_store`
  and `substrate` are required keyword-only arguments, so building one outside a boot without
  naming them is a `TypeError` at that call — not a `None` discovered on the first write of a
  run, and not a fallback to `substrate_for_project(self.fresh_root)` or the host's install
  slot. That is spec AC-4's "impossible rather than merely unused", and it is what
  `tests/engine/test_engine_receives_its_store.py` holds: the probes are built on an engine that
  *has* a `fresh_root` and a host that *has* a `substrate_override`, so neither resolution can
  come back unnoticed, plus an AST walk of `_engine/executor.py` for the two names — a restored
  resolution is red, not merely unwritten.
- **The window is a rule now:** a substrate must be installed before step 6.5 selects the
  store. Boot reads the slot once, and `install_substrate` refuses anything later loudly.
  Nothing is half-applied, and a dropped install cannot degrade silently into the
  filesystem.
- **Settled (FUN-17/T12, decided in TD-1).** A config-driven substrate plugin has a moment
  that is both post-config and pre-selection, and it is **step 6.5 itself**: the plugin
  calls `app.offer_substrate(...)` from its registration call, and `_select_runtime_store`
  invokes the offer after `boot.py`'s resolution chain exists and before it selects. The
  plugin never names a boot step; boot asks it. This is ADR-027's *"split selection from
  construction"*, applied to the case that reopened the question, and it is why
  `AFTER_CONFIG_INIT` was **not** used: `invoke_config_event` logs a failing hook at
  WARNING and continues, and storage has no safe default — ADR-027 already rejected
  re-raising out of a general extension point as the wrong lever.
- **One choice, and two claimants is a refusal.** `install_substrate` and
  `offer_substrate` both record a claim. `_select_runtime_store` refuses with
  `SubstrateInstallError` when more than one plugin claims storage, naming all of them —
  "first wins" would be plugin load order deciding storage, which is the accident
  `tests/plugins/test_substrate_choice_is_not_hook_order.py` exists to forbid.
- **Loud at every door.** `install_substrate`'s post-selection refusal now raises
  `SubstrateInstallError` rather than `RuntimeError`, so the `APP_READY` loops' existing
  `except SubstrateInstallError: raise` stops swallowing it; both plugin-registration
  loops (`_plugins/loader.py`, `boot_static`'s explicit loop) re-raise it by name instead
  of logging and continuing; and the offer is invoked inside the deliberately uncaught
  step 6.5. A dropped install can no longer degrade into the filesystem in silence — the
  failure AC-3's detector exists to catch.
- **The static path keeps its zero-filesystem-IO boot.** `JsonFileSubstrate.for_project`
  resolves its directory on first document access rather than at construction, so
  `_select_runtime_store` neither walks nor creates on either path. The backend is still
  chosen at step 6.5; only one substrate's own root is late, which is the narrow form of
  the split ADR-027 sanctions. `boot_standard` still answers the location question once,
  at step 0.5, read-only.

## 6. Verification

```bash
uv run lint-imports
```
Seven contracts, zero violations — and **not sufficient on its own**.
`exclude_type_checking_imports = true` makes a deferred `_types → _app` import invisible
to it (`contributor/architecture/codemaps/dependencies.md:37`, measured by adding one).
T15 pairs it with an import-line test in the shape of
`tests/types/test_plugin_host_port.py`.
