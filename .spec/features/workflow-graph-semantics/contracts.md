# Contracts — workflow-graph-semantics

External interfaces only.

---

## 1. `functualize.workflow` — loops

```python
@dataclass(frozen=True)
class Loop:
    """A bound on how many times a cycle in the graph may execute."""
    over: str                    # the node the cycle returns to
    max_iterations: int          # required — an unbounded loop is refused
    until: Callable[[Any], bool] | None = None
```

`max_iterations` has **no default**. An unbounded loop in a build tool is a hang, and today an
unbounded cycle is *accepted and silently runs once*, which is the worst of both — see spec
AC-3.

## 2. `functualize.workflow` — failure routing

```python
@dataclass(frozen=True)
class OnFailure:
    """Where control goes when a step raises."""
    source: str
    target: str                                   # or END
    when: Callable[[BaseException], bool] | None = None
```

Absent an `OnFailure`, behaviour is **unchanged**: the walk stops and the scope is `failed`.

> `when` is evaluated **once per scope** and the choice is recorded, exactly as
> `ConditionalEdge`'s condition is (`workflow_walker.py:412-417`). On replay the recorded route
> is **read**, never re-evaluated — *"Calling it and discarding the answer would still run
> whatever side effects it has."* A failure predicate is precisely the kind that pages.

## 3. `functualize.workflow` — notification

```python
@dataclass(frozen=True)
class Notify:
    on: str                      # a derived state: "completed" | "failed" | "blocked" | ...
    to: str                      # an opaque target the provider interprets
    provider: str | None = None  # None = the single registered one
```

An **effect**, so it rides F5's outbox and fires **at most once** across a crash (spec AC-13).

> Not a bus and not a broker — **N8**. `to` is opaque to the engine. *"The moment `to` becomes
> load-bearing routing, you own a broker."*

Providers are named through a table, never imported — the `EXECUTOR_PROVIDERS` /
`STRATEGY_PROVIDERS` shape, joining the parametrized provider-table test F6 introduced.

## 4. Step outcomes — two new values

Persisted step outcomes become:

```
"success" · "failed" · "timed_out" · "cancelled"
```

copying pi-workflows' vocabulary rather than inventing a third (decision **L3**).

**Replay-skip keys on a named set, not a literal:**

```python
TERMINAL_SUCCESS: frozenset[str] = frozenset({"success"})
```

so a future outcome cannot silently become replayable by matching a string comparison nobody
revisited (spec AC-9).

`timed_out` is producible only because F5 gives a step a budget — as a **lease expiry**, not
preemption.

## 5. `RunStatus` — unchanged

`SUCCESS · FAILURE · BLOCKED · SKIPPED · RUNNING · CANCELLED · TIMEOUT · UNKNOWN · REFUSED`,
with `.resumable` and `.ran`.

> It has **no `.ok`** — that is on `WalkReport` (`workflow_walker.py:138-141`). A design
> assuming `RunStatus.ok` is designing against a method that does not exist.

Step outcomes are a **different vocabulary** from run statuses and stay so.

## 6. CLI and MCP — `watch`

```
func builtin workflow watch <scope-id> [--format text|json]
```

Follows F5's event stream; renders the graph advancing, including through a resume.
`--format json` emits one JSON object per event, newline-delimited, so it is pipeable.

MCP gains `watch_workflow` returning a bounded event page — **verb for verb** (decision
**A3**), pinned by the parity test **A7** already in the suite.

`watch` on a scope with **no live lease** reports it parked, not running (spec AC-12) — which
is the whole reason this could not exist before F5.

## 7. Derived state — unchanged

`waiting · ready · running · completed · stalled · failed · cancelled`, plus F5's `abandoned`.
This feature adds none.

## 8. Unchanged

- `Step`, `Gate`, `AgentStep`, `Edge`, `ConditionalEdge`, `END`.
- The walk's BFS, join readiness, and the recorded-branch property.
- `--wf-retry-epilogue`. `--wf-retry-failed` stays withdrawn (**L4**).
- `_execute_lifecycle`'s 20 steps.
