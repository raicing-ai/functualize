# 03 — The four defects

**Every defect here is in shipped code on `origin/master`.** None is a disagreement
about design. Each comes with a script you can paste into a file and run, and the
output shown is real output from running it.

These matter to a *design* document because the first design's Wave 3 imports the data
these defects are writing. A migration cannot verify data whose source is corrupt.

Run everything from the repository root with `uv run python <file>`.

---

## B1 — The fencing generation does not cover `rc.state`

### What is wrong

[`01-orientation.md`](01-orientation.md) §6 explained the fencing rule: a write
carrying a stale generation is refused, and the check lives in one place so that new
write paths inherit it.

`rc.state` is not one of those paths. It goes to a different store object, on a
different document, and that store has never heard of generations:

```bash
$ grep -c generation src/functualize/_primitives/scope_state_store.py
0
```

So a runner that has been **provably evicted** — one whose step-record writes are
correctly refused — can still overwrite the live holder's job state.

### Reproduce it

```python
# defect_b1.py
import tempfile
from pathlib import Path
from functualize._primitives.scope_store import ScopeStore
from functualize._primitives.substrate import JsonFileSubstrate
from functualize._primitives.lease import StaleGenerationError

root = Path(tempfile.mkdtemp())
sub = JsonFileSubstrate(root)

a = ScopeStore(sub); a.ensure_scope("wf")
la = a.claim_scope("wf", owner="runner-A"); a.hold("wf", la.generation)
a.set_state("wf", "rows", "written-by-A-while-holder")

b = ScopeStore(sub)
lb = b.claim_scope("wf", owner="runner-B", force=True); b.hold("wf", lb.generation)
print(f"A holds generation {la.generation}; B now holds {lb.generation} -> A is stale\n")

try:
    a.set_position("wf", "step-by-stale-A")
    print("  record write  : ACCEPTED")
except StaleGenerationError:
    print("  record write  : REFUSED    (StaleGenerationError)")

try:
    a.set_state("wf", "rows", "OVERWRITTEN-BY-STALE-A")
    print("  state write   : ACCEPTED")
except StaleGenerationError:
    print("  state write   : REFUSED    (StaleGenerationError)")

print(f"\n  value B now reads back: {b.get_state('wf','rows')!r}")
```

```
A holds generation 1; B now holds 2 -> A is stale

  record write  : REFUSED    (StaleGenerationError)
  state write   : ACCEPTED
  value B now reads back: 'OVERWRITTEN-BY-STALE-A'
```

### Why it happens

```python
# ScopeStore.set_state — _primitives/scope_store.py:520-525
def set_state(self, scope_id: str, key: str, value: Any) -> None:
    self._state_store(scope_id).set(key, value)     # -> ScopeStateStore

# ScopeStateStore._mutate — _primitives/scope_state_store.py:144-152
def _mutate(self, mutate: Any) -> None:
    if self._batch is not None:
        mutate(self._batch); return
    with self._substrate.lock(self._key):
        state = self._load()
        mutate(state)
        self._substrate.write(self._key, {"state": state})   # no fence, no expect=
```

Compare with the guarded path at `scope_store.py:250-266`. The fence is simply not
there.

### What it falsifies

- The first design's data model says of the `scope_state` table: "unique scope+key;
  **writes require current fence**" (`../runtime-persistence/11-data-model-and-transactions.md`).
  Today they do not.
- The first design's capability table rates the document adapter **`fencing: yes`**
  (`../runtime-persistence/10-target-architecture.md`). It is not yes.
- The earlier adversarial review found the *walk-log* fencing hole (its C-06) but not
  this one, which is larger: walk events are observations, `rc.state` is the user's
  data.

### Status on master

Unchanged. `scope_state_store.py` does not appear in
`git diff --stat HEAD...origin/master`.

---

## B2 — The "fail closed" substrate install is inert

### What is wrong

PR #45 changed the SQLite plugin so an install failure **raises** instead of being
logged, and the docstring explaining the reversal is emphatic and correct:

```python
# plugins/substrates/functualize-substrate-sqlite/.../
#   _plugin.py:86-90   (origin/master)
"""**A failure to install is raised, not logged** (`plugin-taxonomy`/T7, AC-4).
This reverses an earlier decision, and the reversal is the point: the swallow
read as "a working program with a note in the log rather than a boot that dies
over a storage preference", which is only true if the fallback is harmless. It
is not. A user who installed a storage plugin and silently got the filesystem
has their project's data in a place they did not choose and were not told about
"""
```

