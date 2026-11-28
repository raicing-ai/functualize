| Field | Value |
| --- | --- |
| Document type | Shape Intent |
| Status | Exploring |
| Authority | Proposed |
| Owner | Functualize maintainers |
| Product | Functualize |
| Last reviewed | 2026-11-28 |
| Carried by | MCH-299 (A1 of MCH-298) |
| Depends on | None identified |
| Related | SD/3080295 v3; `contributor/architecture/surface-boundary.md`; `contributor/adr/021-capability-duality.md` |

## 1. The shape at a glance (shape)

A job author declares the domain capability as a parameter. With its one provider plugin installed, the same job works from `func` and a `FunctualizeApp`; the author does not construct the capability.

```python
from functualize_ai import AI
from functualize_tasks import Tasks

def prepare(ai: AI, tasks: Tasks) -> str:
    result = ai.complete("Name one release check")
    tasks.add(result)
    return result
```

```text
$ func jobs.py prepare
<the returned check, with no parameter-refusal error>
$ echo $?
0
```

The returned check is illustrative; the absence of a discovery refusal and successful injection are binding. The output renderer's exact spelling remains provisional.

## 2. Problem

Today the documented authoring form is refused even when the plugin is installed (MCH-299, reproduced on `52262afb`):

```python
from functualize_tasks import Tasks
def add(tasks: Tasks) -> int: ...
```

```text
$ func file.py add
job 'add' parameter 'tasks: Tasks' is refused. No provider is registered for functualize_tasks._tasks.Tasks without a qualifier.
Error: job 'add' cannot run
```

The author cannot reach the provider through the advertised job declaration. The published AI travel-plan example is likewise refused before a model call (MCH-299).

## 3. Current reality

The issue's reproduction above is evidence of current behavior at its stated baseline, not a new reproduction on this branch. On `origin/master` at `d58500f76ba65ba169451e3cb4af3820e271e266`, `src/functualize/_app/boot.py:1142-1162` registers jobs before firing `APP_READY`; `plugins/domains/functualize-ai-pydantic/src/functualize_ai_pydantic/_plugin.py:114` provides `AI` in its ready hook; `plugins/domains/functualize-tasks-local/src/functualize_tasks_local/_plugin.py:85` provides `TaskProvider` in its ready hook. `plugins/domains/functualize-tasks/examples/todo/todo.py:6-15` constructs `MockTasks` inside the job today.

**Before:** `ai: AI` or `tasks: Tasks` is refused at discovery with its provider installed. **After:** the job is discoverable and receives the selected capability on execution, as in §1 and UC-1. The exact faulty mechanism is not established by this shape.

## 4. Use cases (shape)

### UC-1 — Job author, one installed provider

The author installs `functualize-ai-pydantic` and `functualize-tasks-local`, writes the `prepare` job in §1, and runs it with `func jobs.py prepare` or from the current project's job directory. Each domain has one provider. Discovery accepts both parameters, the selected instances reach the job, and execution exits 0 if the provider operations succeed. On a second, warm boot the result is the same.

### UC-2 — Job author, two providers in one domain

The author has two AI provider plugins installed and selects one in project configuration:

```toml
[ai]
provider = "pydantic"
```

The `ai: AI` declaration stays the same. Both `func` and `FunctualizeApp` give the job the selected provider. The equivalent Tasks choice uses `[tasks]` and `provider = "local"`. If no provider is selected among two, the run refuses with an ambiguity message that names the configuration key; it does not silently choose one. The second provider's identity is illustrative until one is available for a concrete test.

### UC-3 — Job author, no installed provider

The author leaves `ai: AI` in the job but removes AI provider plugins. Discovery or boot refuses the runnable job, and an attempt to run it exits nonzero with a message that names `functualize-ai-pydantic` as an installable example. The same applies to `tasks: Tasks` with `functualize-tasks-local`. No missing argument reaches the Python function.

### UC-4 — Application or CI caller

An application supplies a function with `tasks: Tasks` through `JobSources(functions=[...])` to `FunctualizeApp`; CI runs it with the real installed entry-point plugin. The app path receives the same selected capability as the CLI path. CI repeats this with a fresh discovery cache and a warm cache, so a cache hit cannot bypass capability classification.

## 5. The shape, surface by surface (shape)

| Surface | Proposed visible shape |
| --- | --- |
| Authoring / library API | `from functualize_ai import AI; from functualize_tasks import Tasks`; declare `def prepare(ai: AI, tasks: Tasks)`. `FunctualizeApp(..., job_sources=JobSources(functions=[prepare]))` accepts the declaration. |
| Command line | `func jobs.py prepare` and `func prepare` from a discovered project both run the same job; success exits 0. Exact success text follows the existing renderer. |
| Configuration | One provider needs no selector. With two, use `[ai] provider = "pydantic"` or `[tasks] provider = "local"` in the project's TOML configuration. |
| Wire / HTTP / file formats | Not touched. No new request, response, or persisted format. |
| UI | Not touched. |
| Errors and refusals | No provider: `job 'prepare' requires AI; install an AI provider (for example functualize-ai-pydantic).` Two providers without selection: `Multiple AI providers are installed; set [ai] provider.` Tasks uses the corresponding names. Exact sentence and rendering are provisional; naming the missing plugin or selection key is binding. |
| Generated or observable artifacts | The job is present in discovery and executes through the existing run result; no new user-visible artifact. A warm cache has the same observable behavior. Cache layout is not touched. |

