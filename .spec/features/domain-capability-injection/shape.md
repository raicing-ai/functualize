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
    """Name one release check and record it."""
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

```text
$ func jobs.py prepare --help
Usage: prepare [OPTIONS]

  Name one release check and record it.

Options:
  --help  Show this message and exit.
```

Neither `ai` nor `tasks` has a spelling on this surface, or on any other the caller reaches. That absence is not a gap: a *domain-capability parameter* is resolved by the framework and never supplied by the caller, which is exactly what makes `prepare` runnable without arguments. §5 shows the two parameter classes side by side on every surface; §8 states the rule that decides which class a parameter is in.

The returned check is illustrative; the absence of a discovery refusal, successful injection, and the absence of a caller spelling for `ai`/`tasks` are binding. The output renderer's exact spelling remains provisional.

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

### What the class looks like on a surface today

A built-in capability is admitted without any plugin, so it renders the class on real output. Captured on this branch's working tree, with `functualize` synced from `uv.lock` (core only, no domain plugins):

```python
from functualize.job import Log

def hello(name: str, count: int = 1, log: Log = None) -> str:
    """Say hello."""
    if log:
        log(f"hi {name}")
    return f"{name} x{count}"
```

```text
$ func hello --help
Usage: hello [OPTIONS] NAME

  Say hello.

Options:
  --count INTEGER
  --help           Show this message and exit.
```

```text
$ func builtin info jobs hello
hello  Say hello.
  source: /tmp/mch299probe/probe.py
  parameters:
    name: str (required)
    count: int (default=1)
```

```text
$ func builtin info schema hello
{
  "name": "hello",
  "kind": "job",
  "path": [
    "hello"
  ],
  "description": "Say hello.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "name": {
        "type": "string"
      },
      "count": {
        "type": "integer",
        "default": 1
      }
    },
    "required": [
      "name"
    ]
  }
}
```

```text
$ func hello Alice --log x
Usage: hello [OPTIONS] NAME
Try 'hello --help' for help.

Error: No such option '--log'.
```

`log: Log` is absent from all four renderings — help, the job detail, the published schema, and the option table — and the only sentence a surface has about it is a refusal when a caller spells it. `ai: AI` and `tasks: Tasks` are the **same verdict class** as `log: Log`: `INJECTED`, published on no surface. They differ only in who registers them (a plugin rather than the engine), and today that difference is what refuses them, for the reason in §2. Nothing about the *caller-facing* boundary changes when they are fixed; what changes is that one more parameter of that class is admitted.

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

### The two parameter classes, on the same surfaces (proposed)

A job that declares one of each, so the boundary is visible in one place:

```python
from functualize_ai import AI
from functualize_tasks import Tasks

def prepare(city: str, ai: AI, tasks: Tasks) -> str:
    """Name one release check for a city and record it."""
    check = ai.complete(f"Name one release check for {city}")
    tasks.add(check)
    return check
```

| Surface | Caller-callable parameter `city: str` | Domain-capability parameter `ai: AI`, `tasks: Tasks` |
| --- | --- | --- |
| `func <job> --help` | `Usage: prepare [OPTIONS] CITY` | absent |
| Shell completion, inline TUI and SmartBar fields | offers `city` | offers nothing |
| `func builtin info jobs <job>` | listed under `parameters:` | absent |
| `func builtin info schema`, MCP `tools/list`, HTTP route, Lambda handler | a `properties.city` of `"type": "string"`, listed in `required` | no property, not required |
| A caller names it | the value binds | refused at the call door: `Argument 'ai' is supplied by the framework, not the caller. Remove it from the call` |
| Where its *selection* is documented | nowhere — the caller decides per call | project configuration: `[ai] provider`, `[tasks] provider` (`docs/guides/domain-sdks.md:133`) |
| Where the class itself is documented | `docs/guides/jobs-discovery.md:154` | `docs/guides/jobs-discovery.md:165`, `docs/guides/domain-sdks.md:64` |

The same job, on the two surfaces that publish a contract (proposed; the exact rendering follows the existing renderer, `path` and `description` included):

```text
$ func jobs.py prepare --help
Usage: prepare [OPTIONS] CITY

  Name one release check for a city and record it.

Options:
  --help  Show this message and exit.
```

```text
$ func builtin info schema prepare
{
  "name": "prepare",
  "kind": "job",
  "inputSchema": {
    "type": "object",
    "properties": {
      "city": {
        "type": "string"
      }
    },
    "required": [
      "city"
    ]
  }
}
```

#### The documentation difference, and the obligation it creates

The two classes are described today in two vocabularies, and the split *inside* the second class is missing:

