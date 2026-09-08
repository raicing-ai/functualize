# 11 · Core, plugins, and fallback

Where every proposal in this folder lands, what it depends on, and what happens when the
dependency is absent. Verified against `78d9ff4`.

---

## 1. Two independent axes — do not conflate them

**Axis A — layer** (inside the core package, enforced by `import-linter`,
`pyproject.toml:227-308`):

```
_types → _primitives → _events → {_discovery, _config, _engine, _plugins, _gate} → _app → _cli
```

with three binding rules for this work:

- `_primitives` and `_types` import **nothing internal** — stdlib only.
- Peer layers are **independent**; wiring happens in `_app`.
- **`_cli` may import public folders only** (`app/`, `job/`, `plugin/`, `types/`,
  `testing/`) — never `_engine`, `_primitives`, `_types`.

That last rule is why `deposit_gate_input` lives at `app/_workflow_resume.py` and is
re-exported through `functualize.app.utils`: it is the *only* legal way for both `_cli`
and a plugin to share one implementation. **Every lift proposed in this folder must land
there.** It is not a stylistic preference; `lint-imports` fails otherwise.

**Axis B — packaging**:

| Tier | Contents | Install |
|---|---|---|
| **Core, unconditional** | engine, walker, state envelope, gates, discovery, config, DI | `pydantic`, `python-dotenv`, `jinja2`, `cryptography` — four deps |
| **Core, `[cli]` extra** | every `func` command, TUI | `click`, `rich`, `textual` |
| **Domain SDK plugin** | protocols only — `functualize-state`, `functualize-ai`, `functualize-tasks` | optional |
| **Provider plugin** | an implementation — `-state-sqlite`, `-ai-pydantic`, `-tasks-local` | optional |
| **Adapter plugin** | a delivery surface — `-mcp`, `-http`, `-lambda`, `-inline`, `-flow-viz`, `-fullscreen-tui` | optional |

The governing principle is already written down, in the ADR-016 note justifying
`cryptography` as a core dependency (`pyproject.toml:26-31`):

> *"a preset whose behaviour depends on whether an optional package happens to be
> installed is the class of surprise that ADR exists to remove."*

Hold that thought — §3 is a live violation of it.

---

## 2. The fact that settles most of the question: there are two state systems

| | **Runtime state envelope** | **State domain** |
|---|---|---|
| Where | `_primitives/state_store.py` → `.functualize/state.json` | `functualize-state` protocols + a backend |
| Packaging | **core, unconditional** | **plugin, optional** |
| Holds | `fingerprints`, **`scopes`**, `history`, `session` | job-authored KV, `ExecutionRecord`/`PhaseRecord` |
| Used by | the walker, `func history`, `func state` | job bodies, `functualize-tasks-local`, MCP history tools |

**The workflow walker uses the core one.** So scopes, steps, branch choices, gate
payloads and the epilogue record are all core, plugin-free, always present.

The two are *deliberately* shape-compatible (`state_store.py:13-19`):

> *"Every section here is a flat `{str: record}` mapping, which is exactly the shape the
> plugin's `StateBackend` KV protocol addresses… so `functualize-state-sqlite` can back
> this store later without a record-format change. The backend indirection itself is not
> built here — there is no second backend to serve yet, and a swap seam with one
> implementation is speculation, not design."*

Two consequences for this folder:

1. **Roadmap item 8's "move scopes to SQLite" is a planned swap, not a rewrite** — and the
   record format is already the constraint. Any new field must stay inside the flat
   `{str: record}` shape or it forecloses that seam.
2. **`notes` must live *inside* the scope record, not as a new top-level section.** A new
   `_SECTIONS` entry changes the envelope schema; a new key inside a scope record does
   not — `normalize_state` validates only `format_version` and section *types*
   (`state_format.py:142-159`), never a scope record's internals. Readers use
   `.get("notes", [])` and old scopes simply lack the key.

   **So notes ship without a `STATE_VERSION` bump.** That is a real relaxation of what
   [10 §2.3](10-coordination-and-nesting.md) implied: item 0 is a prerequisite for
   *trusting* notes (any future bump or `state clear` still erases them), not for
   *shipping* them.

---

## 3. The live boundary violation: observability is behind an optional adapter

`_describe`/`_topology` — the full graph, position, branch choices, per-step return values
and resolved inputs, gate schemas — live in
`plugins/functualize-mcp/.../_workflow_tools.py:471-536`.

