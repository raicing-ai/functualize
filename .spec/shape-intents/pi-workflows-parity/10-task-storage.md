# 10 · Task storage, and the fan-out/reduce design

Exploratory. Not a spec — the shape of the idea, the traps, and what I'd actually build.

---

## 1. Where `tasks-local` stores data today

**Not** in `.functualize/state.json`. It writes to the **State domain** backend:

```
LocalTaskProvider.PREFIX = "tasks:"
  → backend.set(f"tasks:{task_id}", json.dumps({id, title, status, linked_to, notes, creator, created_at}))
```

`_provider.py:21-53`. `list()` scans every `tasks:`-prefixed key and deserializes each one
to filter in Python. The backend arrives by DI at `APP_READY`
(`_plugin.py:57-73`: `backend = app.resolve(StateBackend)`).

So the storage answer depends entirely on which `StateBackend` is wired:

| Wired backend | Where tasks actually live | Survives exit? |
|---|---|---|
| `functualize-state-sqlite` | that plugin's SQLite db (`_plugin.py:123-140`) | yes |
| `InMemoryState` (from `functualize-state`) | RAM | **no** |
| none | `app.resolve(StateBackend)` raises; provider never registers | tasks unavailable |

Two things worth naming:

- **The core runtime envelope and the State domain are different stores.** Workflow scopes
  are in `state.json` (core, unconditional); tasks are in the domain backend (optional,
  four packages deep — [11 §6](11-boundaries.md)). They share no file, no
  lock, no transaction.
- **`list()` is a full scan + deserialize per call.** Fine at tens of tasks. It is the same
  honest-scale assumption the scope store makes, and it will break at the same point.

---

## 2. The idea, restated

A `TaskProvider` that is itself a **multiplexer**: writes fan out to N sinks (memory, a
file, the StateBackend, a remote board), reads reduce back to one list.

This is a good instinct, and it lands on a real problem — but the write half and the read
half have very different difficulty, and conflating them is where designs like this go
wrong.

### Fan-out (write) is easy. Reduce (read) is where the design lives.

Writing the same task to three places is bookkeeping. Reading three places and producing
*one* answer requires deciding, up front:

1. **Who owns identity?**
2. **What is the merge key?**
3. **What happens when two sinks disagree about the same task?**
4. **What happens when a sink contains a task the others have never heard of?**

(4) is the interesting one, because it is the *only* reason to do multi-source reads at
all. If every sink only ever contains what the multiplexer wrote, reading more than one is
pure cost.

---

## 3. Three architectures, in increasing ambition

### A · Primary + projections (write fan-out, single-source read)

One sink is authoritative. It owns ids and answers every read. The others are
**write-only renderings** — a `TODO.md` that a human reads and an editor renders.

- Identity: trivial, the primary owns it.
- Conflicts: impossible by construction.
- Human edits to the projection: **silently lost on the next write.** This must be stated
  loudly or it is a bug factory.
- Failure of a secondary: degraded, never fatal.

This is the materialized-view pattern, it is boring, and it covers what I suspect is
~90% of the actual want: *"an agent keeps a task list; I want to see it in my repo."*

### B · Primary + adopting sources (multi-source read, one writer)

As above, but reads also scan secondary sinks for tasks the primary has never seen, and
**adopt** them: synthesize a stable id from `(sink, content-hash)` or a line's own
`id:` tag, mark them `origin: file`, and on first write promote them into the primary.

- Now a human *can* add `- [ ] rerun migrations` to `TODO.md` and the agent sees it.
- That is a genuinely new capability, and it is the bidirectional bridge people actually
  ask for.
- Cost: an adoption rule, a stable-id rule, and an honest answer for "the human deleted a
  line that the primary still has" (my answer: deletion in a secondary is **not** a
  delete; it is invisible, because a line-based file cannot distinguish "removed" from
  "never written").

### C · Peer sinks with a merge policy (true multi-master)

Every sink is equal; reads reduce across all of them.

