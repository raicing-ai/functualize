# Skill evals

Measures the end-user agent skills in [`../skills`](../skills) — `functualize`,
`functualize-cli`, `functualize-app`, and `functualize-skill`.

**This is deliberately not pytest.** Every case here spends real money and real
wall-clock on a live agent run, which is the opposite of what CI on a pull
request should do. It runs on demand only; `tests/` stays fast.

---

## Quickstart

```bash
cd evals

npm install                              # promptfoo, pinned
npm run image                            # build the sandbox container (once)
# one credential — see "Credentials" below for which one you have
export CLAUDE_CODE_OAUTH_TOKEN=...       # subscription (run `claude setup-token`)
# export ANTHROPIC_API_KEY=sk-ant-...    # ...or API billing, not both

npm run preflight                        # free; fails fast if anything is off
npm run validate                         # free; schema-checks every suite
npm run doctor                           # ~$0.001; proves it actually authenticates

npm run case                             # free; list every case
npm run case -- secret                   # ONE case, one repeat — cents
npm run trigger                          # routing only — ~1 min, cents
npm run task                             # `functualize`      — ~30 min, dollars
npm run app                              # `functualize-app`  — dollars
npm run skill                            # `functualize-skill`— dollars
npm run all                              # all four, sequentially

npm run gate                             # free; did that run pass? (see below)
npm run view                             # browse the last results
```

