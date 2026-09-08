# 05 · `functualize-tasks` and workflows — the relationship is a string

Short answer: **there is none.** They share one unvalidated string literal and nothing
else. No shared identifier, no shared storage, no code path between them.

---

## 1. What `functualize-tasks` actually is

A **mutable planning scratchpad available inside job execution** — a Tasks *domain*, in
the same sense as the State domain, delivered as a plugin pair:

| Package | Role |
|---|---|
| `functualize-tasks` | The SDK: `Tasks` capability, `TaskItem`, `TaskStatus`, `TaskLink`, `TaskProvider` protocol, event emission |
| `functualize-tasks-local` | One provider — `LocalTaskProvider`, persisting through a `StateBackend` |

API is CRUD plus linking (`_tasks.py`): `add`, `list`, `update`, `delete`, `link`. Every
mutation emits a structured event (`tasks.task.created`, `.updated`, `.completed`,
`.deleted`) on a duck-typed EventBus. Storage is provider-delegated, so the domain is
backend-agnostic.

It is a **job-time capability**, not an orchestration primitive. A job injects `Tasks`
and keeps a to-do list while it runs. Nothing schedules from it, nothing blocks on it,
nothing routes on it.

## 2. The entire connection to workflows

`TaskLink.kind` is documented as `"job" | "workflow_step" | "job_phase"`
(`_types.py:20-29`):

```python
@dataclass(frozen=True)
class TaskLink:
    kind: str   # "job" | "workflow_step" | "job_phase"
    target: str
```

That comment is the whole relationship. Verified by exhaustive search — every occurrence
of `workflow_step` in the repository is one of:

| Location | What it is |
|---|---|
| `functualize-tasks/_types.py:24,28` | the docstring and the comment above |
| `functualize-tasks/_tasks.py:140,235` | two docstrings repeating it |
| `functualize-mcp/_task_tools.py:125,156` | the `add_task` tool's parameter help |

**Nothing else.** Specifically:

- `kind` is typed `str`. Nothing validates it against that set of three.
- `target` is a free string. Nothing resolves it to a scope id, a node name, or a step
  record key. The workflow step-record key format is `"<node>::"`
  (`workflow_walker.py:466-473`) and no task code knows that.
- `src/functualize/` contains **zero** references to `functualize_tasks`. The engine,
  walker, runner and frontier have never heard of tasks.
- Storage is disjoint: tasks go through a `StateBackend` in the State domain;
  workflow scopes live in `.functualize/state.json`'s `scopes` section
  (`state_format.py:56`). Different sections, different accessors, no foreign key.

(Unrelated near-miss: flow-viz reads `descriptor.workflow_steps`
(`functualize-flow-viz/plugin.py:348`) — a *descriptor* attribute for deciding whether
to draw a tree. Different concept, similar name.)

## 3. So what is the relationship *supposed* to be?

Two coherent readings, and the codebase has not chosen:

**(a) Tasks as a workflow's observable plan.** A workflow's steps produce tasks; the
task list becomes the human-readable projection of a run. This is close to what
pi-workflows gets from `WORKFLOW_UPDATES.md` — durable non-terminal progress published
mid-step, which *"does not complete a step"*. Under this reading `TaskLink(kind=
"workflow_step")` should carry `"<scope_id>/<node>"` and `list_tasks` should filter by
scope.

**(b) Tasks as a scratchpad, orthogonal to workflows.** What the code does today. The
link kinds are a labelling convenience with no semantics, and that is fine.

Reading (b) is defensible and cheap. But then **the `"workflow_step"` link kind should
be deleted from the docs**, because right now it advertises an integration that does not
exist — an agent reading `add_task`'s tool description will reasonably believe linking a
task to a workflow step does something.

## 4. If you want (a), the cheapest honest version

Do **not** build a tasks↔walker integration. Instead:

1. **Give the link a real address.** `TaskLink(kind="workflow_step", target=f"{scope_id}/{node}")`,
   with a documented format and a helper that builds it. Still no engine coupling — the
   task domain just stores a string it can now be filtered on.
2. **Filter on it.** `tasks.list(linked_to=...)` and the MCP `list_tasks` gain a link
   filter. Pure provider work.
3. **Let the workflow write them, not the framework.** A step job that wants a task
   trail injects `Tasks` and writes one. That keeps the walker ignorant of tasks —
   which is right, and is the same boundary pi-workflows draws when it says the graph
   engine does not import the resource-manager runtime (`RESOURCE_MANAGERS.md`).

The thing to resist is making the walker emit tasks automatically. That is the
"hidden polling, implicit retries, automatic command generation" pi-workflows'
design philosophy explicitly names as the anti-pattern, and functualize's own
constitution says the same thing as *explicit over hidden*.

## 5. Recommendation

Lowest-cost correct action, in order:

1. **Decide and document.** One paragraph in the tasks README stating that tasks are a
   job-time scratchpad with no engine coupling.
2. If (b): **drop `"workflow_step"` from the three docstrings and the MCP tool help.**
   It is currently the only thing implying a relationship, and it implies a false one.
3. If (a): do §4 — address format, filter, author-written. Nothing in the engine.

Either way this is a documentation-weight decision, not a roadmap item. It does not
belong in the parity work; it belongs in the next docs sync.