So **the richest workflow observability in the framework is only available if you install
an MCP adapter.** A user who installs `functualize[cli]` and never touches MCP gets five
fields (`builtins.py:831-841`). That is precisely the surprise ADR-016 exists to remove,
and it is the strongest argument for [07 item 3](07-roadmap.md) — stronger than the UX
argument I gave it originally.

Same class, smaller: `call_gate_tool` is MCP-only. There is no reason a human at a
terminal cannot run a gate's declared tool inside the paused scope.

**Direction of the lift:** `_workflow_tools.py` → `app/_workflow_survey.py`, re-exported
through `functualize.app.utils`, with rendering split per `_cli/info.py`'s
`job_catalog` / `render_catalog_text` / `resolve_renderer` pattern. MCP then becomes a
thin caller, and the CLI gains the projection with no new dependency.

---

## 4. The four fallback patterns already in the codebase

Use the right one; do not invent a fifth.

### P1 · Named-provider table — *core names the package, never imports it*

`_gate/_strategy.py:20-53`:

```python
STRATEGY_PROVIDERS = {
    "resolve": "functualize", "prompt": "functualize",
    "ai_inbound": "functualize-ai", "ai_outbound": "functualize-mcp",
}
```

> *"Core names the plugins; core must never import them. A string in a diagnostic is not a
> dependency… `tests/gate/test_registry.py` pins that with a grep over `src/`."*

Failure mode: the walk **blocks** with `blocked_reason` naming the package to install.
Not a crash, not a silent degrade. **This is the best pattern in the repo** and the
template for any new pluggable capability.

### P2 · Domain/provider discovery — *auto-wire one, refuse to guess between many*

`discover_domains()` / `scan_domain_providers()`, surfaced by
`func builtin domains list` (`builtins.py:1428-1481`). One provider installed → auto-wires
at boot. Several installed, none configured → **none wired**, with the config key to set
printed. Zero installed → the `pip install` line.

### P3 · Capability detection with graceful degrade

`functualize-inline` falls back to plain `input()` when Textual is unavailable;
`functualize-flow-viz` falls back to plain text on a non-TTY. Correct when the *outcome*
is unchanged and only the presentation differs.

### P4 · Import-guarded registration — *the weak one*

MCP's task and history tools: `try: import functualize_tasks / except ImportError: return`
(`_task_tools.py:96-103`, `_history_tools.py:89-96`), logging at `debug`.

The tools simply **do not appear**, with no way for a caller to learn why. An agent that
read the docs and expects `list_tasks` sees nothing and cannot distinguish "not installed"
from "not permitted" from "server broken". **Do not extend P4.** Where a capability is
genuinely absent, prefer P1's shape: register a stub that returns a structured
`capability_unavailable` naming the package.

---

## 5. Where each proposal lands

| Proposal | Layer | Package | Hard deps | Absent ⇒ |
|---|---|---|---|---|
| **Item 0** — stop scope erasure ([07](07-roadmap.md)) | `_primitives` | **core** | none | n/a — unconditional |
| **Item 1** — return `metadata` from MCP doors | plugin | `-mcp` | core | CLI already prints it (`click_params.py:909-940`); the fix removes an adapter-only regression |
| **Item 2** — enforce `cancel` | `_engine` | **core** | none | n/a |
| **Item 3** — lift the projection | `app/` + `_cli` | **core** (+ `[cli]` to render) | none | headless/library callers still get the dict; only rendering needs `[cli]` |
| **Item 4** — `deposit` draft/partial/reopen | `app/` + `_cli` + `-mcp` | **core**, mirrored | none | full-payload deposit still works |
| **Item 5** — `--wf-resume`/`--wf-input` | `app/adapters` | **core `[cli]`** | click | `--scope-id` still resumes |
| **Item 5b** — `run_job(scope_id=…)` | plugin | `-mcp` | core | CLI unaffected |
| **Item 6** — trim per-job tools | plugin | `-mcp` | core | — |
| **`note`** ([10 §3](10-coordination-and-nesting.md)) | `_primitives` + `app/` | **core** | none | — |
| **`--wf-note`** | `app/adapters` | core `[cli]` | click | write via MCP or the builtin |
| **Child addressing D-A/B/C/E** ([10 §5](10-coordination-and-nesting.md)) | `_engine` + `app/` | **core** | none | n/a |
| **Parent close policy D-D** | `_engine` | **core** | none | n/a |
| **Task co-addressing** ([10 §4](10-coordination-and-nesting.md)) | — | `-tasks` + `-tasks-local` | **a `StateBackend`** | see §6 |
| **Provenance / `actor`** | `_primitives` + adapters | **core** schema, adapter capture | none | `actor: unknown` — never guessed |
| **Item 7** — agent-step port | `_types` (Protocol) + `_engine` | **core** protocol, plugin impls | none in core | see §7 |
| **Item 8** — durable run layer | `_primitives`/`_engine` | core, optional SQLite backing | none | JSON stays the default backend |

