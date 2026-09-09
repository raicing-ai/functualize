# HANDOFF — where this work stands, for whoever picks it up next

**Written 2026-09-09.** For an agent or a person joining with **zero prior
context**. Read this file first; it tells you what is settled, what is open,
what is *wrong in the corpus right now*, and the house rules you will violate
if you skip them.

Everything referenced here lives inside this directory unless a `path:line`
points into `src/`.

---

## 0. The thirty-second version

We are designing **risekit** (CLI `rise`): a framework for declaring machine
subjects — tools, packages, services, repositories, machines — as **Python
classes**, hosted on **functualize**, the task runner in this repository.

The design is finished as a design. It is **not implemented**: no `risekit`
code exists anywhere. This directory is the shape intent that a future
`risekit` repository would be built from, plus twelve asks it makes of
functualize, eight of which have already shipped.

The current activity is a **line-by-line review by the repository owner**,
delivered one item at a time. Two items have landed. More are expected.

---

## 1. Where it is

| | |
|---|---|
| Branch | `spec/subject-modeling` (pushed; `origin/spec/subject-modeling` = `7edfaa6`) |
| Worktree | `functualize/.worktrees/subject-modeling` |
| Corpus | `.spec/shape-intents/subject-modeling/` — 56 files, ~4,100 lines of `.md` plus 20 probes |
| PR | **not opened.** `https://github.com/raicing-ai/functualize/pull/new/spec/subject-modeling` |
| Commits ahead of the branch point | 6 |

The corpus is **self-contained by rule** — `.spec/`'s own convention is that a
shape intent needs no external file to start work from. Six superseded design
passes exist as untracked scratch folders in `~/code/raicing-ai/`
(`rise-intent/`, `rise-on-functualize/`, `-oop/`, `-oop-v2/`, `scrills-rise/`,
`scrill-design/`, `vision-implementation/`, `scrill/`). **Do not read them.**
Each carries a supersession header saying so. Two of them recommend an
architecture that `17-subject-modeling.md` later overturned, and reading them
in directory order lands you on that dead architecture twice.

---

## 2. The idea, in enough detail to argue about

**Three axes, not eight kinds** (`01-vocabulary.md`). A subject is a
**substrate** (`Executable`, `Package`, `Process`, `Repository`, `Machine`,
`Endpoint`, `Artifact`, `Nothing`) that satisfies **actions** expressed as
Protocols (`Installable`, `Runnable`, `Controllable`, `Loggable`, `Backupable`,
`Updatable`, `Syncable`) against a **target**. The older eight-kind model
survives only as presets.

```python
class Jsonschema(Executable, Installable, Runnable):
    group = "tools.jsonschema"
    isolation = Isolation.PROJECT

    @job(guards=Guards(status=["command -v jsonschema"]))
    def install(self, sh: Shell, log: Log) -> None: ...
    def run(self, sh: Shell, args: list[str]) -> None: ...
```

**Binding** (`03-binding.md`): class methods become functualize jobs through a
**plugin-registered job provider**, called from inside `plugin.__call__(app)`.
This is the single most valuable finding in the whole corpus — plugins load at
boot step 4, job resolution at step 9 (`_app/boot.py:535` vs `:988`), so a
provider added there arrives **with its parameters intact**. The previous pass
believed this path was dead and had a blocking upstream ask because of it.
Probe 10 killed the blocker.

**Dual delivery** (`04-delivery.md`): one `RisePlugin` object, hosted two ways
— as a `func` plugin (guest) and as a standalone `rise` CLI (host).

**The layer split** (`17-subject-modeling.md`, the most consequential file):
functualize owns **mechanism** and stays vocabulary-blind; risekit owns
**policy** — the concrete substrates, actions and legality tables. Subject
modeling is framed as a *functualize practice* that rise is merely the first
instance of. Use this as the test whenever you are unsure which layer something
belongs in; it has already caught one misfiling of mine (see §4).

**scrill is not a package** (`15-scrill.md` §5). It dissolved into a directory
convention, a generator inside risekit, and three upstream asks.

---

## 3. Reading path

The full corpus is ~4,100 lines. **~600 lines gets you oriented:**

