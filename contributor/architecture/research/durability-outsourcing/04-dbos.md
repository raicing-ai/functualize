# 04 — DBOS

**Level 3 (durable execution), but shaped very differently from Restate.** This is the
strongest candidate in the whole evaluation, and it still does not win. Understanding
exactly *why* is the most useful thing in this folder.

## 1. What it is, for someone who has never heard of it

DBOS Transact is **a library**. There is no server. You decorate functions; it writes
checkpoints to a database; on process start it re-runs anything it finds unfinished.

```python
@DBOS.step(retries_allowed=True, max_attempts=10)
def example_step():
    return requests.get("https://example.com").text

@DBOS.workflow()
def greeting_workflow(name: str, note: str):
    sign_guestbook(name)
    insert_greeting(name, note)
```
— [docs.dbos.dev/python/reference/decorators](https://docs.dbos.dev/python/reference/decorators)

**The data model.** Three tables carry the whole mechanism:

| Table | Holds |
|---|---|
| `dbos.workflow_status` | one row per workflow: UUID, status (`PENDING`/`SUCCESS`/`ERROR`), `executor_id`, `application_version` |
| `dbos.workflow_input` / `workflow_output` | the serialised arguments and result |
| `dbos.operation_outputs` | **one row per completed step**, keyed `(workflow_id, function_id)` |

Cost is exactly "one database write per step … plus two additional database writes per
workflow" ([architecture](https://docs.dbos.dev/architecture)).

`DBOS.launch()` starts, in your process: a `ThreadPoolExecutor`, a startup-recovery
submission that re-invokes `PENDING` workflows for this executor, a queue-polling thread,
a scheduler thread, and a notification-listener thread.

## 2. Why this is the serious candidate

Every objection that killed Restate fails against DBOS:

| Objection to Restate | Does it apply to DBOS? |
|---|---|
| Requires `async` | **No.** The decorators wrap ordinary synchronous functions. |
| Inverts control — a server calls you | **No.** You call your function; it checkpoints on the way through. |
| Needs a separate server process | **No.** It is a library. |
| Needs a network / kills offline | **No.** Since the Python SDK made SQLite the *default* system database (`sqlite:///[application_name].sqlite` when `system_database_url` is unset), a laptop needs nothing. |
| Restrictive licence | **No.** MIT. |

And it brings the one guarantee that is genuinely stronger than anything we have:

> "When a datasource transaction runs inside a DBOS workflow, DBOS records the outcome
> **atomically in the same database transaction**. If the workflow is interrupted and
> replayed, DBOS detects the existing record and returns the stored result without
> re-executing the function — exactly-once semantics even for side effects on your
> application database."
> — [transaction-tutorial](https://docs.dbos.dev/python/tutorials/transaction-tutorial)

That is the outbox problem solved by construction. It is the correct answer, and it is
the answer our own design proposal arrives at independently
([`../runtime-persistence-engine-owned/05-the-design.md`](../runtime-persistence-engine-owned/05-the-design.md) §2.2,
`RuntimeTransaction` with an `EffectWriter`).

**Take this seriously.** If Functualize were being written from scratch today, as a
server-side Python application with a Postgres it already owned, `@DBOS.workflow` would
be a reasonable foundation and this document would read differently.

## 3. Why it still does not fit

### 3.1 The dependency footprint fails the rule we already wrote down

`pip install dbos` pulls: `psycopg[binary]` (a compiled C extension), `sqlalchemy[asyncio]`
(which pulls `greenlet`, also compiled), `websockets`, `click`, `pyyaml`,
`python-dateutil` ([pyproject.toml](https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/pyproject.toml)).

Core today has **four** runtime dependencies, and the one that needed an argument got a
seven-line comment justifying it (`pyproject.toml`, on `cryptography`). The governing
precedent is unambiguous and is written in a `pyproject.toml` we already ship:

> "The reason this is a plugin at all: boto3 and botocore are ~20MB of wheel and a hard
> AWS coupling. `grep -rn boto3 src/functualize/` must stay at 0."
> — `plugins/functualize-aws/pyproject.toml`

So DBOS is a plugin, not core. Which leads directly to the structural problem.

### 3.2 There is no port through which a plugin can install a replay engine

A plugin can install a **substrate** today: `EngineHost.substrate`, at `APP_READY`
(ADR-022). That works because a substrate is *below* everything and the choice moves all
five documents together.

There is no equivalent for an execution engine, and inventing one recreates exactly the
defect ADR-022 was written to remove:

> "A plugin could give a scope SQLite for its **job state** while the **records describing
> that scope** — which steps ran, where the walk stopped, what a human approved — stayed
> on the filesystem. A resumed run then found its steps and not its variables.
>
> Nothing prevented that arrangement; it was what the seam was *for*. **Two seams at two
> levels is how the split brain became reachable.**"
> — `contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md:48-55`

A `functualize-dbos` plugin that replaced the walker would mean: workflow A's steps live
in `dbos.operation_outputs`, workflow B's live in `scopes.json`, and `func builtin data
show` can only see one of them. That is the same bug with a new sponsor.

### 3.3 Its version fence is coarser than ours, and the failure mode is worse

DBOS stamps each workflow with `application_version`, "a hash of the running application
code", and **recovery only resumes `PENDING` workflows whose stamped version matches the
currently-running version**. The documented mitigation is blue/green deployment: keep the
old processes alive to drain their own in-flight work.

Now apply that to a laptop CLI. A user edits an unrelated job, runs `func resume`, and
their parked workflow is a zombie: `PENDING` in the table, gate open, no process that
will ever pick it up — because the version hash moved.

Ours moves only when the *graph* moves, and when it refuses it says so, by name:

```python
class WorkflowGraphChangedError(Exception):
    """A parked walk's graph is not the graph that is loaded now.
    ...
    Names both digests, because the first question is always "what changed",
    and the answer "your workflow" is not one.
    """
```
— `src/functualize/_engine/workflow_validation.py:241-263`

A loud refusal naming both digests beats a silent zombie. This is not a close call.

### 3.4 `pickle` is the default serializer

Confirmed from source — `dbos/_serialization.py` does
`pickled_data = pickle.dumps(data); base64.b64encode(...)`. A portable-JSON mode exists
but is opt-in.

Three consequences for us:

1. Checkpointed payloads become sensitive to Python version and class shape. Move a
   dataclass between modules and old checkpoints stop unpickling — which *compounds* the
   `application_version` problem above rather than being independent of it.
2. Lambdas, file handles, connections and locks cannot cross a step boundary. Our job
   bodies are arbitrary user functions.
3. Our documents are JSON today, inspectable with `cat`. That is a property
   `func builtin data show` depends on and users rely on when debugging.

### 3.5 SQLite mode cannot do the thing we would be adopting it for

From the docs: SQLite is "excellent for prototyping and testing because it requires no
configuration or server. However, because a SQLite database is just a file on disk, it
**can't be used in a distributed setting** where an application runs on multiple servers."

So the laptop story (SQLite) gives up multi-machine, and the multi-machine story
(Postgres) gives up the laptop. The single most valuable thing DBOS could bring us —
durable execution that survives the machine, not just the process — is exactly the thing
that requires the Postgres we cannot mandate.

### 3.6 Version 3.0.0 landed five days before this was written

`dbos` 3.0.0 shipped **2026-09-16** — a major release that "splits workflow inputs and
outputs into their own tables" (a schema migration) and "removes deprecated interfaces
and legacy components". The preceding cadence is roughly weekly.

That is a healthy project. It is not a stable foundation for a framework whose own
persistence layer is what we are trying to stop churning.

## 4. Could DBOS be our *backend store*?

No, for the same structural reason as Restate, though its surface looks more tempting.

`DBOS.set_event()` / `get_event()` and `send()` / `recv()` are real durable primitives —
but they are keyed by workflow UUID and live in `dbos.workflow_events` and
`dbos.notifications`. They are workflow-communication channels, not a document store, and
they are garbage-collected under the same retention policy as the workflow rows (default
threshold: 1M rows).

`fresh`, `scopes`, `runs` and `shell-history` have no home there.

## 5. The one idea worth stealing

Do not adopt DBOS. **Do adopt its transaction guarantee**, which we can implement in a
SQLite substrate in far less code than integrating the library would take:

> the application's state change and the durability record commit in **one** database
> transaction, so a crash cannot separate them.

Our existing design proposal already has the shape for this — `RuntimeTransaction` with
`runs`, `workflows`, `inputs`, `events` and `effects` writers that commit together
([`../runtime-persistence-engine-owned/05-the-design.md`](../runtime-persistence-engine-owned/05-the-design.md) §2.2).
What DBOS contributes is the **evidence that it is the right shape**, from a team whose
entire product is that observation.

That is a citation in an ADR. It costs nothing and it is worth more than the integration.

## 6. Verdict

| Question | Answer |
|---|---|
| As a backend store? | **No.** Event/message tables are workflow-keyed and retention-bounded. |
| As a durability provider (level 3)? | **No** — but on the strongest grounds of any candidate. Blocked by dependency weight, the missing plugin seam, a coarser version fence, `pickle`, and the SQLite/Postgres split that cancels the benefit. |
| Anything to take? | **Yes.** The single-transaction checkpoint guarantee, as a design citation. |

## Facts used, with sources

| Claim | Source |
|---|---|
| Library, no external orchestrator; `DBOS.launch()` starts threads in-process | [dbos.dev/dbos-transact](https://www.dbos.dev/dbos-transact), [`_dbos.py`](https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_dbos.py) |
| One write per step, two per workflow | [architecture](https://docs.dbos.dev/architecture) |
| System tables and their contents | [system-tables](https://docs.dbos.dev/explanations/system-tables) |
| SQLite is the default system DB when unset | [python/reference/configuration](https://docs.dbos.dev/python/reference/configuration) |
| SQLite "can't be used in a distributed setting" | docs.dbos.dev, quoted in the research |
| `@DBOS.transaction` commits write + checkpoint together | [transaction-tutorial](https://docs.dbos.dev/python/tutorials/transaction-tutorial) |
| Plain `@DBOS.step` is at-least-once | [step-tutorial](https://docs.dbos.dev/python/tutorials/step-tutorial) |
| `application_version` gates recovery; blue/green is the mitigation | [production/workflow-recovery](https://docs.dbos.dev/production/workflow-recovery) |
| `SELECT ... FOR UPDATE SKIP LOCKED` + heartbeat lease for queues | [why-postgres-durable-execution](https://www.dbos.dev/blog/why-postgres-durable-execution) |
| Concurrent-execution detection by status check + "parking" | [explanations/concurrent-executions](https://docs.dbos.dev/explanations/concurrent-executions) |
| Default serializer is base64'd `pickle` | [`_serialization.py`](https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/dbos/_serialization.py) |
| MIT licence; deps include `psycopg[binary]`, `sqlalchemy[asyncio]` | [pyproject.toml](https://raw.githubusercontent.com/dbos-inc/dbos-transact-py/main/pyproject.toml) |
| 3.0.0 on 2026-09-16, schema-breaking | [releases](https://github.com/dbos-inc/dbos-transact-py/releases) |
| Self-hosted Conductor is Enterprise-only; Pro $99/mo, Teams $499/mo | [dbos.dev/dbos-pricing](https://www.dbos.dev/dbos-pricing) |

**Not established by the research:** the minimum supported Postgres version; the exact
release in which the Python SDK gained SQLite support; the Python API surface of the
`dbos.streams` table.
