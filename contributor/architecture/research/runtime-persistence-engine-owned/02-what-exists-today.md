# 02 — What exists today

**This document describes shipped behaviour only.** Every statement is either a
citation you can open or a command you can run. Where the code's own documentation
disagrees with the code, both are shown and the disagreement is marked.

Baseline: `feat/substrate-sqlite` @ `8d450ad` (identical to `v0.3.0` for `src/`),
re-checked against `origin/master` @ `8c06198`.

---

## 1. The write path, end to end

```
delivery surface (CLI / MCP / HTTP / Lambda / embedded / Invoke)
   │
   ▼  RunRequest
JobExecutionEngine.run()                         _engine/executor.py:741
   ├── _ensure_scope(request)                    :854   mints a scope if absent
   ├── _open_run_record(request, kwargs)         :799   -> RunStore  (key "runs")
   ├── _execute_lifecycle(...)                   :821   the 20 steps
   │      └── @workflow only:
   │            WorkflowOrchestrator.prelude     workflow_orchestrator.py
   │              └── WorkflowWalker             workflow_walker.py:301
   │                    └── FrontierWalk         frontier.py:139
   │                          └── ScopeStore     (key "scopes")
   │                                └── ScopeStateStore  (key "scope-state/<id>")
   └── finally: _close_run_record / _close_scope / _flush_run_log

EventBus (synchronous, in-process)
   ├── run_log subscriber    buffered, flushed once at run close   _events/run_log.py
   └── walk_log subscriber   write-through, per event              _events/walk_log.py
```

The engine resolves its substrate **once, lazily, on first store access**:

```python
# src/functualize/_engine/executor.py:1509-1527   (branch)
@property
def substrate(self) -> Any:
    if self._substrate is None:
        from functualize._primitives.substrate import substrate_for_project
        chosen = getattr(self.host, "substrate", None)
        self._substrate = chosen or substrate_for_project(self.fresh_root)
    return self._substrate
```

On `origin/master` the host attribute is renamed `substrate_override` and the return
type is narrowed to `StoreSubstrate`; the logic is unchanged.

**Consequence to hold on to:** the engine does not *receive* its storage. It goes and
finds it, later, the first time someone asks. That is the temporal coupling every one
of the three designs is trying to remove, and they remove it differently.

## 2. Where the five documents go

| Key | Store | Rule on an unreadable document | Cap |
|---|---|---|---|
| `fresh` | `FreshStore` | **degrades to empty** — derived data | — |
| `scopes` | `ScopeStore` | **refuses** — records | 500 scopes, terminal-only eviction |
| `scope-state/<id>` | `ScopeStateStore` | **refuses** — records | — |
| `runs` | `RunStore` | — | ring |
| `shell-history` | `ShellHistoryStore` | — | 200 |

The 500-scope cap is worth knowing about because no design currently accounts for it:

```python
# _primitives/scope_format.py — the cap runs inside stamp_scopes(),
# which every ScopeStore write calls, batched writes included.
#   :133  TERMINAL_SCOPE_STATUSES   — only these are eligible for eviction
#   :144  SCOPES_LIMIT = 500
#   :156-185  the eviction
#   :187-197  stamp_scopes
```

A project whose 500 records are all non-terminal stays over cap permanently, and the
records already dropped are gone from any future migration's source data.

## 3. The two safety mechanisms, and how much of the code uses them

The port offers exactly two ways to be safe, and ADR-022 is explicit that this is
deliberate — a filesystem gets mutual exclusion from `flock`, a remote store often
cannot and needs compare-and-swap instead.

### `lock(*keys)` — variadic, and never used variadically

ADR-022 justifies the signature on multi-key atomicity:

> `lock` takes several keys, so a substrate may satisfy it with **one** lock — which
> removes, by construction, a lock-order inversion an external review found between
> the scope lock and the state lock and which no store could fix, because the caller
> chooses which batch to open first.

**Measured: all fourteen call sites in `src/` and `plugins/` pass exactly one key.**

```
_primitives/scope_store.py:263,307          _primitives/fresh_store.py:143,224
_primitives/scope_state_store.py:149,165,227  _primitives/shell_history.py:95,128
_primitives/run_store.py:189,204,367        functualize_tasks_local/_provider.py:64,70
```

So the inversion the ADR describes is unreachable today only because no caller ever
takes two locks — not because the mechanism is in use.

### `write(expect=)` — a real CAS with zero production callers

Both backends implement it properly. `SQLiteSubstrate` does it in one SQL statement;
`JsonFileSubstrate` compares a content hash.

