# Event Vocabulary and Stability Contract

**Status: normative** · Companion to
[ADR-001](../adr/001-surface-architecture-collapse.md)

The Surface collapse traded ceremony for a different obligation: when surfaces
render from a structured event stream rather than from typed renderer callbacks,
**event names and payload keys become API**. A plugin that reads
`payload["invoke_depth"]` is coupled to that key as surely as it would be to a
method signature. This document is that API's contract.

---

## 1. Event shape

Every event is a `StructuredEvent` (`_events/bus.py`):

| Field | Type | Meaning |
|---|---|---|
| `event_name` | `str` | Hierarchical name, `{domain}.{resource}.{action}` |
| `resource` | `str` | Primary resource identifier (job name, file path) |
| `related` | `list[str]` | Associated resource identifiers |
| `payload` | `dict[str, Any]` | Event-specific data |
| `timestamp` | `float` | Seconds since epoch |
| `trace_id` / `span_id` | `str \| None` | Auto-attached from `PropagationContext` |

Consumers **must** read `payload` defensively (`payload.get(key, default)`).
An absent key is always possible: an older emitter, a partially-populated
event, or a future version that moved the field.

---

## 2. Who receives what — the framework/domain split

This is the single most surprising rule, and the one most likely to waste an
implementer's afternoon.

`RunContext._emit_event` dispatches to two places:

1. **The EventBus** — every event, always. Subscribers via
   `rc.on_event(pattern, cb)` and `EventBus.subscribe` see everything.
2. **Registered surfaces** (`_dispatch_to_surfaces` → `iter_fanout_surfaces`) —
   **domain events only**. Events whose name starts with any
   `RunContext._FRAMEWORK_EVENT_PREFIXES` entry are filtered out:

   ```
   job.execute.    job.teardown.    plugin.    config.    cli.    tui.
   ```

**Consequence:** a `Surface` — and therefore any `LiveConstruct` hosted by a
live zone, since zones forward through `handle_event` — never sees job
lifecycle events. A construct that wants to draw an execution tree from
`job.execute.start` gets nothing. This is deliberate (framework churn would
drown a user-facing surface), and it is why flow-viz's job-lifecycle tree was
dead code long before it became a construct.

To observe lifecycle events, subscribe to the EventBus directly rather than
registering a surface.

---

## 3. Framework event names

Emitted by the framework, delivered to the EventBus only (see §2).

### Job execution

| Name | Payload keys | Notes |
|---|---|---|
| `job.execute.start` | `job_name`, `invoke_depth` | `invoke_depth` is 0 for a top-level run and increments for each `rc.invoke()` level — this is how nesting is expressed. There is **no** separate `invoke.started`/`invoke.completed` pair. |
| `job.execute.end` | `job_name`, `duration_ms`, `status` | `status` is `"success"` or `"failure"`. Emitted for blocked and validation-failed runs too. |
| `job.execute.error` | `job_name` | Error path. |
| `job.teardown.start` / `job.teardown.end` | `job_name` | |

### Other framework domains

`plugin.discovery.*`, `plugin.load.*`, `plugin.registration.*`,
`config.resolution.*`, `config.file.parse.*`, `config.annotation.resolve.*`,
`config.remote.fetch.*`, `cli.parse.*`, `tui.session.*`,
`lifecycle.registry.frozen`, `interactivity.job.submit`.

The authoritative registry is `_events/_catalog_entries.py`.

---

## 4. Domain events (`rc.emit`)

Anything a job emits with `rc.emit(name, resource=..., **payload)` that does
**not** match a framework prefix. These reach surfaces and hosted constructs.

Job authors own this namespace. Recommended shape: `{domain}.{resource}.{action}`
(`upload.chunk.complete`, `migration.table.applied`).

One payload key has cross-cutting meaning consumers may rely on:

| Key | Type | Meaning |
|---|---|---|
| `progress` | `int \| float` | Percent complete, 0–100. Renderers may draw a progress bar. |

---

## 5. Stability contract

Within a major version:

1. **Names are not renamed or removed.** A name that ships is a name consumers
   may match on, including with prefix globs.
2. **Payload keys are not renamed, removed, or retyped.** Additions are allowed
   and are the only expected change — consumers must tolerate unknown keys.
3. **Semantics do not change.** If `status` means "the job's terminal outcome",
   it will not come to mean "the HTTP status of something".
4. **The framework/domain split is part of the contract.** Moving a name across
   the `_FRAMEWORK_EVENT_PREFIXES` boundary changes who receives it, and is a
   breaking change even though the name is unchanged.
5. **Emission order and count are *not* contractual** beyond the obvious pairing
   (a `.start` precedes its `.end`). Do not assume exactly one `job.execute.end`
   per run without checking `job_name`.

Breaking any of 1–4 requires a major version bump and a migration note in
`CHANGELOG.md`.

### Adding an event

1. Register it in `_events/_catalog_entries.py`.
2. Decide the side of the framework/domain split deliberately — a name under an
   existing framework prefix is invisible to surfaces.
3. Add it to §3 or §4 here.

---

## 6. Consumer guidance

- Match names with explicit prefixes (`event_name.startswith("upload.")`),
  not substring checks.
- Read every payload key with a default; never index.
- Treat an unrecognized event as data to display or ignore, never as an error.
- A construct's `handle_event` **must not raise** — zones log and continue, but
  a raising construct still forfeits that event.
