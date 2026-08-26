---
name: functualize-app
description: >
  Build a new CLI or TUI program on functualize, end to end — scaffold the
  project, author jobs, wire config, write tests that actually catch
  regressions, and verify the program renders and runs. Use when starting a
  new functualize project or command-line tool, when adding a significant
  feature to one, when asked to make a functualize app "production ready" or
  well tested, or when packaging a functualize CLI for distribution.
license: MIT
metadata:
  version: "0.1.0"
  project: functualize
---

# Building a functualize app

Load the **`functualize`** skill first — it carries the invocation ladder and
the four contracts that are wrong by default. This skill is the procedure
around them; it does not repeat them.

---

## 1. Scaffold rather than hand-roll

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

## 2. Shape the jobs

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

---

## 3. Wire it, then prove the wiring

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

## 4. Test

```python
from functualize.testing import TestRunContext, CapturingLog, MockInvoke

def test_deploy_logs_progress():
    log = CapturingLog()
    deploy(rc=TestRunContext(), log=log)
    assert "Starting deployment" in log.messages
```

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

## 5. See it run

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

## 6. Package

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

## Definition of done

- `func builtin info` lists every intended job, on a **cleared** cache.
- `func builtin why` explains each one correctly.
- Every wiring path was broken once and something failed.
- Config resolves correctly under at least two environments.
- The program was run and its output looked at, TTY and piped.
- No credential appears unmasked in any output.