**Measured: `expect=` is never passed anywhere in `src/`.** The only occurrences are
docstrings, the backends' own implementations, and the SQLite plugin's own tests.

The central write path ignores it:

```python
# src/functualize/_primitives/scope_store.py:255-266
def _guarded(envelope): ...
if self._batch is not None:
    _guarded(self._batch)
    return
with self._substrate.lock(self._key):
    envelope = self._load()
    _guarded(envelope)
    self._substrate.write(self._key, stamp_scopes(envelope))   # no expect=
```

**Both backends' safety therefore rests entirely on `lock()`.** For SQLite that is a
real transaction. For the filesystem it is an advisory lock that is documented to give
up:

```python
# src/functualize/_primitives/fresh_format.py:268-289
def _lock_timeout(path, timeout) -> None:
    """Say that the lock was given up on, then let the caller proceed.

    Proceeding is the right default — a stuck lock must not wedge a build — but
    it is also the **one path where a write can be lost**, because two
    processes then read-modify-write the same file with nothing between them.
    """
```

and to be absent entirely on a platform without `fcntl`/`msvcrt`.

## 4. Fencing: what is covered and what is not

Fencing is implemented in one place and covers writes that route through it:

```python
# src/functualize/_primitives/scope_store.py:250-257
def _guarded(envelope: dict[str, Any]) -> None:
    held = self._generations.get(scope_id) if scope_id is not None else None
    if held is not None and scope_id is not None:
        check_generation(scope_id, read_lease(envelope["scopes"].get(scope_id)), held)
    mutate(envelope)
```

Read that carefully. It is a no-op in three situations, and all three occur in
production:

| Situation | Why the check is skipped |
|---|---|
| `scope_id is None` | `claim_scope` itself passes no scope id — **the claim is unfenced** |
| `held is None` | the store instance never had `hold()` called on it |
| a different store object | `_generations` is per-instance, and fresh `ScopeStore`s are built constantly |

That last one is not hypothetical. `JobExecutionEngine._scope_store()` returns a
**new** `ScopeStore` every call, and says so:

```python
# src/functualize/_engine/executor.py:1548-1564
# **Not for correctness.** The first version of this said sharing one
# instance would make a parent's fence apply to a child's scope. That was
# true before `durable-run-layer`/T6 keyed the hold per scope and is not
# true now ...
return ScopeStore(self.substrate)
```

And the walk-log subscriber builds another one per event
(`_app/boot.py:140-151`), so every durable walk event is written by a store with an
empty `_generations` map — i.e. unfenced.

**Who actually claims:** exactly one call site, `FrontierWalk.claim()`
(`_engine/frontier.py:183-190`). Therefore:

- A `@workflow` walk is fenced for its step records.
- **A plain job writing `rc.state` never claims a lease at all.** Two processes calling
  `app.execute(..., workflow_scope_id="x")` — the documented way to share durable
  state across runs — contend with zero fencing.

## 5. Atomicity: there is none across documents

A step record goes to key `scopes`. The state that step produced goes to key
`scope-state/<scope_id>`. These are different documents, different locks, and
different atomic replaces.

```python
# ScopeStore.batch() — _primitives/scope_store.py:291-313
with self._substrate.lock(self._key):     # self._key == "scopes", one key
    self._batch = self._load()
    try:
        yield self
        self._substrate.write(self._key, stamp_scopes(self._batch))
    finally:
        self._batch = None
```

`ScopeStateStore` has its own separate `batch()` on its own key
(`scope_state_store.py:153-170`). **No code path opens both.** The store even
documents them as deliberately different locks (`scope_store.py:541-548`).

Concretely, blocking at a gate is **not** one write. Reconstructed from
`frontier.py` and `workflow_walker.py`, a fresh scope that runs one step and blocks
performs roughly fifteen separate locked read-modify-writes of the whole `scopes`
document. Only three groups are batched:

| Batched together | Where |
|---|---|
| ensure_scope + status RUNNING + position | `frontier.py:314-320` |
| step record + branch + position/terminal status | `frontier.py:354-386` |
| position + status BLOCKED + gate record | `frontier.py:414-422` |
| step record + position + mapped status (failure path) | `workflow_walker.py:1018-1025` |

Everything else — the claim, the graph digest, every emitted event, the lease renewal,
the gate payload deposit, the notification branch record, the release — is its own
write. And one path is worse: the nested-block arm at `workflow_walker.py:767-770`
does `set_position` then `set_scope_status(BLOCKED)` as **two independent writes**
with no batch.

## 6. Status: twelve writers, no transition table

