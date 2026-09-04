---
name: functualize-app
description: >
  Build a CLI or TUI program on functualize, end to end — decide between a
  single-file script and a scaffolded project, author jobs, configure the
  FunctualizeApp (job sources, discovery filters, config presets), write tests
  that actually catch regressions, and verify the program renders and runs. Use
  when starting a new functualize project, command-line tool, or standalone
  script, when adding a significant feature to one, when configuring or
  restructuring an existing functualize app, when asked to make one "production
  ready" or well tested, or when packaging a functualize CLI for distribution.
license: MIT
metadata:
  version: "0.2.2"
  project: functualize
---

# Building a functualize app

Load the **`functualize`** skill first — it carries the invocation ladder and
the four contracts that are wrong by default. This skill is the procedure
around them; it does not repeat them.

---

## 1. Choose the shape first

Three different things get called "a functualize app", and picking the wrong one
costs a migration later:

| If the work is… | Build | Entry point |
| --- | --- | --- |
| One command, no project, must run anywhere | **a single file** with a PEP 723 header — [references/standalone-scripts.md](references/standalone-scripts.md) | `./script.py` |
| Several jobs, shared config, a name and users | **a scaffolded project** — §2 onward | `myapp <job>` |
| An extension to functualize itself | **a plugin** — `--template plugin-project` | installed, not run |

The single-file route is not a lesser version of the project route: it is the
right answer whenever the program is one verb and the reader should not have to
install anything first. Migrating up later leaves the job function unchanged —
only its home and its dependency declaration move.

The rest of this skill is the project route.

## 2. Scaffold rather than hand-roll

```bash
<prefix> func builtin scaffold init <name> --template <template>
```

| Template | Use when |
| --- | --- |
| `simple` | One or more jobs plus layered config. The default; start here. |
| `full-interactivity` | The program prompts, streams events, or has workflow steps |
| `plugin-project` | You are extending functualize itself, not building an app |
| `job-folder` | A jobs directory with no `FunctualizeApp` and no `main.py` |

Adding pieces later:

```bash
<prefix> func builtin scaffold add job <name>
<prefix> func builtin scaffold add tui-screen <name>
```

Scaffold output is **yours** — a starting point, hand-edited afterwards. It is
not regenerated, so do not re-run `add` over a file you have edited.

---

## 3. Shape the jobs

Decide these before writing, because retrofitting them is disruptive:

- **What is a job?** One user-facing verb. If a function needs a paragraph to
  describe, it is probably two jobs.
- **Grouping.** Jobs in a group become `func <group> <job>`. Names are
  canonical lowercase-hyphenated.
- **Config vs flags.** A `JobConfig` pydantic model gives layered resolution,
  env vars, and `--help` for free. Reach for bare `Arg`/`Option` markers only
  for things that genuinely vary per invocation.
- **Secrets.** Any credential is `Secret[str]` from the first commit, not
  retrofitted. See the base skill's config reference.

For *which* declaration each intent calls for — `Deps` vs `FromJob`,
`Fingerprint` vs `Guards`, a workflow vs a chain — read the base skill's
[idiomatic reference](../functualize/references/idiomatic.md) before writing
declarations. It is indexed by intent and names the combinations.

### Keep the framework out of your domain layer

The single highest-value structural decision, and the one that is expensive to
undo. `jobs/` is a **wiring layer** — declarations plus a call into code that
imports nothing from functualize:

```
myapp/
├── main.py            FunctualizeApp + adapter — a handful of lines
├── config.base.toml   one section per job, addressed by job name
├── lib/               domain code — no functualize import anywhere
│   ├── models.py        pydantic models for the values jobs pass around
│   └── detect.py        the real logic, as plain functions
└── jobs/
    ├── audit.py       the stages: declarations, then delegation
    └── pipeline.py    the workflow topology and its gates
```

```python
# ✓ jobs/audit.py — declare, then delegate
@job(group=JOB_GROUP, cache=Fingerprint(sources=["repos/**/*.tf"]))
def collect(config: CollectConfig, log: Log) -> SourceTree:
    return build_source_tree(root=config.root)      # ← lib/

# ✗ 200 lines of parsing inline: untestable without booting an app
```

If a job body is long, the logic belongs in `lib/`, where it can be tested with
no framework at all and reused from somewhere that is not a CLI.

---

## 4. Wire it, then prove the wiring

A component that is built, unit-tested, and never reached is the failure mode
this framework has shipped more than once. Unit tests do not catch it.

For every new job, capability, or config field, **name each production path
that reaches it** — and note that cold-cache and warm-cache are *different
paths*:

- Cold: discovery scans the file, imports it, registers the job.
- Warm: the cached descriptor is read from disk; the file may never be
  imported at all.

Then break each path once on purpose and confirm something fails. Commit
first, sabotage, observe, `git checkout --` to restore — that restore discards
everything uncommitted in the file, which is why the commit comes first.

Sabotage also catches *vacuous tests*, which running them cannot.

```bash
<prefix> func builtin cache clear      # force the cold path
<prefix> func builtin info             # job still appears?
<prefix> func builtin why <job>        # and for the right reason?
```