1. `README.md` — what changed and what it supersedes
2. `17-subject-modeling.md` — the functualize/risekit split. Read it **second**, not last
3. `01-vocabulary.md` — the three axes; the actual idea
4. `15-scrill.md` §5 — where scrill went
5. `11-architecture.md` §1–2 — package layout and the 13-step build order
6. `14-risks-decisions.md` — settled vs. open

For *why any of this exists*, `intent/01-vision.md` is the only file that
answers that question. `intent/` also carries the **69 acceptance criteria**
this design is scored against (`12-acceptance-mapping.md` maps every one), with
a 10-row divergence ledger in `intent/README.md` recording where v3 knowingly
departs from the original intent.

---

## 4. The review loop so far — and two errors I made

The owner is reviewing one item at a time. **Both items so far found a real
problem, and in both cases the fix was not the one the report implied.** Read
these before proposing anything; they are the shape of mistake this corpus
invites.

### Item 1 — "it looks like `rise` can execute a job, and it shouldn't"

The owner was right that the docs **contradicted themselves**, and wrong that
the design was broken.

- `04` §3a claimed the split *"keeps `rise` from needing to run jobs at all"* —
  four sections above its own example list of `rise` running things.
- `14` said *"`rise` is not a job runner"* — three lines above a table whose
  "Rise's role" column reads "installs them".

The real line is **project jobs vs. rise modules**, not describing vs.
executing. Standalone `rise` executes its own modules' methods because
bootstrapping a bare machine requires it — `rise tools mise install` must work
before any project or `func` exists. It scans no `jobs/` directory, so
`rise build` and `rise deploy` do not exist in either delivery. **Decision
taken by the owner: keep execution as designed.** Both sentences fixed, plus a
clarifying note under the README example (commit `337c6f4`).

### Item 2 — "shouldn't chaining be a capability within functualize then?"

Yes — and checking it exposed **two** errors in my Dagger audit.

1. **Misfiling.** I had filed chaining under rise's Protocol signatures.
   Composition is vocabulary-blind mechanism, so by `17` §2's own test it is
   functualize's. The owner caught this.
2. **A false claim about our own system.** I wrote that composition "neither
   expresses 'this produced a thing, now do something to the thing'".
   **`FromJob` expresses exactly that, and functualize ships it**
   (`src/functualize/_types/from_job.py:60`).

```python
def build() -> str:
    return "artifact-v1"

def publish(artifact: Annotated[str, FromJob("build")]) -> str:
    return f"published {artifact}"

app.execute("publish").return_value   # -> 'published artifact-v1'
```

`build` ran because `publish` referenced it, and its value was injected.
`run=False` reads a recorded value without causing work.

The **residual gap is agent legibility**: the chain executes correctly and is
invisible on the agent surface.

```
job_detail("publish")  ->  dependencies: []
                           parameters  : []
                           inputSchema : {'type': 'object', 'properties': {}}
```

`dependencies` is filled from `descriptor.dependencies` (`_cli/info.py:152`),
which `FromJob` never reaches. Excluding the injected parameter from
`inputSchema` is *correct* — a caller does not supply it — but the edge then
appears nowhere at all. Filed as **upstream ask 12**. Recorded in `19` §3 G1 as
a marked `> **Correction.**` block rather than a silent edit, so the wrong
version stays visible beside what replaced it (commit `7edfaa6`).

> **The lesson, stated plainly for the next agent:** I read Dagger's
> documentation carefully and this repository's composition story *from
> memory*. Verify every claim about functualize against source before writing
> it down. The corpus marks verified claims **[probed]** for exactly this
> reason — respect that marker and do not add it without running something.

---

## 5. ⚠️ The most important open item: the base moved to 0.3.0

**This branch is 3 commits behind `origin/master`, and the drift is not
cosmetic.** Nobody has re-probed against it yet. This is the first thing to do.