This needs conflict resolution, and **the data model cannot currently support any
principled one**:

- **Last-write-wins is not computable.** `TaskItem` has `created_at` and **no
  `updated_at`** (`_types.py:32-44`). Exactly the same defect as the scope record having
  no timestamps ([01 §C.6](01-current-state.md)) — and the same fix is required first.
- **The status lattice is not monotonic.** `PENDING, IN_PROGRESS, DONE, SKIPPED, BLOCKED`
  (`_types.py:9-16`). If status only ever moved forward you could merge with `max` over
  the lattice — a clean, conflict-free join-semilattice. But `BLOCKED` can follow
  `IN_PROGRESS` *and* precede it again. So the elegant CRDT shortcut is unavailable
  without declaring an ordering the enum does not have.

**So C is not buildable today**, and saying so is more useful than designing it. If it is
wanted later, the prerequisites are: `updated_at`, a declared status ordering (or a
`terminal` flag on DONE/SKIPPED), and per-field merge declarations.

**Recommendation: build A, design for B, refuse C until the model earns it.**

---

## 4. The reason this idea is worth more than it looks

Not interop. **Fallback.**

[11 §6](11-boundaries.md) established that durable tasks need four packages,
and that with no `StateBackend` wired they are in-memory and vanish at exit. A **file
sink needs nothing** — stdlib `json` and `pathlib`. So it fills in the missing rung:

| Installed | Task storage today | With a file sink |
|---|---|---|
| `functualize` only | **unavailable** | `TODO.md` — durable, zero plugins |
| `+ functualize-tasks` | in-memory, lost at exit | file — durable |
| `+ -state`, `+ -state-sqlite`, `+ -tasks-local` | SQLite | SQLite, plus a human-readable projection |
| `+ remote` | — | multica / Issues / Taskwarrior |

And note where the file sink could live: **inside `functualize-tasks` itself**, since it
needs no `StateBackend`. That collapses the four-package chain to one for the common case.
That is the strongest argument in the whole idea — it turns tasks from a
four-plugins-deep optional feature into something that works out of the box.

It also softens [08 §4](08-coordination.md)'s reasoning: I argued against
coupling tasks to workflow coordination *because* they were four packages deep. A
one-package durable default weakens that objection — though co-addressing over coupling
still holds for the other reasons (different mutability, different owner, engine never
reads either).

---

## 5. Formats — what each one can and cannot carry

| Format | Fidelity | Human-editable | Round-trip | Verdict |
|---|---|---|---|---|
| **todo.txt** | good — `x` done, `(A)` priority, `+project`, `@context`, and **`key:value` tags carry an id** (`id:a3f9c2`) natively | excellent | **yes** | **best round-trip sink.** The tag extension is the reason: identity survives a human edit. |
| **Markdown `TODO.md`** | poor — `- [ ]` / `- [x]` is binary; `in_progress`/`blocked`/`skipped` are unrepresentable | excellent | one-way | **best projection sink.** Renders on GitHub, familiar to everyone. Ids need an HTML comment or a trailing `<!--id:…-->`, which is ugly but invisible when rendered. |
| **JSON** | full | poor in practice | yes | Fine as the durable local sink. **Do not call it `tasks.json`** — VS Code owns that name in a repo root. `.functualize/tasks.json`. |
| **TaskPaper** | good — `- task @done @tag(value)` | good | yes | Niche but genuinely well-designed; a nice third option, not a first. |
| **Taskwarrior** | full | via `task` CLI | yes | Not a file format — a *remote* sink that shells out. Owns its own UUIDs, which means architecture B, not A. |
| **multica** (your own board) | full | via the board | yes | The natural remote sink. Same shape as Taskwarrior: it owns ids. |

The pairing I would ship: **todo.txt as the round-trip sink, Markdown as the read-only
projection, JSON when fidelity matters.** Never Markdown as the *only* sink — silently
losing three of five statuses is worse than not writing the file.

---

## 6. Traps

