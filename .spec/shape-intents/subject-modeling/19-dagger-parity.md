# 19 — Dagger Parity: What to Take, What to Leave

Dagger is the closest production-adopted system to what functualize and rise are
building, and it got there independently. This file audits the overlap.

**Verification basis.** Dagger claims cite `docs.dagger.io` as read on
2026-09-09. functualize claims cite this repository at `c0c921f`, checked in
source — in particular `builtin cache` is the *job metadata* cache
(`_cli/builtins.py:79`), not a result cache, and `Fingerprint`
(`_primitives/fingerprint.py`) decides *skip or run* rather than storing and
replaying a result. Both facts matter to §3.

## 1. The one-paragraph read

Dagger and this stack **agree almost completely on how work is authored** and
**disagree almost completely on where it runs** — and both halves of that are
correct, because they manage different things. Dagger's subjects are *ephemeral
artifacts inside a sandbox*: a container, a directory, a file, built from
nothing and thrown away. Rise's subjects are *persistent state on a real
machine*: is mise installed, is postgres running, is this repo checked out at
the right branch. Dagger can containerize everything because nothing it manages
outlives the run. Rise cannot, because everything it manages does.

The convergence is strong evidence the authoring model is right. The divergence
is why the caching model cannot simply be copied.

## 2. Where the two designs already agree

Convergent evolution, arrived at separately. Each row is a decision this corpus
argued for at length and Dagger shipped to production users first.

| Conviction | Dagger | Here |
|---|---|---|
| Code, not YAML | "Real code — Go, Python, TypeScript — not YAML" | `02` §9: the language-neutral module file is gone, deliberately |
| A function *is* the command, no scaffolding | `@function` → `dagger call` | `@job` → CLI; rise methods → the command surface (`03` §4) |
| A closed vocabulary of typed things-that-exist | `Container`, `Directory`, `File`, `Secret`, `Service`, `GitRepository` | 8 substrates: `Executable`, `Package`, `Process`, `Repository`, `Machine`, `Endpoint`, `Artifact`, `Nothing` (`01` §2) |
| Agents discover tools from the same surface humans use | "an LLM can automatically discover and use any available Dagger Functions" | the MCP adapter over `job_detail`'s `inputSchema` (`15` §1) |
| Modules are the sharing unit, installed from git | `dagger install github.com/dagger/eslint` | entry-point plugins; rise's registry (`06`) |
| Drop into a terminal at the point of failure | interactive debug on failure | the inline TUI, `Precondition` → `REFUSED` with guidance (`15` §1) |

**`GitRepository` deserves its own line.** Dagger has a first-class repository
type for the same reason `01` §5 added `Repository`: a checkout is a subject
with identity, not a directory. Two systems independently discovering that the
eight-kind/artifact-only vocabulary needed a repository slot is the strongest
external validation the three-axis model has received.

## 3. The gaps, ranked by value-per-cost

### G1 — Chaining. **Functualize already has it. The gap is that agents cannot see it.**

> **Correction.** The first version of this file called chaining "the one this
> corpus has no answer to" and filed the fix under rise's Protocol signatures.
> Both halves were wrong. Chaining is composition mechanism, so by `17` §2's own
> test it is functualize's — and functualize **ships it today** as `FromJob`
> (`_types/from_job.py`). This section is the corrected finding.

Dagger's fluent form:

```python
dag.container().from_("golang:1.21").with_mounted_directory("/src", src).with_exec(...)
```

Functualize's declared form — same semantics, different surface:

```python
def build() -> str:
    """Build it."""
    return "artifact-v1"

def publish(artifact: Annotated[str, FromJob("build")]) -> str:
    """Publish what build produced."""
    return f"published {artifact}"
```

```
app.execute("publish").return_value  ->  'published artifact-v1'
```