- `docs/guides/jobs-discovery.md:165-167` has one bullet for two admission rules. It calls `Log` and "a class a plugin provides" both "a parameter supplied by the framework", yet `Log` is never refused and a provider type is refused whenever no provider answers for its type and qualifier (§8).
- `docs/guides/domain-sdks.md:64` calls the same thing "DI Injection" under a heading about domain SDKs, so a reader of that page learns that `ai: AI` is injected but not that the caller can never supply it.
- No page says that a caller naming such a parameter is refused, nor that its selection lives in `[ai] provider` rather than on the declaration. The selection does have a home (`docs/guides/domain-sdks.md:133`); the parameter-side half does not.

So the spec gains one documentation deliverable, in scope in §8: split that bullet in two, name `ai`/`tasks` as a domain capability in the second, and link it to the selection section. Shown as the replacement it writes:

```markdown
- **A parameter the framework fills from a built-in capability** (`Log`,
  `RunContext`, `Shell`) is published on no surface and needs no plugin. A call
  that names it is refused.
- **A parameter the framework fills from an installed domain provider**
  (`ai: AI`, `tasks: Tasks`) is published on no surface either. Its provider is
  selected in project configuration (`[ai] provider`, `[tasks] provider`, see
  [Domain SDKs](domain-sdks.md)), and with no provider installed discovery
  refuses the job.
```

The table below those bullets is rendered from `tests/_support/parameter_matrix.py` between the markers at `docs/guides/jobs-discovery.md:174` and `:196`, so no row is hand-edited: both classes already have a row (`p: Log | None = None` at `:188`, `p: ProvWidget` at `:189`). A row that names a domain capability is added to the matrix, not to the guide.

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

Where the caller's arrow stops, for the same job:

```text
caller: func, MCP tool, HTTP route, Lambda handler, app
  |
  |  values for caller-callable parameters only
  v
job function
  |- city: str    <- from the caller, per call; a flag / positional / schema property
  |- log: Log     <- from the engine, every call; on no caller surface
  `- ai: AI       <- from the installed provider, every call; on no caller surface
        ^
        |  the provider is chosen once, by configuration ([ai] provider),
        |  never by the declaration and never per call
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
| `[ai] provider`, `[tasks] provider`, `pydantic`, `local` | Binding | Existing selectors and known provider names are the user choice shape — and the only place selection is written, never the declaration. |
| Auto-select one provider; require a selector for two; refuse zero with an installable plugin named; cold/warm and CLI/app parity | Binding | Observable behavior fixed by approval. |
| Exact success rendering, exact refusal sentences, refusal timing within boot/discovery/run | Provisional | The spec settles these while preserving the outcomes above. |
| `prepare`, `jobs.py`, the returned release check, a hypothetical second provider | Illustrative | Scenario data, not public names. |
| `functualize-ai-pydantic`, `functualize-tasks-local` | Binding | Existing packages named in actionable missing-provider guidance. |
| The boundary in §5 and §8: a caller-callable parameter appears on every caller surface, a domain-capability parameter appears on none and is refused when a caller names it | Binding | The observable half of the boundary; approval fixes it. |
| "caller-callable parameter", "domain-capability parameter" | Provisional | The boundary and the rule are binding; the spec settles these two labels and uses them in the guides. |
| `Argument 'ai' is supplied by the framework, not the caller. Remove it from the call` | Provisional | Today's refusal at the single call door; the spec confirms it reads correctly for a domain capability. |
| The two replacement bullets for `docs/guides/jobs-discovery.md` in §5 | Provisional | Shape fixed, wording the spec's. |
| `city: str` and `prepare(city, ai, tasks)` in §5 | Illustrative | Scenario data only. |
| `@job(ai="pydantic")`, `Annotated[AI, Provider("pydantic")]` | Illustrative | A rejected candidate's spelling in §9; not proposed. |

## 8. Boundaries and non-goals

### Two parameter classes, and the rule that separates them

Every job parameter is one of three kinds, and the kind is decided once, at discovery, from the **declared type** — never from the parameter's name, its position, or whether it has a default (`src/functualize/_primitives/parameter_contract.py`, `_classify`):

| Kind | Decided by | Verdict | Who supplies the value | Caller surfaces |
| --- | --- | --- | --- | --- |
| Caller-callable | a value type: `str`, `int`, `bool`, `list[str]`, `dict`, a config model | `ACCEPTED_FLAG`, `ACCEPTED_POSITIONAL`, `CONFIG_FIELD`, `INVOCATION_ONLY` | the caller, per call | a flag, a positional, or a schema property |
| Framework-supplied: built-in capability | the type's **name** is one of the 15 in `INJECTED_PARAM_TYPE_NAMES` (`src/functualize/_primitives/capability_names.py`) — `RunContext`, `Log`, `Invoke`, `Shell`, `Vault`, … | `INJECTED`, never refused | the engine, every call | nothing |
| Framework-supplied: domain provider | **any other class**, plus `Provide(qualifier=…)` when several are registered | `INJECTED` while a provider answers for its type and qualifier; otherwise `REJECTED_DISCOVERY` | an installed plugin, chosen by configuration | nothing |