**The raise never escapes.** The plugin installs itself as an `APP_READY` hook, and
the boot loop that calls `APP_READY` hooks catches `Exception`:

```python
# origin/master:src/functualize/_app/boot.py:879-882   (and :467-473, static boot)
try:
    hook(app)
except Exception as exc:
    logger.warning(f"APP_READY hook {hook_name!r} raised: {exc}")
```

The swallow moved one frame up. It was not removed.

### Reproduce it

Against master's real code, not a stand-in:

```bash
git archive origin/master | tar -x -C /tmp/master-tree
cd /tmp/master-tree
```

```python
# defect_b2.py
import logging, tempfile, pathlib
logging.disable(logging.CRITICAL)
from functualize import FunctualizeApp
from functualize.app.config import PluginSources
from functualize_substrate_sqlite import SQLiteSubstratePlugin

plugin = SQLiteSubstratePlugin()
# a directory component that is actually a file -> SQLiteSubstrate(...) raises
blocker = pathlib.Path(tempfile.mkdtemp()) / "not-a-dir"
blocker.write_text("i am a file")
plugin._db_path = lambda app, _p=blocker: _p / "sub" / "state.db"

try:
    app = FunctualizeApp("probe",
        plugin_sources=PluginSources(explicit_plugins=[plugin]))
    print("BOOT SUCCEEDED despite the substrate plugin raising.")
except Exception as exc:
    print(f"BOOT FAILED as intended: {type(exc).__name__}: {exc}")
    raise SystemExit(0)

print("  plugin._substrate   :", plugin.substrate)
print("  engine is running on:", type(app.execution_engine.substrate).__name__)
```

```
BOOT SUCCEEDED despite the substrate plugin raising.
  plugin._substrate   : None
  engine is running on: JsonFileSubstrate
```

Run with `uv run --with ./plugins/substrates/functualize-substrate-sqlite python defect_b2.py`.

### What it falsifies

- The first design's invariant: "Explicitly configured persistence **fails boot if
  unavailable**. Silent fallback is permitted only when no provider was explicitly
  requested" (`../runtime-persistence/README.md`).
- Its smell #7 — "the SQLite plugin catches every installation error and falls back to
  files even when SQLite was explicitly selected"
  (`../runtime-persistence/01-current-state-and-blast-radius.md:106-107`) — which
  reads as resolved by PR #45 and is not.

### Why the obvious fix is wrong

Do **not** widen the hook loop to re-raise. `APP_READY` is a general extension point;
a telemetry plugin that throws must not kill the app. The distinction is that
*choosing storage* is not an observation — it is a boot decision with no safe default.
See [`05-the-design.md`](05-the-design.md) §4 for the placement that fixes this
without changing what a hook means.

---

## B3 — There is no cross-document atomicity, and both mechanisms for it are unused

### What is wrong

Covered in [`02-what-exists-today.md`](02-what-exists-today.md) §3 and §5. In short:

- `lock(*keys)` is variadic for exactly this purpose. All **14** call sites pass one
  key.
- `write(expect=)` is a real CAS in both backends. **Zero** production callers.
- Therefore a step record (`scopes`) and the state it produced
  (`scope-state/<id>`) are two documents, two locks, two atomic replaces, with no code
  path that commits them together.

### Check it yourself

```bash
# every lock() call site, with its arity
rg -n '\.lock\(' --include='*.py' src/ plugins/ | grep -v tests/

# every expect= argument in the framework
rg -n 'expect\s*=' src/functualize/ | grep -v 'def write'
```

### What it falsifies

The first design's transaction catalogue
(`../runtime-persistence/11-data-model-and-transactions.md`) lists, for "complete
step": *"step outcome, branch/position, scope status, evidence, outbox intents"* as
one atomic unit. Its Wave 1 then says the document adapter will satisfy the same
semantic contract while "on-disk data and transaction limits are unchanged"
(`12-migration-and-delivery.md`).

Those two statements cannot both hold. The contract requires an atomicity the document
layout does not have and the Wave-1 adapter is explicitly not adding.