`set_scope_status` assigns a string and validates nothing
(`_primitives/scope_store.py:361-367`).

| Value | Written at |
|---|---|
| `running` | `scope_store.py:85` (the blank-record default), `frontier.py:319` |
| `blocked` | `frontier.py:416`, `workflow_walker.py:770` |
| `completed` | `frontier.py:383`, `workflow_walker.py:419`, `:535`, `executor.py:1029` |
| `failed` | `workflow_walker.py:1025`, `executor.py:1029` |
| `cancelled` | `workflow_walker.py:1025`, `app/_workflow_control.py:443` |

The only write-time precondition in the whole codebase is one line —
`if record.get("status") != "running": return` (`executor.py:1027-1029`). Everything
else that looks like a state set (`LIVE_STATUSES` at `app/_workflow_view.py:47`,
`TERMINAL_SCOPE_STATUSES` at `scope_format.py:133`) is a **read filter**, not a guard.

And there are four parallel vocabularies: the raw string above, `StepStatus`
(`frontier.py:99`), `WalkState` (`frontier.py:91`), and the derived display states
`stalled` / `waiting` / `ready` / `abandoned` that are computed for rendering and
never stored (`app/_workflow_view.py:217-242`).

## 7. Durability is best-effort in thirteen places

The codebase is honest about this — every site carries a comment explaining itself —
but the sum is that **the run log is an observation, not a record**.

| Site | Comment |
|---|---|
| `executor.py:982` | `an observation is never worth a run` — `_open_run_record` returns `None` |
| `executor.py:1032`, `:1061`, `:1073` | same — scope close and run close |
| `executor.py:877` | `a missing scope must not kill a run` |
| `frontier.py:285`, `:298` | lease renew and release |
| `run_log.py:174`, `:194` | per-event buffering, **and the entire batched flush** |
| `walk_log.py:108` | every durable walk event |
| `app/_workflow_control.py:439` | `a store without leases still cancels` — the cancel then proceeds **unclaimed** |
| `notify.py:169` | delivery, *after* the branch was already recorded as `sent` |
| `workflow_validation.py:234` | the graph digest |

Plus `_events/bus.py:404-409`, which catches every subscriber exception — this is what
makes a fenced walk-log refusal invisible to the walk that caused it.

