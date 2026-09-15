# Domain SDKs

Functualize's capabilities are organized as standalone Domain SDK packages. Each SDK defines a capability class, provider protocol, shared types, testing doubles, and domain metadata — carrying no heavy dependencies.

---

## Architecture

```mermaid
graph TD
    subgraph "Domain SDKs (lightweight)"
        ai["functualize-ai"]
        tasks["functualize-tasks"]
    end

    subgraph "Implementation Plugins (heavyweight)"
        pydantic["functualize-ai-pydantic"]
        local["functualize-tasks-local"]
    end

    subgraph "Storage (not a domain)"
        sqlite["functualize-state-sqlite"]
    end

    pydantic --> ai
    local --> tasks
```

**Domain SDKs** define _what_ a capability does (protocols, types). **Implementation Plugins** provide _how_ it works (real backends, API clients).

!!! note "Storage is not a domain SDK"
    There was a `functualize-state` SDK, and it was retired. A
    backend-agnostic key-value protocol can only offer the **intersection of
    every backend**, which is worth least exactly where having a real database
    is worth most. `functualize-state-sqlite` now supplies a
    **`StoreSubstrate`** — *give me this document, put this document back, stop
    anyone else while I do both* — and every store follows it. See
    `contributor/adr/022-storage-is-a-substrate-not-a-key-value-domain.md` and
    the [Custom Substrate example](../examples/plugins/custom-state-backend.md).

!!! note "Interactivity is not a domain SDK"
    Interactivity is *presentation architecture* (a surface stack, phase-scoped
    activation, per-job `TTY`/`Live` grants), not backend selection with one
    active provider — so it was evicted from the domain-SDK pattern and folded
    into core. See [Interactivity](interactivity.md) and
    `contributor/adr/001-surface-architecture-collapse.md`.

---

## Available Domains

| Domain | SDK Package | Capability Class | Default Plugin |
|--------|-------------|-----------------|----------------|
| AI | `functualize-ai` | `AI` | `functualize-ai-pydantic` |
| Tasks | `functualize-tasks` | `Tasks` | `functualize-tasks-local` |

Storage is **not** in this table — see the note above. A job's own durable state
is `rc.state`, and where functualize keeps its bookkeeping is a substrate.

---

## Using Domain SDKs

### In Jobs (DI Injection)

Capabilities are injected into job functions via type annotations:

```python
from functualize.job import RunContext
from functualize_ai import AI, ToolScope

def analyze(ai: AI, rc: RunContext):
    result = ai.complete("Analyze this data...", response_model=Analysis)
    rc.log(f"Analysis: {result.summary}")
```

### In Standalone Scripts

Use testing doubles directly without a project:

```python
from functualize_ai.testing import MockAI
from functualize_tasks import MockTasks

ai = MockAI(responses={"*summarize*": "Short summary"})
tasks = MockTasks()
```

---

## Testing

Each SDK provides testing doubles that work without implementation plugins:

```python
from functualize_ai.testing import MockAI
from functualize_tasks.testing import MockTasks
```

For interactivity, `functualize.testing` provides `AutoPrompt` (and see the
`Surface`/`PromptCollector` test doubles in `tests/`).

These doubles are suitable for unit testing job logic without network calls, databases, or API keys.

---

## Writing a Custom Implementation

Implement the domain's provider protocol and register via entry point:

```python
# my_plugin/_provider.py
from functualize_tasks import TaskProvider

class JiraTasks:
    def add(self, title, *, linked_to=None): ...
    def update(self, task_id, *, status=None, notes=None): ...
    def list(self, *, status=None, filter=None): ...
```

```toml
# pyproject.toml
[project.entry-points."functualize.tasks_providers"]
jira = "my_plugin:JiraPlugin"
```

Storage follows a different shape — one substrate, installed at `APP_READY`.
See the [Custom Substrate example](../examples/plugins/custom-state-backend.md)
for a complete walkthrough.

---

## Auto-Selection

When only one implementation plugin is installed for a domain, functualize auto-selects it. No configuration needed.

When multiple implementations are installed, specify your choice in the config file:

```toml
[ai]
provider = "pydantic"

[tasks]
provider = "local"
```

---

## Scaffolding

Generate new SDK or plugin packages:

```bash
func builtin scaffold add domain --name my-domain
func builtin scaffold add plugin --domain tasks --name jira
```

---

## Related

- [AI Capability Guide](ai.md)
- [Workflows Guide](workflows.md)
- [Plugins Guide](plugins.md)
- [Custom State Backend Example](../examples/plugins/custom-state-backend.md)