This is the single most important structural objection in this folder, and the
independent third design reaches the same conclusion from a different direction —
see [`04-three-designs-compared.md`](04-three-designs-compared.md) §4.

---

## B4 — The claim is not atomic, and the fence is owner-blind

### What is wrong

Two separate bugs that compound.

**(a) The claim is a plain read-modify-write.** `claim_scope` routes through `_mutate`
with `scope_id=None`, so the fencing check is skipped for the claim itself
(`scope_store.py:715-750`), and `_mutate` writes without `expect=`. The only
protection is the advisory lock, which is documented to give up after ten seconds and
to be absent on platforms without `fcntl`/`msvcrt`.

**(b) The fence compares the generation and never the owner:**

```python
# src/functualize/_primitives/lease.py:282-305
if existing.generation != generation:
    raise StaleGenerationError(...)
```

So two runners that both came away believing they hold generation 1 will *both* pass
every subsequent fencing check.

### Reproduce it

```python
# defect_b4.py — two real OS processes
import json, tempfile, contextlib, multiprocessing as mp
from pathlib import Path

def worker(root, barrier, out, idx):
    # neuter the advisory lock exactly the way the shipped code degrades
    import functualize._primitives.fresh_format as ff
    import functualize._primitives.substrate as sub
    @contextlib.contextmanager
    def _noop(path, timeout=10.0): yield
    ff.file_lock = _noop; sub.file_lock = _noop
    from functualize._primitives.scope_store import ScopeStore
    from functualize._primitives.substrate import JsonFileSubstrate
    store = ScopeStore(JsonFileSubstrate(Path(root)))
    store.ensure_scope("wf")
    barrier.wait()
    lease = store.claim_scope("wf", owner=f"runner-{idx}")
    out.put((idx, lease.generation, lease.owner))

if __name__ == "__main__":
    from functualize._primitives.scope_store import ScopeStore
    from functualize._primitives.substrate import JsonFileSubstrate
    root = tempfile.mkdtemp()
    ScopeStore(JsonFileSubstrate(Path(root))).ensure_scope("wf")
    ctx = mp.get_context("fork"); barrier = ctx.Barrier(2); out = ctx.Queue()
    ps = [ctx.Process(target=worker, args=(root, barrier, out, i)) for i in range(2)]
    for p in ps: p.start()
    for p in ps: p.join()
    results = sorted(out.get() for _ in range(2))
    for r in results: print("   ", r)
    print("distinct generations:", len({g for _, g, _ in results}), "of 2")
```

```
    (0, 1, 'runner-0')
    (1, 1, 'runner-1')
distinct generations: 1 of 2
```

And the loser is not merely confused — its writes are accepted, because the number on
the record matches the number it holds.

### What it falsifies

`lease.py`'s own module docstring, which is otherwise the best explanation of fencing
in the codebase:

> So the fencing check is a **comparison of a recorded number**, and holds with
> locking disabled entirely. `tests/primitives/test_lease_fencing.py` asserts that
> directly (risk R-a), because a test that runs with locking working cannot tell the
> two designs apart.

That is true of a *write* under an established generation. It is false of the
*claim*, which is where the generation is established. The test asserts the first and
is read as proving the second.

### Status on master

Unchanged. `lease.py` does not appear in `git diff --stat HEAD...origin/master`.

---

## Summary: what the four cost a migration

| Defect | What a Wave-3 import would inherit |
|---|---|
| B1 | State values written by runners that had already lost the scope, indistinguishable from legitimate ones |
| B2 | Projects whose data is on the filesystem although the operator selected SQLite — so "import from the selected source" imports the wrong source |
| B3 | Step records with no corresponding state, and state with no step, with no way to tell a crash from a normal record |
| B4 | Scope records interleaved by two runners at one generation |

The first design's cutover procedure (`../runtime-persistence/12-migration-and-delivery.md`)
has as step 4: *"verify counts, identities, terminal/live status, state keys, sequence
order, and payload digests"*. None of those verifications can distinguish corrupt
source data from correct source data. That is why
[`08-delivery-and-tests.md`](08-delivery-and-tests.md) puts a repair wave before
everything else.

---

Next: [`04-three-designs-compared.md`](04-three-designs-compared.md).