**Read the middle column:** almost everything is **core and unconditional**. That is the
correct answer and it follows from §2 — the walker's state is core, so anything that
reads or writes a scope is core. Plugins are *mirrors*, never owners.

---

## 6. The one deep optional chain: tasks

Task persistence needs **four** packages:

```
functualize-tasks          (domain SDK: Tasks, TaskItem, TaskLink, TaskProvider)
  └ functualize-tasks-local (provider: JSON blobs under a "tasks:" key prefix)
      └ functualize-state    (StateBackend protocol)
          └ functualize-state-sqlite (an actual backend)   ← or InMemoryState, non-durable
```

`functualize-tasks-local` *"persists tasks as JSON blobs in the active `StateBackend`"* —
so with no backend wired, tasks are in-memory and vanish at process exit.

**This is the reason [10 §4](10-coordination-and-nesting.md) recommends co-addressing over
coupling.** A workflow scope is core and always durable; a task is optional and durable
only four packages deep. Putting task state on the coordination path would make workflow
behaviour depend on an optional install — the ADR-016 surprise again.

**Fallback:** the scope projection carries a task *reference and count*, never contents.
With the chain absent, the field is simply omitted. Nothing in the walk changes.

---

## 7. The agent-step port — the one genuinely new pluggable capability

Everything else in this folder is core. Item 7 is not, and it needs P1's shape:

| Piece | Layer / package |
|---|---|
| `AgentStepExecutor` Protocol + capability flags | **core** `_types/` — `@runtime_checkable Protocol`, per the constitution's ports rule |
| The refusal when a capability is missing | **core** `_engine/` — fail closed, do not degrade |
| `EXECUTOR_PROVIDERS = {"mcp": "functualize-mcp", "ai": "functualize-ai", "prompt": "functualize"}` | **core** — strings only, grep-pinned like `STRATEGY_PROVIDERS` |
| Implementations | `-mcp` (elicitation), `-ai` (model), core `[cli]` (prompt) |

**Fallback ladder, mirroring `_gate_strategy_list`** (`workflow_walker.py:475-487`): a
workflow declaring an agent step with no registered executor **blocks** with a
`blocked_reason` naming the package — exactly what a gate declaring `ai_inbound` does
today without `functualize-ai`.

And copy pi-workflows' discipline verbatim ([06 §1](06-pi-workflows-model.md)): when the
step declares `allowed_tools` and the wired executor cannot enforce them, **refuse**. Do
not run the step with tools unrestricted. `enforcesToolAllowlist` is a typed capability
there, not a documented caveat, and that is the half worth stealing.

---

## 8. Rules to hold the line

1. **Core owns scope state; plugins mirror it.** Any verb that reads or writes a scope has
   its implementation in `app/`, re-exported through `functualize.app.utils`. Adapters are
   thin callers. `deposit_gate_input` is the precedent; `_describe` is the outstanding
   violation.
2. **Never gate workflow *behaviour* on an optional install.** Presentation may degrade
   (P3); outcomes may not. ADR-016, stated.
3. **Name the package, never import it** (P1), and keep the grep test that pins it.
4. **No new import-guarded silent absences** (P4). A missing capability returns a
   structured refusal naming what to install.
5. **New scope fields go inside the scope record**, not into `_SECTIONS` — no
   `STATE_VERSION` bump, no erasure exposure, and the `StateBackend` swap seam stays open.
6. **`_cli` touches public API only.** If a lift is awkward, the target is wrong, not the
   rule.

## 9. What this changes in the roadmap

- **Item 3 gets a second, stronger justification** — not "the CLI is thin" but "the
  framework's best workflow observability is behind an optional adapter," which the repo's
  own ADR-016 principle forbids. Its priority holds.
- **`note` is cheaper than [10](10-coordination-and-nesting.md) implied** — inside the
  scope record, no new section, no version bump. Item 0 remains a prerequisite for trust,
  not for shipping.
- **Task co-addressing drops further down.** Four optional packages deep, and doc-weight
  either way.
- **Item 7 needs `EXECUTOR_PROVIDERS` in core from day one.** Adding the provider table
  after the Protocol means the first missing-executor failure is a bare name, which is the
  exact defect `STRATEGY_PROVIDERS` was written to fix.
