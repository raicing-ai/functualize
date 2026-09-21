# 07 — The design: where each abstraction belongs

This answers the question that was actually asked:

> *"How should we design this? What are the abstractions and at what level? Should
> durability guarantee, persistence be at different abstraction levels?"*

## 1. The answer in one page

**Yes, they belong at different levels — three of them — and the levels are distinguished
by how often the answer changes.**

| Level | The question it answers | Changes | Where it lives | Who may supply it |
|---|---|---|---|---|
| **3 — Execution** | *Does this computation survive the death of its process?* | never | `_engine/` | **nobody but us** |
| **2 — Guarantee** | *What does this store actually promise?* | once per app, at boot | `StoreProfile`, **data** | declared by the substrate, verified by tests |
| **1 — Persistence** | *Where do the bytes go?* | once per app, by config | `RuntimeStore` / `StoreSubstrate` | any plugin |

The load-bearing move is **level 2**, and it is the one most designs miss. A guarantee is
not a method and it is not a docstring. It is **a field with a value, checked at boot**.

That single idea resolves the whole question, because it is what lets level 1 be pluggable
without level 3 having to be. The engine does not ask *what backend is this*; it asks
*does this backend promise what I need*, and boot refuses if the answer is no.

## 2. Why the engine has no plugin seam, on purpose

`02-what-we-already-have.md` established that Functualize already implements durable
execution, and `03`/`04` established that adopting Restate or DBOS replaces that engine
rather than extending it.

So the design rule is:

> **Level 3 has exactly one implementation and no port. A plugin can change where a step
> record is stored. A plugin can never change what it means for a step to have run.**

This is not conservatism. It is ADR-022's finding applied one layer up:

> "A plugin could give a scope SQLite for its job state while the records describing that
> scope … stayed on the filesystem. A resumed run then found its steps and not its
> variables. **Two seams at two levels is how the split brain became reachable.**"
> — `contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md:48-55`

Two *replay engines* at two levels would be worse than two stores, because the split
would be in the semantics rather than in the bytes: `func builtin data show` could render
one workflow's steps and not another's, and neither would be wrong.

**The test for any future proposal:** if it introduces a second way for a workflow to be
durable, it is the ADR-022 mistake wearing a new hat, regardless of how good the vendor is.

## 3. Level 2, concretely: the guarantee is data

The existing design proposal already has this
([`../runtime-persistence-engine-owned/05-the-design.md`](../runtime-persistence-engine-owned/05-the-design.md) §2.1).
The research in `03`–`06` says it needs four more fields, each earned by a specific
finding.

```python
@dataclass(frozen=True)
class StoreProfile:
    """What this store can actually promise. Checked at boot, never probed.

    Every field is a statement a maintainer must be able to defend with a test.
    """

    name: str

    # --- correctness, from the original design -------------------------------
    cross_aggregate_atomicity: bool
    fencing: Literal["none", "process-local", "cross-process"]
    multi_process: bool
    multi_machine: bool
    durable_outbox: bool
    versioned_migrations: bool

    # --- added by this research ----------------------------------------------

    #: Can a transaction hold statements open across a Python decision?
    #: D1 cannot: no BEGIN/COMMIT; everything atomic must be one batch.
    #: 05-cloudflare.md §A.3
    interactive_transaction: bool

    #: Does every operation cross a network? Decides whether the engine may
    #: read-modify-write in a loop, or must buffer and flush once.
    #: 06-s3.md §5 — a 200-transition workflow is 200 round trips.
    remote: bool

    #: Largest single document the backend accepts. D1 caps a row at 2 MB;
    #: SQLite and the filesystem are effectively unbounded.
    #: 05-cloudflare.md §A.5
    max_document_bytes: int | None

    #: Does this store work with no network at all? ADR-015's guarantee is a
    #: property of the *configured* store, and today nothing states it.
    offline_capable: bool

    description: str = ""
```

Filled in from the evidence in this folder:

| | filesystem | SQLite | **D1** | **S3** | **R2** |
|---|---|---|---|---|---|
| `cross_aggregate_atomicity` | `False` | `True` | `True` (batch) | `False` | `False` |
| `fencing` | `"process-local"` | `"cross-process"` | `"cross-process"` | `"cross-process"` | **unknown — blocked** |
| `multi_machine` | `False` | `False` | `True` | `True` | — |
| `interactive_transaction` | n/a | `True` | **`False`** | `False` | `False` |
| `remote` | `False` | `False` | `True` | `True` | `True` |
| `max_document_bytes` | `None` | `None` | **2 MB** | 5 TB | 5 TB |
| `offline_capable` | `True` | `True` | `False` | `False` | `False` |

Read the `fencing` row for R2. It is not `False`; it is **unknown**, because Cloudflare
documents strong read-after-write consistency but does not state that a conditional
`PutObject`'s check and commit are atomic against concurrent writers
(`05-cloudflare.md` §C). A profile field forces that to be answered before a plugin
ships, instead of being assumed by whoever writes the README. **That is the entire value
of making the guarantee data.**

And the enforcement:

```python
require(store.profile, multi_machine=True,
        because="workflow resume across runners was configured")
# -> RuntimeStoreCapabilityError naming the store, the field, and the config key
```

Boot refuses. It does not degrade, and it does not `hasattr`.

## 4. The transaction port must buffer, not stream

This is the one place the research changes a decision that had already been made.

The existing proposal's `RuntimeTransaction` reads naturally as a context manager whose
writers issue statements as you call them:

```python
with store.transaction() as tx:
    tx.workflows.complete_step(cmd)     # issues SQL now?
    tx.events.append(evt)               # issues SQL now?
```

