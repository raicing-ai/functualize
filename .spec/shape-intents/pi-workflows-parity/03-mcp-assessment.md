# 03 · MCP assessment — reach, naivety, and context cost

Answers three questions: *can an agent run any job over MCP?* · *is the implementation
naive?* · *does it bloat context?*

---

## 1. Can an agent run any job? — Yes, four different ways

`MCPServer._register_tools` (`_server.py:72-108`) registers, in order:

| Group | Count | Gate |
|---|---|---|
| Core | **5** — `discover_jobs`, `get_job_schema`, `run_job`, `run_job_async`, `get_execution_status` | always |
| Task | **4** — `add_task`, `list_tasks`, `update_task`, `plan_tasks` | `functualize_tasks` importable |
| History | **2** — `get_job_history`, `get_execution_detail` | `functualize_state` importable |
| Management | **4** — `mcp_start_server`, `mcp_list_servers`, `mcp_stop_server`, `mcp_get_server_tools` | `enable_management=True` (default False) |
| Workflow | **6** — see [01](01-surface-inventory.md) | always |
| **Per-job** | **one tool per discovered job** | visibility + tag filters |

So a job is reachable by: its own generated tool, `run_job`, `run_job_async`, or (for a
workflow's constituent steps) not at all except through the walk.

**Filtering that exists** (`_config.py:33-39`): `include_tags`, `exclude_tags`,
`exclude_jobs`, plus a per-job `visibility` marker. All opt-in. **The default is: every
visible job becomes a tool.** There is no cap, no "generic door only" mode, and no
lazy/paged tool listing.

---

## 2. Is it naive? — In three specific ways, yes

### 2.1 The per-job tools duplicate the generic door, completely

`run_job(name, config)` reaches every job. `discover_jobs` + `get_job_schema` give
progressive disclosure of exactly the same information the per-job tool schemas carry.
The per-job tools add one capability the generic door lacks — **typed parameters at the
call site**, which lets the client validate before dispatch — and pay for it with a
schema per job in the connect-time tool list.

Both paths funnel to `_execute_job` / `app.execute`, so there is no behavioural
divergence to justify the duplication. `_gate_refusal` even exists specifically because
they *are* redundant (`_tools.py:79-95`):

> *"`run_job` is a generic door to the same room the per-job tools open, so it takes the
> same lock. Without this an agent refused `deploy` as a tool just calls
> `run_job("deploy")` and the gate policy is theatre."*

That comment is the design admitting the duplication.

### 2.2 Metadata is discarded at every execution door

Covered in [01 §C.1](01-surface-inventory.md). `{status, return_value, duration_ms}` and
nothing else, from all four doors. For a workflow this is fatal: `"Blocked"` with no
scope id.

It is also lossy for ordinary jobs — `JobResult.metadata` is where the engine puts
anything a caller might need to act on, and the MCP adapter is the one delivery surface
that throws it away. The CLI's `deliver_job_result` does not.

### 2.3 `run_job_async` has no lifecycle

`_run_async_worker` spawns a `daemon=True` thread (`_tools.py:322-333`) and records into
an in-memory dict. Consequences:

- **No cancellation.** No `cancel_execution` tool. The thread runs to completion.
- **No persistence.** `self._async_executions` dies with the server process; every
  `execution_id` handed out is orphaned on restart.
- **Unbounded growth.** Nothing evicts finished executions.
- **`daemon=True`** means a server shutdown kills in-flight jobs mid-side-effect, with
  no record — the same class of hazard pi-workflows' effects outbox exists to close.

This is the "async" story the previous study cited as evidence that `run_job` is not
merely synchronous. It is closer to fire-and-forget than to a durable run.

---

## 3. Context bloat — the numbers

An MCP client loads the full tool list at connect time and carries it for the session.

**Fixed cost:** 5 core + 6 workflow = **11 tools** always, +4 task, +2 history, +4
management when enabled. Call it 11–21.

**Variable cost:** one tool per discovered job, each carrying a name, a description
assembled from the docstring first paragraph plus `extra_description` plus **examples**
(`_translator.py:186-208`), and a full JSON Schema built from the job's config model
with per-field types, descriptions, defaults and examples (`:229-268`) — plus every
inherited **group option** merged in (`:134-163`).

The description builder appends examples unconditionally, and the schema builder inlines
field-level `description` and `examples`. So the per-job cost scales with how well the
job is documented — **the better a project documents its jobs, the more context every
agent session pays before saying anything.**

For a repository with a few dozen jobs and thorough config models this is a
five-figure-token tool list, none of which the agent asked for, most of which it will
never call, and all of which is already retrievable on demand through `discover_jobs`
and `get_job_schema`.

### The shape of the fix

The framework already has every piece:

1. **A `job_tools` mode in `MCPConfig`** — `"all"` (today's default), `"tagged"` (only
   jobs carrying an opt-in tag), `"none"` (generic door only). `include_tags` already
   implements the mechanism; what is missing is making *off* expressible and making
   *tagged* the recommended default.
2. **Stop appending examples to per-job tool descriptions** when the schema already
   carries them. One is enough for tool selection; the other is for the call.
3. **Return `metadata`** from all four doors, so the generic door loses nothing relative
   to the per-job ones. This is a precondition for (1): today, turning per-job tools off
   costs you nothing *because* both paths are equally lossy — but the moment blocked
   metadata matters, the generic door must carry it.

Note the ordering: (3) is required by [07-roadmap](07-roadmap.md) item 1 anyway, and it
is what makes (1) safe.

---

## 4. What MCP gets right (do not regress these)

- **The gate tool policy is enforced at the funnel, not at each call site.**
  `_execute_job` is *"the one place a job-executing call cannot get past, so there is no
  version of the check a caller can forget to make"* (`_server.py:239-242`). Both the
  generic and per-job doors take the same lock.
- **Bound arguments are made inexpressible, not merely refused.** `_tool_summaries`
  publishes each gate tool's schema **minus** its bound parameters (`:578-607`), so an
  overreaching call cannot be formed. Refusal at dispatch (`:309-323`) is the backstop,
  not the mechanism. This is genuinely stronger than pi-workflows' `allowedTools`, which
  is an allowlist of whole tools.
- **`_topology` falls back to the live declaration** when the discovery cache has no
  workflow shape (`:511-536`) — so a plugin-registered or dynamically-registered
  workflow is still visible to an agent, rather than reporting an empty graph it could
  advance blindly. The comment names the exact bug this fixed.
- **`deposit_gate_input` is lifted, not duplicated** (`app/_workflow_resume.py`), so CLI
  and MCP share one notion of accepting gate input. That lift is the model for the
  `call_gate_tool` and `_describe` lifts recommended in [01 §D](01-surface-inventory.md).