A `FromJob` declaration is a fourth, narrower form — a value another job produces — and is outside this page; `admit()` leaves it unchanged too.

`admit()` states the rule for the last two in one sentence (`parameter_contract.py:170-186`): only an `INJECTED` contract that carries a `provider_type` can change; capabilities and `FromJob` never do. The consequences:

- **A capability parameter is never refused for lack of a provider.** The engine is the provider.
- **A provider parameter is admitted only while a plugin answers for its type *and* its qualifier.** `Provide("pydantic")` with no `pydantic` registration is refused even when the type is registered under another qualifier, because resolving it would be a guess.
- **No caller surface supplies either one.** Both are `INJECTED`, so `json_schema is None` and neither is published (`_primitives/job_schema.py:96-113`); a value a caller sends for one is refused with `supplied by the framework, not the caller` (`_primitives/argument_binding.py:112-125`).

`ai: AI` and `tasks: Tasks` are the third kind. The boundary is unchanged by this page: their declaration, their absence from every caller surface, and their refusal when a caller names them are already what the class means. What the page changes is that they are admitted — because a plugin answers for them, which it does not today (§2, §10). The reason they are refused today is registration order, not the boundary.

**In scope:** job parameter declarations `ai: AI` and `tasks: Tasks`; one-provider auto-selection; configured selection when two exist; actionable refusal when none exists; cold and warm discovery; parity across `func` single-file, `func` project discovery, and `FunctualizeApp`; the two existing examples exercising injection; and the documentation of the boundary in §5 — split the jobs-guide bullet that merges a built-in capability with a plugin-provided class, and link it to the selection section.

**Out of scope:** a new provider API, new CLI flags, new HTTP or UI surface, new cache file format, new declaration syntax for selecting a provider (`@job(...)` kwargs or an `Annotated` wrapper, both shown and rejected in §9), credentials and live external model calls, the broader post-release plugin test standard, and release or tag work. The later spec determines internal timing and dependency wiring under the repository's layer rules.

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

**Rejected public shape: select the provider on the job declaration (`@job` kwargs).**

The review asked whether a domain provider should move onto the job's own decorator. Shown with the main use case and with the case that decides it:

```python
@job(ai="pydantic", tasks="local")
def prepare(ai: AI, tasks: Tasks) -> str:
    ...
```

```text
# one provider installed, decorator and config agree
$ func jobs.py prepare
<the returned check>
$ echo $?
0
```

```toml
# functualize.toml — and the decorator says something else
[ai]
provider = "mistral"
```

```python
@job(ai="pydantic")
def prepare(ai: AI) -> str: ...
```

That last declaration has no answer in this shape, or in any shape that adds the field: the decorator and the config both select the one capability, and neither is named as the winner. The reasons, in order of weight:

- `@job`'s keyword set is closed and validated at decoration time (`src/functualize/job/decorators.py:47-60`: `group`, `extra_description`, `category`, `examples`, `tags`, `visibility`, `config_section`, `deps`, `cache`, `guards`, `exec`). A provider field is a new public API for a value configuration already owns.
- It would not fix the reported defect. `tasks: Tasks` is refused because no provider answers when discovery admits the declaration, not because the selection is hard to spell (§8). Changing where selection is written leaves that untouched.
- An app or CI caller hands plain functions to `JobSources(functions=[...])`; a decorator kwarg is a surface that caller does not control.

**Rejected public shape: an `Annotated` wrapper named `Provider`.**

```python
# proposed by the review; no such name is importable today
from functualize.job import Provider

def prepare(
    ai: Annotated[AI, Provider("pydantic")],
    tasks: Annotated[Tasks, Provider("local")],
) -> str: ...
```

The framework already has this marker under another name, for the same idea — choosing among registered implementations:

```python
# src/functualize/_primitives/di.py:123 — its own docstring shows this usage
from functualize._primitives import Provide

def my_job(cache: Annotated[Cache, Provide("redis")]) -> None: ...
```