### 6.1 Partial write failure is the effects-outbox problem again

Fan out to three sinks, sink two throws — you now have inconsistent state and a caller who
was told `add()` succeeded. This is precisely what pi-workflows' effects outbox exists for
([03 §3](03-pi-workflows.md)), and it would be absurd to build one for a to-do list.

The proportionate answer: **the primary write is the transaction; secondary failures are
degraded-but-non-fatal and are recorded, never swallowed.** A secondary sink must never
fail a job. But `logger.debug` is not "recorded" — that is the [11 §4 P4](11-boundaries.md)
anti-pattern. Surface it where someone will see it.

### 6.2 File sinks need a lock, and the plugin has none

Two agents appending to `TODO.md` concurrently will interleave and corrupt. Core solved
this once already — `state_lock` plus atomic `tmp + fsync + os.replace`
(`state_format.py:178-231`) — and a plugin cannot reach into `_primitives` without
violating the layer spirit.

So either the file sink reimplements atomic-write-under-lock (~30 lines, easy to get
subtly wrong), or **core exposes the lock/atomic-write helpers on the public surface**
(`functualize.app.utils`), which is the better answer and useful well beyond tasks.

### 6.3 The multiplexer must not become a config puzzle

`sinks = [memory, file, state, remote]` with per-sink read/write/merge flags is a
combinatorial surface that nobody will get right. Keep it to one declaration:

```toml
[tasks]
provider = "multi"
primary  = "state"          # or "file"
project  = ["todo.txt"]     # write-only renderings
adopt    = false            # architecture B, off by default
```

One primary, a list of projections, one boolean for adoption. If that is not expressive
enough, the answer is a purpose-built provider, not more flags.

### 6.4 It multiplies the "installed but not wired" state

`func builtin domains list` already handles multiple providers by wiring **none** and
telling you to pick (`builtins.py:1457-1479`). A multiplexer that *is* a provider, wrapping
other providers, needs to show up in that listing as one active provider with its sinks
named — otherwise the framework's own capability-introspection surface starts lying.

### 6.5 Do not let it become the coordination channel

A shared, human-editable, multi-writer task file is *very* tempting as an agent
coordination substrate. It is a bad one: no ordering, no identity, no atomicity, no
reader position. That is what scope-bound notes are for
([08 §3](08-coordination.md)). Tasks are a checklist; notes are the reasoning.
Keep the split.

---

## 7. What I would actually build, in order

1. **`updated_at` on `TaskItem`, and a `terminal` marker on DONE/SKIPPED.** Two fields.
   Without them no merge policy beyond primary-wins is ever principled, and adding them
   later is a format change to every stored blob.
2. **A file sink inside `functualize-tasks`** — JSON under `.functualize/`, atomic write,
   locked. **This alone is the highest-value piece**: durable tasks with one package
   instead of four.
3. **`MultiTaskProvider`, architecture A only** — one primary, N write-only projections,
   secondary failures degraded and surfaced.
4. **todo.txt as the first projection**, with `id:` tags — because it is the one format
   that can later become a *source* without redesign.
5. **Adoption (architecture B) behind a flag,** once (1) exists and someone has actually
   asked to hand-edit a file and have the agent see it.
6. **Remote sinks (multica, Taskwarrior)** last, and as architecture B by nature — they
   own their own ids, so they are never simple projections.

Explicitly not doing: peer multi-master (C), per-field merge policies, delete propagation
from line-based sinks, or a task-shaped coordination channel.

## 8. The honest summary

The fan-out half is easy and worth it. The reduce half is only worth it for **one** case —
a human hand-editing a file that the agent then adopts — and that case needs `updated_at`
first. Everything else people imagine wanting from "read all sinks" is really wanting a
projection they can read, which architecture A gives them for a fraction of the cost.

And the part of the idea that most deserves building has nothing to do with fan-out at
all: **a file-backed task sink that needs no plugins** would fix the real defect, which is
that tasks are currently four optional packages deep and silently ephemeral without them.
