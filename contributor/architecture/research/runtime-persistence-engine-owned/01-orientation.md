# 01 — Orientation

**Audience:** you joined this week and have not read the codebase.
**Goal:** after this page, every other page in this folder makes sense.
**Everything here is verifiable.** Each claim names a file and line. Go and look.

---

## 1. What Functualize is

A Python framework for writing **jobs** — functions that do a unit of work — and
**workflows** — graphs of those jobs with branching, human approval gates and
resumption.

```python
from functualize import job

@job
def deploy(env: str) -> str:
    return f"deployed to {env}"
```

Two things can run that job, and the distinction matters constantly:

```
func deploy --env prod              ./main.py deploy --env prod
└── the `func` CLI, which discovers  └── an embedded FunctualizeApp the user
    your file from the filesystem        constructed in their own script
```

They are **not two views of one program**. `func` has a whole pre-boot layer —
filesystem discovery, caching, routing — that an embedded app does not. The shared
part starts at `FunctualizeApp(...)`. This is drawn properly in
[`../../surface-boundary.md`](../../surface-boundary.md), and it is the reason you
will see tests that run the same job "through two doors".

Everything below the boundary funnels into one place:

```
any surface  ->  RunRequest  ->  JobExecutionEngine.run()  ->  JobResult
```

`RunRequest` is a frozen dataclass (`src/functualize/_types/run_request.py:191-221`)
carrying `job_name`, `surface`, `kwargs`, `parent_scope`, `workflow_scope_id`,
`parent_run_id`, `invoke_depth` and a dozen more fields. One request type, one engine
entry point. That invariant is recorded in
[`../../../adr/020-engine-entrypoint-encapsulation.md`](../../../adr/020-engine-entrypoint-encapsulation.md)
and enforced by an import-linter contract ("Delivery adapters go through the request,
not the engine", `pyproject.toml:368-380`).

**Why you care:** any persistence design must sit behind that single path. If a
design adds a second way for work to reach storage, it has broken the invariant the
whole architecture is built on.

## 2. The five nouns

You will drown in these words in every other document. Learn them here.

| Noun | What it is | Where it lives on disk |
|---|---|---|
| **Run** | One execution of one job. Has an id, a status, a surface, a parent. | `runs` document |
| **Scope** | The durable container a run executes *in*. Holds step records, branch decisions, gate payloads, the walk position and a lease. | `scopes` document |
| **State** | Key/value data a job body wrote via `rc.state.set(...)`. Survives a resume. | `scope-state/<scope_id>` document |
| **Gate** | A pause point in a workflow waiting for a human or an agent to supply input. | inside the scope record |
| **Fingerprint** | Derived data saying "this job already ran with these inputs" — a cache. | `fresh` document |

Two of those have opposite durability rules, and the difference is load-bearing:

- `scopes` holds **records**. Not recomputable. If the file cannot be parsed, the
  store **refuses** rather than pretending there is nothing
  (`_primitives/scope_store.py:204-227`).
- `fresh` holds **derived** data. Recomputable. A bad read **degrades to empty**.

Getting that backwards silently loses a user's work. The codebase is careful about
it; any new design must be too.

### A scope record, concretely

```python
# src/functualize/_primitives/scope_store.py:81-110
def _blank_scope() -> dict[str, Any]:
    return {
        "workflow": None,
        "status": "running",
        "steps": {},
        "branches": {},
        "gates": {},
        "position": None,
        "epilogue": None,
        "tool_calls": [],
        "state": {},        # <- see the trap below
        "events": [],
        ...
    }
```

> **Trap for a newcomer.** That `"state": {}` field carries a twelve-line docstring
> explaining that job state lives here beside `steps` and `gates`. **It does not.**
> State moved to its own per-scope document in a change called
> `scope-record-lifecycle`/T3, and `scope_store.py:102` is now the only place the key
> appears — nothing reads it, nothing writes it. Every new scope record on disk
> carries a dead empty dict and an authoritative docstring that is wrong. The same
> stale explanation appears again at `_engine/capabilities/state.py:1-33`.
>
> This is the first thing you should verify yourself, because it teaches the habit
> this folder is built on: **the comments in this codebase are unusually good and
> occasionally out of date, so check the code.**

## 3. Where the data actually goes

All five documents go through one port, `StoreSubstrate`
(`src/functualize/_types/protocols.py:760-900`). Six methods:

```python
class StoreSubstrate(Protocol):
    def read(self, key: str) -> Stored | None: ...
    def write(self, key: str, payload: dict[str, Any], *,
              expect: int | None = None) -> bool: ...
    def lock(self, *keys: str) -> AbstractContextManager[None]: ...
    def clear(self, key: str) -> str | None: ...
    def delete(self, key: str) -> bool: ...
    def describe(self, key: str) -> str: ...
```

A **key is not a path**. `"fresh"`, `"scopes"`, `"runs"`,
`"scope-state/<scope-id>"`, `"shell-history"` are logical names; a backend maps them
however it likes (`_primitives/fresh_format.py:85`, `run_format.py:73`,
`scope_format.py:68`, `scope_state_store.py:46`, `shell_history.py:51`).

Two implementations exist:

| | `JsonFileSubstrate` | `SQLiteSubstrate` |
|---|---|---|
| Where | `_primitives/substrate.py:72` | the SQLite plugin — see the branch note below |
| Layout | one `.json` file per key | one row per key in `documents(key, payload, revision)` |
| `lock()` | `fcntl.flock` on a `.lock` sidecar per key | `BEGIN IMMEDIATE` — one transaction |
| `write(expect=)` | compares a content hash | a real SQL compare-and-swap |

> **Branch note — you will `ls` and not find it.** This branch is three commits
> behind `master`, and PR #45 renamed and moved the SQLite plugin. On
> `feat/substrate-sqlite` it is `plugins/functualize-state-sqlite/`
> (package `functualize_state_sqlite`, class `SQLiteStatePlugin`, entry-point group
> `functualize.state_providers`). On `origin/master` it is
> `plugins/substrates/functualize-substrate-sqlite/` (package
> `functualize_substrate_sqlite`, class `SQLiteSubstratePlugin`, group
> `functualize.plugins`). **Every path in this folder that begins
> `plugins/substrates/` is an `origin/master` path.** Use
> `git show origin/master:<path>` to read it without switching branches.

**The choice is made once per app.** A plugin installs a substrate at the `APP_READY`
boot hook, and every store follows. That is
[ADR-022](../../../adr/022-storage-is-a-substrate-not-a-key-value-domain.md), and its
whole point is that you cannot end up with scope records in one backend and their job
state in another — a resumed run that finds its steps but not its variables.

## 4. The layers, and the one rule you cannot break

`src/functualize/` is split into private (underscore) and public packages:

```
_types/       vocabulary + Protocols.  Imports nothing internal. Stdlib only.
_primitives/  small building blocks.   Imports only _types.
_events/      the event bus.           Imports _types, _primitives.

_discovery/  _config/  _gate/  _engine/  _plugins/     <- PEER LAYERS
     these five may import _types, _primitives, _events — and NEVER each other.

_app/         the composition root.    Imports everything internal.
_cli/         the `func` command.      Imports ONLY public packages.

app/ job/ plugin/ types/ workflow/ testing/ ui/        <- PUBLIC
```

Full table: [`../../../reference/layer-rules.md`](../../../reference/layer-rules.md).

**This is mechanically enforced.** `pyproject.toml:249-390` declares seven
import-linter contracts, and CI runs `uv run lint-imports`. All seven currently pass.
You cannot merge a peer-layer cross-import; the build stops you.

**Why you care:** the first design proposes adding a *sixth* peer layer called
`_persistence`. Whether that is legal, and whether it is wise, are two different
questions — and the answers differ. See
[`04-three-designs-compared.md`](04-three-designs-compared.md) §3.

## 5. How a job actually runs

`JobExecutionEngine._execute_lifecycle` is a twenty-step linear procedure
(`_engine/executor.py`). **Almost every step's position is a constraint, not a
preference** — a dependency must run before the freshness check because it may
regenerate a file the check fingerprints, and so on. The order is documented at
[`../../../reference/execution-lifecycle.md`](../../../reference/execution-lifecycle.md)
and **asserted by `tests/engine/test_lifecycle_order.py`**, which is what makes it a
contract rather than a comment.

Remember that test. It is the single strongest argument in
[`04-three-designs-compared.md`](04-three-designs-compared.md) §3.

For a `@workflow`, an extra machine runs first:

```
WorkflowOrchestrator.prelude
  └── WorkflowWalker           walks the declared graph
        └── FrontierWalk       claims the scope, records steps, decides the next node
              └── ScopeStore   reads and writes the scope document
```

`FrontierWalk.claim()` (`_engine/frontier.py:160-192`) is the **only** place in the
entire codebase that takes a lease. Note what follows: a plain job that writes
`rc.state` never claims anything.

## 6. Leases and fencing — the one concept to actually understand

Two runners must not walk one workflow at the same time. The mechanism is **not** a
lock. It is a **monotonically increasing generation number**.

The reasoning, from `_primitives/lease.py:12-30`, is worth reading in full once:

> Two runners disagree about the time — clock skew, a VM suspended and resumed, an
> NTP step. Runner A believes its lease is live; runner B believes A's lease expired
> and takes it. Now both are walking, and **nothing in an owner-plus-expiry scheme
> can tell them apart**, because each one's evidence is its own clock.
>
> A **monotonically increasing generation** fixes it without trusting any clock.

So: every claim increments the generation. A write carries the generation it was
acquired under. The store refuses a write whose generation is not current.

```python
# src/functualize/_primitives/lease.py:282-305
def check_generation(scope_id, existing, generation) -> None:
    if existing is None:
        raise StaleGenerationError(...)
    if existing.generation != generation:
        raise StaleGenerationError(...)
```

And the check runs in exactly one place, deliberately —
`ScopeStore._mutate` (`_primitives/scope_store.py:235-266`):

> Putting the check on each of the eleven write methods would fence them all today
> and miss the twelfth, added next month by someone who did not know the rule. One
> check here means a write path added tomorrow is fenced the day it is written.

That is excellent reasoning and the implementation is sound **for the writes that go
through it**. [`03-the-four-defects.md`](03-the-four-defects.md) is about the ones
that do not.

## 7. Running things yourself

```bash
uv sync --all-packages --all-extras   # you need this or plugin tests silently skip
uv run pytest tests/ -x -q
uv run pytest tests/primitives/ tests/workflow/ -q   # the persistence-relevant ones
uv run lint-imports                                   # the seven layer contracts
```

To see the live CLI or TUI render, use the `observe-tui` skill
(`.agents/skills/observe-tui/SKILL.md`). Never in automated tests — it is for looking
at things with your own eyes.

> **Skip trap.** `tests/spec/test_a_substrate_plugin_loads_through_its_entry_point.py`
> (on `origin/master`, not on this branch)
> carries `pytestmark = pytest.mark.installed_plugins` and an
> `importorskip`. Without `--all-packages` it **skips**, and a green run proves
> nothing about whether the SQLite plugin activates. This has bitten before.

## 8. Glossary

| Term | Meaning |
|---|---|
| **Substrate** | The storage port. Where documents live. One choice per app. |
| **Scope** | The durable container a run executes in. Has an id, a status, a lease. |
| **Lease / generation** | The fencing token. Increments on every claim. A write carrying a stale generation is refused. |
| **Frontier / walk** | The workflow graph traversal. `FrontierWalk` owns claim, record, position. |
| **Gate** | A workflow node that blocks for human or agent input. |
| **Batch** | `ScopeStore.batch()` — hold the lock, mutate in memory, write once on clean exit. |
| **Surface** | Which door a run came through: `func.job`, `mcp`, `http`, `lambda`, `invoke`. |
| **Peer layer** | One of `_discovery`, `_config`, `_gate`, `_engine`, `_plugins`. May not import each other. |
| **Composition root** | `_app/`. The only layer allowed to wire concrete implementations together. |
| **Outbox** | A proposed table holding "an external effect should happen", committed with the state change that caused it. Does not exist yet. |
| **Unit of Work** | A proposed object grouping several repository writes into one transaction. Does not exist yet. |

---

Next: [`02-what-exists-today.md`](02-what-exists-today.md) — what the code actually
does, as opposed to what it is documented to do.