---

## 5. Test

```python
from functualize.testing import TestRunContext, CapturingLog, FakeStdout

def test_deploy_logs_progress():
    log, out = CapturingLog(), FakeStdout()
    deploy(rc=TestRunContext.create(), log=log, out=out)
    assert ("info", "Starting deployment") in log.calls
    assert out.emitted[-1]["status"] == "ok"
```

The fakes record structurally, not as text: `CapturingLog.calls` is a list of
`(level, message)` tuples, `FakeStdout.emitted` is the list of objects passed to
`emit()` and `.text` is what a pipe consumer would have seen. `FakeStdout`
accepts an `output_format` so a test can pin the wire shape (`FakeStdout("json")`).

Because capabilities are injected by parameter type, a job is testable by
calling it directly with fakes — no CLI, no subprocess, no monkeypatching.
That is the main reason to accept a capability rather than reach for a module
global.

What to cover, in order of value:

1. **Config resolution** — the layered chain is where surprises live. Assert
   the resolved value under a given environment, not the default.
2. **The job's own logic**, with capabilities faked.
3. **Discovery** — that the job is actually found, on both cache paths.
4. **Failure modes** — what happens when a credential is missing, a dependency
   is down, a guard rejects.

Do not test that functualize injects capabilities. That is the framework's
test, not yours.

---

## 6. See it run

Tests passing is not the same as the program working. A CLI has a rendered
surface, and TTY and non-TTY paths diverge.

```bash
<prefix> func <job> --help          # flags read correctly?
<prefix> func <job>                 # runs?
<prefix> func <job> --output json   # machine-readable path intact?
<prefix> func <job> | cat           # non-TTY path — no control codes leaking?
```

For a TUI, run it and look at the screen. Snapshot tests confirm a screen has
not changed; they do not confirm it was ever right. If an agent cannot see the
terminal directly, drive it in a PTY and read back the rendered cells rather
than asserting on log output.

---

## 7. Configure the app itself

Two different things get configured and they are not the same question:

| Question | Where it is answered |
| --- | --- |
| What settings does *this job* take? | a `JobConfig` model + the layered config chain |
| How does *the app* find jobs, read config, load plugins? | `FunctualizeApp(...)` constructor arguments |

```python
from functualize.app import FunctualizeApp, JobSources, DiscoveryConfig, twelve_factor

app = FunctualizeApp(
    "myapp",
    job_sources=JobSources(directories=["jobs"]),
    config_sources=twelve_factor(),
    discovery_config=DiscoveryConfig(require_job_prefix="cmd_"),
)
```

**Pick the config preset deliberately** — it decides which sources exist at all,
not merely their order:

| Preset | Chain | Use when |
| --- | --- | --- |
| `classic()` | CLI → Env → Files (upward search) → Defaults | The default. A developer tool run from a repo. |
| `twelve_factor()` | CLI → Env → Defaults | Containers and CI: no file discovery, `dotenv=False`, so a run is reproducible |
| `env_only()` | CLI → Env → Defaults | Minimal configuration |
| `remote_first()` | CLI → Remote → Env → Files → Defaults | A remote config provider is authoritative |

`ConfigSources` is the escape hatch when none fits: it carries the file pattern,
the resolution chain, and whether `.env` loads.

`DiscoveryConfig` holds the same filters the `func` CLI exposes as flags —
setting them here is how an app declares its convention permanently rather than
asking every user to pass flags. `JobSources(lazy=True)` (the default) keeps boot
cheap by materializing a job only when it is invoked.

Project-level settings live in `.functualize.toml` or `[tool.functualize]` in
`pyproject.toml`. Everything an app resolves is visible at runtime:

```bash
myapp builtin info             # jobs, config resolution, state path
myapp builtin info schema      # every job's arguments as JSON Schema
myapp builtin config show      # resolved values, with the source that won
```

`info schema` is worth knowing about when packaging: it is how a coding agent
(or anything scripting your app) discovers the whole command surface in one
call, without walking each group's `--help`. You get it for free.

Those builtins come with the framework, so your app gets them for free — which
also means `builtin` is the one reserved top-level name your jobs cannot use.

---

## 8. Package

For distribution, expose the app through `[project.scripts]`:

```toml
[project.scripts]
myapp = "myapp.main:main"
```

Then the user's entry point is `myapp <job>`, not `func <job>`, and
functualize is an implementation detail. Verify the installed console script
works from a clean environment — not just from the source checkout, where
imports resolve differently.

---

## References

| File | Read when |
| --- | --- |
| [standalone-scripts.md](references/standalone-scripts.md) | The program is one file with no project |
| [../functualize/references/idiomatic.md](../functualize/references/idiomatic.md) | Choosing which declarations to compose |

Installing, upgrading and configuring `func` itself is the **`functualize-cli`**
skill.

---

## Definition of done

- `func builtin info` lists every intended job, on a **cleared** cache.
- `func builtin why` explains each one correctly.
- Every wiring path was broken once and something failed.
- Config resolves correctly under at least two environments.
- The program was run and its output looked at, TTY and piped.
- No credential appears unmasked in any output.