## 6. Diagrams (shape)

Structure; arrows show use or selection, not an implementation choice:

```text
job author (ai: AI / tasks: Tasks)
          | declares
          v
FunctualizeApp kernel <--- func delivery
          | selects capability by domain config
          v
domain capability (AI / Tasks)
          | backed by
          v
installed provider plugin (pydantic / local)
```

Behavior on both entry points:

```text
author/CI -> func or FunctualizeApp -> discovery: accept capability declaration
                                      -> provider selection: one, or configured among two
                                      -> execution: inject AI / Tasks -> job -> result
                                      -> no provider: clear refusal naming installable plugin
```

Lifecycle observations to preserve:

```text
cold boot -> discover/register -> ready hooks -> execute
warm boot -> cached discovery -> ready hooks -> execute
both paths must make the same declared capability runnable
```

## 7. Binding, provisional and illustrative (shape)

| Item shown here | Status | Meaning |
| --- | --- | --- |
| `AI`, `Tasks`, `ai: AI`, `tasks: Tasks`, their existing imports, `func`, `FunctualizeApp`, `JobSources` | Binding | Existing authoring and entry-point surfaces remain usable. |
| `[ai] provider`, `[tasks] provider`, `pydantic`, `local` | Binding | Existing selectors and known provider names are the user choice shape. |
| Auto-select one provider; require a selector for two; refuse zero with an installable plugin named; cold/warm and CLI/app parity | Binding | Observable behavior fixed by approval. |
| Exact success rendering, exact refusal sentences, refusal timing within boot/discovery/run | Provisional | The spec settles these while preserving the outcomes above. |
| `prepare`, `jobs.py`, the returned release check, a hypothetical second provider | Illustrative | Scenario data, not public names. |
| `functualize-ai-pydantic`, `functualize-tasks-local` | Binding | Existing packages named in actionable missing-provider guidance. |

## 8. Boundaries and non-goals

**In scope:** job parameter declarations `ai: AI` and `tasks: Tasks`; one-provider auto-selection; configured selection when two exist; actionable refusal when none exists; cold and warm discovery; parity across `func` single-file, `func` project discovery, and `FunctualizeApp`; and the two existing examples exercising injection.

**Out of scope:** a new provider API, new CLI flags, new HTTP or UI surface, new cache file format, credentials and live external model calls, the broader post-release plugin test standard, and release or tag work. The later spec determines internal timing and dependency wiring under the repository's layer rules.

| Surface | Owner and boundary |
| --- | --- |
| Job declaration and app execution | Functualize public app/job contract; no CLI-only capability behavior. |
| `func` command rendering | CLI delivery; it reaches the app execution path. |
| AI and Tasks behavior | Domain SDKs; provider plugins supply their implementations without requiring job authors to construct them. |
| Provider selection | Existing domain configuration and installed provider entry points; no new selector syntax. |

## 9. Candidate models

**Selected public shape: implicit capability parameter with existing configuration.**

```python
def prepare(ai: AI, tasks: Tasks): ...
# one provider per domain: no selector; two: [ai]/[tasks] provider in TOML
```

This preserves the published authoring form and gives configuration one selection role. Internal registration order remains for Specify/Plan.

**Rejected public shape: require a qualifier in each declaration.**

```python
def prepare(ai: Annotated[AI, "pydantic"]): ...
```

This would force the common one-provider case to name an implementation and would not match the existing configuration contract.

**Rejected public shape: author constructs capabilities inside each job.**

```python
def prepare():
    tasks = MockTasks()
```

This is the current Tasks example's workaround; it bypasses installed provider selection and does not address AI injection.

## 10. Hypotheses and risks

- Job discovery may classify parameters before ready-hook registration; the ordering is visible in `boot.py`, but whether that is the sole cause requires a falsifying run.
- Tasks-local provides `TaskProvider`, while the job requests `Tasks`; the required adapter or registration path is not selected here.
- Domain entry-point metadata might help declare capabilities early, but there is no evidence here that it is used by job discovery.
- A cold-path fix may leave warm-cache behavior broken. Both paths must produce UC-1 and UC-3 outcomes.
- A second provider can be simulated in acceptance tests if no second published implementation exists; the actual selection path must still be exercised.

## 11. Next falsifiable experiment

Run from a checkout with the domain plugins installed. The command uses the existing published example as the smallest real-loader probe:

```sh
uv sync --frozen --all-extras --all-packages
uv run func plugins/domains/functualize-ai-pydantic/examples/travel_plan/travel_plan.py run --city Tokyo
```

For a hermetic automated version, use PydanticAI `TestModel` rather than a network model. Expected after the change: discovery accepts `ai: AI` and reaches the model call. Falsifier: a parameter-refusal message before that call. Repeat with a warm discovery cache and with the Tasks declaration through `FunctualizeApp`; a pass on only one path falsifies parity.

## 12. Open questions

No public-shape decision remains. The internal choice between earlier capability declaration and later classification is for Specify/Plan after the measured experiment; both yield the same §1 interaction. Work on the approved behavior can proceed regardless of which mechanism survives.

## 13. Outcome

Proposed for member review at the commit SHA linked from the issue. No approval or implementation is recorded here.