**Improving a skill starts with `npm run case`, not `npm run task`.** See
[Iterating on one case](#iterating-on-one-case).

`promptfoo`'s own exit code answers "did every assertion pass", which is the
wrong question for a non-deterministic suite. **`npm run gate` is the verdict** —
see [What counts as passing](#what-counts-as-passing).

Run `npm run preflight` first. It is free and catches the mistakes that
otherwise surface only after you have started paying: no credential, no
container image, no engine.

The gated pairs `npm run trigger:ci` / `npm run all:ci` run a suite and then
let the gate decide the exit code.

> `npm run all` runs **one eval per suite, sequentially**. It must not be
> written as `promptfoo eval -c 'suites/*.yaml'`: promptfoo *merges* multiple
> configs into a single eval and takes the cross-product, so every provider in
> every suite runs against every test in every other suite — 5 providers x 35
> tests instead of 35 cases, most of them nonsense (a routing probe with no
> shell, handed "build me an app"), times the repeat count. Hours and tens of
> dollars per invocation. The same trap applies to `-c a.yaml -c b.yaml`.

## Iterating on one case

`npm run task` answers "is the suite green". It is the wrong tool for making a
skill better: 9 cases x 2 arms x 3 repeats is half an hour and dollars per
iteration, and what comes back is a scoreboard. Skill work is a loop over a
*single* scenario — read the trace, find the question the agent could not answer
from the skill, answer it in the skill, run that one case again.

```bash
npm run case                       # every case in every suite, with its slug
npm run case -- secret             # run the one whose slug matches
npm run case -- secret --repeat 3  # ...three times, once it looks right
npm run case -- secret --both      # ...and the baseline arm too
npm run case -- secret --show      # ...printing the agent's full reply
npm run case -- secret --dry-run   # just print the promptfoo command
```

Defaults are chosen for the loop rather than for the verdict: **one repeat, the
`with-skills` arm only, workspace kept on disk.** That is roughly a sixth of
what the same case costs under `npm run task`. It prints the contract the case
is graded on *before* spending anything, so a case you are about to iterate on
cannot surprise you:

```
suite    suites/functualize.yaml
case     uses-secret-for-a-credential
fixture  uv-mise-repo
arm      with-skills   repeat 1
graded on
  · source_contract.py  require: config field marked secret; …
```

...then, afterwards, what the agent actually did — skills loaded, every bash
command, every check with its exit code, the assertion's reason, and the path to
the kept workspace. An ambiguous slug lists the matches rather than picking one,
and a missing credential stops the run *before* it starts, because `claude`
answers "Please run /login" and the case would otherwise report as a **failing
skill**.

Reach for `npm run task` + `npm run gate` when you want the verdict, and for the
two-stage pair when you want it cheaply:

```bash
npm run smoke                      # every task case, --repeat 1, with-skills only
npm run confirm -- <eval-id>       # only what failed, --repeat 5, then gate
```

A flat `--repeat 3` pays three times over on the cases that were never going to
fail. One pass finds the candidates; the second spends the repeats where the
0/k-versus-flaky distinction is actually decided.

## Seeing progress

A single case is 10-60 seconds of an agent thinking, and promptfoo's bar only
advances on *completion* — so a working run and a wedged one look identical.
The harness therefore narrates every step to stderr, which promptfoo passes
straight through to your terminal:

```
[12:56:18 +   0.0s] snapshot building source snapshot (once per process)...
[12:56:18 +   0.3s] snapshot ready at /tmp/fz-eval-src-pl6hfs03
[12:56:31 +  13.2s] agent  START [docker] Add a job to this project called `greet`...
[12:57:44 +  86.1s] agent  done   in 73s - 8 turns, $0.114, 14 tool calls, skills=['functualize']
[12:57:51 +  93.0s] check  [ok]    7s  uv run func greet world
```

The same lines are appended to `results/progress.log`, so you can review a
finished run or follow one from another terminal:

```bash
npm run watch      # tail -f results/progress.log
```

Point it elsewhere with `FZ_EVAL_LOG=/path/to/file`. Progress reporting never
fails a run - if the log is unwritable it is silently skipped.

`npm run trigger` also passes `-j 6`, so six routing probes run at once and
results land steadily instead of in one clump at the end. The task suites keep
the default concurrency: they each build a container and run `uv sync`, so
piling six on at once mostly buys memory pressure.

## Credentials

The harness passes an **allowlisted environment** to the agent, not a copy of
your shell, and gives it a throwaway `HOME`. That is a safety property, but it
has a consequence worth stating plainly:

> **Being logged in to `claude` on your host is not enough.** The agent gets an
> isolated `HOME`, so it never sees your `~/.claude` credentials. You have to
> hand it one explicitly.

There are two kinds of credential and they are **not interchangeable**:

| You have | Export | Notes |
| --- | --- | --- |
| A Claude subscription (Pro/Max) | `CLAUDE_CODE_OAUTH_TOKEN` | Mint it with `claude setup-token` (requires a subscription). This is a long-lived OAuth token, **not** an API key: signing into `claude` does not give you an `ANTHROPIC_API_KEY`, and this token is not usable against the raw Anthropic API. |
| API billing (console.anthropic.com) | `ANTHROPIC_API_KEY` | The `sk-ant-...` key. Billed per token against that account. |

```bash
# subscription: run the interactive flow, then export the token it shows you
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN=<the token it printed>

# or API billing
export ANTHROPIC_API_KEY=sk-ant-...

# or, host mode only: reuse the login you already have, no token needed
export FZ_EVAL_INHERIT_HOME=1
```

`claude setup-token` is an interactive browser flow, not something to wrap in
command substitution — it prints the token for you to copy once.

> **Set exactly one.** `claude` prefers `ANTHROPIC_API_KEY` whenever several are
> present, so a stale key left in a shell profile silently beats a subscription
> token you just exported — and the run 401s while both look correctly
> configured. The harness forwards **one** credential, preferring
> `CLAUDE_CODE_OAUTH_TOKEN`, and `preflight` names the one it dropped:
>
> ```
> [ok  ] credential: CLAUDE_CODE_OAUTH_TOKEN (sk-ant-o…, 108 chars)
> [warn] also set but NOT forwarded: ANTHROPIC_API_KEY
> ```
>
> Force the other with `FZ_EVAL_AUTH=api-key` (or `oauth`).

`FZ_EVAL_INHERIT_HOME=1` passes your real `HOME` through, so an existing
`claude` login works with no token at all — at the cost of the agent being able
to read `~/.claude`. Fine for a local debugging run, wrong for CI, and host
mode only (the container never sees your home).

### Proving it works

`preflight` checks a credential is *set*. **`npm run doctor` checks it
*authenticates***, by making one tiny real call through the exact path the
suites use — same env allowlist, same sandbox wrapper, same streaming parser —
in both modes:

```
credential         : CLAUDE_CODE_OAUTH_TOKEN
HOME for the agent : /tmp/fz-eval-...-home

─── docker ──────────────────────────────────────────────
  ok    sandbox runs commands
  ok    claude present: 2.1.251 (Claude Code)
  ...   calling the API (a few seconds)
  ok    API round trip: FUNCTUALIZE-OK ($0.0009)
```

It probes three things that fail **independently**, so a failure localises
instead of leaving you guessing:

| Probe | Answers |
| --- | --- |
| sandbox | can it run a command at all (image present, mounts, uid) |
| agent | can `claude -p` reach the API with your credential |
| **grader** | can `llm-rubric` assertions authenticate and return a verdict |

The grader arm matters because it is the one failure a suite run disguises: the
agent path can be perfect while every rubric fails, and that reports as failing
*skills*. Skip it with `npm run doctor -- --no-grader`.

**If it reports `401 authentication_failed`**, the credential reached the API
and was refused. In order of likelihood:

1. **Two credentials set, the wrong one forwarded.** Check doctor's first line
   against the `auth=` in the stream — they name the variable actually used.
2. **Wrong account.** An `sk-ant-...` key from a different org than you meant.
3. **A subscription login used as an API key.** Being signed into `claude` does
   not give you `ANTHROPIC_API_KEY`; run `claude setup-token` and export
   `CLAUDE_CODE_OAUTH_TOKEN` instead.
4. **A stale OAuth token.** Re-mint it with `claude setup-token`.

That failure used to look exactly like a hang: `claude` retries a 401 ten times
with exponential backoff, well past two minutes of silence. The harness now
watches the `api_retry` events and abandons a 401/403 on the first one, so a bad
credential fails in ~2 seconds and names itself:

```
13:25:30 w8003   · model=claude-opus-5 auth=CLAUDE_CODE_OAUTH_TOKEN
13:25:31 w8003   ! API 401 authentication_failed — retry 1/10
13:25:31 w8003 ✖ agent credential rejected by the API (401 authentication_failed).
```

The `auth=` line comes from `claude` itself, so it is the authority on which
credential was actually used — not what you think you exported.

Everything below — and nothing else — reaches the agent:

| Passed through | Deliberately withheld |
| --- | --- |
| **Exactly one** of `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` | the other two, even when set |
| `ANTHROPIC_BASE_URL`, `PATH`, `LANG`, `LC_ALL`, `TERM`, `TZ` | `SSH_AUTH_SOCK`, `GH_TOKEN`, `AWS_*`, and everything else in your shell |
| `HOME`, pointed at a throwaway directory | your real `HOME` (unless `FZ_EVAL_INHERIT_HOME=1`) |

To change what is passed, edit `BASE_ENV_ALLOWLIST` (non-credential vars) or
`CREDENTIAL_VARS` (the preference order) in `providers/_harness.py`. Both are
short, deliberate lists; keep them that way.

Cost control lives in the suites: `max_turns` caps a runaway agent and `runs: 3`
sets the repeat count. At `--repeat 3` a full `npm run all` is **132 agent
runs**: 63 routing probes (cheap, no shell) plus 69 full agent runs (54 of them
the `functualize` suite's two arms). Dropping the `baseline` arm takes it to
105 and removes 27 of the expensive ones.

## Sandboxing

Agent runs use `--permission-mode bypassPermissions` with Bash enabled, which
Claude Code's own help describes as *"Recommended only for sandboxes with no
internet access."* Three measures make that defensible.

**1. Fixtures never touch your checkout.** They depend on functualize by path,
and that path is a **snapshot**, so uncommitted framework changes are still
under test but an agent that misdiagnoses a fixture bug as a framework bug edits
the copy. The dependency is also **not** editable, so nothing writes build
artifacts back into the source tree.

The snapshot is **narrowed to what a path build actually needs** —
`SNAPSHOT_INCLUDE` in `providers/_harness.py`, which mirrors pyproject's sdist
`only-include` plus `pyproject.toml`, `uv.lock` and the plugin manifests the uv
workspace requires. 381 files, not 1571.

That is a *validity* measure, not only a safety one. It used to be the whole
working tree, which handed every agent a read-only checkout of `evals/`
(including the suites grading it), `examples/`, `tests/`, `contributor/` and
`AGENTS.md` at `/src`. One case caught it outright: "hands framework-internal
work back to the functualize repo" failed all three repeats because the agent
found `/src/tests/tui_audit`, installed the dev group from `/src/uv.lock`, ran
the suite to green and reported "no bug in the source" — a perfectly good answer
to a question no real user can ask, since a real user has site-packages and
nothing else.

> Note the limit of this. The wheel carries the skills at
> `functualize/_skills/`, so **the `baseline` arm can still read them out of its
> own `.venv`** — a mount cannot fix that, because it is what shipping the
> skills means. Another reason the baseline arm is not the number to read.

**2. The environment is allowlisted**, per the table above.

**3. `sandbox: docker`** — the default for the task suites — runs the agent *and*
the verification commands in a container: workspace read-write at `/work`, the
source snapshot **read-only** at `/src`, `--security-opt no-new-privileges`, a
4 GB memory cap and a 512 pid cap. Checks share the container by necessity: a
`.venv` built inside it is not runnable from the host, so a host-side check
would report failures the agent never caused.

Engine detection prefers **rootless podman**. The agent must not be root
inside the container — Claude Code refuses `bypassPermissions` under uid 0, and
rootless podman maps the caller to root by default — so podman runs get
`--userns keep-id` (same uid inside as out) and docker runs get
`--user $(id -u):$(id -g)`. Either way bind-mounted files come back owned by
you, not root.

> The first `keep-id` run remaps the image's layers and can take a minute with
> no output. Subsequent runs are instant. It is not hung.

| Knob | Default | Purpose |
| --- | --- | --- |
| `FZ_EVAL_SANDBOX` | per suite (see below) | `host` or `docker`; **overrides** every suite's `sandbox:` key |
| `FZ_EVAL_ENGINE` | auto-detect | force `podman` or `docker` |
| `FZ_EVAL_IMAGE` | `functualize-evals:latest` | image tag |
| `FZ_EVAL_MEMORY` | `4g` | per-container memory cap |
| `FZ_EVAL_AUTH` | prefers OAuth | force which credential is forwarded: `oauth` or `api-key` |
| `FZ_EVAL_MODEL` | `claude-sonnet-5` (pinned per suite) | override the model under test; env beats the suite |
| `FZ_EVAL_KEEP` | `failed` | keep workspaces on disk: `all`, `failed`, or `none` |
| `FZ_EVAL_INHERIT_HOME` | unset | `1` passes your real `HOME` so an existing `claude` login works (host only) |
| `FZ_EVAL_SNAPSHOT_DIR` | `$TMPDIR` | where the shared source snapshot lives |
| `FZ_EVAL_LOG` | `results/progress.log` | progress log path |

### Which suite runs where

Not everything is containerised, and the split is deliberate:

| Suite | Default | Why |
| --- | --- | --- |
| `suites/triggering.yaml` | **host** | its provider allows no tool but `Skill` — no shell to contain, no image needed |
| `suites/functualize*.yaml` | **docker** | a full agent with Bash |

`FZ_EVAL_SANDBOX` beats the `sandbox:` key in a suite, in both directions:
`FZ_EVAL_SANDBOX=docker` containerises the routing probe too,
`FZ_EVAL_SANDBOX=host` takes the task suites out of the container. An
unrecognised value raises rather than falling back — a typo silently running
unconfined is the failure this knob exists to prevent.

`npm run preflight` prints the effective mode for both, so you never have to
infer it.

The container still has network access — the agent must reach the API and `uv`
must reach PyPI. It is a blast-radius limiter for a *confused* agent, not a
boundary against a hostile one.

> ⚠️ **`FZ_EVAL_SANDBOX=host` runs an unattended agent on your machine with no
> permission prompts and unrestricted Bash.** The snapshot and the env allowlist
> still apply, so your checkout and your credentials are protected, but nothing
> else is. Use it to debug the harness, not for a full run.

## The three axes

A skill can fail independently at each, and a suite that measures only the last
one will happily report green while the skill never loads at all.

| Axis | What breaks | Where it lives | Cost |
| --- | --- | --- | --- |
| **Freshness** | The skill documents a flag that no longer exists | [`tests/skills/`](../tests/skills/), *not here* | free |
| **Routing** | The description never fires, or the wrong one of the four wins | `suites/triggering.yaml` | cents |
| **Task outcome** | It fires, and the code it writes does not work | `suites/functualize*.yaml` | dollars |

Freshness is not in this directory on purpose — it needs no model, so paying an
agent to check it would be wasteful. `tests/skills/` already covers it in the
fast pytest suite: `test_api_claims.py` checks that every type, flag and command
a skill names still exists, `test_cli_surface.py` that `func` points at the
skills, `test_runnable_snippets.py` that the introspection one-liners the skills
tell agents to run actually run, and `test_frontmatter.py` that the shipped
skills stay on the portable six fields.

## The suites

Four suites, one npm script each. `npm run case` runs a single case out of any
of them and is where skill work actually happens; these are for the verdict.

| Suite | Script | Cases | Arms | Subject |
| --- | --- | --- | --- | --- |
| `suites/triggering.yaml` | `npm run trigger` | 21 | `router` | which of the four skills a query loads — no shell, no fixture |
| `suites/functualize.yaml` | `npm run task` | 9 | `with-skills`, `baseline` | the core reference skill: does it produce working code |
| `suites/functualize-app.yaml` | `npm run app` | 4 | `with-skills` | the procedural skill: does the program it builds run |
| `suites/functualize-skill.yaml` | `npm run skill` | 3 | `with-skills` | the meta skill: is the skill it authors well formed |

Only `functualize.yaml` carries a `baseline` arm. functualize is not in any
model's training data, so baseline scores near zero everywhere and the delta is
uninformative — see [Reading the baseline arm](#reading-the-baseline-arm). The
other suites dropped it rather than pay for it.

`npm run all` runs the four in that order. Repeat count is `FZ_EVAL_REPEAT`,
default 3.

### The two shapes an app can take

`functualize-app` §1 opens with a decision table, and its first row — *one
command, no project, must run anywhere ⇒ a single file with a PEP 723 header* —
is the one that is easy to leave untested. Every other case in the app suite
wants a project, and `greenfield` *requires* `scaffold init` in the trace, so an
agent that scaffolds unconditionally passes all of them. `standalone-one-file-with-a`
is the counterweight: the `loose-script` fixture has no `pyproject.toml`, the
trace forbids `scaffold init`, and a check asserts none was created.

`bundles-a-standalone-pep-723` applies the same shape to `functualize-skill`, whose
§"Scripts that do real work" forwards bundled scripts to that same reference.
It uses `loose-script` rather than `bootstrap` deliberately: `uv run` walks *up*
to the nearest project, so `uv run func --help` inside a skill directory under
`bootstrap` succeeds against bootstrap's own project whether or not the bundled
script is self-contained.

Both invoke the produced script as `func <script.py>`, never `uv run --script
<script.py>`. Only `func` reads the `# /// script` block and dispatches to the
job named in `[tool.functualize]`; `uv run --script` hands the file to `python`,
which executes the module body — imports and a `def` — and exits **0 having run
nothing**. A check written that way passes on a file that is not a program.

## Fixtures

A fixture is a directory under `fixtures/`, copied into the throwaway workspace
before the agent starts. `{{REPO_ROOT}}` is rewritten to the source snapshot
(`/src` under docker) — but only in `.toml`, `.cfg`, `.ini`, `.txt` and `.md`
files, so a fixture cannot ship a `.py` that depends on it.

| Fixture | Shape | Used by |
| --- | --- | --- |
| `uv-mise-repo` | a working project with jobs in `src/acme/jobs.py` and a `uv.lock` | most of `functualize.yaml`, two app cases |
| `undiscovered-job` | a project whose `.functualize.toml` silently hides one job | `diagnoses-a-silently-undiscovered-job` |
| `bootstrap` | an empty project with functualize on the path dependency, ready to scaffold into | `greenfield`, `authors-a-skill-whose-script` |
| `team-repo` | a shared repo with a `RELEASE.md` and a committed `.claude/` | `places-a-team-skill-in` |
| `loose-script` | **no project at all** — no `pyproject.toml`, nothing to `uv sync` | the two standalone-script cases |

`loose-script` cannot pin functualize in a `pyproject.toml`, because it has
none, and a PEP 723 header resolves `functualize[cli]` from **PyPI** — which is
a real, older release. So the fixture records the snapshot path in
`functualize-path.txt` (a `.txt`, so it is token-expanded) and its `README.md`
tells the agent to depend on that path. Checks read the same file:

```yaml
checks:
  - 'uv tool run --from "functualize[cli] @ file://$(cat functualize-path.txt)" func disk_report.py --help'
```

That works in both sandbox modes, needs nothing installed first, and does not
assume which shebang the agent chose.

> Write `uv tool run`, not `uvx`. The sandbox image copies only `/uv` out of
> the upstream uv image, so `uvx` is `sh: 1: uvx: not found` inside the
> container — a check that fails identically whether the agent wrote a perfect
> script or none at all.

New fixtures reference functualize as `{ path = "{{REPO_ROOT}}" }` — never with
`editable = true`, which would hand the agent a writable handle on the source.

## How a case works

`providers/claude_agent.py` is a promptfoo provider that, per run:

1. builds a throwaway workspace from a directory in `fixtures/`, with
   `{{REPO_ROOT}}` rewritten to the source snapshot (`/src` under docker),
2. mounts `../skills` into it as `.claude/skills/` — **or does not**, which is
   the ablation,
3. runs `claude -p` headless with `--setting-sources project`, so your own
   `~/.claude/skills` is out of both arms and the only difference is this repo,
4. runs the case's `checks` shell commands in the same sandbox afterwards,
5. returns the tool-call trace, the produced files, and the check exit codes.

Assertions in `asserts/` grade that record. Most never consult a model:

| Assertion | Grades |
| --- | --- |
| `checks_pass.py` | Did the produced program run? Exit codes only. |
| `trace_contract.py` | What the agent *did* — e.g. ran `func builtin` instead of guessing |
| `env_prefix.py` | The invocation ladder: `uv run func`, first try, no stray `pip install` |
| `source_contract.py` | Greps produced source for `Secret[...]`, `Log`, bare `print(` … |
| `frontmatter_legal.py` | A produced `SKILL.md` stays on the portable six fields |
| `skill_selected.py` | Which of the four skills won the routing decision |

The few `llm-rubric` cases exist only for judgments with no exit code — did it
*decline* to invent a capability, did it *hand off* rather than answer.

> **`llm-rubric` does not use your credential by default.** It grades with
> **gpt-5 over the OpenAI API**, a separate key from the one the agent runs on.
> With no `OPENAI_API_KEY` every rubric fails at the grader and reports as a
> failing skill — and a subscription OAuth token cannot stand in, since it
> authenticates Claude Code rather than the raw API. The suites therefore set
> `defaultTest.options.provider: file://../providers/claude_grader.py`, which
> grades through the same `claude -p` path as everything else, so one
> credential covers the whole directory. `FZ_EVAL_GRADER_MODEL` overrides the
> grading model; the grader runs with **no skills mounted**, so the thing under
> test cannot bias its own verdict.

A failing run keeps its workspace and names the path in the result, so you can
go and look. Passing runs are deleted.

## Seeing what the agent actually did

`npm run view` shows scores. To read the *work* — the code it wrote, the
commands it ran, which skill it loaded — use the inspector:

```bash
npm run inspect                    # summary of the latest run
npm run inspect -- --failures      # only the cases that failed
npm run inspect -- --extract       # write everything to results/runs/
npm run inspect -- --list          # older runs, by id
npm run inspect -- --eval <id>     # a specific one
```

The summary shows, per case, what was expected against what happened, the
first few commands the agent ran, every verification check with its exit code,
and the assertion's reason for failing:

```
✖ [0/3] with-skills  resolves the invocation prefix without guessing
      $ uv sync
      $ uv run func greet world
      [x1] uv run func greet world
      → First `func` call did not use `uv run`: pip install functualize
```

`--extract` writes one directory per run under `results/runs/<eval-id>/`:

| File | What it holds |
| --- | --- |
| `workspace/` | **every file the agent wrote**, at the paths it wrote them |
| `trace.txt` | the tools it called, in order |
| `checks.txt` | each verification command with its exit code and output |
| `answer.md` | its final reply |
| `case.json` | the prompt vars, score, cost, and failure reasons |

Routing cases have no `workspace/` — they are probes and produce no code.

For a failing task case you may want the *live* workspace, `.venv` and all, to
re-run a check by hand. Those are kept automatically (the run reports the path)
and `FZ_EVAL_KEEP=all` keeps passing ones too.

## Reading the baseline arm

The task suites run a `baseline` arm with no skills mounted. **Do not read the
delta as the score.** functualize is not in any model's training data, so the
baseline sits near zero and the delta is enormous no matter how good or bad the
skill is. All it establishes is that the skill is load-bearing.

The number that matters is the per-case `with-skills` pass rate: that is where
the skill is still failing. Once you have measured the floor once, delete the
`baseline` provider from the suite and halve your spend.

## Variance

Repeats come from promptfoo's `--repeat`, which the npm scripts pass as
`--repeat 3`. There is no `runs:` key in `defaultTest` — that is a different
tool's concept and promptfoo ignores it silently, so a suite that looks like it
repeats may be running each case exactly once. Check the run count in
`npm run inspect` against your case count.

A single run of an agent eval is noise. Go to `--repeat 5` before calling a
small regression real — via `npm run smoke` + `npm run confirm`, which spends
the repeats only on what failed rather than flat across the suite.

`FZ_EVAL_REPEAT` overrides the repeat count of every npm script.

## What counts as passing

**Not a percentage.** `npm run gate` decides, and it decides on the *shape* of
the failures rather than their count:

```
npm run trigger          # run it
npm run gate             # then: does this run pass?
npm run trigger:ci       # both, with the gate's exit code as the verdict
```

| Shape | Meaning | Verdict |
| --- | --- | --- |
| harness error | the run never happened — credentials, sandbox, timeout | **blocks**, and is not a quality signal at all |
| 0/k | reproducible defect | **blocks** |
| 1/k … k-1/k | the model being a model | reported, does not block |
| k/k | pass | — |
| aggregate < floor | broad erosion no single case makes obvious | **blocks** (default 90%, `--floor` / `FZ_EVAL_FLOOR`) |

The `baseline` ablation arm is excluded before gating — it is *designed* to
score near zero, so gating on it would fail every run. `--exclude-arm ''`
includes it.

### Why not just a pass-rate threshold

Because this repo has already produced the counterexample. A run came in at
**60/63 = 95.2%**, which clears the 95% floor that most guidance suggests —
while one case failed **all three repeats**. That case was a real, reproducible
defect and the percentage hid it.

promptfoo cannot express the distinction: `PROMPTFOO_PASS_RATE_THRESHOLD` is
global across the suite, so a case can fail every repeat and still exit 0 if
the others carry the average ([promptfoo#5847][pf5847]). Hence `scripts/gate.py`.

The published floors — safety ≥95%, task success ≥80% — are worth knowing but
are the weaker gate. The stronger one is delta from your own baseline: run the
suite a few times on a known-good build, watch where it settles, and set the
floor a comfortable margin below that so ordinary noise stays green.

Conversely, do not gate on 2/3. With k=3 the 95% confidence interval on a 2/3
case runs roughly [0.09, 0.99] — it is not distinguishable from a 3/3, and
blocking on it teaches everyone to ignore the gate.

[pf5847]: https://github.com/promptfoo/promptfoo/issues/5847

### Routing failures vs behaviour failures

Keep them in the suite that can measure them. `suites/triggering.yaml` runs a
probe that stops the agent after its first step and asks for one sentence about
what it did — so it can answer "which skill fired" and nothing else. An
`llm-rubric` about what the agent *said to the user* placed there grades the
probe's own `STOP_INSTRUCTION`, not the skill.

That is not hypothetical: the two contributor-handoff cases lived there and one
failed 3/3 while routing was perfectly correct. They now assert routing in
`triggering.yaml` and behaviour in `functualize.yaml`, where the agent runs to
completion.

## Adding a case

Cases are derived from claims the skills make, so each should be traceable to a
line in a `SKILL.md`:

```yaml
- description: what contract this pins
  vars:
    fixture: uv-mise-repo          # a directory under fixtures/
    task: >-                       # the user prompt, written like a real one
      ...
    checks:                        # shell, run in the sandbox, exit 0 = pass
      - 'uv run func thing --flag'
  assert:
    - type: python
      value: file://../asserts/checks_pass.py
```

Prefer a `check` over an assertion, and an assertion over a rubric. If you find
yourself reaching for `llm-rubric`, ask what command would settle it instead.

> ⚠️ **Assertion `config:` is not templated.** promptfoo renders test `vars`
> but passes an assertion's `config` block through verbatim, so `{{expect}}`
> arrives as the literal five characters and every comparison silently fails.
> Read per-case values from `context["vars"]`; keep `config` for static things
> like regex patterns. This cost a whole run before it was spotted, because a
> uniformly-failing suite looks like a bad skill rather than a bad harness.

If no existing fixture has the shape you need, add one — see
[Fixtures](#fixtures) for the `{{REPO_ROOT}}` rules and the reason
`loose-script` carries a `functualize-path.txt`.

## Relationship to `tests/skills/`

The two suites apply some of the same rules to different subjects, which is not
duplication:

| Rule | `tests/skills/` checks | this directory checks |
| --- | --- | --- |
| Portable-six frontmatter | the skills **we ship** | a `SKILL.md` an agent **produced** |
| Named APIs exist | prose in our skills | code an agent **wrote** |

If a rule can be settled without a model, it belongs in `tests/skills/` and
should be deleted from here.

## CI

[`.github/workflows/skill-evals.yml`](../.github/workflows/skill-evals.yml) is
**`workflow_dispatch` only** — never on a push, a pull request, or a schedule.
It builds the sandbox image as a step and uploads results as an artifact.

Run it after editing a `SKILL.md`, from the Actions tab or:

```bash
gh workflow run skill-evals.yml -f suite=triggering
```

A weekly cron used to sit here to catch drift from merged skill edits. It is
commented out at the top of the workflow rather than deleted: an unattended job
that spends money every Monday needs an owner for both the bill and the
results. Restore it when there is one.

It needs one credential as a repository secret. Prefer `ANTHROPIC_API_KEY`
there: an OAuth token from `claude setup-token` is tied to a personal
subscription and expires — which matters most if you ever restore the cron, as
a scheduled job then fails silently weeks later. `FZ_EVAL_INHERIT_HOME` must
never be set in CI — there is no home to inherit.

The job runs `preflight` → `doctor` → the suite → `gate`. The eval step ends in
`|| true` on purpose: promptfoo exits non-zero on any single failing assertion,
which is not the question being asked. **The gate step is the verdict.** It
runs with `--max-age 120`, so if promptfoo dies before writing anything the
gate refuses to grade the previous run and calls the pipeline good.

## The discovery boundary

`func builtin info schema` prints every job's arguments as JSON Schema in one
call, and the skills now point at it before `--help`. Two cases guard the
routing that follows from that:

- *"list every job and its args, machine readable"* → **`functualize`**, whose
  §1 owns `info schema`. It is a question about the jobs.
- *"make `builtin info` print JSON by default"* → **`functualize-cli`**, which
  owns `[cli] output`. It is a question about the tool.

`suites/functualize.yaml` additionally checks the *behaviour*, in two cases:

- given "tell me every job and what it takes", the agent must reach for the
  structured surface rather than opening each group's `--help` in turn;
- given a task that needs a *builtin* (clear runtime state, not the cache), it
  must find the right command rather than spelunking `func builtin --help` or
  guessing a plausible-looking flag.

Walking `--help` still produces a right-looking answer, so only the tool trace
can tell the two apart — exactly the kind of rule that cannot move to
`tests/skills/`. The second case also has a wrong-but-adjacent answer
(`builtin cache clear`) that a confident agent reaches for, which is what
`forbid_bash` pins.

## The tool/jobs boundary

`functualize` and `functualize-cli` once both advertised the literal trigger
*"when `func` is not found"*. That is settled: `functualize-cli` owns the tool
(is it installed, which one is on PATH, what version), `functualize` owns the
jobs, and each description now says so explicitly. The `func-not-found` cases in
`suites/triggering.yaml` are the regression guard — if they start failing,
someone reintroduced the overlap in a description.

Note that the invocation-prefix table is still duplicated in prose between
`functualize` §0 and `functualize-cli` §2. That is defensible (§0 is a
precondition an agent needs before doing anything) but it is two copies of one
table, and `tests/skills/` will not notice if they drift apart.