`build` ran because `publish` referenced it, its return value was injected, and
nothing had to be wired by hand. `FromJob`'s own docstring places it in the
right lineage: *"referencing a value declares the dependency — the idiom every
comparable system follows (doit's `getargs`… Dagster infers upstreams…)"*.
`run=False` reads a recorded value without causing work; values persist through
the state store; a completed workflow scope replays its memoized `body_value`
(`_engine/executor.py:1270,1299`). That is the substance of chaining.

**The real gap is legibility, and it is a defect rather than a feature
request.** The chain above executes correctly and is *invisible* on the agent
surface:

```
job_detail("publish")  ->  dependencies: []
                           parameters  : []
                           inputSchema : {'type': 'object', 'properties': {}}
```

An LLM reading that sees an input-less job with no upstreams. It cannot learn
that `publish` consumes `build`'s output, or that invoking `publish` will run
`build`. `dependencies` is populated from `descriptor.dependencies`
(`_cli/info.py:152`), which `FromJob` never reaches; excluding the injected
parameter from `inputSchema` is *correct* — a caller does not supply it — but
then the edge appears nowhere at all.

For a stack whose thesis is agent-legible operations, a working data-flow graph
that no agent can read is the wrong half to have. **Upstream ask 12:** surface
`FromJob` edges in `job_detail` — as `dependencies` entries, or a sibling
`consumes` field naming the upstream job and the parameter it feeds.

**What is genuinely missing** is *caller-composed* chains: `FromJob` fixes the
edge at authoring time, where Dagger's caller assembles the chain at call time,
including from the CLI. Whether that is worth having here is doubtful — see
§4's last paragraph. Rise's operations converge state rather than transform
artifacts, and for that, authored edges are the honest shape.

**The rise-side consequence is smaller than first claimed, and still real.**
Action Protocols that return `None` can never be a `FromJob` source, so a rise
module could not participate in the mechanism functualize already has. Letting
actions return their substrate is therefore not "adding chaining" — it is
**not foreclosing the chaining that exists**. Cheap now, breaking later.

### G2 — Zero-setup tracing. **Take the idea, not the cloud.**

Dagger: "Every step traced automatically. No instrumentation code," plus a
hosted timeline. Here: `builtin history` records runs (`args_hash` only, never
values), rise adds a JSONL audit (`08`), and `func why` explains a freshness
decision — but there is **no span model**, so no nesting, no timing tree, no
"which of the 40 things `bootstrap` did was slow."

`_events/middleware_stack.py` is the only OTel-shaped thing in the tree. The
event bus already sees everything a span would need; what is missing is
parent/child and duration, and an exporter.

**Cost: medium.** `func why` is genuinely ahead of Dagger — Dagger tells you it
cached, `why` tells you *which source changed*. Spans would make that
explainability navigable rather than per-job.

### G3 — A result cache, not just a skip. **Take it, carefully.**

Three distinct Dagger caches: layer, volume, and **function-call results**.
Here there is one, and it is not a result cache:

| | Dagger | Here |
|---|---|---|
| discovery metadata | — | `builtin cache` (`_cli/builtins.py:79`) |
| declared-source staleness | layer cache | `Fingerprint` → skip (`_primitives/fingerprint.py`) |
| stored results, replayed | function-call cache, content-keyed, across runs | **narrower** — a completed workflow scope replays its `body_value` on resume (`_engine/executor.py:1299`), and `FromJob(run=False)` reads a recorded value. Neither is a content-keyed cache across arbitrary runs |
| dependency dirs across runs | cache volumes | **nothing** |

`Fingerprint` already computes the hard part — a content key over declared
sources — and then only decides *skip or run*. Storing the result under that
key and replaying it is a smaller step than it looks.

**The honest limit:** a rise `install` mutates the host. Replaying a cached
result is *wrong* if the machine changed underneath, which is exactly what
`diagnose` exists to detect. So a result cache is safe for **pure** jobs
(build, render, compute) and unsafe for **mutating** ones — and this stack
already distinguishes those, via the action Protocols. Cache keyed by substrate
presence, not by inputs alone.

### G4 — An index over modules *and* functions. **Take the index, not the package.**

The Daggerverse "indexes all publicly available Dagger modules and Dagger
functions, and lets you easily search and consume them." Note the second noun:
it indexes at *function* granularity, which is what makes it searchable rather
than a package list.

`15` §5 concluded scrill is not a package, and that stands. But it framed the
question as *format*, and the Daggerverse suggests the valuable half was never
the format — it is the **index**. `builtin info --json` already emits every job
with its group, docstring, tags, examples and `inputSchema` (ask 7, landed).
That is a publishable record. Nothing consumes it across projects.

**Cost: low to prototype, high to operate** — an index is a service, with all
that implies. Worth naming as a direction, not scheduling.

### G5 — Just-in-time services. **Probably take.**

Dagger: "Service dependencies build on demand, no pre-provisioning." A test
declares it needs postgres; the engine starts one, binds it, tears it down.

Rise has `Process` + `Controllable` — start/stop/status on a *persistent*
service. It has no notion of "for the duration of this job." Functualize has
nothing service-shaped at all. This is the gap most likely to bite a real user:
`func test` that needs a database is the common case, and today the answer is
"start it yourself first."

**Cost: medium**, and it interacts with G3 — an ephemeral service is exactly the
kind of thing a sandbox makes easy and a host makes fiddly.

### G6 — SDK codegen against installed modules. **Leave, but note.**

`dagger develop` regenerates a vendored, typed client so the IDE completes
against the whole installed module graph. Here, mypy checks against
hand-written Protocols, which covers the *vocabulary* but not *other people's
installed modules*. Rise's `rise new` scaffolds; it does not codegen.

**Cost: high, benefit narrow** while the module ecosystem is one package.
Revisit if a registry of third-party rise modules ever exists.

## 4. What not to copy

**Containerize execution by default.** This is Dagger's foundation and it is
the wrong foundation here. Dagger sandboxes because its subjects are ephemeral;
"fully sandboxed execution... without direct access to the host system" is
precisely what rise cannot do, because rise's job is to *change the host*. A
rise that could not touch the machine would have no reason to exist. The
sandbox is available where it applies — `08`'s destructive-test tier already
refuses on the host and passes in a container — and that targeted use is
correct. Adopting it wholesale would be adopting Dagger's problem.

**A language-agnostic API core.** Dagger's real architecture is a GraphQL API
with generated SDKs, which is why it supports Go, Python, TypeScript and PHP.
`02` §9 accepted Python-only as a deliberate cost. Dagger shows the road not
taken, and it is a *road*, not a patch: it would mean the contract becomes an
API and the classes become clients. That is a different project. Worth knowing
the fork exists; not worth taking now.

**Pipelines as the organizing metaphor.** Dagger is CI/CD-shaped — its verbs
are build, test, publish. Rise's are install, start, diagnose, validate. Reading
Dagger too closely would pull rise toward being a worse CI tool instead of the
thing nobody has built.

## 5. What this stack has that Dagger does not

Worth stating, because the gap list above reads one-directionally.

| | Here | Dagger |
|---|---|---|
| **Diagnose/validate as an inherited contract** — any module answers "what am I, am I healthy" in one machine-readable record (`05`) | yes, and it is the differentiator | no equivalent; Dagger describes builds, not machine state |
| **Refusal with guidance** — `Precondition` → `REFUSED`, message verbatim to the agent at the moment of failure (`15` §1) | yes | rarely needed; the sandbox means less to refuse |
| **A published exit-code contract** (0/1/2/3/4/5) | yes | not published as a contract |
| **Explainable caching** — `func why` names the source file that changed | yes | "it cached", without the why |
| **Config ladder + vault** — CLI → Env → File → Default, with `aws-sm://` resolution (ADR-016) | richer | secrets, but a flatter chain |
| **Isolation as a declared property of a subject** (`HOST`/`PROJECT`/`PROCESS`) | yes | one global answer: the sandbox |

The last row is the crux. Dagger has *one* isolation answer for everything.
Rise makes isolation a per-subject declaration, which is more work and is the
only way to be honest about a tool that must sometimes write to `/usr/local`.

## 6. Recommendation

Sequenced by value-per-cost, and none of it blocks the current build order:

| | Do | When |
|---|---|---|
| 1 | **G1a** — surface `FromJob` edges in `job_detail` (**ask 12**) | now; it is a defect, not a feature |
| 2 | **G1b** — let rise actions return their substrate, so a rise module can be a `FromJob` source at all | **before modules exist.** Free now, breaking later |
| 3 | **G2 spans** — parent/child + duration on the existing event bus | after step 5 (`11` §2), once diagnosis emits records worth nesting |
| 4 | **G5 ephemeral services** — a scope-bound `Process` | with the registry, step 8 |
| 5 | **G3 result cache** for pure actions only, keyed on substrate presence | after `06`; needs the lockfile's notion of state |
| 6 | G4 index, G6 codegen | not scheduled; revisit when third-party modules exist |

**The strategic point.** Dagger owns "build my software reproducibly" and owns
it well enough that competing there is a mistake. Nobody owns "converge and
diagnose my machine, legibly to an agent." That is the space this stack is
actually in, and every gap above should be taken only insofar as it serves that
— G1 because a data-flow graph no agent can read defeats the point, G2 for the
same reason at run level, G5 because it is the common case. The rest is Dagger solving
Dagger's problem.