| Commit | What it does | Why it touches us |
|---|---|---|
| `24c5cc0` (#34) | Workflow scopes get their own durable file — `scopes.json`, split from `state.json` on the discard rule | Directly affects `19` §3 **G3**, whose "stored results" row describes scope replay. Scopes are now durable across a `STATE_VERSION` bump; that row is now understated |
| `2a079de` (#35) | **Workflows can be driven to completion without a shell.** `answer` records, `resume` advances. `builtin workflow` 4 verbs → 7; MCP matches verb for verb. **Version is now 0.3.0** | Hits `16-skill-to-workflow.md` head-on and probes 16/17/18 |
| `e57f0c9` (#36) | CI skips heavy jobs on `.spec/`-only pushes | Good news: our spec pushes no longer burn a 20-minute suite |

**Known-stale right now, unfixed:**

- `16-skill-to-workflow.md:58` and `:394` name the MCP tool **`resume_gate`**,
  which #35 **removed** in favour of `answer_gate`. `list_active_workflows`
  became `list_workflows`. `--scope-id` is gone in both spellings, replaced by
  the `--wf-*` family.
- **13 files pin "functualize 0.2.3"**, including `00-baseline.md`,
  `README.md`'s verification basis, and `evidence/README.md`.
- Probes 16, 17 and 18 exercise workflow gates and have not been run against
  #35. Treat their recorded outputs as **unverified** until they are.

Re-running all 20 probes, from the repository root:

```bash
uv sync
for p in .spec/shape-intents/subject-modeling/evidence/probe_*.py; do
  echo "=== $p"
  PYTHONPATH=src uv run python "$p"
done
```

Then update **both** `evidence/README.md`'s drift table and
`evidence/transcript.md`. The convention this corpus holds itself to is that
every base change triggers a full re-run — a five-probe sample once undercounted
the drift and had to be publicly corrected in `evidence/README.md`.

---

## 6. Open upstream asks

`13-upstream-asks.md` indexes all twelve in one table. **Asks 1–8 shipped** in
`78d9ff4`. Four are outstanding:

| # | Ask | Kind |
|---|---|---|
| 9 | Re-export `StaticProvider` from `functualize.plugin` — probe 10 imports the private path | fix |
| 10 | Display dedupe: last-wins, or warn on a discarded provider | fix |
| 11 | Protect the whole first-party top level, or warn — `mcp` is claimable, `builtin` is not | fix |
| 12 | Surface `FromJob` edges in `job_detail` — a working data-flow graph is invisible to agents | fix |

**Defect #32** (recorded, not fixed): two functions normalizing to the same job
name **silently become one job** on the default path. Probe 11 falsified the
corpus's earlier claim that this was fatal.

**My standing argument, which the owner has not yet ruled on:** #32 outranks
asks 9–11. It is the only one that silently loses a user's job on the default
path, and asks 10 and 11 are the *same silent-collision shape* one layer up —
a display provider discarded without a word, a top-level name claimed without a
word. Fixing the class once may cover all three. Ask 12 is separate and, I
would argue, the most urgent of the four: an agent-legibility stack whose
working data-flow graph is invisible to agents has the two halves the wrong way
round.

---

## 7. Open questions the owner has *not* answered

1. **Is caller-composed chaining worth having at all?** `FromJob` fixes the
   edge at **authoring** time; Dagger's caller assembles it at **call** time,
   including from the CLI. I now doubt it fits here — rise converges state
   rather than transforming artifacts, so authored edges look like the honest
   shape — but that is a judgement, not a finding, and it is the owner's call.
2. **Sequencing of asks 9–12 against defect #32** (§6).
3. **`14` §3's one unprobed surface**: the MCP and TUI plugins were never
   probed directly — only the CLI adapter and `builtin info`, which share the
   `job_schema` renderer. A one-hour probe installing `functualize-mcp` and
   listing tools over a rise group would close it. It is a **check, not a
   choice**; nothing else depends on the answer.
4. **zvec-grep index**: offered, not built (~51s, ~62MB). Requires explicit
   authorization and must never be built silently.
5. **`guide/subjects.md` has not landed** in `docs/guides/`. Its 9 cross-links
   read as broken until it does — documented as expected in `guide/README.md`.

---

## 8. Revised Dagger recommendation (`19-dagger-parity.md` §6)

Post-correction ordering:

| | Do | When |
|---|---|---|
| 1 | **G1a** — surface `FromJob` edges in `job_detail` (ask 12) | now; it is a defect |
| 2 | **G1b** — let rise actions return their substrate, so they can be `FromJob` sources at all | before modules exist |
| 3 | **G2** — zero-setup tracing spans | after build step 5 |
| 4 | **G5** — just-in-time / ephemeral services | with the registry, build step 8 |
| 5 | **G3** — a result cache, pure actions only | after `06` |

G1b is **not** "adding chaining" — it is *not foreclosing* the chaining that
already exists. An action returning `None` can never be a `FromJob` source.
Cheap now, breaking later.

§4 records what **not** to copy from Dagger, and §5 what this stack has that
Dagger does not.

---

## 9. House rules — you will break something if you skip these

**Repository**

- **The spec gate is enforced by a `PreToolUse` hook.** Modifying
  `src/functualize/**` or `plugins/*/src/**` requires an existing
  `.spec/features/*/tasks.md` carrying a parseable `## Task Dependency Graph`.
  Produce one via `/agentic-specify` → `/agentic-plan` *first*, or the write is
  denied. `.spec/`, `tests/`, `docs/`, `contributor/` and `.claude/` are
  ungated — which is why all work so far has been possible.
- **Conventional commits are hook-enforced.** Allowed types: `feat`, `fix`,
  `docs`, `refactor`, `test`, `perf`, `ci`, `build`, `chore`, `revert`.
  `spec:` is **rejected** — use `docs(spec): …`.
- **Git strips `##` headings from commit messages as comments.** Use
  `git commit --cleanup=verbatim` when the body contains them.
- **Never use bare `git stash` / `git stash pop`.** The stash stack is shared
  across worktrees and other sessions may be using it. Prefer a temporary WIP
  commit; if you must stash, `git stash push -u -m "<unique-tag>"`, capture the
  SHA, and `git stash apply <sha>`.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

**Owner preferences**

- **Ask outstanding decisions one at a time**, in simple wording, with a
  snippet, an example and a use case — written so the question is answerable
  **without reading any file** and without assuming any context. This is
  explicit and repeatedly reinforced.
- Answer only in **English or Indonesian**. Never Chinese.
- Internet access order: **WebFetch/WebSearch first** (free) → **ctx7** for
  library docs → **Firecrawl last resort only** (paid, limited credits).
- Persistent operational memory belongs in **Lark**, profile `hakim-co`,
  `--as bot` for wiki/docs/tasks and `--as user` for calendar/mail. Prefix
  agent-created artifacts with `Agent-`.

**Retrieval**

- `graphify` is built and portable (8,608 nodes, committed as
  `graphify-out/graph.json`); `.serena/` is committed too. `.zvec-grep/` is
  **never** committed, and creating or rebuilding a persistent index needs
  explicit authorization.
- The repo ships a `code-intel` skill that routes a codebase question to the
  right tool. Use it before guessing.

---

## 10. Traps

- **Do not read the superseded scratch folders.** §1 says why.
- **Do not trust the corpus's prose over the source.** Two of its claims have
  already been falsified — probe 11's collision claim, and my own chaining
  claim. `path:line` citations are into 0.2.3 and the base is now 0.3.0.
- **`13-upstream-asks.md` §1–§5 read as though the defects are live.** They are
  the preserved 0.2.3 argument, not open work. Its top banner says so and the
  bottom Summary table is authoritative. Read the Summary first.
- **Ask numbering has collided once already.** `17` §3 defines ask 9, `18` §5
  ask 10; `13`'s table is the only place all twelve are indexed. Add new asks
  there.
- **Probes import functualize from *this* repository**, so no external checkout
  is needed — but that also means their output changes when the base moves.
  That is the point of them.

---

## 11. If you do exactly one thing next

Re-probe against `origin/master` (0.3.0), fix the `resume_gate` /
`list_active_workflows` / `--scope-id` references in `16-skill-to-workflow.md`,
and re-pin the version basis in the 13 files that still say 0.2.3. That is
mechanical, it is certainly needed, and it does not pre-empt any decision the
owner still has to make.

Then **stop and wait.** The owner reviews one item at a time and has asked to
drive that pace.