## 8. The SQLite backend

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    key      TEXT PRIMARY KEY,
    payload  TEXT NOT NULL,
    revision INTEGER NOT NULL
);
"""
```

Four properties matter for any design that builds on it:

1. **`lock(*keys)` ignores `keys` entirely.** The body is one `BEGIN IMMEDIATE`, which
   takes SQLite's write lock on the whole database file. Unrelated scopes serialize.
   Measured with two processes: a holder of `lock("scope-state/alpha")` blocked a
   writer of `lock("scope-state/totally-unrelated")` for **3.7 s**, and with a longer
   hold the waiter failed with `sqlite3.OperationalError: database is locked` after
   **10.1 s**.

   This *reverses* the isolation that `scope-record-lifecycle`/T3 bought by giving
   each run its own state file — a property that module's docstring still advertises
   (`scope_state_store.py:11-21`).

2. **Nothing handles `sqlite3.OperationalError`.** There is no
   `except sqlite3.OperationalError` anywhere in `src/`. A busy-timeout expiry
   surfaces a raw storage-engine exception on an unguarded write path.

3. **No schema version, no migration.** `PRAGMA user_version` is 0;
   `CREATE TABLE IF NOT EXISTS` can never migrate an existing table. A changed column
   fails at first read with `no such column: payload`. The repository already does this
   properly elsewhere — `_config/vault.py:417` has a `_SCHEMA_VERSION` and `:727-730`
   an `_upgrade` making exactly this argument.

4. **`clear()` is three autocommit statements** — SELECT, INSERT backup, DELETE — with
   a TOCTOU in the backup-naming loop.

## 9. Three places the documentation and the code disagree

These matter because designs get written from documentation. The first two are claims
that are false on `origin/master`; the third is the opposite — a docstring that is right
and a type annotation beneath it that is wrong.

**"Two processes on different machines can reach the same database."**
`plugins/substrates/functualize-substrate-sqlite/src/functualize_substrate_sqlite/substrate.py:20-22`,
verbatim on master. It is false for a local SQLite file, and two shipped guides act on
it: `docs/guides/workflows.md:366-372` recommends
`db_path = "/mnt/shared/functualize/state.db"` ("Point it wherever your processes can
all reach") and `docs/guides/hosting.md:214-225` pairs that with workers behind a load
balancer. SQLite's WAL mode needs a shared-memory index and is unsafe over NFS/SMB.

The repository's own test says so plainly —
`tests/integration/test_substrate_durability.py:24-30`: "That a *remote* substrate
works. SQLite is still a local file".

**"State lives in `scopes.json`."** `_engine/capabilities/state.py:1-33` and the
docstring on the dead `scope_store.py:102` field. It moved.

**`Stored.revision` is typed `int` and documented as opaque.**
`src/functualize/_types/protocols.py:755-756` declares:

```python
@dataclass(frozen=True)
class Stored:
    data: dict[str, Any]
    revision: int
```

while the docstring seven lines above it (`:748-752`) says:

> "revision: An **opaque token** identifying *this* content. Compare it, pass it to
> `StoreSubstrate.write`; **do not order it or do arithmetic on it**. A filesystem
> derives one from the bytes, **a remote store from its own row version**, and neither
> meaning survives the other."

Nothing is broken today — both shipped substrates happen to produce integers
(`plugins/functualize-state-sqlite/.../substrate.py:112` returns `int(row[1])`). But the
annotation contradicts the contract, and it forecloses the case the contract was written
for: an S3 ETag is a quoted hex string, and for multipart or SSE-KMS objects it is not
even an MD5. **A remote substrate over S3 cannot be written until this changes**
([`../durability-outsourcing/06-s3.md`](../durability-outsourcing/06-s3.md) §3).

The fix is a type alias in `_types` and a `str()` in one substrate. Confirm nothing
depends on the integer first:

```console
$ grep -rn '\.revision' src/functualize plugins --include=*.py
```

This is a latent defect, not a fifth entry in [`03`](03-the-four-defects.md) — that
document is reserved for things that misbehave at runtime today, and this one does not.

## 10. The public surface, which is smaller and stranger than it looks

```
PUBLIC   functualize.app.utils.__all__
           FreshStore (:259)  ScopeStore (:260)  RunStore (:264)  ShellHistoryStore (:265)

NOT PUBLIC   StoreSubstrate — defined only at _types/protocols.py:760
```

So the four **concrete stores** are public API covered by
`tests/test_public_api_surface.py`, while the **port a third-party substrate must
implement** is public nowhere. The only documented way to write one tells the author
to import a private module: `docs/guides/workflows.md:386` — "Implement
`functualize._types.protocols.StoreSubstrate`".

On master this got sharper, not softer: the new public `PluginHost` protocol has

```python
def install_substrate(self, substrate: StoreSubstrate) -> None: ...   # _types/host.py:311
```

naming a type that `functualize.plugin` does not export.

**Why you care:** the first design's cleanup step says "move or delete runtime stores
from `_primitives`". That is a public API break, and none of the three designs costs
it.

## 11. Boot order — the fact that decides one whole argument

```
boot_standard()                                  _app/boot.py:485
  1. core infrastructure                         :516-697
       app._execution_engine = build_engine(app) :614      <-- ENGINE BUILT HERE
  2. provider registry                           :699
  3. observability                               :713
  4. LOAD PLUGINS                                :718-735
  5. config entry points                         :744
  6. RESOLVE CONFIG                              :754-798
  7. AFTER_CONFIG_INIT                           :800
  8. register jobs                               :818
  9. APP_READY hooks  <- the substrate is installed here   :841-857
```

Two consequences, both load-bearing later:

**(a) The engine is built before plugins load and before config resolves.** It
therefore cannot be handed a fully-constructed storage provider today. It already
works around this for config with a late-binding closure:

```python
# src/functualize/_app/boot.py:236-243
def _config_view_factory(*, section_prefix: str) -> Any:
    chain = getattr(app, "_resolution_chain", None) or ResolutionChain([])
    ...
```

`_resolution_chain` does not exist at step 1. The closure reads it at call time.

**(b) Nothing touches the engine between step 1 and step 9.** Grep the span: the only
reference is the assignment itself. So engine construction could simply move later —
which is the cheapest available fix and is what
[`05-the-design.md`](05-the-design.md) §4 proposes.

**(c) An APP_READY hook that raises is swallowed:**

```python
# src/functualize/_app/boot.py:841-857  (branch) — identical on master at :868-884
try:
    hook(app)
except Exception as exc:
    logger.warning(f"APP_READY hook {hook_name!r} raised: {exc}")
```

Hold that thought until [`03-the-four-defects.md`](03-the-four-defects.md) §B2.

---

Next: [`03-the-four-defects.md`](03-the-four-defects.md) — four things that are
broken, each with a script you can run.