It is internal today (exported from `functualize._primitives`, not from `functualize` or `functualize.job`), and the framework already points authors at it when a qualifier is missing (`di.py:88`: `Use Annotated[Cache, Provide('qualifier')] to disambiguate.`). So a public wrapper named `Provider` would be a second spelling beside `Provide`, published where `Provide` is not. Beyond that: it forces the common one-provider case to name an implementation; it leaves `[ai] provider` and the annotation as two sources that can disagree, exactly as the `@job` candidate does; and `Provider` is already the framework's word for the *plugin* (`ProviderRegistry`, `TaskProvider`, "installed provider plugin"), so a parameter wrapper called `Provider` reads as "this parameter is the plugin" — the confusion the review is asking to remove, not a fix for it. If a per-declaration selection is ever wanted, publishing `Provide` and letting it carry a domain qualifier is the narrower change, and this candidate is recorded so that work starts from these trade-offs.

**Selected: the first shape.** The declaration names the capability and nothing else; the class decides that it is framework-supplied rather than caller-supplied; and the one place a provider is chosen is configuration.

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
- Fixing admission without the documentation split in §5 leaves the class describable only by reading the code: a reader of the jobs guide meets one bullet for two admission rules, and a reader of the domain guide learns that `ai` is injected but not that a caller can never supply it. The guide change is part of the deliverable, not a follow-up.

## 11. Next falsifiable experiment

Run from a checkout with the domain plugins installed. The command uses the existing published example as the smallest real-loader probe:

```sh
uv sync --frozen --all-extras --all-packages
uv run func plugins/domains/functualize-ai-pydantic/examples/travel_plan/travel_plan.py run --city Tokyo
```

For a hermetic automated version, use PydanticAI `TestModel` rather than a network model. Expected after the change: discovery accepts `ai: AI` and reaches the model call. Falsifier: a parameter-refusal message before that call. Repeat with a warm discovery cache and with the Tasks declaration through `FunctualizeApp`; a pass on only one path falsifies parity.

## 12. Open questions

### Q-1 — Where should a domain provider be selected? (raised in review)

Three answers, side by side, same job each time:

```python
# (a) declaration only — selected here
def prepare(ai: AI, tasks: Tasks) -> str: ...
```

```toml
# (a) ... and chosen here
[ai]
provider = "pydantic"
```

```python
# (b) on the job's decorator
@job(ai="pydantic", tasks="local")
def prepare(ai: AI, tasks: Tasks) -> str: ...
```

```python
# (c) in the annotation, wrapper named as the review suggested
def prepare(
    ai: Annotated[AI, Provider("pydantic")],
    tasks: Annotated[Tasks, Provider("local")],
) -> str: ...
```

| | What the author types | Where selection lives | One provider | Two providers, disagreeing sources | Fixes the reported refusal | Cost |
| --- | --- | --- | --- | --- | --- | --- |
| (a) selected | `ai: AI` | `[ai] provider` | nothing to type | impossible: one source | yes, once admission is fixed | none |
| (b) | `@job(ai="pydantic")` | decorator **and** config | must name it, or leave a field blank | no stated precedence; job runs with whichever is read first | no | new validated `@job` kwarg |
| (c) | `Annotated[AI, Provider("pydantic")]` | annotation **and** config | must name it | no stated precedence | no | second `Annotated` marker beside `Provide` |

**Recommendation: (a).** The refusal in §2 is not about where a provider is *named* — the provider is installed and is the only one — so (b) and (c) add a second selection surface without addressing it, and each introduces a precedence question between two surfaces that nothing in the framework currently answers. (a) keeps one owner, already implemented (`docs/guides/domain-sdks.md:133`), and leaves the declaration saying only what the job needs. §9 keeps (b) and (c) with their reasons so a future need for per-job selection starts from these trade-offs.

**Proceeds regardless of the answer:** the admission fix (§10, §11), the two examples, and the documentation split in §5. All three are independent of where a selection is written; (b) or (c) would be added on top of a working (a), never instead of it.

### Q-2 — Earlier declaration or later classification?

The internal choice between declaring capabilities before discovery and classifying after it is for Specify/Plan, decided by the §11 experiment; both yield the same §1 interaction and the same Q-1 answer. Work on the approved behavior proceeds regardless of which mechanism survives.

## 13. Outcome

Proposed for member review at the commit SHA linked from the issue. No approval or implementation is recorded here.

Revision 2 (2026-11-28) answers the review on the intent and boundary: §1 and §3 now show the class on real output, §5 compares both parameter classes surface by surface and names the documentation obligation, §6 shows where the caller's arrow stops, §8 defines the three kinds and the rule that separates them, and §9 and §12 carry the two alternatives the review named (`@job` parameters, an `Annotated` wrapper called `Provider`) with their reasons and a recommendation. Neither alternative changes any §7 binding outcome: both are marked rejected/illustrative.