On SQLite that works. **On D1 it cannot** — there is no `BEGIN` to hold open, and the
atomic unit is one `{"batch": [...]}` request
([alpha-migration](https://developers.cloudflare.com/d1/platform/alpha-migration/)).
On S3 it also cannot, for a different reason: there is no multi-key atomicity at all
([S3 consistency model](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html#ConsistencyModel)).

So the port must be **accumulate-then-commit**:

```python
with store.transaction() as tx:
    tx.workflows.complete_step(cmd)     # appends a command to a list
    tx.events.append(evt)               # appends a command to a list
# __exit__ flushes ONE unit: one SQLite transaction, or one D1 batch,
# or — on a store with cross_aggregate_atomicity=False — a documented refusal.
```

**The design already chose command-shaped writers** (`ClaimWorkflow`, `CompleteStep`,
`StartAttempt` — `05-the-design.md` §2.3), and that choice is what makes this possible.
A command is a value; it can sit in a list. A method call that issues SQL cannot.

That is worth recording as a vindication rather than a revision: the command shape was
argued for on readability and testability grounds, and it turns out to be the only shape
that admits a remote backend at all.

**Consequence to state plainly:** a store with `cross_aggregate_atomicity=False` must
*refuse* a transaction spanning two aggregates, not silently apply it in parts. The
filesystem substrate declares `False` today and is where defect B3 lives; a refusal turns
a silent split brain into a boot-time or call-time error naming the store.

## 5. Where durability is *declared* versus where it *happens*

The question "should durability guarantee and persistence be at different levels" has a
sharper form once §3 is in place:

```
    the ENGINE            states what it needs      require(profile, fencing="cross-process")
        │                                                        ▲
        ▼                                                        │
    the PROFILE           states what is promised    StoreProfile (data, tested)
        │                                                        ▲
        ▼                                                        │
    the STORE             does the work              RuntimeStore.transaction()
        │
        ▼
    the SUBSTRATE         moves the bytes            read / write(expect=) / lock
```

Three properties fall out, and each one is a defect we have today:

1. **The engine never names a backend.** Today `_cli/tui/shell_mode.py:312` on master
   writes through a path that bypasses the fenced store — a split brain that exists
   because a caller knew about storage.
2. **A guarantee that is not true is a failing test, not a wrong docstring.** Today
   the SQLite substrate's module docstring **on `origin/master`** (at that branch's path
   `plugins/substrates/functualize-substrate-sqlite/.../substrate.py:20-22`; this branch
   still has it at `plugins/functualize-state-sqlite/`) claims the backend works across
   "different machines" and it does not. A `multi_machine: bool` cannot be wrong in prose.
3. **The substrate stays dumb.** Six methods, no semantics. ADR-022's core finding — "the
   contract can only promise the intersection of every possible backend" — only bites when
   the port carries *meaning*. A port that carries only *documents* is the one thing that
   genuinely survives a filesystem, SQLite, D1 and S3 at once, and `06-s3.md` §2 showed
   five of its six methods map to S3 unchanged.

## 6. The two concrete repairs this research found

Both are small, both are needed regardless of whether any remote backend is ever built.

### 6.1 `Stored.revision: int` must become opaque

```python
@dataclass(frozen=True)
class Stored:
    data: dict[str, Any]
    revision: int          # src/functualize/_types/protocols.py:756
```

Its own docstring says "An **opaque token** … do not order it or do arithmetic on it. A
filesystem derives one from the bytes, **a remote store from its own row version**."
An S3 ETag is a quoted hex string. The type contradicts the contract.

Fix: `Revision = str | int` in `_types`, or `revision: str` with the SQLite substrate
stringifying. Confirm nothing depends on the integer first:

```console
$ grep -rn '\.revision' src/functualize plugins --include=*.py
```

### 6.2 `StoreProfile` needs the four fields in §3

Because without `offline_capable`, ADR-015's guarantee — the whole reason the standalone
binary exists — is enforced by nothing but the fact that no remote substrate has been
written yet.

## 7. What this design deliberately does not do

| Not doing | Why |
|---|---|
| A `DurableExecutionProvider` port | §2. One replay engine, no seam. |
| A generic "remote substrate" base class | The backends differ in what matters (S3 has no multi-key atomicity, D1 has no interactive transaction). A shared base would have to promise the intersection — the exact ADR-022 failure. |
| Making core depend on `httpx`/`boto3`/`cloudflare` | `plugins/functualize-aws/pyproject.toml`: "`grep -rn boto3 src/functualize/` must stay at 0." |
| Letting a remote store be the default | ADR-015. The default is a file; a network store is an operator's deliberate choice. |
| Dual-write or migration-by-shadowing | Already rejected as RP-7 in [`../runtime-persistence/13-decisions-and-research.md`](../runtime-persistence/13-decisions-and-research.md). |

## 8. If someone builds a remote substrate anyway

The order matters, and it is the opposite of the tempting one.

1. **Fix the four defects first** on the substrates we already have
   ([`../runtime-persistence-engine-owned/03-the-four-defects.md`](../runtime-persistence-engine-owned/03-the-four-defects.md)).
   A remote substrate under a broken fence inherits the break *and* adds 50 ms to every
   occurrence of it.
2. **Make the revision opaque** (§6.1) — without it, S3 cannot be implemented at all.
3. **Add the profile fields and the `require()` check** (§6.2) — without them, a remote
   store silently voids the offline guarantee.
4. **Then pick D1**, not S3 and not R2, because it is the only candidate that supports
   atomic multi-document commit (`05-cloudflare.md` §A.1) and needs no port change.
5. **Reuse the SQLite substrate's schema and SQL verbatim.** D1 *is* SQLite; the 225-line
   plugin is most of the work already done.

Steps 1–3 are worth doing whether or not step 4 ever happens. That asymmetry is the
recommendation in `09-verdict.md`.
